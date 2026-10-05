"""Percorre todo o currículo: gera material, notas, quizzes e responde corretamente."""

import re
from pathlib import Path

from learning_agent import db
from learning_agent.config import DOCS_PATH
from learning_agent.core import curriculum, indexing, knowledge, quiz

SUMMARY_TEMPLATES: dict[str, str] = {
    "python": "Conceito fundamental de Python relacionado a {title}. Prática com exemplos e exercícios.",
    "javascript": "Conceito fundamental de JavaScript relacionado a {title}.",
    "git": "Prática de controle de versão: {title}.",
    "sql": "Conceito de banco de dados SQL: {title}.",
    "web": "Conceito web/API: {title}.",
    "algoritmos": "Conceito de algoritmos e estruturas: {title}.",
    "arquitetura": "Boas práticas e arquitetura: {title}.",
    "ferramentas": "Ferramenta e workflow de desenvolvimento: {title}.",
    "projeto": "Projeto prático aplicando: {title}.",
}


def _slugify(title: str) -> str:
    slug = title.lower()
    slug = re.sub(r"[^\w\s-]", "", slug, flags=re.UNICODE)
    slug = re.sub(r"[\s_]+", "-", slug).strip("-")
    return slug[:80] or "topico"


def _level_dir(level: str) -> str:
    match = re.search(r"(\d+)", level)
    num = match.group(1) if match else "0"
    return f"nivel-{num}"


def _generate_content(topic: dict) -> str:
    title = topic["title"]
    level = topic["level"]
    tags = ", ".join(topic["tags"])
    primary_tag = topic["tags"][0] if topic["tags"] else "geral"
    template = SUMMARY_TEMPLATES.get(primary_tag, "Conceito de programação: {title}.")
    summary = template.format(title=title)

    return f"""# {title}

**Nível:** {level}  
**Tags:** {tags}

## Conceito

{summary}

## Pontos-chave

- Definição e propósito de **{title}**
- Quando usar na prática
- Erros comuns a evitar

## Exemplo

```python
# Exemplo ilustrativo — {title}
# (expandir com prática real durante estudo guiado)
```

## Referências

- Material gerado pelo learning-agent bootstrap
- Tópico {topic['index']} do currículo
"""


def _create_topic_quiz(topic: dict) -> int:
    title = topic["title"]
    primary_tag = topic["tags"][0] if topic["tags"] else "general"
    question = f"Qual o conceito central de '{title}'?"
    answer = f"Conceitos fundamentais de {title}, aplicados em {primary_tag}."

    now = db._utcnow()
    with db.get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO quiz_items (topic, question, answer, next_review, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (primary_tag, question, answer, now, now),
        )
        return cursor.lastrowid


def run_bootstrap(skip_existing: bool = True) -> dict:
    db.init_db()
    topics = curriculum._parse_curriculum()
    studied_titles, _ = curriculum.get_studied_data()

    stats = {
        "topics_total": len(topics),
        "notes_created": 0,
        "docs_created": 0,
        "quizzes_answered": 0,
        "skipped": 0,
    }

    for topic in topics:
        norm = curriculum._normalize(topic["title"])
        if skip_existing and norm in studied_titles:
            stats["skipped"] += 1
            continue

        # 1. Gerar e salvar material
        level_dir = DOCS_PATH / _level_dir(topic["level"])
        level_dir.mkdir(parents=True, exist_ok=True)
        doc_path = level_dir / f"{_slugify(topic['title'])}.md"
        if not doc_path.exists():
            doc_path.write_text(_generate_content(topic), encoding="utf-8")
            stats["docs_created"] += 1

        indexing.index_file(doc_path, topic["tags"])

        # 2. Registrar nota
        knowledge.add_note(
            topic["title"],
            f"Estudado: {topic['title']}. Nível: {topic['level']}. "
            f"Tags: {', '.join(topic['tags'])}.",
            topic["tags"],
        )
        stats["notes_created"] += 1
        studied_titles.add(norm)

        # 3. Quiz específico do tópico + resposta correta
        quiz_id = _create_topic_quiz(topic)
        quiz.record_answer(quiz_id, correct=True, response="Resposta correta (bootstrap automático).")
        stats["quizzes_answered"] += 1

    # Responder quizzes pendentes antigos
    with db.get_connection() as conn:
        pending = conn.execute(
            """
            SELECT qi.id FROM quiz_items qi
            LEFT JOIN quiz_attempts qa ON qa.quiz_item_id = qi.id
            WHERE qa.id IS NULL
            """
        ).fetchall()
    for row in pending:
        quiz.record_answer(row["id"], correct=True, response="Resposta correta (bootstrap automático).")
        stats["quizzes_answered"] += 1

    stats["final"] = curriculum.get_next_topic()
    stats["overview"] = curriculum.get_curriculum_overview()
    return stats


def main() -> None:
    import json

    print("Iniciando bootstrap do currículo completo...")
    result = run_bootstrap()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
