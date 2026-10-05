"""Browser headless — navegação web real (Playwright) com fallback HTTP.

Suporta a fonte virtual @web: busca páginas, extrai título e texto legível.
Playwright é preferido (páginas com JS); sem ele, fallback HTTP + strip de HTML.
"""

from __future__ import annotations

import re
from typing import Any

_STRIP_BLOCKS = re.compile(
    r"<script[\s\S]*?</script>|<style[\s\S]*?</style>|<noscript[\s\S]*?</noscript>",
    re.IGNORECASE,
)
_STRIP_TAGS = re.compile(r"<[^>]+>")

_USER_AGENT = "Mozilla/5.0 (compatible; RavennaIDE/1.0; +https://ravenna.local)"


def _extract_title(html: str) -> str:
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else ""


def _html_to_text(html: str) -> str:
    out = _STRIP_BLOCKS.sub(" ", html)
    out = _STRIP_TAGS.sub(" ", out)
    out = out.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    out = re.sub(r"[ \t]+", " ", out)
    out = re.sub(r"\n\s*\n+", "\n", out)
    return out.strip()


def _http_fetch(url: str, timeout: int) -> dict[str, Any]:
    import urllib.request

    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read(2_000_000)
        content_type = resp.headers.get("content-type", "")
    charset = "utf-8"
    if "charset=" in content_type:
        charset = content_type.split("charset=")[-1].split(";")[0].strip() or charset
    try:
        html = raw.decode(charset, errors="replace")
    except Exception:
        html = raw.decode("utf-8", errors="replace")
    return {"title": _extract_title(html), "text": _html_to_text(html), "engine": "http"}


def _playwright_fetch(url: str, timeout: int) -> dict[str, Any]:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto(url, timeout=timeout * 1000, wait_until="domcontentloaded")
            title = page.title()
            text = page.inner_text("body")
        finally:
            browser.close()
    return {"title": title, "text": text, "engine": "playwright"}


def browse_web(url: str, *, max_chars: int = 6000, timeout: int = 20) -> dict[str, Any]:
    """Busca uma página web e retorna título + texto legível."""
    url = (url or "").strip()
    if not re.match(r"^https?://", url):
        return {"success": False, "error": "URL inválida (use http/https)"}

    result: dict[str, Any] | None = None
    errors: list[str] = []
    for fn in (_playwright_fetch, _http_fetch):
        try:
            result = fn(url, timeout)
            break
        except Exception as exc:
            errors.append(f"{fn.__name__}: {exc}")

    if not result:
        return {"success": False, "error": "; ".join(errors) or "falha ao buscar página"}

    text = (result.get("text") or "")[:max_chars]
    return {
        "success": True,
        "url": url,
        "title": result.get("title") or "",
        "engine": result.get("engine"),
        "text": text,
    }


def fetch_web_search(query: str, *, max_chars: int = 4000, timeout: int = 20) -> dict[str, Any]:
    """Busca web simples via DuckDuckGo HTML (sem API key)."""
    from urllib.parse import quote

    q = (query or "").strip()
    if not q:
        return {"success": False, "error": "query obrigatória"}
    url = f"https://html.duckduckgo.com/html/?q={quote(q)}"
    try:
        result = _http_fetch(url, timeout)
    except Exception as exc:
        return {"success": False, "error": str(exc)}
    text = (result.get("text") or "")[:max_chars]
    return {"success": True, "query": q, "title": result.get("title") or "Busca web", "text": text}
