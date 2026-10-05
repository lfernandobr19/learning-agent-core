"""Saldo DeepSeek via GET /user/balance (conta pré-paga)."""

from __future__ import annotations

from typing import Any

import httpx

from learning_agent.config import DEEPSEEK_API_BASE, DEEPSEEK_API_KEY


def _balance_url() -> str:
    base = (DEEPSEEK_API_BASE or "https://api.deepseek.com/v1").rstrip("/")
    if base.endswith("/v1"):
        root = base[: -len("/v1")]
    else:
        root = base
    return f"{root}/user/balance"


def fetch_deepseek_balance(*, timeout: float = 15.0) -> dict[str, Any]:
    """
    Consulta saldo oficial DeepSeek.
    A API não expõe cota % mensal — só saldo absoluto (total/granted/topped_up).
    """
    if not DEEPSEEK_API_KEY:
        return {
            "ok": False,
            "configured": False,
            "error": "DEEPSEEK_API_KEY não configurada",
        }

    url = _balance_url()
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.get(
                url,
                headers={
                    "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                    "Accept": "application/json",
                },
            )
        if resp.status_code >= 400:
            return {
                "ok": False,
                "configured": True,
                "error": f"HTTP {resp.status_code}: {resp.text[:200]}",
            }
        data = resp.json()
    except Exception as exc:
        return {"ok": False, "configured": True, "error": str(exc)}

    infos = data.get("balance_infos") or []
    primary = infos[0] if infos else {}
    try:
        total = float(str(primary.get("total_balance") or "0").strip() or "0")
    except ValueError:
        total = 0.0
    try:
        granted = float(str(primary.get("granted_balance") or "0").strip() or "0")
    except ValueError:
        granted = 0.0
    try:
        topped = float(str(primary.get("topped_up_balance") or "0").strip() or "0")
    except ValueError:
        topped = 0.0

    return {
        "ok": True,
        "configured": True,
        "is_available": bool(data.get("is_available")),
        "currency": str(primary.get("currency") or "USD"),
        "total_balance": total,
        "granted_balance": granted,
        "topped_up_balance": topped,
        "source": "deepseek:/user/balance",
    }
