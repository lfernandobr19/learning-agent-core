"""Testes — orquestrador Ravenna."""

from __future__ import annotations

from learning_agent.core.ravenna_orchestrator import evaluate_ravenna_reply


def test_evaluate_detects_theater():
    ev = evaluate_ravenna_reply(
        "estude o REMOTE_APP",
        {"success": True, "reply": "Vou estudar a aplicação e volto em instantes com o mapa."},
    )
    assert ev["needs_correction"]
    assert any("teatro" in i for i in ev["issues"])


def test_evaluate_ok_reply():
    ev = evaluate_ravenna_reply(
        "o que é PETR4?",
        {"success": True, "reply": "PETR4 é preferencial da Petrobras na B3, ticker de ações."},
    )
    assert ev["score"] >= 70
    assert not ev["needs_correction"]
