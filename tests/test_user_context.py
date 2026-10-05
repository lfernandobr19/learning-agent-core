"""Testes — contexto de geolocalização do motor Ravenna."""

from __future__ import annotations

from unittest.mock import patch

from learning_agent.core import user_context


@patch.dict(
    "os.environ",
    {
        "USER_TIMEZONE": "America/Sao_Paulo",
        "USER_CITY": "São Paulo",
        "USER_REGION": "SP",
        "USER_COUNTRY": "BR",
        "USER_LOCALE": "pt-BR",
    },
)
def test_profile_configured():
    import importlib

    import learning_agent.config as cfg

    importlib.reload(cfg)
    import learning_agent.core.user_context as uc

    importlib.reload(uc)
    assert uc.is_configured()
    p = uc.profile()
    assert p["city"] == "São Paulo"
    assert p["timezone"] == "America/Sao_Paulo"
    assert p["local_time_label"]
    assert p["b3_session"] in {"pré-abertura", "aberta", "fechada (pós-pregão)", "fechada (fim de semana)"}


def test_not_configured_when_empty():
    with patch.multiple(
        user_context,
        USER_TIMEZONE="",
        USER_CITY="",
        USER_COUNTRY="",
    ):
        assert not user_context.is_configured()
        assert user_context.format_system_block() == ""


def test_format_system_block_with_patch():
    with patch.multiple(
        user_context,
        is_configured=lambda: True,
        profile=lambda: {
            "city": "Curitiba",
            "region": "PR",
            "country": "BR",
            "timezone": "America/Sao_Paulo",
            "local_time_label": "08/06/2026 10:00",
            "locale": "pt-BR",
            "b3_session": "aberta",
        },
    ):
        block = user_context.format_system_block()
    assert "Curitiba" in block
    assert "America/Sao_Paulo" in block
    assert "B3" in block
