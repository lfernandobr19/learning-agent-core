import html
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from learning_agent.config import DOCS_PATH
from learning_agent.core import indexing, knowledge
from learning_agent import sync
from learning_agent.core import proofs
from learning_agent.identity import RAVENNA_SYSTEM_BRIEF

WEB_DOCS_DIR = DOCS_PATH / "web"
MAX_DOWNLOAD_BYTES = 2_000_000
MAX_TEXT_CHARS = 80_000
USER_AGENT = "LearningAgent/0.1 (local research bot)"

# Domínios priorizados na busca automática Telegram
TRUSTED_DOMAIN_SUFFIXES: tuple[str, ...] = (
    ".gov.br",
    "bcb.gov.br",
    "anbima.com.br",
    "b3.com.br",
    "cvm.gov.br",
    "reuters.com",
    "valor.globo.com",
    "infomoney.com.br",
    "investopedia.com",
    "wikipedia.org",
    "docs.python.org",
    "developer.mozilla.org",
    "fastapi.tiangolo.com",
    "openstreetmap.org",
    "github.com",
    "stackoverflow.com",
    "learn.microsoft.com",
    "home-assistant.io",
    "tailscale.com",
    "ollama.com",
    "pwa.dev",
)


def _domain_trust_score(url: str) -> int:
    host = urlparse(url or "").netloc.lower()
    if not host:
        return 0
    best = 0
    for i, suffix in enumerate(TRUSTED_DOMAIN_SUFFIXES):
        if host == suffix.lstrip(".") or host.endswith(suffix) or suffix in host:
            best = max(best, len(TRUSTED_DOMAIN_SUFFIXES) - i)
    return best


def search_trusted_web(query: str, *, limit: int = 4, fetch_limit: int = 12) -> list[dict[str, Any]]:
    """DuckDuckGo com prioridade para fontes confiáveis."""
    raw = search_web(query, limit=max(fetch_limit, limit))
    ranked = sorted(
        raw,
        key=lambda item: (_domain_trust_score(item.get("url", "")), item.get("title", "")),
        reverse=True,
    )
    picked: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in ranked:
        url = (item.get("url") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        picked.append(item)
        if len(picked) >= limit:
            break
    return picked


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._chunks: list[str] = []
        self._skip = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "nav", "footer", "header", "noscript"}:
            self._skip = True

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "nav", "footer", "header", "noscript"}:
            self._skip = False
        if tag in {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "tr"}:
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            text = data.strip()
            if text:
                self._chunks.append(text + " ")

    def get_text(self) -> str:
        raw = "".join(self._chunks)
        raw = re.sub(r"[ \t]+", " ", raw)
        raw = re.sub(r"\n{3,}", "\n\n", raw)
        return raw.strip()


def _slugify(text: str, max_len: int = 80) -> str:
    slug = text.lower()
    slug = re.sub(r"https?://", "", slug)
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug).strip("-")
    return slug[:max_len] or "pagina-web"


def _extract_title(html_content: str) -> str | None:
    match = re.search(r"<title[^>]*>(.*?)</title>", html_content, re.IGNORECASE | re.DOTALL)
    if not match:
        return None
    title = html.unescape(re.sub(r"\s+", " ", match.group(1)).strip())
    return title[:200] if title else None


def _html_to_text(html_content: str) -> str:
    parser = _HTMLTextExtractor()
    parser.feed(html_content)
    return parser.get_text()


def fetch_url_content(url: str, timeout: float = 30.0) -> dict[str, Any]:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("URL deve começar com http:// ou https://")

    headers = {"User-Agent": USER_AGENT, "Accept": "text/html,application/json,text/plain,*/*"}

    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        response = client.get(url, headers=headers)
        response.raise_for_status()

        content_type = response.headers.get("content-type", "").lower()
        raw = response.content[:MAX_DOWNLOAD_BYTES]

        if "html" in content_type or raw.strip()[:15].lower().startswith(b"<!doctype") or b"<html" in raw[:500].lower():
            html_content = raw.decode(response.encoding or "utf-8", errors="replace")
            title = _extract_title(html_content) or parsed.netloc
            text = _html_to_text(html_content)
            format_type = "html"
        elif "json" in content_type:
            text = raw.decode("utf-8", errors="replace")
            title = parsed.path.rstrip("/").split("/")[-1] or parsed.netloc
            format_type = "json"
        else:
            text = raw.decode("utf-8", errors="replace")
            title = _extract_title(text) if "<title" in text[:2000].lower() else (parsed.path.split("/")[-1] or parsed.netloc)
            if "<html" in text[:500].lower():
                text = _html_to_text(text)
                format_type = "html"
            else:
                format_type = "text"

    if len(text) > MAX_TEXT_CHARS:
        text = text[:MAX_TEXT_CHARS] + "\n\n[... conteúdo truncado ...]"

    if not text.strip():
        raise ValueError("Nenhum conteúdo textual extraído da URL")

    return {
        "url": url,
        "title": title,
        "content": text,
        "format": format_type,
        "chars": len(text),
    }


def fetch_and_learn(
    url: str,
    title: str = "",
    tags: list[str] | None = None,
    auto_sync: bool = True,
) -> dict[str, Any]:
    fetched = fetch_url_content(url)
    page_title = title.strip() or fetched["title"]
    tag_list = tags or ["web", "pesquisa"]
    slug = _slugify(page_title if title else fetched["url"])
    host = urlparse(url).netloc.replace(".", "-")
    if host and host not in slug:
        slug = f"{host}-{_slugify(page_title)}"

    WEB_DOCS_DIR.mkdir(parents=True, exist_ok=True)
    doc_path = WEB_DOCS_DIR / f"{slug}.md"

    # Evitar sobrescrever sem sufixo
    if doc_path.exists():
        base = doc_path.stem
        n = 2
        while doc_path.exists():
            doc_path = WEB_DOCS_DIR / f"{base}-{n}.md"
            n += 1

    summary = fetched["content"][:600].strip()
    if len(fetched["content"]) > 600:
        summary += "..."

    markdown = f"""# {page_title}

**Fonte:** {url}  
**Formato:** {fetched['format']}  
**Tags:** {', '.join(tag_list)}

## Resumo

{summary}

## Conteúdo extraído

{fetched['content']}
"""

    doc_path.write_text(markdown, encoding="utf-8")
    doc_id = indexing.index_file(doc_path, tag_list + ["web-ingest"])

    note = knowledge.add_note(
        page_title,
        f"Aprendido da web: {url}\n\nResumo: {summary}",
        tag_list,
        sync_cloud=auto_sync,
    )

    result = {
        "success": True,
        "url": url,
        "title": page_title,
        "doc_path": str(doc_path.relative_to(DOCS_PATH.parent)),
        "doc_id": doc_id,
        "note_id": note["id"],
        "chars_indexed": fetched["chars"],
        "tags": tag_list,
    }
    if auto_sync:
        result = sync.attach_cloud_sync(result)
    return proofs.attach_proofs(result)


def _get_ddgs_client():
    try:
        from ddgs import DDGS

        return DDGS
    except ImportError:
        try:
            from duckduckgo_search import DDGS

            return DDGS
        except ImportError as exc:
            raise RuntimeError("Instale ddgs: pip install ddgs") from exc


def search_web(query: str, limit: int = 5) -> list[dict[str, Any]]:
    """Search the web via DuckDuckGo (no API key required)."""
    DDGS = _get_ddgs_client()
    limit = max(1, min(limit, 10))
    results: list[dict[str, Any]] = []

    with DDGS() as ddgs:
        for item in ddgs.text(query, max_results=limit):
            results.append(
                {
                    "title": item.get("title", ""),
                    "url": item.get("href", ""),
                    "snippet": item.get("body", ""),
                }
            )

    return results


def format_web_search_telegram(query: str, *, limit: int = 3) -> str:
    """Busca web leve para Telegram — não indexa, só resume resultados."""
    try:
        hits = search_web(query, limit=limit)
    except Exception as exc:
        return f"Busca web falhou: {exc}"

    if not hits:
        return f"Nenhum resultado na web para: {query}"

    lines = [f"Web — «{query}» ({len(hits)} resultados)", ""]
    for i, item in enumerate(hits, 1):
        title = (item.get("title") or "Sem título").strip()
        url = (item.get("url") or "").strip()
        snippet = (item.get("snippet") or "").strip()[:220]
        lines.append(f"{i}. {title}")
        if url:
            lines.append(url)
        if snippet:
            lines.append(snippet)
        lines.append("")
    lines.append("— busca DuckDuckGo (não grava no RAG). Use /learn para indexar.")
    return "\n".join(lines).strip()


def format_trusted_web_telegram(query: str, *, limit: int = 4) -> str:
    """Busca web + síntese Ravenna — fontes confiáveis primeiro."""
    try:
        hits = search_trusted_web(query, limit=limit)
    except Exception as exc:
        return f"Busquei na web mas falhou: {exc}"

    if not hits:
        return format_web_search_telegram(query, limit=limit)

    source_blocks: list[str] = []
    for i, item in enumerate(hits, 1):
        title = (item.get("title") or "Sem título").strip()
        snippet = (item.get("snippet") or "").strip()[:320]
        url = (item.get("url") or "").strip()
        trust = _domain_trust_score(url)
        label = "confiável" if trust > 0 else "web"
        source_blocks.append(f"[{i}] ({label}) {title}\n{snippet}\n{url}")

    summary = ""
    try:
        from learning_agent.core import llm

        summary, _ = llm.chat_with_fallback(
            [
                {
                    "role": "system",
                    "content": (
                        f"{RAVENNA_SYSTEM_BRIEF} "
                        "Responda em português BR usando SOMENTE os trechos numerados. "
                        "Cite fontes como [1], [2]. Máximo ~180 palavras."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Pergunta: {query}\n\nFontes:\n\n" + "\n\n".join(source_blocks),
                },
            ],
            max_tokens=380,
            temperature=0.35,
        )
    except Exception:
        summary = ""

    lines: list[str] = []
    if summary.strip():
        lines.append(summary.strip())
        lines.extend(["", "Fontes:"])
    else:
        lines.append(f"Encontrei isto na web sobre «{query}»:")
        lines.append("")

    for i, item in enumerate(hits, 1):
        title = (item.get("title") or "Sem título").strip()
        url = (item.get("url") or "").strip()
        snippet = (item.get("snippet") or "").strip()[:200]
        lines.append(f"[{i}] {title}")
        if url:
            lines.append(url)
        if snippet and not summary.strip():
            lines.append(snippet)
        lines.append("")

    lines.append("— busca web (fontes confiáveis priorizadas)")
    return "\n".join(lines).strip()


def is_web_consult_request(text: str) -> tuple[bool, str]:
    """Detecta pedido explícito de busca web (prefixo ou /web)."""
    t = text.strip()
    low = t.lower()
    if low.startswith("/web"):
        rest = t.split(maxsplit=1)
        return (True, rest[1].strip() if len(rest) > 1 else "")
    for prefix in (
        "pesquise na web",
        "pesquisa na web",
        "busca na web",
        "busque na web",
        "verifique na web",
        "confira na web",
    ):
        if low.startswith(prefix):
            return (True, t[len(prefix) :].strip(" :—-"))
    return (False, "")


def search_and_learn(
    query: str,
    limit: int = 3,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """Search the web and fetch/index the top results automatically."""
    tag_list = tags or ["web", "pesquisa"]
    search_limit = max(limit, limit + 2)  # busca extra para compensar falhas
    results = search_web(query, limit=min(search_limit, 10))

    if not results:
        return {
            "success": False,
            "query": query,
            "message": "Nenhum resultado encontrado na web",
            "learned": [],
            "errors": [],
        }

    learned: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for item in results:
        if len(learned) >= limit:
            break
        url = item.get("url", "")
        if not url:
            continue
        try:
            entry = fetch_and_learn(
                url, title=item.get("title", ""), tags=tag_list, auto_sync=False
            )
            entry["snippet"] = item.get("snippet", "")
            learned.append(entry)
        except Exception as exc:
            errors.append({"url": url, "title": item.get("title", ""), "error": str(exc)})

    result = {
        "success": len(learned) > 0,
        "query": query,
        "results_found": len(results),
        "learned_count": len(learned),
        "search_results": results,
        "learned": learned,
        "errors": errors,
    }
    if learned:
        result = sync.attach_cloud_sync(result, force=True)
    return proofs.attach_proofs(result)
