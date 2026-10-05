"""Quizzes — reforço pós-avaliação (tópicos fracos Backend + Details)."""

from __future__ import annotations

from typing import Any

from learning_agent.core import quiz as quiz_core

REINFORCE_WEAK_QUESTIONS: list[dict[str, str]] = [
    {
        "topic": "Reforço — Status HTTP e contratos",
        "question": (
            "No learning-agent, mapeie: validação Pydantic falha, teatro já rodando com outro "
            "currículo, timeout do LLM e rota inexistente — status HTTP e corpo de erro esperado."
        ),
        "answer": (
            "422 Unprocessable Entity para Pydantic; 409 Conflict ou 400 com mensagem clara "
            "quando teatro ativo com currículo diferente; 504/503 para timeout LLM; "
            "404 Not Found para rota/recurso. Corpo com `detail` estruturado — nunca 200 com erro."
        ),
    },
    {
        "topic": "Reforço — FastAPI camadas e testes",
        "question": (
            "Por que handlers em api.py devem ser finos e como testar o teatro com "
            "max_cycles=1 sem depender do LLM real?"
        ),
        "answer": (
            "Handlers finos delegam regra de negócio para core/ (theater, consolidation), "
            "facilitando testes e evolução. TestClient POST /api/theater/start com mock/patch "
            "de chat.reply e knowledge.add_note garante determinismo; pytest unit em core/ "
            "valida contadores e whitelist de currículo."
        ),
    },
    {
        "topic": "Reforço — Segurança e observabilidade",
        "question": (
            "Liste três controles de segurança e o que GET /health deve reportar no learning-agent."
        ),
        "answer": (
            "Segurança: validação Pydantic + limites; CORS restrito em prod; secrets fora do repo; "
            "rate limit em chat; logs sem tokens. Health: ping SQLite, status do teatro "
            "(running, curriculum, cycle), stats de aprendizado incluindo weak_areas e quizzes pendentes."
        ),
    },
    {
        "topic": "Reforço — DOM e realocação chat",
        "question": (
            "Descreva a árvore DOM válida ao mover o raciocínio neural para fora da bolha, "
            "abaixo do timestamp no ChatPanel."
        ),
        "answer": (
            "Container da mensagem: div.bubble com `<p>` do conteúdo; `<time>`; "
            "`<NeuralReasoningDetails>` (details+summary+conteúdo) como irmão, fora da bolha. "
            "`<summary>` permanece primeiro filho direto de `<details>`; mover o bloco inteiro."
        ),
    },
    {
        "topic": "Reforço — a11y e CSS RemoteApp details",
        "question": (
            "Como implementar acordeão exclusivo no ObserverPanel e estilizar summary sem "
            "quebrar teclado, SR e prefers-reduced-motion?"
        ),
        "answer": (
            "Atributo `name=\"remote_app-observer-reasoning\"` em todos os details de raciocínio — "
            "acordeão exclusivo nativo. CSS `.remote_app-details`: esconder marker; indicador em "
            "`summary::after`; foco visível no summary. "
            "`@media (prefers-reduced-motion: reduce)`: `animation: none` no conteúdo revelado."
        ),
    },
    {
        "topic": "Reforço — cenário especialista disclosure",
        "question": (
            "Checklist de 5 passos para refatorar disclosures no RemoteApp sem regressão "
            "em chat, observador e a11y."
        ),
        "answer": (
            "1) Localizar com `rg '<details'` e NeuralReasoningDetails; "
            "2) Validar summary primeiro filho; "
            "3) Chat: raciocínio abaixo do time, fora da bolha; "
            "4) Observer: name para acordeão exclusivo; "
            "5) CSS motion seguro + teste toggle teclado/SR."
        ),
    },
]


def create_reinforce_weak_quiz() -> dict[str, Any]:
    """Cria quizzes de reforço (spaced repetition)."""
    result = quiz_core.insert_curriculum_questions(REINFORCE_WEAK_QUESTIONS)
    return {
        "topic": "Reforço — áreas fracas Backend + Details",
        "total": result["total"],
        "skipped": result.get("skipped", 0),
        "questions": result["questions"],
        "goal": (
            "Validar correção dos tópicos que falharam na avaliação automática de quizzes "
            "Backend Mastery e HTML details/summary."
        ),
    }
