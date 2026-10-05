"""Fine-tune do student — exporta dados e gera Modelfile Ollama."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from learning_agent import db
from learning_agent.identity import AGENT_NAME, AGENT_ROLE, MODELFILE_SYSTEM, RAVENNA_SYSTEM_BRIEF
from learning_agent.config import (
    DATA_DIR,
    GEMMA4_FEWSHOT_MAX,
    GEMMA4_NUM_CTX,
    GEMMA4_RAVEN_MODEL,
    GEMMA4_RUNTIME_BASE,
    PROJECT_ROOT,
    RAVEN_BASE_MODEL,
    RAVEN_RUNTIME_BASE,
    STUDENT_FINETUNE_MODEL,
    STUDENT_MODEL,
)

TRAINING_DIR = DATA_DIR / "training"

# Few-shots no Modelfile — 1+ por domínio, sem duplicar prompts
FEWSHOT_DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "backend": ["backend", "fastapi", "api", "postgresql", "rest", "websocket"],
    "frontend": ["frontend", "react", "typescript", "css", "vitals", "a11y"],
    "qa": ["qa", "teste", "pytest", "vitest", "e2e", "playwright"],
    "data": ["data", "rag", "embedding", "sqlite", "etl", "pipeline"],
    "reliability": ["reliability", "observabilidade", "slo", "resilien", "incident"],
    "agents": ["agent", "mcp", "orquestra", "playbook", "scaffold", "distill"],
    "remote_app": ["remote_app", "flask", "neon", "tratativa", "notifica", "deploy", "patch"],
}
FEWSHOT_MAX = 6
FEWSHOT_ASSISTANT_CHARS = 500


def _topic_domain(topic: str) -> str | None:
    blob = topic.lower()
    for domain, keywords in FEWSHOT_DOMAIN_KEYWORDS.items():
        if any(kw in blob for kw in keywords):
            return domain
    return None


def _select_few_shot_examples(
    examples: list[dict[str, Any]],
    *,
    max_examples: int | None = None,
) -> list[dict[str, Any]]:
    """Seleciona exemplos distintos por domínio; completa com pares restantes."""
    cap = max_examples if max_examples is not None else FEWSHOT_MAX
    distill = [e for e in examples if e.get("source") == "distillation"]
    picked: list[dict[str, Any]] = []
    seen_users: set[str] = set()
    covered: set[str] = set()

    for ex in distill:
        topic = str(ex.get("topic", ""))
        domain = _topic_domain(topic)
        if not domain or domain in covered:
            continue
        user = next((m["content"] for m in ex["messages"] if m["role"] == "user"), "")
        if not user or user in seen_users:
            continue
        picked.append(ex)
        seen_users.add(user)
        covered.add(domain)

    for ex in distill:
        if len(picked) >= cap:
            break
        user = next((m["content"] for m in ex["messages"] if m["role"] == "user"), "")
        if user and user not in seen_users:
            picked.append(ex)
            seen_users.add(user)

    return picked[:cap]


def export_training_data(min_pairs: int = 1) -> dict[str, Any]:
    """Exporta pares teacher/student + notas em JSONL (formato chat)."""
    db.init_db()
    TRAINING_DIR.mkdir(parents=True, exist_ok=True)
    jsonl_path = TRAINING_DIR / "ravenna_train.jsonl"
    examples: list[dict[str, Any]] = []

    with db.get_connection() as conn:
        pairs = conn.execute(
            "SELECT topic, teacher_output, student_output FROM distillation_pairs ORDER BY id"
        ).fetchall()
        notes = conn.execute(
            """
            SELECT title, content
            FROM learning_notes
            WHERE title NOT LIKE '[Lição]%'
              AND COALESCE(memory_status, 'active') != 'superseded'
            ORDER BY id DESC
            LIMIT 200
            """
        ).fetchall()

    for pair in pairs:
        examples.append(
            {
                "messages": [
                    {"role": "system", "content": RAVENNA_SYSTEM_BRIEF},
                    {"role": "user", "content": f"Explique: {pair['topic']}"},
                    {"role": "assistant", "content": pair["student_output"][:4000]},
                ],
                "source": "distillation",
                "topic": pair["topic"],
            }
        )

    for note in notes:
        examples.append(
            {
                "messages": [
                    {"role": "system", "content": RAVENNA_SYSTEM_BRIEF},
                    {"role": "user", "content": f"O que você sabe sobre {note['title']}?"},
                    {"role": "assistant", "content": note["content"][:4000]},
                ],
                "source": "note",
                "topic": note["title"],
            }
        )

    with jsonl_path.open("w", encoding="utf-8") as f:
        for ex in examples:
            f.write(json.dumps(ex, ensure_ascii=False) + "\n")

    return {
        "success": len(examples) >= min_pairs,
        "examples": len(examples),
        "path": str(jsonl_path),
        "min_pairs_required": min_pairs,
    }


def export_hf_sft_dataset() -> dict[str, Any]:
    """Exporta dataset no formato HuggingFace (messages) para QLoRA na Kaggle/Colab."""
    export = export_training_data(min_pairs=0)
    src = Path(export["path"])
    hf_dir = TRAINING_DIR / "hf_sft"
    hf_dir.mkdir(parents=True, exist_ok=True)
    hf_path = hf_dir / "train.jsonl"

    lines_out: list[str] = []
    if src.is_file():
        for line in src.read_text(encoding="utf-8").strip().splitlines():
            row = json.loads(line)
            msgs = row.get("messages", [])
            if len(msgs) >= 2:
                lines_out.append(json.dumps({"messages": msgs}, ensure_ascii=False))

    hf_path.write_text("\n".join(lines_out) + ("\n" if lines_out else ""), encoding="utf-8")
    meta = {
        "format": "chat_messages",
        "base_model_recommended": "Qwen/Qwen2.5-7B-Instruct",
        "method": "QLoRA 4-bit (Kaggle T4 free)",
        "examples": len(lines_out),
        "source_jsonl": str(src),
    }
    (hf_dir / "dataset_info.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {
        "success": len(lines_out) > 0,
        "path": str(hf_path),
        "examples": len(lines_out),
        "meta_path": str(hf_dir / "dataset_info.json"),
        "kaggle_notebook": str(PROJECT_ROOT / "notebooks" / "kaggle_qlora_raven.py"),
    }


def create_modelfile(
    *,
    target_model: str | None = None,
    runtime_base: str | None = None,
    modelfile_name: str = "Modelfile",
    num_ctx: int = 4096,
    fewshot_max: int | None = None,
    temperature: float = 0.7,
    assistant_chars: int | None = None,
    agent_mode_hint: bool = False,
) -> dict[str, Any]:
    """Gera Modelfile Ollama com system prompt + few-shots diversos por domínio."""
    export = export_training_data(min_pairs=0)
    modelfile_path = TRAINING_DIR / modelfile_name
    tgt = target_model or STUDENT_FINETUNE_MODEL
    base = runtime_base or RAVEN_RUNTIME_BASE
    shot_cap = fewshot_max if fewshot_max is not None else FEWSHOT_MAX
    asst_chars = assistant_chars if assistant_chars is not None else FEWSHOT_ASSISTANT_CHARS

    few_shot = ""
    few_shot_domains: list[str] = []
    jsonl = Path(export["path"])
    if jsonl.exists():
        all_examples = [json.loads(line) for line in jsonl.read_text(encoding="utf-8").strip().splitlines()]
        for data in _select_few_shot_examples(all_examples, max_examples=shot_cap):
            msgs = data.get("messages", [])
            user = next((m["content"] for m in msgs if m["role"] == "user"), "")
            assistant = next((m["content"] for m in msgs if m["role"] == "assistant"), "")
            if user and assistant:
                domain = _topic_domain(str(data.get("topic", "")))
                if domain:
                    few_shot_domains.append(domain)
                few_shot += f'\nMESSAGE user {json.dumps(user, ensure_ascii=False)}\n'
                few_shot += f'MESSAGE assistant {json.dumps(assistant[:asst_chars], ensure_ascii=False)}\n'

    from learning_agent.core.user_context import modelfile_location_line

    system = MODELFILE_SYSTEM.strip()
    if agent_mode_hint:
        system += (
            "\nModo agente: investigar (read_file/grep), diagnosticar, entregar solução completa "
            "com blocos ```write``` / ```patch``` / ```shell``` quando aplicável."
        )
    loc_line = modelfile_location_line()
    if loc_line:
        system = f"{system}\n{loc_line}"

    content = f"""FROM {base}
PARAMETER temperature {temperature}
PARAMETER num_ctx {num_ctx}
PARAMETER num_gpu 99
PARAMETER top_p 0.95
PARAMETER top_k 64

SYSTEM \"\"\"{system}\"\"\"
{few_shot}
"""
    modelfile_path.write_text(content, encoding="utf-8")
    return {
        "success": True,
        "modelfile": str(modelfile_path),
        "target_model": tgt,
        "base_model": RAVEN_BASE_MODEL,
        "runtime_base": base,
        "distill_student": STUDENT_MODEL,
        "examples_used": export["examples"],
        "few_shot_count": few_shot.count("MESSAGE user"),
        "few_shot_domains": few_shot_domains,
        "create_command": f"ollama create {tgt} -f {modelfile_path}",
    }


def create_gemma4_raven_modelfile() -> dict[str, Any]:
    """Modelfile gemma4-raven leve: ctx 4096, 2 few-shots, temp 0.5."""
    return create_modelfile(
        target_model=GEMMA4_RAVEN_MODEL,
        runtime_base=GEMMA4_RUNTIME_BASE,
        modelfile_name="Modelfile.gemma4-raven",
        num_ctx=GEMMA4_NUM_CTX,
        fewshot_max=GEMMA4_FEWSHOT_MAX,
        temperature=0.5,
        assistant_chars=300,
        agent_mode_hint=True,
    )


def _run_ollama_create(target: str, modelfile: str, *, timeout: int = 900) -> dict[str, Any]:
    ollama = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe"
    cmd = [str(ollama) if ollama.is_file() else "ollama", "create", target, "-f", modelfile]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(PROJECT_ROOT),
        )
        return {
            "success": result.returncode == 0,
            "exit_code": result.returncode,
            "stdout": (result.stdout or "")[-800:],
            "stderr": (result.stderr or "")[-800:],
            "command": " ".join(cmd),
        }
    except FileNotFoundError:
        return {"success": False, "error": "ollama não encontrado no PATH"}
    except subprocess.TimeoutExpired:
        return {"success": False, "error": f"timeout após {timeout}s"}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def create_gemma4_raven_model(dry_run: bool = True) -> dict[str, Any]:
    """Exporta corpus, gera Modelfile e cria gemma4-raven no Ollama."""
    info = create_gemma4_raven_modelfile()
    info["export"] = {"examples": info.get("examples_used")}
    if dry_run:
        info["dry_run"] = True
        info["message"] = "Modelfile gemma4-raven gerado. Rode create_command para criar o modelo."
        return info
    create_result = _run_ollama_create(info["target_model"], info["modelfile"])
    info.update(create_result)
    info["dry_run"] = False
    return info


def create_ollama_model(dry_run: bool = True) -> dict[str, Any]:
    """Cria modelo Ollama customizado (raven)."""
    info = create_modelfile()
    if dry_run:
        info["dry_run"] = True
        info["message"] = "Modelfile gerado. Rode create_command para criar o modelo."
        return info
    create_result = _run_ollama_create(info["target_model"], info["modelfile"])
    info.update(create_result)
    info["dry_run"] = False
    return info
