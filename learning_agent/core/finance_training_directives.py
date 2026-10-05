"""Diretivas de treino finance-lead — chat Telegram → fila → execução real.

Evita que a Ravenna diga que aplicou sugestões sem o motor local ter executado.
"""

from __future__ import annotations

import json
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from learning_agent.config import PROJECT_ROOT

AGENT = "finance-lead"
FINANCE_ROOT = PROJECT_ROOT / "agents" / "projects" / AGENT
DIRECTIVES_PATH = FINANCE_ROOT / "data" / "training_directives.json"
OVERRIDE_PATH = FINANCE_ROOT / "data" / "directive_cycle_override.json"
PROMPTS_PATH = PROJECT_ROOT / "agents" / "projects" / AGENT / "overnight-prompts.yaml"
PLAYBOOK_PATH = PROJECT_ROOT / "agents" / "projects" / AGENT / "playbook.md"

ALLOWED_DIMENSIONS = frozenset({"knowledge", "reasoning", "decision"})
APPLY_KEYWORDS = (
    "aplica",
    "aplicar",
    "aplique",
    "execute",
    "executa",
    "coloque em andamento",
    "alinhe com",
    "pode aplicar",
    "aplica as sugest",
    "aplicar as sugest",
    "aplica isso",
    "aplica o que",
    "aplica agora",
)

# Pedidos de geo/maps não devem disparar fila de treino finance-lead
_APPLY_GEO_BLOCK = (
    "google maps",
    "maps api",
    "geolocal",
    "localização",
    "localizacao",
    "mercado mais próximo",
    "mercado mais proximo",
    "perto de mim",
    "openstreetmap",
    "botfather",
    "telegraf",
    "node.js",
    "location-assistant",
    "rua ",
    "endereço",
    "endereco",
    "moro na",
    "moro em",
)


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _read_json(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_store() -> dict[str, Any]:
    doc = _read_json(DIRECTIVES_PATH, {"directives": []})
    if not isinstance(doc.get("directives"), list):
        doc["directives"] = []
    return doc


def _save_store(doc: dict[str, Any]) -> None:
    doc["directives"] = doc.get("directives", [])[-100:]
    _write_json(DIRECTIVES_PATH, doc)


def chat_rules_block() -> str:
    """Regras anti-alucinação para injetar no system prompt."""
    summary = format_status_summary()
    return (
        "REGRAS TELEGRAM — TREINO FINANCE-LEAD:\n"
        "- Você NÃO executa código nem altera treino diretamente no chat.\n"
        "- NUNCA diga que já aplicou mudanças unless existir diretiva com status "
        '"applied" listada abaixo.\n'
        "- Para executar sugestões: peça ao usuário enviar «aplica isso» ou /apply.\n"
        "- Após /apply, o motor local (overnight + consolidação) aplica de fato.\n"
        f"{summary}\n"
        f"{_cursor_rules()}"
    )


def _cursor_rules() -> str:
    try:
        from learning_agent.core import cursor_agent_bridge

        return cursor_agent_bridge.chat_rules_snippet()
    except Exception:
        return ""


def format_status_summary() -> str:
    recent = list_directives(limit=5)
    if not recent:
        return "Diretivas recentes: nenhuma.\n"
    lines = ["Diretivas recentes:"]
    for d in recent:
        lines.append(
            f"- {d.get('directive_id')}: {d.get('action')} → {d.get('status')} "
            f"({(d.get('summary') or '')[:60]})"
        )
    return "\n".join(lines) + "\n"


def list_directives(*, limit: int = 10, status: str | None = None) -> list[dict[str, Any]]:
    items = _load_store().get("directives") or []
    if status:
        items = [d for d in items if d.get("status") == status]
    return list(reversed(items[-limit:]))


def is_apply_request(text: str, *, channel: str = "telegram", user_id: str = "default") -> bool:
    t = text.lower().strip()
    if t.startswith("/apply"):
        return True
    if any(k in t for k in _APPLY_GEO_BLOCK):
        return False
    if not any(k in t for k in APPLY_KEYWORDS):
        return False
    # "implementa/implemente" só com contexto finance explícito (evita loop geo/maps)
    if any(k in t for k in ("implementa", "implemente", "implementar")):
        if not (
            finance_context_in_recent_history(channel, user_id)
            and any(x in t for x in ("finance", "treino", "treinamento", "overnight", "prove"))
        ):
            return False
    if finance_context_in_recent_history(channel, user_id):
        return True
    return "finance" in t or "treinamento" in t or "treino" in t


def finance_context_in_recent_history(channel: str, user_id: str) -> bool:
    from learning_agent.core import chat, finance_status

    history = chat._load_history(channel, user_id, limit=8)
    blob = " ".join(m.get("content", "") for m in history).lower()
    if finance_status.is_finance_status_query(blob):
        return True
    keys = ("finance-lead", "finance lead", "treinamento", "quiz", "reasoning", "prove", "overnight")
    return any(k in blob for k in keys)


def _extract_suggestions_text(channel: str, user_id: str, extra: str = "") -> str:
    from learning_agent.core import chat

    history = chat._load_history(channel, user_id, limit=8)
    parts: list[str] = []
    for msg in reversed(history):
        if msg.get("role") == "assistant":
            parts.append(msg.get("content", ""))
            if len(parts) >= 2:
                break
    if extra:
        parts.insert(0, extra)
    return "\n\n".join(parts).strip()


def extract_directives(suggestions_text: str) -> list[dict[str, Any]]:
    """Extrai ações estruturadas das sugestões (LLM + fallback heurístico)."""
    if not suggestions_text.strip():
        return []

    parsed = _extract_via_llm(suggestions_text)
    if parsed:
        return parsed
    return _extract_heuristic(suggestions_text)


def _extract_via_llm(text: str) -> list[dict[str, Any]]:
    try:
        from learning_agent.core import llm

        system = (
            "Extraia diretivas executáveis para treino do agente finance-lead. "
            "Responda SOMENTE JSON válido: "
            '{"directives":[{"action":"...", ...}]}. '
            "Ações permitidas: add_teacher_topic (topic, level 2-6, tags[]), "
            "prioritize_dimension (dimension: knowledge|reasoning|decision, cycles 1-6), "
            "append_playbook_note (text), run_consolidation (full bool), "
            "run_quality_cycle (dimension, topic opcional). "
            "Máximo 5 diretivas, concisas."
        )
        raw, _ = llm.chat_with_fallback(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": text[:4000]},
            ],
            max_tokens=800,
        )
        match = re.search(r"\{[\s\S]*\}", raw)
        if not match:
            return []
        data = json.loads(match.group())
        items = data.get("directives") if isinstance(data, dict) else None
        if not isinstance(items, list):
            return []
        return [_normalize_directive(d) for d in items if isinstance(d, dict)][:5]
    except Exception:
        return []


def _extract_heuristic(text: str) -> list[dict[str, Any]]:
    directives: list[dict[str, Any]] = []
    lower = text.lower()
    if any(w in lower for w in ("reasoning", "raciocínio", "raciocinio", "paridade")):
        directives.append(
            _normalize_directive({"action": "prioritize_dimension", "dimension": "reasoning", "cycles": 3})
        )
    if any(w in lower for w in ("quiz", "sm-2", "sm2", "revisão espaçada", "revisao espacada")):
        directives.append(_normalize_directive({"action": "run_consolidation", "full": False}))
    if any(w in lower for w in ("decisão", "decisao", "paper", "carteira")):
        directives.append(
            _normalize_directive({"action": "prioritize_dimension", "dimension": "decision", "cycles": 2})
        )
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if re.match(r"^[-*•\d]+[\.)]\s+", line):
            topic = re.sub(r"^[-*•\d]+[\.)]\s+", "", line).strip()
            if len(topic) > 15 and any(
                w in topic.lower() for w in ("estud", "tópico", "topico", "foc", "trein", "pratic")
            ):
                directives.append(
                    _normalize_directive(
                        {
                            "action": "add_teacher_topic",
                            "topic": topic[:200],
                            "level": 5,
                            "tags": ["finance", "telegram-directive"],
                        }
                    )
                )
    if not directives and len(text) > 40:
        directives.append(
            _normalize_directive(
                {
                    "action": "append_playbook_note",
                    "text": text[:500],
                }
            )
        )
    return directives[:5]


def _normalize_directive(raw: dict[str, Any]) -> dict[str, Any]:
    action = str(raw.get("action", "")).strip()
    d: dict[str, Any] = {"action": action}
    if action == "add_teacher_topic":
        d["topic"] = str(raw.get("topic", "")).strip()[:200]
        d["level"] = max(2, min(6, int(raw.get("level") or 5)))
        tags = raw.get("tags") or ["finance", "telegram-directive"]
        d["tags"] = [str(t) for t in tags][:8]
    elif action == "prioritize_dimension":
        dim = str(raw.get("dimension", "reasoning")).lower()
        d["dimension"] = dim if dim in ALLOWED_DIMENSIONS else "reasoning"
        d["cycles"] = max(1, min(6, int(raw.get("cycles") or 3)))
    elif action == "append_playbook_note":
        d["text"] = str(raw.get("text", "")).strip()[:800]
    elif action == "run_consolidation":
        d["full"] = bool(raw.get("full"))
    elif action == "run_quality_cycle":
        dim = str(raw.get("dimension", "reasoning")).lower()
        d["dimension"] = dim if dim in ALLOWED_DIMENSIONS else "reasoning"
        if raw.get("topic"):
            d["topic"] = str(raw.get("topic"))[:200]
    return d


def queue_directives(
    directives: list[dict[str, Any]],
    *,
    source: str = "telegram",
    requested_by: str = "",
) -> list[dict[str, Any]]:
    doc = _load_store()
    queued: list[dict[str, Any]] = []
    for raw in directives:
        action = raw.get("action")
        if action not in {
            "add_teacher_topic",
            "prioritize_dimension",
            "append_playbook_note",
            "run_consolidation",
            "run_quality_cycle",
        }:
            continue
        if action == "add_teacher_topic" and not raw.get("topic"):
            continue
        if action == "append_playbook_note" and not raw.get("text"):
            continue
        entry = {
            "directive_id": f"td-{uuid.uuid4().hex[:8]}",
            "action": action,
            "params": raw,
            "status": "queued",
            "source": source,
            "requested_by": requested_by,
            "created_at": _utcnow(),
            "applied_at": None,
            "summary": "",
            "result": None,
            "error": None,
        }
        doc["directives"].append(entry)
        queued.append(entry)
    _save_store(doc)
    return queued


def apply_directive(entry: dict[str, Any]) -> dict[str, Any]:
    action = entry.get("action")
    params = entry.get("params") or {}
    try:
        if action == "add_teacher_topic":
            result = _apply_add_teacher_topic(params)
        elif action == "prioritize_dimension":
            result = _apply_prioritize_dimension(params)
        elif action == "append_playbook_note":
            result = _apply_append_playbook(params)
        elif action == "run_consolidation":
            result = _apply_run_consolidation(params)
        elif action == "run_quality_cycle":
            result = _apply_run_quality_cycle(params)
        else:
            return {"success": False, "error": f"ação desconhecida: {action}"}
        return {"success": True, **result}
    except Exception as exc:
        return {"success": False, "error": str(exc)[:300]}


def _apply_add_teacher_topic(params: dict[str, Any]) -> dict[str, Any]:
    import yaml

    topic = params["topic"]
    cfg = yaml.safe_load(PROMPTS_PATH.read_text(encoding="utf-8")) if PROMPTS_PATH.is_file() else {}
    topics = cfg.setdefault("teacher_topics", [])
    if any(t.get("topic") == topic for t in topics if isinstance(t, dict)):
        return {"summary": f"tópico já existia: {topic[:60]}", "duplicate": True}
    topics.append(
        {
            "level": params.get("level", 5),
            "topic": topic,
            "tags": params.get("tags") or ["finance", "telegram-directive"],
        }
    )
    PROMPTS_PATH.write_text(
        yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return {"summary": f"tópico adicionado: {topic[:60]}"}


def _apply_prioritize_dimension(params: dict[str, Any]) -> dict[str, Any]:
    dim = params.get("dimension", "reasoning")
    cycles = int(params.get("cycles") or 3)
    _write_json(
        OVERRIDE_PATH,
        {
            "force_dimension": dim,
            "remaining": cycles,
            "updated_at": _utcnow(),
        },
    )
    return {"summary": f"próximos {cycles} ciclos: dim={dim}"}


def _apply_append_playbook(params: dict[str, Any]) -> dict[str, Any]:
    text = params.get("text", "").strip()
    marker = "## Diretivas Telegram"
    content = PLAYBOOK_PATH.read_text(encoding="utf-8") if PLAYBOOK_PATH.is_file() else ""
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    block = f"\n\n- [{stamp}] {text}\n"
    if marker in content:
        idx = content.index(marker) + len(marker)
        content = content[:idx] + block + content[idx:]
    else:
        content = content.rstrip() + f"\n\n{marker}\n{block}"
    PLAYBOOK_PATH.write_text(content, encoding="utf-8")
    return {"summary": f"playbook atualizado ({len(text)} chars)"}


def _apply_run_consolidation(params: dict[str, Any]) -> dict[str, Any]:
    from learning_agent.core import finance_consolidation

    result = finance_consolidation.run_phase1_consolidation(full=bool(params.get("full")))
    return {
        "summary": (
            f"consolidação F1 proof_gate={result.get('proof_gate_ok')} "
            f"quiz={result.get('quiz_items_reviewed')}"
        ),
        "detail": result,
    }


def _apply_run_quality_cycle(params: dict[str, Any]) -> dict[str, Any]:
    from learning_agent.core import finance_lead_engine

    dim = params.get("dimension", "reasoning")
    topic = params.get("topic")
    result = finance_lead_engine.run_quality_cycle(
        cycle_n=0,
        dimension=dim,
        topic=topic,
        full_verify=False,
    )
    return {
        "summary": f"ciclo qualidade dim={dim} distilled={result.get('distilled')}",
        "detail": {"dimension": dim, "distilled": result.get("distilled")},
    }


def apply_queued(*, directive_ids: list[str] | None = None) -> dict[str, Any]:
    doc = _load_store()
    applied: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    for i, entry in enumerate(doc.get("directives") or []):
        if entry.get("status") != "queued":
            continue
        if directive_ids and entry.get("directive_id") not in directive_ids:
            continue
        outcome = apply_directive(entry)
        entry = {
            **entry,
            "status": "applied" if outcome.get("success") else "failed",
            "applied_at": _utcnow(),
            "summary": outcome.get("summary") or entry.get("summary") or "",
            "result": outcome,
            "error": outcome.get("error"),
        }
        doc["directives"][i] = entry
        (applied if outcome.get("success") else failed).append(entry)
    _save_store(doc)
    return {"success": not failed, "applied": applied, "failed": failed}


def apply_from_chat(
    channel: str,
    user_id: str,
    *,
    user_message: str = "",
    run_heavy_in_background: bool = True,
) -> dict[str, Any]:
    """Extrai sugestões do histórico, enfileira e aplica."""
    extra = user_message.split(maxsplit=1)[1] if user_message.strip().startswith("/apply ") else ""
    suggestions = _extract_suggestions_text(channel, user_id, extra=extra)
    if not suggestions:
        return {
            "success": False,
            "error": "Nenhuma sugestão recente no chat. Converse sobre melhorias e envie «aplica isso».",
        }

    raw_directives = extract_directives(suggestions)
    if not raw_directives:
        return {
            "success": False,
            "error": "Não consegui extrair ações concretas das sugestões. Seja mais específico ou use /apply <texto>.",
        }

    queued = queue_directives(raw_directives, source="telegram", requested_by=user_id)
    if not queued:
        return {"success": False, "error": "Nenhuma diretiva válida para enfileirar."}

    heavy = {"run_consolidation", "run_quality_cycle"}
    light_ids = [q["directive_id"] for q in queued if q["action"] not in heavy]
    heavy_ids = [q["directive_id"] for q in queued if q["action"] in heavy]

    light_result = apply_queued(directive_ids=light_ids) if light_ids else {"applied": [], "failed": []}

    if heavy_ids and run_heavy_in_background:
        def _bg() -> None:
            from learning_agent.core import telegram_alerts

            outcome = apply_queued(directive_ids=heavy_ids)
            lines = ["Diretivas pesadas concluídas:"]
            for e in outcome.get("applied") or []:
                lines.append(f"✓ {e.get('directive_id')}: {e.get('summary')}")
            for e in outcome.get("failed") or []:
                lines.append(f"✗ {e.get('directive_id')}: {e.get('error')}")
            telegram_alerts.send_alert("\n".join(lines))

        threading.Thread(target=_bg, daemon=True).start()
        heavy_note = f"{len(heavy_ids)} ação(ões) pesada(s) em background — aviso no Telegram."
    elif heavy_ids:
        heavy_result = apply_queued(directive_ids=heavy_ids)
        light_result["applied"] = (light_result.get("applied") or []) + (heavy_result.get("applied") or [])
        light_result["failed"] = (light_result.get("failed") or []) + (heavy_result.get("failed") or [])
        heavy_note = ""
    else:
        heavy_note = ""

    all_applied = light_result.get("applied") or []
    all_failed = light_result.get("failed") or []
    return {
        "success": bool(all_applied),
        "queued": len(queued),
        "applied": all_applied,
        "failed": all_failed,
        "heavy_note": heavy_note,
        "extracted": raw_directives,
    }


def format_apply_reply(result: dict[str, Any]) -> str:
    if not result.get("success") and not result.get("applied"):
        return f"Não apliquei: {result.get('error', 'erro desconhecido')}"

    lines = ["Diretivas aplicadas (motor local):"]
    for e in result.get("applied") or []:
        lines.append(f"✓ {e.get('directive_id')} {e.get('action')}: {e.get('summary')}")
    for e in result.get("failed") or []:
        lines.append(f"✗ {e.get('directive_id')}: {e.get('error')}")
    if result.get("heavy_note"):
        lines.append(result["heavy_note"])
    lines.append("\nConfira com /directives ou /finance.")
    return "\n".join(lines)


def format_directives_message(limit: int = 8) -> str:
    items = list_directives(limit=limit)
    if not items:
        return "Nenhuma diretiva registrada. Sugira melhorias no chat e envie «aplica isso» ou /apply."
    lines = ["Diretivas treino finance-lead:"]
    for d in items:
        status = d.get("status", "?")
        lines.append(
            f"- {d.get('directive_id')} [{status}] {d.get('action')}: "
            f"{(d.get('summary') or '')[:70]}"
        )
    lines.append("\n«aplica isso» ou /apply — executar sugestões do chat")
    return "\n".join(lines)


def get_cycle_overrides() -> dict[str, Any]:
    return _read_json(OVERRIDE_PATH, {})


def tick_cycle_override() -> None:
    doc = _read_json(OVERRIDE_PATH, {})
    remaining = int(doc.get("remaining") or 0)
    if remaining <= 1:
        if OVERRIDE_PATH.is_file():
            OVERRIDE_PATH.unlink(missing_ok=True)
        return
    doc["remaining"] = remaining - 1
    _write_json(OVERRIDE_PATH, doc)
