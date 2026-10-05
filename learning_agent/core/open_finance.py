"""Open Finance proxy — Belvo/Pluggy (MVP). Secrets stay server-side."""

from __future__ import annotations

import os
from typing import Any

import httpx

BELVO_SANDBOX = "https://sandbox.belvo.com"
BELVO_PRODUCTION = "https://api.belvo.com"


def _belvo_base() -> str:
    env = (os.getenv("BELVO_ENV") or "sandbox").strip().lower()
    return BELVO_PRODUCTION if env == "production" else BELVO_SANDBOX


def _credentials() -> tuple[str, str] | None:
    secret_id = (os.getenv("BELVO_SECRET_ID") or "").strip()
    secret_password = (os.getenv("BELVO_SECRET_PASSWORD") or "").strip()
    if secret_id and secret_password:
        return secret_id, secret_password
    return None


def status_payload() -> dict[str, Any]:
    creds = _credentials()
    return {
        "ok": True,
        "configured": creds is not None,
        "mode": "belvo" if creds else "mock",
        "env": os.getenv("BELVO_ENV") or "sandbox",
        "provider": "belvo",
        "resources": [
            "ACCOUNTS",
            "TRANSACTIONS",
            "CREDIT_CARDS",
            "CREDIT_OPERATIONS",
        ],
    }


def create_widget_token(
    *,
    callback_success: str = "",
    callback_exit: str = "",
) -> dict[str, Any]:
    creds = _credentials()
    if not creds:
        return {
            "ok": True,
            "mock": True,
            "widget_url": None,
            "message": "Configure BELVO_SECRET_ID e BELVO_SECRET_PASSWORD no .env",
        }

    secret_id, secret_password = creds
    base = _belvo_base()
    payload = {
        "id": secret_id,
        "password": secret_password,
        "scopes": "read_institutions,write_links,read_consents,write_consents,write_consent_callback,delete_consents",
        "fetch_resources": ["ACCOUNTS", "TRANSACTIONS", "CREDIT_CARDS", "CREDIT_OPERATIONS"],
        "widget": {
            "purpose": "Controle financeiro pessoal — saldo, extrato, cartões e faturas.",
            "openfinance_feature": "consent_link_creation",
            "callback_urls": {
                "success": callback_success or "https://localhost/callback/success",
                "exit": callback_exit or "https://localhost/callback/exit",
                "event": callback_exit or "https://localhost/callback/exit",
            },
            "consent": {
                "terms_and_conditions_url": "https://bigxandi.github.io/Financeiro/",
                "permissions": ["REGISTER", "ACCOUNTS", "CREDIT_CARDS", "CREDIT_OPERATIONS"],
            },
        },
    }

    with httpx.Client(timeout=30.0) as client:
        resp = client.post(f"{base}/api/token/", json=payload)
        resp.raise_for_status()
        data = resp.json()

    access = data.get("access") or data.get("access_token")
    widget_url = f"https://widget.belvo.io/?access_token={access}&locale=pt" if access else None
    return {
        "ok": True,
        "mock": False,
        "widget_url": widget_url,
        "expires_in": data.get("expires_in"),
    }
