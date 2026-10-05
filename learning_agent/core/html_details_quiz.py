"""Quizzes — HTML details/summary mastery (Fase A + B)."""

from __future__ import annotations

from typing import Any

from learning_agent.core import quiz as quiz_core

HTML_DETAILS_QUESTIONS: list[dict[str, str]] = [
    {
        "topic": "Details — estrutura DOM",
        "question": (
            "Qual a regra estrutural obrigatória entre `<details>` e `<summary>` e por que "
            "envolver o summary em um `<div>` intermediário quebra o disclosure nativo?"
        ),
        "answer": (
            "`<summary>` deve ser o primeiro filho direto de `<details>`. "
            "Wrappers entre `details` e `summary` impedem o algoritmo de disclosure do HTML "
            "de associar o summary ao widget; o toggle deixa de funcionar ou comporta-se de forma inconsistente."
        ),
    },
    {
        "topic": "Details — localizar no RemoteApp",
        "question": (
            "Como localizar todos os disclosures no frontend Ravenna sem ruído de `summary` "
            "em APIs Python (progress.summary, record_session)?"
        ),
        "answer": (
            "Buscar `<details`, `</details>`, ou o componente `NeuralReasoningDetails`. "
            "Evitar grep isolado em `summary`. Paths: ChatPanel.tsx, ObserverPanel.tsx, "
            "NeuralReasoningDetails.tsx, globals.css (.remote_app-details)."
        ),
    },
    {
        "topic": "Details — realocar no chat",
        "question": (
            "No ChatPanel RemoteApp, mover o raciocínio neural para fora da bolha da mensagem, "
            "abaixo do timestamp. Qual árvore DOM final válida?"
        ),
        "answer": (
            "Dentro do container da mensagem Ravenna: `div.bubble` com `<p>` do conteúdo; "
            "`<time>`; depois `<NeuralReasoningDetails>` (details+summary+conteúdo) como irmão, "
            "não dentro da bolha. O bloco details inteiro se move; summary permanece primeiro filho."
        ),
    },
    {
        "topic": "Details — componente React",
        "question": (
            "Por que extrair `NeuralReasoningDetails` em vez de duplicar `<details>` no Chat e Observer?"
        ),
        "answer": (
            "Um único ponto para classes RemoteApp (.remote_app-details), a11y do summary, prop `name` "
            "para acordeão exclusivo, e testes. Evita divergência ao realocar markup e facilita "
            "search_code encontrar o padrão."
        ),
    },
    {
        "topic": "Details — acordeão exclusivo",
        "question": (
            "No ObserverPanel com várias mensagens com raciocínio, como garantir que abrir um "
            "raciocínio feche os outros sem JavaScript?"
        ),
        "answer": (
            "Atributo `name` compartilhado em todos os `<details>` do grupo, ex.: "
            "`name=\"remote_app-observer-reasoning\"`. O comportamento é nativo do HTML; "
            "só um details com o mesmo name fica aberto por vez."
        ),
    },
    {
        "topic": "Details — a11y teclado e SR",
        "question": (
            "Quais garantias de acessibilidade o disclosure nativo oferece vs um `div` com "
            "`onClick` e `aria-expanded` manual?"
        ),
        "answer": (
            "Summary é focável, ativável por Enter/Espaço, semântica de disclosure embutida. "
            "Leitores de tela anunciam expandido/recolhido. Implementação manual exige "
            "sincronizar aria-expanded, id de controls, foco e teclado — maior risco de regressão."
        ),
    },
    {
        "topic": "Details — CSS marker RemoteApp",
        "question": (
            "Como estilizar o summary do RemoteApp removendo o triângulo padrão e indicando aberto/fechado "
            "sem quebrar acessibilidade?"
        ),
        "answer": (
            "`summary { list-style: none; cursor: pointer }`, esconder `::-webkit-details-marker`, "
            "adicionar `summary::after` com rotação em `details[open]`. Manter contraste e "
            "foco visível; não remover o summary do tab order."
        ),
    },
    {
        "topic": "Details — motion reduzido",
        "question": (
            "Animar abertura com `::details-content` no RemoteApp. O que fazer em "
            "`prefers-reduced-motion: reduce`?"
        ),
        "answer": (
            "Manter toggle instantâneo; desabilitar keyframes em `::details-content` "
            "(`animation: none`). Preservar cores/layout; não remover o widget, só o motion decorativo."
        ),
    },
    {
        "topic": "Details — estado controlado",
        "question": (
            "Quando usar `open` controlado em React em `<details>` no chat Ravenna e qual o handler correto?"
        ),
        "answer": (
            "Só quando estado externo deve forçar aberto/fechado (ex.: deep-link, tutorial). "
            "`<details open={open} onToggle={(e) => setOpen(e.currentTarget.open)}>`. "
            "Chat padrão: não controlado — menos efeitos e comportamento nativo."
        ),
    },
    {
        "topic": "Details — cenário especialista",
        "question": (
            "Ravenna deve mover raciocínio do observador para details exclusivos, estilizar com "
            ".remote_app-details, e passar axe-core. Liste a ordem de implementação segura."
        ),
        "answer": (
            "1) Criar/estender NeuralReasoningDetails com name + classes; 2) ObserverPanel trocar "
            "`<p>` italic por componente; 3) globals.css .remote_app-details + reduced-motion; "
            "4) search_code validar únicos `<details`; 5) teste manual teclado; 6) quizzes Details."
        ),
    },
]


def create_html_details_quiz() -> dict[str, Any]:
    """Cria quizzes HTML details/summary (spaced repetition)."""
    result = quiz_core.insert_curriculum_questions(HTML_DETAILS_QUESTIONS)
    return {
        "topic": "HTML details/summary — maestria Ravenna",
        "total": result["total"],
        "skipped": result.get("skipped", 0),
        "questions": result["questions"],
        "goal": (
            "Validar localização, realocação, a11y, CSS e padrões React de "
            "<details>/<summary> no RemoteApp IDE."
        ),
    }
