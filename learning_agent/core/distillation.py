"""Knowledge Distillation — teacher (modelo grande/API) → student (modelo local leve)."""

from __future__ import annotations

import json
import re
import time
from typing import Any

import httpx

from learning_agent import db
from learning_agent import rag
from learning_agent import sync
from learning_agent.config import (
    AUTO_DISTILL,
    CHAT_TIMEOUT_SECONDS,
    DISTILL_SOFT_TEMPERATURE,
    DISTILL_TEMPERATURE,
    STUDENT_API_BASE,
    STUDENT_API_KEY,
    STUDENT_MODEL,
    TEACHER_API_BASE,
    TEACHER_API_KEY,
    TEACHER_MODEL,
)
from learning_agent.core import graph as graph_core
from learning_agent.core import knowledge, proofs

TEACHER_SYSTEM = """Você é o modelo professor em um pipeline de Knowledge Distillation.
Gere conhecimento rico e estruturado sobre o tópico pedido.
Responda APENAS com JSON válido neste formato:
{
  "summary": "resumo técnico completo em markdown",
  "key_concepts": ["conceito1", "conceito2"],
  "examples": ["exemplo de código ou uso"],
  "pitfalls": ["erro comum"],
  "soft_labels": {
    "conceito_relacionado": 0.0-1.0
  }
}
soft_labels deve ter 3-6 conceitos relacionados com pesos que somam ~1.0 (distribuição suave)."""

STUDENT_SYSTEM = """Você é o modelo aluno em Knowledge Distillation.
Recebe a saída do professor (soft labels + resumo) e produz uma versão
condensada mas correta, como se estivesse aprendendo do professor.
Responda em markdown, em português, de forma direta — no máximo 350 palavras.
Foque nos pontos essenciais; não repita o enunciado."""


def _chat_complete(
    *,
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict[str, str]],
    temperature: float,
    max_tokens: int | None = None,
    timeout: float | None = None,
    max_retries: int = 4,
) -> str:
    effective_timeout = CHAT_TIMEOUT_SECONDS if timeout is None else timeout
    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }
    if max_tokens and max_tokens > 0:
        payload["max_tokens"] = max_tokens

    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            with httpx.Client(timeout=effective_timeout) as client:
                response = client.post(url, json=payload, headers=headers)
                if response.status_code in {429, 503, 502} and attempt < max_retries - 1:
                    retry_after = response.headers.get("Retry-After")
                    delay = float(retry_after) if retry_after and retry_after.isdigit() else min(2.0 ** attempt, 30.0)
                    time.sleep(delay)
                    continue
                response.raise_for_status()
                data = response.json()
            content = data["choices"][0]["message"]["content"]
            if not isinstance(content, str):
                raise ValueError("Resposta do modelo sem conteúdo textual")
            return content.strip()
        except httpx.HTTPStatusError as exc:
            last_exc = exc
            if exc.response.status_code in {429, 503, 502} and attempt < max_retries - 1:
                time.sleep(min(2.0 ** (attempt + 1), 30.0))
                continue
            raise
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last_exc = exc
            if attempt < max_retries - 1:
                time.sleep(min(2.0 ** attempt, 15.0))
                continue
            raise
    if last_exc:
        raise last_exc
    raise RuntimeError("_chat_complete failed without exception")


def _parse_teacher_json(raw: str) -> dict[str, Any]:
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    return {
        "summary": raw,
        "key_concepts": [],
        "examples": [],
        "pitfalls": [],
        "soft_labels": {},
    }


def teacher_configured() -> bool:
    return bool(TEACHER_API_KEY and TEACHER_MODEL)


def student_configured() -> bool:
    return bool(STUDENT_MODEL)


def is_configured() -> bool:
    return teacher_configured() and student_configured()


def get_status() -> dict[str, Any]:
    db.init_db()
    with db.get_connection() as conn:
        count = conn.execute("SELECT COUNT(*) FROM distillation_pairs").fetchone()[0]

    return {
        "configured": is_configured(),
        "auto_distill": AUTO_DISTILL,
        "teacher": {
            "model": TEACHER_MODEL,
            "base_url": TEACHER_API_BASE,
            "configured": teacher_configured(),
        },
        "student": {
            "model": STUDENT_MODEL,
            "base_url": STUDENT_API_BASE,
            "configured": student_configured(),
        },
        "pairs_count": count,
    }


def compute_similarity(teacher_text: str, student_text: str) -> float:
    """Similaridade lexical simples (proxy da soft loss)."""
    def tokens(text: str) -> set[str]:
        return {w.lower() for w in re.findall(r"\w{4,}", text)}

    t = tokens(teacher_text)
    s = tokens(student_text)
    if not t or not s:
        return 0.0
    return round(len(t & s) / len(t | s), 4)


def _store_pair(
    topic: str,
    source_ref: str,
    teacher_output: str,
    student_output: str,
    soft_labels: dict[str, Any],
    similarity: float,
    *,
    teacher_model: str | None = None,
) -> int:
    db.init_db()
    now = db._utcnow()
    with db.get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO distillation_pairs (
                topic, source_ref, teacher_output, student_output,
                soft_labels, similarity_score, teacher_model, student_model, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                topic,
                source_ref,
                teacher_output,
                student_output,
                json.dumps(soft_labels, ensure_ascii=False),
                similarity,
                teacher_model or TEACHER_MODEL,
                STUDENT_MODEL,
                now,
            ),
        )
        return int(cursor.lastrowid)


def teacher_generate(topic: str, context: str = "") -> dict[str, Any]:
    if not teacher_configured():
        raise ValueError("Teacher não configurado — defina TEACHER_API_KEY e TEACHER_MODEL no .env")

    user_msg = f"Tópico: {topic}"
    if context:
        user_msg += f"\n\nContexto existente:\n{context[:6000]}"

    raw = _chat_complete(
        base_url=TEACHER_API_BASE,
        api_key=TEACHER_API_KEY,
        model=TEACHER_MODEL,
        messages=[
            {"role": "system", "content": TEACHER_SYSTEM},
            {"role": "user", "content": user_msg},
        ],
        temperature=DISTILL_SOFT_TEMPERATURE,
    )
    parsed = _parse_teacher_json(raw)
    summary = parsed.get("summary", raw)
    soft_labels = parsed.get("soft_labels", {})
    if not isinstance(soft_labels, dict):
        soft_labels = {}

    teacher_doc = {
        "summary": summary,
        "key_concepts": parsed.get("key_concepts", []),
        "examples": parsed.get("examples", []),
        "pitfalls": parsed.get("pitfalls", []),
        "soft_labels": soft_labels,
        "raw": raw,
    }
    return teacher_doc


def student_distill(topic: str, teacher_doc: dict[str, Any], context: str = "") -> str:
    if not student_configured():
        raise ValueError("Student não configurado — defina STUDENT_MODEL e STUDENT_API_BASE no .env")

    soft = json.dumps(teacher_doc.get("soft_labels", {}), ensure_ascii=False, indent=2)
    teacher_summary = teacher_doc.get("summary", "")

    user_msg = (
        f"Tópico: {topic}\n\n"
        f"## Saída do professor (soft target)\n{teacher_summary}\n\n"
        f"## Soft labels (pesos dos conceitos)\n{soft}\n\n"
    )
    if context:
        user_msg += f"## Contexto adicional\n{context[:3000]}\n"

    user_msg += "\nProduza sua versão destilada (aluno)."

    return _chat_complete(
        base_url=STUDENT_API_BASE,
        api_key=STUDENT_API_KEY,
        model=STUDENT_MODEL,
        messages=[
            {"role": "system", "content": STUDENT_SYSTEM},
            {"role": "user", "content": user_msg},
        ],
        temperature=DISTILL_TEMPERATURE,
        max_tokens=350,
        timeout=CHAT_TIMEOUT_SECONDS,
    )


def distill_topic(
    topic: str,
    context: str = "",
    source_ref: str = "",
    tags: list[str] | None = None,
    sync_cloud: bool = True,
) -> dict[str, Any]:
    """Pipeline completo: teacher → student → armazena → indexa → nota."""
    if not is_configured():
        status = get_status()
        raise ValueError(
            "Distillation não configurada. "
            f"teacher={status['teacher']['configured']}, student={status['student']['configured']}"
        )

    if not context:
        hits = rag.search_knowledge(topic, limit=3)
        if hits:
            context = "\n\n".join(h["content"][:1500] for h in hits)

    teacher_doc = teacher_generate(topic, context)
    teacher_text = json.dumps(teacher_doc, ensure_ascii=False, indent=2)
    student_text = student_distill(topic, teacher_doc, context)
    similarity = compute_similarity(teacher_doc.get("summary", ""), student_text)

    pair_id = _store_pair(
        topic=topic,
        source_ref=source_ref,
        teacher_output=teacher_text,
        student_output=student_text,
        soft_labels=teacher_doc.get("soft_labels", {}),
        similarity=similarity,
    )

    if teacher_doc.get("soft_labels"):
        graph_core.add_edges_from_soft_labels(topic, teacher_doc["soft_labels"], f"distill:{pair_id}")

    tag_list = tags or ["distillation", "knowledge-distillation"]
    note = knowledge.add_note(
        title=f"[Distilled] {topic}",
        content=(
            f"## Versão aluno (destilada)\n{student_text}\n\n"
            f"---\n"
            f"**Similaridade com professor:** {similarity}\n"
            f"**Soft labels:** {json.dumps(teacher_doc.get('soft_labels', {}), ensure_ascii=False)}\n"
            f"**Pair ID:** {pair_id}"
        ),
        tags=tag_list,
        sync_cloud=sync_cloud,
    )

    rag.index_document(
        f"distill:teacher:{pair_id}",
        teacher_doc.get("summary", teacher_text),
        {"type": "distillation_teacher", "topic": topic, "pair_id": str(pair_id)},
    )
    rag.index_document(
        f"distill:student:{pair_id}",
        student_text,
        {"type": "distillation_student", "topic": topic, "pair_id": str(pair_id)},
    )

    result: dict[str, Any] = {
        "success": True,
        "pair_id": pair_id,
        "topic": topic,
        "teacher_model": TEACHER_MODEL,
        "student_model": STUDENT_MODEL,
        "similarity_score": similarity,
        "soft_labels": teacher_doc.get("soft_labels", {}),
        "student_preview": student_text[:500],
        "note_id": note.get("note_id"),
        "verified": note.get("verified"),
    }
    if sync_cloud:
        result = sync.attach_cloud_sync(result)
    return proofs.attach_proofs(result)


def distill_from_teacher_content(
    topic: str,
    teacher_content: str,
    *,
    context: str = "",
    source_ref: str = "cursor",
    teacher_model: str = "cursor",
    tags: list[str] | None = None,
    sync_cloud: bool = False,
) -> dict[str, Any]:
    """Destilação com professor externo (ex.: Cursor Sonnet/Opus) — só o aluno local roda."""
    if not student_configured():
        raise ValueError("Student não configurado — defina STUDENT_MODEL e STUDENT_API_BASE no .env")

    teacher_doc = {
        "summary": teacher_content.strip(),
        "key_concepts": [],
        "examples": [],
        "pitfalls": [],
        "soft_labels": {},
        "raw": teacher_content,
        "source": teacher_model,
    }
    student_text = student_distill(topic, teacher_doc, context)
    similarity = compute_similarity(teacher_doc["summary"], student_text)

    pair_id = _store_pair(
        topic=topic,
        source_ref=source_ref,
        teacher_output=teacher_content,
        student_output=student_text,
        soft_labels={},
        similarity=similarity,
        teacher_model=teacher_model,
    )

    tag_list = tags or ["distillation", "cursor-teacher", "knowledge-distillation"]
    note = knowledge.add_note(
        title=f"[Distilled/Cursor] {topic}",
        content=(
            f"## Professor ({teacher_model})\n{teacher_content[:3000]}\n\n"
            f"## Versão aluno (destilada)\n{student_text}\n\n"
            f"**Similaridade:** {similarity}\n**Pair ID:** {pair_id}"
        ),
        tags=tag_list,
        sync_cloud=sync_cloud,
    )

    rag.index_document(
        f"distill:teacher:{pair_id}",
        teacher_doc["summary"],
        {"type": "distillation_teacher", "topic": topic, "pair_id": str(pair_id), "source": teacher_model},
    )
    rag.index_document(
        f"distill:student:{pair_id}",
        student_text,
        {"type": "distillation_student", "topic": topic, "pair_id": str(pair_id)},
    )

    return proofs.attach_proofs(
        {
            "success": True,
            "pair_id": pair_id,
            "topic": topic,
            "teacher_model": teacher_model,
            "student_model": STUDENT_MODEL,
            "similarity_score": similarity,
            "student_preview": student_text[:500],
            "note_id": note.get("note_id"),
            "verified": note.get("verified"),
            "source": "cursor_teacher",
        }
    )


def distill_from_note(note_id: int, sync_cloud: bool = True) -> dict[str, Any]:
    db.init_db()
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT id, title, content FROM learning_notes WHERE id = ?",
            (note_id,),
        ).fetchone()
    if not row:
        raise ValueError(f"Nota {note_id} não encontrada")

    return distill_topic(
        topic=row["title"],
        context=row["content"],
        source_ref=f"note:{note_id}",
        tags=["distillation", "from-note"],
        sync_cloud=sync_cloud,
    )


def list_pairs(limit: int = 20) -> list[dict[str, Any]]:
    db.init_db()
    with db.get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, topic, similarity_score, teacher_model, student_model, created_at
            FROM distillation_pairs
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def maybe_auto_distill(topic: str, content: str, source_ref: str = "") -> dict[str, Any] | None:
    if not AUTO_DISTILL or not is_configured():
        return None
    try:
        return distill_topic(topic, context=content, source_ref=source_ref, sync_cloud=True)
    except Exception:
        return None
