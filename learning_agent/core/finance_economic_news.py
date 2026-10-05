"""Notícias econômicas — RSS + fallback web search para finance-lead."""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

import httpx
import yaml

from learning_agent.config import DOCS_PATH, PROJECT_ROOT
from learning_agent.core import indexing, knowledge

FINANCE_ROOT = PROJECT_ROOT / "agents" / "projects" / "finance-lead"
FEEDS_CFG = FINANCE_ROOT / "config" / "economic_news_feeds.yaml"
NEWS_DIR = DOCS_PATH / "economic-news"
MANIFEST = FINANCE_ROOT / "data" / "economic_news_manifest.json"


def _load_cfg() -> dict[str, Any]:
    if not FEEDS_CFG.is_file():
        return {"feeds": [], "max_items_per_feed": 3, "fallback_search_query": "economia brasil"}
    return yaml.safe_load(FEEDS_CFG.read_text(encoding="utf-8")) or {}


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text).strip()


def _parse_rss(xml_text: str, limit: int) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return items

    ns = {"atom": "http://www.w3.org/2005/Atom"}
    nodes = root.findall(".//item")
    if not nodes:
        nodes = root.findall(".//atom:entry", ns)

    for node in nodes[:limit]:
        title = (
            (node.findtext("title") or node.findtext("atom:title", namespaces=ns) or "").strip()
        )
        link = (node.findtext("link") or "").strip()
        if not link:
            link_el = node.find("atom:link", ns)
            if link_el is not None:
                link = link_el.attrib.get("href", "")
        desc = _strip_html(
            node.findtext("description")
            or node.findtext("summary")
            or node.findtext("atom:summary", namespaces=ns)
            or ""
        )
        pub = (
            node.findtext("pubDate")
            or node.findtext("published")
            or node.findtext("atom:published", namespaces=ns)
            or ""
        )
        if title:
            items.append({"title": title[:200], "link": link, "summary": desc[:800], "published": pub})
    return items


def _fetch_feed(url: str, timeout: float = 20.0) -> list[dict[str, str]]:
    headers = {"User-Agent": "Ravenna-Finance-Lead/1.0 (RSS research)"}
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        r = client.get(url, headers=headers)
        r.raise_for_status()
    return _parse_rss(r.text, limit=10)


def _slug(title: str) -> str:
    s = re.sub(r"[^\w\s-]", "", title.lower())
    s = re.sub(r"[\s_]+", "-", s).strip("-")
    return (s[:60] or "noticia") + f"-{datetime.now().strftime('%Y%m%d')}"


def fetch_and_index_economic_news(*, use_web_fallback: bool = True) -> dict[str, Any]:
    """Busca RSS, indexa em docs/economic-news + knowledge."""
    cfg = _load_cfg()
    max_per = int(cfg.get("max_items_per_feed") or 3)
    max_total = int(cfg.get("max_total_items") or 12)
    indexed: list[dict[str, Any]] = []
    errors: list[str] = []

    for feed in cfg.get("feeds") or []:
        url = feed.get("url", "")
        name = feed.get("name", "feed")
        tags = list(feed.get("tags") or ["economic-news", "finance"])
        if not url:
            continue
        try:
            entries = _fetch_feed(url)[:max_per]
        except Exception as exc:
            errors.append(f"{name}: {exc!r}")
            continue
        for entry in entries:
            if len(indexed) >= max_total:
                break
            title = entry.get("title") or "Notícia econômica"
            body = (
                f"Fonte RSS: {name}\n"
                f"Link: {entry.get('link', '')}\n"
                f"Publicado: {entry.get('published', '')}\n\n"
                f"{entry.get('summary', '')}"
            )
            NEWS_DIR.mkdir(parents=True, exist_ok=True)
            path = NEWS_DIR / f"{_slug(title)}.md"
            if not path.is_file():
                path.write_text(f"# {title}\n\n{body}\n", encoding="utf-8")
                indexing.index_file(path, tags + ["web-ingest"])
            note = knowledge.add_note(title, body[:2000], tags + ["finance-lead"], sync_cloud=False)
            indexed.append(
                {
                    "title": title,
                    "source": name,
                    "url": entry.get("link"),
                    "note_id": note.get("id"),
                    "path": str(path.relative_to(PROJECT_ROOT)),
                }
            )

    if not indexed and use_web_fallback:
        from learning_agent.core import web

        query = str(cfg.get("fallback_search_query") or "economia brasil Selic")
        try:
            web_result = web.search_and_learn(
                query,
                limit=2,
                tags=["economic-news", "finance-lead", "brasil"],
            )
            if web_result.get("success"):
                for item in web_result.get("learned") or []:
                    indexed.append(
                        {
                            "title": item.get("title"),
                            "source": "web-fallback",
                            "url": item.get("url"),
                            "note_id": item.get("note_id"),
                        }
                    )
        except Exception as exc:
            errors.append(f"web-fallback: {exc!r}")

    if not indexed:
        for item in cfg.get("static_headlines") or []:
            title = str(item.get("title") or "Headline econômica")
            summary = str(item.get("summary") or "")
            tags = ["economic-news", "finance-lead", "brasil", "static-fallback"]
            NEWS_DIR.mkdir(parents=True, exist_ok=True)
            path = NEWS_DIR / f"{_slug(title)}.md"
            if not path.is_file():
                path.write_text(f"# {title}\n\n{summary}\n", encoding="utf-8")
                indexing.index_file(path, tags)
            note = knowledge.add_note(title, summary, tags, sync_cloud=False)
            indexed.append(
                {"title": title, "source": "static-fallback", "url": "", "note_id": note.get("id")}
            )
            if len(indexed) >= 3:
                break

    manifest = {
        "updated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "indexed_count": len(indexed),
        "items": indexed,
        "errors": errors,
    }
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "success": len(indexed) > 0,
        "indexed_count": len(indexed),
        "manifest": str(MANIFEST.relative_to(PROJECT_ROOT)),
        "errors": errors,
        "items": indexed[:5],
    }


def manifest_fresh(max_age_hours: int = 168) -> bool:
    if not MANIFEST.is_file():
        return False
    try:
        data = json.loads(MANIFEST.read_text(encoding="utf-8"))
        updated = data.get("updated_at", "")
        if not updated:
            return False
        dt = datetime.fromisoformat(updated.replace("Z", "+00:00"))
        age = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
        return age <= max_age_hours and int(data.get("indexed_count") or 0) >= 3
    except (json.JSONDecodeError, ValueError):
        return False
