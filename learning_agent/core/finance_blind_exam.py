"""Prompt e helpers compartilhados — blind exams finance-lead."""

from __future__ import annotations

# Palavras que satisfazem rubrica risk_section (PT/EN, volatilidade incluída).
RISK_SECTION_KEYWORDS = (
    "risco",
    "drawdown",
    "stop",
    "sizing",
    "volatilidade",
    "volatility",
    "var ",
    "value at risk",
    "exposição",
    "exposicao",
    "position size",
    "tamanho da pos",
)


BLIND_EXAM_SYSTEM = """Voce e finance-lead (Ravenna). Responda APENAS JSON valido, sem markdown.
Campos obrigatorios:
- data_source: caminho fixture ou manifest (ex: agents/projects/finance-lead/fixtures/PETR4_sample.csv)
- action: hold ou watch (nunca buy/sell sem dados ao vivo)
- recommendation: hold ou watch
- tickers: array, SOMENTE tickers permitidos (formato B3: PETR4, VALE3 — sem sufixo .SA)
- risk: string em portugues com risco + drawdown OU sizing OU stop OU volatilidade
  (ex: "Drawdown max 8%; sizing 2% patrimonio; stop abaixo do suporte")
- invalidation: criterio explicito de invalidacao
- summary: 1-2 frases
NUNCA invente precos ao vivo (R$). Use apenas fixtures locais."""


def risk_section_present(text: str) -> bool:
    lower = text.lower()
    return any(k in lower for k in RISK_SECTION_KEYWORDS)
