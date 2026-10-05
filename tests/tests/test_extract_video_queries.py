"""Testes do extrator multi-filme (aspas + fallback singular)."""

from __future__ import annotations

from learning_agent.core.file_transfer import extract_video_queries, extract_video_query


def test_extract_two_quoted_titles() -> None:
    msg = (
        'Enviar os vídeos "Nefarious_2023" e "Frequencies_2013" para o Debian, por favor. '
        "Ao enviar, solicite que o Cursor disponibilize na biblioteca do teatrinho."
    )
    assert extract_video_queries(msg) == ["Nefarious_2023", "Frequencies_2013"]
    assert extract_video_query(msg) == "Nefarious_2023"


def test_extract_one_quoted_title() -> None:
    msg = 'Manda o filme "Guardiões da Galáxia Vol. 3" pro Debian'
    assert extract_video_queries(msg) == ["Guardiões da Galáxia Vol. 3"]
    assert extract_video_query(msg) == "Guardiões da Galáxia Vol. 3"


def test_extract_unquoted_fallback() -> None:
    msg = "Enviar o filme Frequencies para o Debian"
    qs = extract_video_queries(msg)
    assert len(qs) == 1
    assert "Frequencies" in qs[0]
    assert extract_video_query(msg) == qs[0]


def test_extract_dedupes_quoted() -> None:
    msg = 'Envie "Nefarious_2023" e "Nefarious_2023" pro Debian'
    assert extract_video_queries(msg) == ["Nefarious_2023"]


def test_extract_empty() -> None:
    assert extract_video_queries("") == []
    assert extract_video_query("") is None
