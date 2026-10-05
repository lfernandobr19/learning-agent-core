from __future__ import annotations

import pytest

from learning_agent.core import chat


def test_ide_chat_does_not_set_explicit_response_token_cap() -> None:
    prepared = chat._prepare_reply(
        "Explique detalhadamente a arquitetura da Ravenna IDE, incluindo backend, frontend, streaming, persistência e memória?",
        channel="ide",
        task_mode="chat",
        include_context=False,
        persist_history=False,
    )

    assert prepared["max_tokens"] == 0


def test_ide_agent_does_not_set_explicit_response_token_cap() -> None:
    prepared = chat._prepare_reply(
        "Implemente e explique uma melhoria completa.",
        channel="ide",
        task_mode="agent",
        include_context=False,
        persist_history=False,
    )

    assert prepared["max_tokens"] == 0


def test_ide_stream_preserves_long_response(monkeypatch: pytest.MonkeyPatch) -> None:
    long_response = "R" * 5000 + "END_OF_LONG_RESPONSE"

    class FakeStream:
        model_name = "fake-model"

        def __iter__(self):
            yield long_response[:2500]
            yield long_response[2500:]

    def fake_stream(*args, **kwargs):
        assert kwargs["max_tokens"] == 0
        return FakeStream()

    monkeypatch.setattr(chat.llm, "chat_stream_with_fallback", fake_stream)

    events = list(
        chat.iter_reply_deltas(
            "Explique com muitos detalhes o fluxo completo de mensagens da IDE?",
            channel="ide",
            task_mode="chat",
            include_context=False,
            persist_history=False,
        )
    )

    assert "".join(item for item in events if isinstance(item, str)) == long_response
    assert events[-1]["reply"] == long_response
    assert events[-1]["reply"].endswith("END_OF_LONG_RESPONSE")
