"""Fontes externas — GitHub repos, RSS/changelogs."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any
from urllib.parse import urlparse

import httpx

from learning_agent.config import GITHUB_TOKEN
from learning_agent.core import knowledge, web
from learning_agent.core import proofs


def _github_headers() -> dict[str, str]:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "ravenna-learning-agent"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    return headers


def _parse_github_url(url: str) -> tuple[str, str] | None:
    parsed = urlparse(url)
    if "github.com" not in parsed.netloc:
        return None
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) < 2:
        return None
    return parts[0], parts[1]


def learn_from_repo(url: str, tags: list[str] | None = None) -> dict[str, Any]:
    """Aprende de um repositório GitHub: README + descrição."""
    parsed = _parse_github_url(url)
    if not parsed:
        raise ValueError("URL GitHub inválida — use https://github.com/owner/repo")

    owner, repo = parsed
    tag_list = tags or ["github", "repo", owner, repo]

    with httpx.Client(timeout=30.0, headers=_github_headers()) as client:
        meta_resp = client.get(f"https://api.github.com/repos/{owner}/{repo}")
        meta_resp.raise_for_status()
        meta = meta_resp.json()

        readme_content = ""
        readme_resp = client.get(f"https://api.github.com/repos/{owner}/{repo}/readme")
        if readme_resp.status_code == 200:
            import base64

            readme_content = base64.b64decode(readme_resp.json()["content"]).decode("utf-8", errors="replace")

    title = f"GitHub: {owner}/{repo}"
    summary = (
        f"# {meta.get('full_name')}\n\n"
        f"**Descrição:** {meta.get('description') or 'N/A'}\n\n"
        f"**Linguagem:** {meta.get('language') or 'N/A'}\n"
        f"**Stars:** {meta.get('stargazers_count', 0)}\n\n"
        f"## README\n\n{readme_content[:12000]}"
    )

    note = knowledge.add_note(title, summary, tag_list)
    return proofs.attach_proofs(
        {
            "success": True,
            "source": url,
            "title": title,
            "note_id": note.get("note_id"),
            "language": meta.get("language"),
            "stars": meta.get("stargazers_count"),
        }
    )


def learn_from_rss(feed_url: str, limit: int = 5, tags: list[str] | None = None) -> dict[str, Any]:
    """Aprende dos últimos itens de um feed RSS/Atom."""
    tag_list = tags or ["rss", "feed"]

    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        response = client.get(feed_url)
        response.raise_for_status()
        xml_text = response.text

    root = ET.fromstring(xml_text)
    items: list[dict[str, str]] = []

    for item in root.iter():
        if item.tag.endswith("item") or item.tag.endswith("entry"):
            title = ""
            link = ""
            desc = ""
            for child in item:
                local = child.tag.split("}")[-1]
                if local == "title":
                    title = (child.text or "").strip()
                elif local in ("link", "id"):
                    link = child.text or child.get("href", "")
                elif local in ("description", "summary", "content"):
                    desc = (child.text or "").strip()
            if title:
                items.append({"title": title, "link": link, "description": desc[:2000]})

    learned: list[dict[str, Any]] = []
    for item in items[:limit]:
        if item.get("link") and item["link"].startswith("http"):
            try:
                result = web.fetch_and_learn(item["link"], title=item["title"], tags=tag_list)
                learned.append(result)
            except Exception as exc:
                note = knowledge.add_note(
                    f"RSS: {item['title'][:80]}",
                    item.get("description") or item["title"],
                    tag_list,
                )
                learned.append({"title": item["title"], "note_id": note.get("note_id"), "error": str(exc)})
        else:
            note = knowledge.add_note(
                f"RSS: {item['title'][:80]}",
                item.get("description") or item["title"],
                tag_list,
            )
            learned.append({"title": item["title"], "note_id": note.get("note_id")})

    return proofs.attach_proofs(
        {
            "success": True,
            "feed": feed_url,
            "items_found": len(items),
            "learned": learned,
        }
    )
