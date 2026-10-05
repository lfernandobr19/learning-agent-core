import os
from pathlib import Path
from typing import Any

import chromadb
from chromadb.utils import embedding_functions

from learning_agent.config import CHROMA_PATH

COLLECTION_NAME = "knowledge"

# Embedding function:
# - "default" (padrão): EF nativa do ChromaDB (onnxruntime). Consistente com a
#   coleção já persistida e evita carregar o torch.
# - "sentence-transformers": só quando RAG_EMBEDDINGS=sentence-transformers.
#
# IMPORTANTE (Windows): carregar torch (sentence-transformers) E onnxruntime
# (EF default) no mesmo processo duplica o runtime OpenMP (libiomp5md.dll) e
# causa access violation (0xC0000005). Por isso usamos UM backend só.
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

_EMBEDDINGS_BACKEND = os.environ.get("RAG_EMBEDDINGS", "default").strip().lower()

# Cache em nível de módulo: recriar client/EF a cada chamada é lento e pode
# causar access violations no Windows quando repetido no mesmo processo.
_client: Any = None
_embedding_fn: Any = None
_collection: Any = None


def _get_embedding_function():
    global _embedding_fn
    if _embedding_fn is not None:
        return _embedding_fn
    if _EMBEDDINGS_BACKEND in {"sentence-transformers", "st", "sbert"}:
        try:
            _embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
                model_name="all-MiniLM-L6-v2"
            )
            return _embedding_fn
        except Exception:
            pass
    _embedding_fn = embedding_functions.DefaultEmbeddingFunction()
    return _embedding_fn


def _get_client():
    global _client
    if _client is None:
        _client = chromadb.PersistentClient(path=str(CHROMA_PATH))
    return _client


def get_collection():
    global _collection
    if _collection is not None:
        return _collection

    client = _get_client()
    try:
        _collection = client.get_or_create_collection(
            name=COLLECTION_NAME,
            embedding_function=_get_embedding_function(),
            metadata={"hnsw:space": "cosine"},
        )
    except ValueError:
        # ChromaDB recente recusa trocar a embedding function de uma coleção já
        # persistida. Reaproveita a coleção existente com a EF que ela gravou.
        _collection = client.get_collection(name=COLLECTION_NAME)
    return _collection


def index_document(
    doc_id: str,
    content: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    if chroma_disabled():
        return
    collection = get_collection()
    meta = metadata or {}
    collection.upsert(
        ids=[doc_id],
        documents=[content],
        metadatas=[{k: str(v) for k, v in meta.items()}],
    )


def index_file(path: Path, tags: list[str] | None = None) -> str:
    content = path.read_text(encoding="utf-8", errors="replace")
    doc_id = f"file:{path.name}"
    index_document(
        doc_id,
        content,
        {
            "source": str(path),
            "filename": path.name,
            "tags": ",".join(tags or []),
        },
    )
    return doc_id


def chroma_disabled() -> bool:
    return os.environ.get("RAG_DISABLE_CHROMA", "").lower() in {"1", "true", "yes", "on"}


def search_knowledge(query: str, limit: int = 5) -> list[dict[str, Any]]:
    if chroma_disabled():
        return []
    collection = get_collection()
    if collection.count() == 0:
        return []

    results = collection.query(query_texts=[query], n_results=min(limit, collection.count()))
    items: list[dict[str, Any]] = []
    for i, doc_id in enumerate(results["ids"][0]):
        items.append(
            {
                "id": doc_id,
                "content": results["documents"][0][i],
                "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
                "distance": results["distances"][0][i] if results.get("distances") else None,
            }
        )
    return items


def list_all_documents() -> list[dict[str, Any]]:
    if chroma_disabled():
        return []
    collection = get_collection()
    if collection.count() == 0:
        return []
    data = collection.get()
    items: list[dict[str, Any]] = []
    for i, doc_id in enumerate(data["ids"]):
        items.append(
            {
                "id": doc_id,
                "content": data["documents"][i] if data["documents"] else "",
                "metadata": data["metadatas"][i] if data["metadatas"] else {},
            }
        )
    return items
