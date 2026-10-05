"""Testes — geolocalização Ravenna e anti-loop /apply."""

from __future__ import annotations

from learning_agent.core import finance_training_directives as ftd
from learning_agent.core import user_geolocation as ug


def test_is_location_query():
    assert ug.is_location_query("qual o mercado mais próximo de mim?")
    assert ug.is_location_query("Moro na rua das flores, 100 - centro")
    assert ug.is_location_query("Qual o meu endereço atual?")
    assert not ug.is_location_query("Qual a capital da França?")


def test_current_address_intent():
    assert ug.is_current_address_query("Qual o meu endereço atual?")
    assert ug.is_current_address_query("onde estou?")
    assert not ug.is_current_address_query("qual o mercado mais próximo?")


def test_apply_blocked_on_geo():
    assert not ftd.is_apply_request("implementarmos a API do Google Maps no código")
    assert not ftd.is_apply_request("qual mercado mais próximo de mim")
    assert ftd.is_apply_request("/apply")


def test_live_location_active():
    now = 1_700_000_000.0
    rec = {
        "source": "telegram_live",
        "live_until_unix": now + 600,
        "updated_at_unix": now - 30,
    }
    assert ug.is_live_location_active(rec, now=now)
    rec["updated_at_unix"] = now - 200
    assert not ug.is_live_location_active(rec, now=now)
    rec["updated_at_unix"] = now - 30
    rec["live_until_unix"] = now - 1
    assert not ug.is_live_location_active(rec, now=now)


def test_location_status_line():
    now = 1_700_000_000.0
    rec = {
        "source": "telegram_live",
        "live_until_unix": now + 300,
        "updated_at_unix": now - 10,
    }
    assert "ao vivo" in ug.location_status_line(rec, now=now).lower()


def test_extract_address():
    addr = ug.extract_address_from_message(
        "Moro na rua dos pica paus, 446 - Jardim Primavera"
    )
    assert addr
    assert "pica paus" in addr.lower()
