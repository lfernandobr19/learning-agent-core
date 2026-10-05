"""Ship autônomo — testes verdes → git commit (sem merge manual diário)."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from learning_agent.config import PROJECT_ROOT
from learning_agent.core import agent_action_journal, ship_pipeline

LOG_PATH = PROJECT_ROOT / "data" / "ship_autonomous.log"
MAX_LINES_LLM = 400


def _log(msg: str) -> None:
    line = f"[ship-auto] {msg}"
    print(line, flush=True)
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
        timeout=120,
    )


def _git_ok() -> bool:
    return _git("rev-parse", "--is-inside-work-tree").returncode == 0


def _run_pytest(tests: list[str]) -> dict[str, Any]:
    if not tests:
        return {"passed": True, "detail": "sem testes declarados"}
    cmd = [sys.executable, "-m", "pytest", *tests, "-q", "--tb=line"]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300, cwd=str(PROJECT_ROOT))
    out = (proc.stdout + proc.stderr)[-800:]
    return {"passed": proc.returncode == 0, "detail": out, "exit_code": proc.returncode}


def _stage_files(paths: list[str]) -> dict[str, Any]:
    staged: list[str] = []
    missing: list[str] = []
    for rel in paths:
        p = PROJECT_ROOT / rel.replace("/", os.sep)
        if p.is_file() or p.is_dir():
            r = _git("add", rel)
            if r.returncode == 0:
                staged.append(rel)
            else:
                return {"success": False, "error": r.stderr[:200]}
        else:
            missing.append(rel)
    return {"success": True, "staged": staged, "missing": missing}


def _commit(message: str) -> dict[str, Any]:
    if os.environ.get("AUTO_SHIP_DRY_RUN", "").lower() in {"1", "true", "yes"}:
        return {"success": True, "commit": "dry-run", "dry_run": True}
    r = _git("commit", "-m", message)
    if r.returncode != 0:
        text = (r.stdout + r.stderr).lower()
        if "nothing to commit" in text or "no changes added to commit" in text:
            return {"success": True, "commit": "nothing-to-commit", "skipped": True}
        return {"success": False, "error": (r.stderr or r.stdout)[:300]}
    hash_r = _git("rev-parse", "--short", "HEAD")
    return {"success": True, "commit": hash_r.stdout.strip()}


def _should_push() -> bool:
    mode = ship_pipeline.load_operating_mode()
    ship_cfg = mode.get("ship") or {}
    if ship_cfg.get("auto_push") is False:
        return False
    return os.environ.get("AUTO_SHIP_PUSH", "true").lower() not in {"0", "false", "no", "off"}


def _push_branch() -> dict[str, Any]:
    if os.environ.get("AUTO_SHIP_DRY_RUN", "").lower() in {"1", "true", "yes"}:
        return {"success": True, "pushed": False, "dry_run": True}

    if not _should_push():
        return {"success": True, "pushed": False, "skipped": True, "detail": "AUTO_SHIP_PUSH off"}

    remote = os.environ.get("AUTO_SHIP_REMOTE", "origin").strip() or "origin"
    remotes = _git("remote")
    if not remotes.stdout.strip():
        return {
            "success": False,
            "pushed": False,
            "error": "sem git remote — rode: git remote add origin <url>",
        }

    branch = _git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    upstream = _git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    if upstream.returncode != 0:
        r = _git("push", "-u", remote, branch)
    else:
        r = _git("push", remote, branch)

    if r.returncode != 0:
        err = (r.stderr or r.stdout)[:400]
        return {"success": False, "pushed": False, "error": err, "branch": branch, "remote": remote}

    _log(f"push OK → {remote}/{branch}")
    return {"success": True, "pushed": True, "branch": branch, "remote": remote}


def _llm_write_file(rel_path: str, prompt: str) -> dict[str, Any]:
    """Gera um arquivo via LLM local/cloud — só para itens pequenos."""
    from learning_agent.core.llm import chat_with_fallback

    if os.environ.get("AUTO_SHIP_LLM", "true").lower() in {"0", "false", "no", "off"}:
        return {"success": False, "error": "AUTO_SHIP_LLM desligado"}

    system = (
        "Você gera APENAS o conteúdo do arquivo solicitado, sem markdown fence, "
        "sem explicação. Código ou markdown válido."
    )
    try:
        content, model = chat_with_fallback(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            max_tokens=2048,
        )
    except Exception as exc:
        return {"success": False, "error": f"LLM: {exc!r}"}

    content = content.strip()
    if content.startswith("```"):
        content = re.sub(r"^```[\w]*\n?", "", content)
        content = re.sub(r"\n?```$", "", content)

    if len(content.splitlines()) > MAX_LINES_LLM:
        return {"success": False, "error": f"LLM gerou >{MAX_LINES_LLM} linhas — rejeitado"}

    path = PROJECT_ROOT / rel_path.replace("/", os.sep)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return {"success": True, "path": rel_path, "model": model, "lines": len(content.splitlines())}


def _handler_verify_and_commit(item: dict[str, Any]) -> dict[str, Any]:
    tests = item.get("tests") or []
    if isinstance(tests, str):
        tests = [tests]
    test_result = _run_pytest(tests)
    if not test_result["passed"]:
        return {"success": False, "stage": "pytest", **test_result}

    files = item.get("files_touch") or []
    stage = _stage_files(files)
    if not stage.get("success"):
        return {"success": False, "stage": "git_add", **stage}

    msg = f"ship(auto): {item.get('id')} {item.get('title', '')[:60]}"
    commit = _commit(msg)
    if not commit.get("success"):
        return {"success": False, "stage": "git_commit", **commit}

    push_result: dict[str, Any] = {"pushed": False}
    if not commit.get("skipped"):
        push_result = _push_branch()
        if not push_result.get("success"):
            return {"success": False, "stage": "git_push", **push_result}

    return {
        "success": True,
        "tests": test_result,
        "staged": stage.get("staged"),
        "commit": commit.get("commit"),
        "push": push_result,
    }


def _handler_llm_then_verify(item: dict[str, Any]) -> dict[str, Any]:
    """LLM preenche files_touch[0] se ausente, depois pytest + commit."""
    files = item.get("files_touch") or []
    if not files:
        return {"success": False, "error": "files_touch vazio"}

    target = files[0]
    path = PROJECT_ROOT / target.replace("/", os.sep)
    if not path.is_file() and item.get("llm_prompt"):
        gen = _llm_write_file(target, str(item["llm_prompt"]))
        if not gen.get("success"):
            return {"success": False, "stage": "llm", **gen}

    return _handler_verify_and_commit(item)


HANDLERS = {
    "verify_and_commit": _handler_verify_and_commit,
    "llm_then_verify": _handler_llm_then_verify,
}


def process_item(item: dict[str, Any], *, dry_run: bool = False) -> dict[str, Any]:
    if not item.get("autonomous"):
        return {"success": False, "error": "item não marcado autonomous: true", "item_id": item.get("id")}

    if (item.get("status") or "").lower() != "ready":
        return {"success": False, "error": f"status={item.get('status')}", "item_id": item.get("id")}

    if not _git_ok():
        return {"success": False, "error": "não é repositório git", "item_id": item.get("id")}

    handler_name = item.get("ship_handler") or "verify_and_commit"
    handler = HANDLERS.get(handler_name)
    if not handler:
        return {"success": False, "error": f"handler desconhecido: {handler_name}"}

    if dry_run:
        return {"success": True, "dry_run": True, "item_id": item.get("id"), "handler": handler_name}

    prev_dry = os.environ.get("AUTO_SHIP_DRY_RUN")
    if dry_run:
        os.environ["AUTO_SHIP_DRY_RUN"] = "true"
    try:
        result = handler(item)
    finally:
        if prev_dry is None:
            os.environ.pop("AUTO_SHIP_DRY_RUN", None)
        else:
            os.environ["AUTO_SHIP_DRY_RUN"] = prev_dry

    if result.get("success"):
        mark = ship_pipeline.mark_done(
            str(item["id"]),
            commit=str(result.get("commit") or ""),
        )
        result["mark_done"] = mark
        agent_action_journal.log_action(
            item.get("agent", "ravenna"),
            "ship_autonomous",
            topic=item.get("title", ""),
            project="ship-auto",
            success=True,
            summary=(
                f"commit={result.get('commit')} push={result.get('push', {}).get('pushed')} "
                f"files={item.get('files_touch')}"
            ),
        )
    else:
        agent_action_journal.log_action(
            item.get("agent", "ravenna"),
            "ship_autonomous",
            topic=item.get("title", ""),
            project="ship-auto",
            success=False,
            error=str(result.get("error") or result.get("detail") or "")[:500],
        )

    return {"item_id": item.get("id"), **result}


def run_autonomous_queue(*, max_items: int = 2, dry_run: bool = False) -> dict[str, Any]:
    if os.environ.get("AUTO_SHIP_ENABLED", "true").lower() in {"0", "false", "no", "off"}:
        return {"success": False, "error": "AUTO_SHIP_ENABLED=false"}

    mode = ship_pipeline.load_operating_mode()
    if not mode.get("ship", {}).get("autonomous", True):
        return {"success": False, "error": "operating_mode.ship.autonomous=false"}

    results: list[dict[str, Any]] = []
    for item in ship_pipeline.list_queue():
        if not item.get("autonomous"):
            continue
        if (item.get("status") or "").lower() != "ready":
            continue
        _log(f"processando {item.get('id')}")
        results.append(process_item(item, dry_run=dry_run))
        if len(results) >= max_items:
            break

    summary = {
        "success": True,
        "processed": len(results),
        "ok": sum(1 for r in results if r.get("success")),
        "results": results,
    }
    out = PROJECT_ROOT / "data" / "ship_autonomous_last.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    try:
        from learning_agent.core import telegram_alerts

        if summary.get("processed", 0) > 0:
            failed = [r for r in results if not r.get("success")]
            if failed or summary.get("ok", 0) > 0:
                telegram_alerts.alert_ship_summary(summary)
    except Exception:
        pass

    return summary
