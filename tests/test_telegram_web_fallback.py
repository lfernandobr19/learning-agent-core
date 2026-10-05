"""Testes — fallback web e detecção de incerteza Telegram."""

from __future__ import annotations

from learning_agent.core import telegram_web_fallback as twf
from learning_agent.core.web import _domain_trust_score


def test_uncertain_reply():
    assert twf.is_uncertain_reply("Não sei responder isso com certeza.")
    assert twf.is_uncertain_reply("Infelizmente não tenho essa informação.")
    assert not twf.is_uncertain_reply("O IPCA mede a inflação oficial do Brasil via IBGE.")


def test_should_web_fallback():
    assert twf.should_web_fallback(
        "Qual a capital da Mongólia?",
        "Não sei, não tenho essa informação no momento.",
    )
    assert not twf.should_web_fallback(
        "Obrigado!",
        "De nada! 😊",
    )


def test_trusted_domain_score():
    assert _domain_trust_score("https://www.bcb.gov.br/controleinflacao") > 0
    assert _domain_trust_score("https://random-blog.example.com/post") == 0
