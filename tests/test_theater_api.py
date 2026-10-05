"""Testes de contrato HTTP e teatro com max_cycles=1 (mock LLM)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from learning_agent.api import app
from learning_agent.core import theater
from learning_agent.core.theater import TheaterHTTPError


async def _hang_teaching_loop() -> None:
    """Mantém o teatro 'rodando' sem completar ciclos."""
    theater._state["running"] = True
    await theater._stop.wait()


async def _stop_clean() -> None:
    theater._stop.set()
    if theater._task and not theater._task.done():
        theater._task.cancel()
        try:
            await theater._task
        except asyncio.CancelledError:
            pass
    theater._task = None
    theater._state["running"] = False


def test_unknown_curriculum_returns_404():
    with TestClient(app) as client:
        client.post("/api/theater/stop?consolidate=false")
        r = client.post("/api/theater/start?curriculum=nao-existe&reset=true")
        assert r.status_code == 404
        assert "detail" in r.json()


def test_curriculum_conflict_returns_409_via_api():
    with TestClient(app) as client:
        client.post("/api/theater/stop?consolidate=false")
        with patch.object(theater, "_teaching_loop", side_effect=_hang_teaching_loop):
            r1 = client.post(
                "/api/theater/start?curriculum=reinforce-weak&reset=true&max_cycles=5"
            )
            assert r1.status_code == 200
            assert r1.json()["success"] is True

            r2 = client.post("/api/theater/start?curriculum=backend-mastery&reset=false")
            assert r2.status_code == 409
            body = r2.json()
            assert "detail" in body
            assert body.get("curriculum") == "reinforce-weak"

        client.post("/api/theater/stop?consolidate=false")


@pytest.mark.asyncio
async def test_curriculum_conflict_raises_theater_http_error():
    await _stop_clean()
    with patch.object(theater, "_teaching_loop", side_effect=_hang_teaching_loop):
        started = await theater.start_theater(curriculum="reinforce-weak", reset=True)
        assert started["success"] is True

        with pytest.raises(TheaterHTTPError) as exc:
            await theater.start_theater(curriculum="backend-mastery", reset=False)
        assert exc.value.status_code == 409

    await _stop_clean()


@pytest.mark.asyncio
async def test_max_cycles_1_completes_with_mocks():
    await _stop_clean()
    with (
        patch.object(theater, "_pause", new_callable=AsyncMock),
        patch.object(theater.knowledge, "add_note", return_value={"id": 1}),
        patch.object(
            theater.chat,
            "reply",
            return_value={"success": True, "reply": "ok", "model": "test"},
        ),
        patch.object(
            theater.codebase,
            "index_codebase",
            return_value={"indexed": 0},
        ),
        patch(
            "learning_agent.ide.ravenna_ide.broadcast_theater",
            new_callable=AsyncMock,
        ),
        patch(
            "learning_agent.core.consolidation.consolidate_and_broadcast",
            new_callable=AsyncMock,
            return_value={"success": True, "quiz_count": 0},
        ),
    ):
        result = await theater.start_theater(
            max_cycles=1,
            reset=True,
            curriculum="reinforce-weak",
        )
        assert result["success"] is True

        status = theater.get_status()
        for _ in range(80):
            status = theater.get_status()
            if not status["running"] and status["cycle"] >= 1:
                break
            await asyncio.sleep(0.05)

        assert status["cycle"] == 1
        assert status["running"] is False
        assert status["curriculum"] == "reinforce-weak"

    await _stop_clean()
