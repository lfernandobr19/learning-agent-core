"""Testes — ferramentas factuais (router web, clima, câmbio)."""

from __future__ import annotations

from learning_agent.core import factual_tools as ft
from learning_agent.core import user_geolocation as ug


def test_current_address_not_nearby():
    assert ug.is_current_address_query("Qual o meu endereço atual?")
    assert not ug.NEARBY_QUERY_RE.search("Qual o meu endereço atual?")


def test_is_location_query_address_vs_nearby():
    assert ug.is_location_query("qual o mercado mais próximo de mim?")
    assert ug.is_location_query("Qual o meu endereço atual?")
    assert not ug.is_location_query("Qual a capital da França?")


def test_auto_web_router():
    assert ft.is_auto_web_query("notícias de economia hoje")
    assert ft.is_auto_web_query("o que aconteceu hoje no mercado")
    assert not ft.is_auto_web_query("cotação do dólar hoje")  # vai para FX factual
    assert ft.is_fx_query("cotação do dólar hoje")


def test_weather_query():
    assert ft.is_weather_query("como está o clima hoje?")
    assert not ft.is_weather_query("capital da frança")
