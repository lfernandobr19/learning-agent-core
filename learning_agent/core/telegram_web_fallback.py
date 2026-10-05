"""Fallback web Telegram — quando a Ravenna não sabe responder."""

from __future__ import annotations

import re

# Resposta indica incerteza ou falta de dados
UNCERTAIN_REPLY_RE = re.compile(
    r"(?i)"
    r"n[aã]o (sei|tenho|consigo|posso|encontrei|disponho|tenho certeza|tenho informa)"
    r"|sem (informa[cç][aã]o|dados|acesso|contexto)"
    r"|n[aã]o tenho como (responder|confirmar|verificar)"
    r"|infelizmente n[aã]o"
    r"|fora (do|de) (meu )?(conhecimento|escopo|alcance)"
    r"|n[aã]o est[aá] (claro|disponível|no meu contexto)"
    r"|n[aã]o possuo (dados|informa)"
    r"|desculpe.{0,40}n[aã]o (sei|tenho)"
)

# Pergunta factual — candidata a busca web
FACTUAL_QUESTION_RE = re.compile(
    r"(?i)"
    r"\?"
    r"|^(qual|quem|quando|onde|como|por que|porque|quanto|o que|que horas)"
)


def is_uncertain_reply(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return True
    if len(t) < 25 and UNCERTAIN_REPLY_RE.search(t):
        return True
    return bool(UNCERTAIN_REPLY_RE.search(t))


def should_web_fallback(user_message: str, assistant_reply: str) -> bool:
    """True se devemos buscar na web após resposta do LLM."""
    msg = user_message.strip()
    reply = (assistant_reply or "").strip()
    if not msg or len(msg) < 8:
        return False
    if is_uncertain_reply(reply):
        return True
    if (
        FACTUAL_QUESTION_RE.search(msg)
        and len(reply) < 100
        and any(w in reply.lower() for w in ("não", "desculpe", "infelizmente", "incerto"))
    ):
        return True
    return False
