"""Alertas Telegram — Prove, Ship e Train."""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

from learning_agent.config import TELEGRAM_ALLOWED_USERS, TELEGRAM_BOT_TOKEN

DEFAULT_AGENTS = [
    "finance-lead",
    "backend-lead",
    "frontend-lead",
    "qa-guardian",
    "data-engineer",
    "reliability-lead",
]


def _alerts_enabled() -> bool:
    if not TELEGRAM_BOT_TOKEN:
        return False
    return os.environ.get("TELEGRAM_ALERT_ENABLED", "true").lower() not in {"0", "false", "no", "off"}


def _chat_id() -> int | None:
    raw = os.environ.get("TELEGRAM_ALERT_CHAT_ID", "").strip()
    if raw.isdigit():
        return int(raw)
    if TELEGRAM_ALLOWED_USERS:
        return next(iter(sorted(TELEGRAM_ALLOWED_USERS)))
    return None


def send_alert(message: str, *, parse_mode: str = "") -> dict[str, Any]:
    """Envia mensagem para Telegram. Retorna {sent, detail}."""
    if not _alerts_enabled():
        return {"sent": False, "detail": "alertas desligados ou token ausente"}
    chat = _chat_id()
    if chat is None:
        return {"sent": False, "detail": "TELEGRAM_ALERT_CHAT_ID ou ALLOWED_USER_IDS ausente"}

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload: dict[str, Any] = {"chat_id": chat, "text": message[:4000]}
    if parse_mode:
        payload["parse_mode"] = parse_mode

    try:
        with httpx.Client(timeout=20.0) as client:
            r = client.post(url, json=payload)
            r.raise_for_status()
            body = r.json()
            result = body.get("result") if isinstance(body, dict) else {}
            return {
                "sent": True,
                "detail": f"chat_id={chat}",
                "message_id": result.get("message_id"),
                "chat_id": chat,
            }
    except Exception as exc:
        return {"sent": False, "detail": str(exc)[:200]}


def alert_prove_report(report: dict[str, Any]) -> dict[str, Any]:
    agent = report.get("agent", "finance-lead")
    external = report.get("external") or {}
    ready = external.get("external_ready", False)
    passed = external.get("passed_count", 0)
    total = external.get("total", 5)
    blinds = report.get("blind_runs") or []
    blind_fail = [b for b in blinds if b.get("success") and not b.get("passed")]
    blind_scores = [
        f"{b.get('blind_id')}: {b.get('composite', 0)}%"
        for b in blinds
        if b.get("success")
    ]

    if ready and not blind_fail:
        msg = (
            f"Prove OK — {agent}\n"
            f"Externo: {passed}/{total} Go\n"
            f"Blinds: {', '.join(blind_scores) or 'n/a'}"
        )
    else:
        msg = (
            f"Prove FALHOU — {agent}\n"
            f"Externo: {passed}/{total} {'Go' if ready else 'No-Go'}\n"
            f"Blinds falhos: {len(blind_fail)}\n"
            f"Scores: {', '.join(blind_scores) or 'n/a'}"
        )
    return send_alert(msg)


def alert_ship_summary(summary: dict[str, Any]) -> dict[str, Any]:
    results = summary.get("results") or []
    failed = [r for r in results if not r.get("success")]
    if not results:
        return {"sent": False, "detail": "nenhum item processado"}
    if not failed:
        ok_ids = [r.get("item_id") for r in results if r.get("success")]
        msg = f"Ship OK\nItens: {', '.join(str(i) for i in ok_ids if i)}"
        return send_alert(msg)

    lines = ["Ship FALHOU"]
    for r in failed:
        lines.append(f"- {r.get('item_id')}: {r.get('error') or r.get('detail') or 'erro'}")
    return send_alert("\n".join(lines))


def alert_train_result(*, cycles: int, ship_ok: bool, detail: str = "") -> dict[str, Any]:
    status = "OK" if cycles > 0 else "SEM CICLOS"
    msg = f"Train {status}\nCiclos: {cycles}\nShip pos-train: {'OK' if ship_ok else 'falhou'}"
    if detail:
        msg += f"\n{detail[:500]}"
    return send_alert(msg)


def alert_generic(title: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    body = json.dumps(payload or {}, ensure_ascii=False, indent=2)[:2500]
    return send_alert(f"{title}\n{body}")


def alert_blind_batch(report: dict[str, Any], *, source: str = "batch") -> dict[str, Any]:
    """Alerta Telegram — batch/fresh blind exams (limiar 80%)."""
    overall = report.get("overall") or {}
    threshold = float(report.get("pass_threshold") or 80)
    fail = int(overall.get("total_fail") or 0)
    below = int(overall.get("total_below_threshold") or 0)
    mean = overall.get("mean_composite", 0)
    mode = report.get("mode") or source

    lines = [f"Blind {mode} — finance-lead"]
    for b in report.get("blinds") or []:
        fails = b.get("criteria_failures") or {}
        extra = f" falhas={fails}" if fails else ""
        lines.append(
            f"- {b.get('blind_id')}: {b.get('mean_composite')}% "
            f"(min {b.get('min_composite')}){extra}"
        )
    lines.append(f"Média: {mean}% | limiar {threshold}%")

    if report.get("success") and fail == 0 and below == 0:
        lines.insert(1, "OK — todos passaram")
        return send_alert("\n".join(lines))

    lines.insert(1, f"ATENÇÃO — fail={fail} abaixo_limiar={below}")
    return send_alert("\n".join(lines))
