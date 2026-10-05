"""LSP-lite — completions, hover, definition, references, symbols e diagnostics.

Profundidade real a partir do workspace: AST (Python) + regex (TS/JS) com
fallback para o índice semântico (RAG/Chroma) quando o símbolo não está no
arquivo corrente. Sem dependência externa (pyright/tsc) — roda no servidor
ravenna com o Python do próprio projeto.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from learning_agent.config import PROJECT_ROOT
from learning_agent.core.workspace import read_file, resolve_path

_KEYWORDS: dict[str, list[str]] = {
    "python": [
        "def", "class", "import", "from", "return", "async", "await", "if", "elif", "else",
        "for", "while", "try", "except", "finally", "with", "yield", "pass", "raise",
    ],
    "typescript": [
        "import", "export", "const", "let", "function", "class", "interface", "type",
        "return", "async", "await", "if", "else", "switch", "case", "try", "catch",
    ],
    "javascript": [
        "import", "export", "const", "let", "function", "class", "return", "async", "await",
    ],
    "typescriptreact": ["import", "export", "const", "function", "return", "useState", "useEffect"],
    "javascriptreact": ["import", "export", "const", "function", "return", "useState", "useEffect"],
}

_CODE_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".jsx"}
_SKIP_PARTS = ("node_modules", ".venv", "dist", "build", "__pycache__", ".git", ".cursor", "chroma", "data")
_CODE_ROOTS = ("learning_agent", "ravenna-ide/frontend/src", "agents", "tests", "scripts")


def _lang(language_id: str) -> str:
    return (language_id or "plaintext").lower().replace("tsx", "typescriptreact").replace("jsx", "javascriptreact")


def _python_symbols(path: Path, content: str) -> list[str]:
    symbols: list[str] = []
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return symbols
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef) or isinstance(node, ast.ClassDef):
            symbols.append(node.name)
    return symbols


def _scan_workspace_symbols(max_files: int = 40) -> list[str]:
    symbols: set[str] = set()
    count = 0
    for ext in (".py", ".ts", ".tsx", ".js"):
        for path in PROJECT_ROOT.rglob(f"*{ext}"):
            if count >= max_files:
                break
            rel = str(path.relative_to(PROJECT_ROOT)).replace("\\", "/")
            if any(skip in rel for skip in ("node_modules", ".venv", "dist", "build", "__pycache__")):
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")[:8000]
            except OSError:
                continue
            if ext == ".py":
                for s in _python_symbols(path, text):
                    symbols.add(s)
            else:
                for m in re.finditer(r"(?:function|class|const|let|interface|type)\s+([A-Za-z_]\w*)", text):
                    symbols.add(m.group(1))
            count += 1
    return sorted(symbols)[:200]


def get_completions(
    *,
    language_id: str,
    path: str = "",
    line: int = 1,
    character: int = 1,
    prefix: str = "",
) -> dict[str, Any]:
    """Completions estilo LSP — keywords + símbolos do workspace."""
    lang = _lang(language_id)
    items: list[dict[str, Any]] = []
    pref = (prefix or "").lower()

    for kw in _KEYWORDS.get(lang, _KEYWORDS.get("python", [])):
        if not pref or kw.startswith(pref):
            items.append({"label": kw, "kind": "keyword", "detail": "keyword", "insertText": kw})

    file_symbols: list[str] = []
    if path:
        try:
            resolved = resolve_path(path)
            if resolved.is_file():
                data = read_file(path)
                content = str(data.get("content") or "")
                if path.endswith(".py"):
                    file_symbols = _python_symbols(resolved, content)
        except Exception:
            pass

    for sym in file_symbols + _scan_workspace_symbols():
        if pref and not sym.lower().startswith(pref):
            continue
        if sym not in {i["label"] for i in items}:
            items.append({"label": sym, "kind": "symbol", "detail": "workspace", "insertText": sym})
        if len(items) >= 48:
            break

    return {
        "success": True,
        "languageClient": "ravenna-lsp-proxy",
        "items": items,
        "count": len(items),
    }


def get_hover(*, path: str, line: int, character: int, language_id: str = "") -> dict[str, Any]:
    """Hover básico — linha atual + path."""
    content = ""
    if path:
        try:
            content = str(read_file(path).get("content") or "")
        except Exception:
            pass
    lines = content.splitlines()
    text = lines[line - 1] if 0 < line <= len(lines) else ""
    word_m = re.search(r"[A-Za-z_]\w*", text[character - 1 :] if character > 0 else text)
    word = word_m.group(0) if word_m else ""
    return {
        "success": True,
        "languageClient": "ravenna-lsp-proxy",
        "contents": f"**{word or 'token'}** · `{path}`\n\n```\n{text.strip()}\n```",
    }


# ---------------------------------------------------------------------------
# Definition / references / symbols / diagnostics (profundidade real)
# ---------------------------------------------------------------------------

def _word_at(content: str, line: int, character: int) -> str:
    """Extrai o identificador sob o cursor (character 1-indexado)."""
    lines = content.splitlines()
    if not 0 < line <= len(lines):
        return ""
    text = lines[line - 1]
    i = max(0, min(character - 1, len(text)))
    if i < len(text) and not (text[i].isalnum() or text[i] == "_"):
        # se caiu no fim da palavra, ande para trás até o token
        while i > 0 and not (text[i - 1].isalnum() or text[i - 1] == "_"):
            i -= 1
    if i >= len(text) or not (text[i].isalnum() or text[i] == "_"):
        return ""
    start = i
    while start > 0 and (text[start - 1].isalnum() or text[start - 1] == "_"):
        start -= 1
    end = i
    while end < len(text) and (text[end].isalnum() or text[end] == "_"):
        end += 1
    return text[start:end]


_PY_DEF_KINDS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
_TS_DEF_RE = re.compile(
    r"^\s*(?:export\s+)?(?:default\s+)?(?:declare\s+)?"
    r"(?P<kw>async\s+function|function|class|interface|type|enum|const|let|var)\s+"
    r"(?P<name>[A-Za-z_$][\w$]*)"
)
_TS_FN_RE = re.compile(
    r"(?:async\s+)?(?:function\s+)?(?P<name>[A-Za-z_$][\w$]*)\s*\([^)]*\)\s*\{"
)


def _definitions_in_content(content: str, suffix: str) -> list[dict[str, Any]]:
    """Símbolos definidos no conteúdo com linha/coluna."""
    out: list[dict[str, Any]] = []
    if suffix == ".py":
        try:
            tree = ast.parse(content)
        except SyntaxError:
            return out
        for node in ast.walk(tree):
            if isinstance(node, _PY_DEF_KINDS):
                kind = "class" if isinstance(node, ast.ClassDef) else "function"
                out.append(
                    {
                        "name": node.name,
                        "kind": kind,
                        "line": node.lineno,
                        "character": (node.col_offset or 0) + 1,
                        "end_line": node.end_lineno or node.lineno,
                    }
                )
        return out
    for i, raw in enumerate(content.splitlines(), 1):
        m = _TS_DEF_RE.match(raw)
        if m:
            out.append(
                {
                    "name": m.group("name"),
                    "kind": "function" if "function" in m.group("kw") else m.group("kw"),
                    "line": i,
                    "character": raw.find(m.group("name")) + 1,
                    "end_line": i,
                }
            )
    return out


def _iter_workspace_code(max_files: int = 400) -> Iterator[tuple[Path, str]]:
    """Varre apenas os diretórios de código (evita rglob global lento em data/)."""
    seen: set[str] = set()
    count = 0
    for root_name in _CODE_ROOTS:
        root = PROJECT_ROOT / root_name
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            if path.suffix.lower() not in _CODE_SUFFIXES:
                continue
            rel = path.relative_to(PROJECT_ROOT).as_posix()
            if any(part in _SKIP_PARTS for part in rel.split("/")):
                continue
            if rel in seen:
                continue
            seen.add(rel)
            if count >= max_files:
                return
            yield path, rel
            count += 1


def _find_definition_across_workspace(name: str, origin_path: str) -> dict[str, Any] | None:
    """Varre o workspace atrás da definição do símbolo (fora do arquivo atual)."""
    normalized_origin = origin_path.replace("\\", "/").strip("/")
    for path, rel in _iter_workspace_code():
        if rel == normalized_origin:
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="replace")[:200_000]
        except OSError:
            continue
        for d in _definitions_in_content(content, path.suffix):
            if d["name"] == name:
                return {
                    "path": rel,
                    "name": name,
                    "kind": d["kind"],
                    "line": d["line"],
                    "character": d["character"],
                    "end_line": d["end_line"],
                }
    return None


def _semantic_definition_fallback(name: str, origin_path: str) -> dict[str, Any] | None:
    """Fallback: índice semântico (RAG/Chroma) para go-to-definition."""
    try:
        from learning_agent.core.codebase import search_code

        hits = search_code(name, limit=6)
    except Exception:
        return None
    origin = origin_path.replace("\\", "/").strip("/")
    for h in hits:
        meta = h.get("metadata") or {}
        src = str(meta.get("source") or "")
        if src == origin:
            continue
        content = h.get("content") or ""
        if name not in content:
            continue
        line = 0
        for i, raw in enumerate(content.splitlines(), 1):
            if re.search(rf"\b{re.escape(name)}\b", raw):
                line = i
                break
        return {
            "path": src,
            "name": name,
            "kind": meta.get("kind") or "symbol",
            "line": line or 1,
            "character": 1,
            "end_line": line or 1,
            "semantic": True,
        }
    return None


def get_definition(*, path: str, line: int, character: int) -> dict[str, Any]:
    """Go-to-definition real: arquivo atual → workspace → índice semântico."""
    content = ""
    if path:
        try:
            content = str(read_file(path).get("content") or "")
        except Exception:
            content = ""
    word = _word_at(content, line, character)
    if not word:
        return {"success": True, "definitions": []}

    suffix = Path(path).suffix if path else ""
    rel = path.replace("\\", "/").strip("/")

    # 1) definição no próprio arquivo
    local: list[dict[str, Any]] = []
    for d in _definitions_in_content(content, suffix):
        if d["name"] == word:
            local.append({"path": rel, **d})

    # 2) workspace
    if not local:
        ext = _find_definition_across_workspace(word, rel)
        if ext:
            local.append(ext)

    # 3) índice semântico
    if not local:
        sem = _semantic_definition_fallback(word, rel)
        if sem:
            local.append(sem)

    return {"success": True, "definitions": local}


def get_references(*, path: str, line: int, character: int, max_results: int = 100) -> dict[str, Any]:
    """Referências do símbolo sob o cursor em todo o workspace."""
    content = ""
    if path:
        try:
            content = str(read_file(path).get("content") or "")
        except Exception:
            content = ""
    word = _word_at(content, line, character)
    if not word:
        return {"success": True, "references": []}

    origin = path.replace("\\", "/").strip("/")
    pattern = re.compile(rf"\b{re.escape(word)}\b")
    refs: list[dict[str, Any]] = []

    for p, rel in _iter_workspace_code():
        if len(refs) >= max_results:
            break
        try:
            text = p.read_text(encoding="utf-8", errors="replace")[:200_000]
        except OSError:
            continue
        for i, raw in enumerate(text.splitlines(), 1):
            if len(refs) >= max_results:
                break
            if pattern.search(raw):
                refs.append(
                    {
                        "path": rel,
                        "line": i,
                        "character": raw.find(word) + 1,
                        "text": raw.strip()[:160],
                    }
                )

    # o próprio arquivo entra primeiro
    refs.sort(key=lambda r: (0 if r["path"] == origin else 1, r["path"], r["line"]))
    return {"success": True, "references": refs}


def get_document_symbols(*, path: str) -> dict[str, Any]:
    """Outline do arquivo (document symbols)."""
    content = ""
    if path:
        try:
            content = str(read_file(path).get("content") or "")
        except Exception:
            content = ""
    suffix = Path(path).suffix if path else ""
    symbols = _definitions_in_content(content, suffix)
    return {"success": True, "symbols": symbols}


def get_diagnostics(*, path: str) -> dict[str, Any]:
    """Diagnósticos reais — erros de sintaxe Python via AST (com linha/coluna)."""
    diagnostics: list[dict[str, Any]] = []
    content = ""
    if path:
        try:
            content = str(read_file(path).get("content") or "")
        except Exception:
            content = ""
    if path.endswith(".py") and content.strip():
        try:
            ast.parse(content)
        except SyntaxError as exc:
            diagnostics.append(
                {
                    "severity": "error",
                    "line": exc.lineno or 1,
                    "character": (exc.offset or 1),
                    "message": exc.msg or "SyntaxError",
                    "source": "ravenna-lsp",
                }
            )
    return {"success": True, "diagnostics": diagnostics}


# ---------------------------------------------------------------------------
# Tab AI — fill-in-middle (prefixo + sufixo) com modelo local + contexto
# ---------------------------------------------------------------------------

def _completion_context(path: str, prefix: str, limit: int = 3) -> str:
    """Top-K chunks relevantes do codebase para informar a completion."""
    tail = " ".join((prefix or "").splitlines()[-2:])[-160:].strip()
    if not tail:
        return ""
    try:
        from learning_agent.core.codebase import search_code

        hits = search_code(tail, limit=limit)
    except Exception:
        return ""
    if not hits:
        return ""
    blocks: list[str] = []
    for h in hits:
        src = str((h.get("metadata") or {}).get("source") or "")
        content = str(h.get("content") or "").strip()
        if not content:
            continue
        blocks.append(f"// referência: {src}\n{content[:600]}")
    if not blocks:
        return ""
    return "Contexto relevante do codebase:\n" + "\n\n".join(blocks) + "\n\n"


def _clean_completion(text: str, prefix: str, suffix: str) -> str:
    """Limpa a saída do modelo: remove fences, prefixo/sufixo repetidos e markdown."""
    out = (text or "").strip()
    # remove fences ```lang ... ```
    out = re.sub(r"```[a-zA-Z0-9_+-]*\n?", "", out)
    out = out.replace("```", "").strip()
    # remove qualquer linha que seja só o prefixo inteiro (duplicação)
    prefix_tail = (prefix or "").rstrip().splitlines()[-1:] or []
    if prefix_tail:
        p_last = prefix_tail[0].strip()
        if p_last and out.startswith(p_last):
            out = out[len(p_last):].lstrip("\n")
    # corta onde o sufixo já começa a aparecer (evita repetir código existente)
    suffix_head = (suffix or "").lstrip().splitlines()
    if suffix_head:
        s_first = suffix_head[0].strip()
        if s_first and s_first in out:
            out = out.split(s_first, 1)[0].rstrip()
    # limita a primeira linha completa (multi-linha ok, mas sem lixo de markdown)
    out = out.strip("`\n")
    return out


def get_inline_completion(
    *,
    path: str,
    language_id: str,
    prefix: str,
    suffix: str,
) -> dict[str, Any]:
    """Fill-in-middle via modelo local (Ollama) com contexto do codebase."""
    from learning_agent.config import (
        COMPLETION_API_BASE,
        COMPLETION_API_KEY,
        COMPLETION_MAX_TOKENS,
        COMPLETION_MODEL,
    )
    from learning_agent.core.llm import chat_complete

    if not COMPLETION_MODEL:
        return {"success": False, "items": []}

    ctx = _completion_context(path, prefix)
    system = (
        "Você é um autocomplete de código embutido. Complete SOMENTE o trecho entre o "
        "prefijo e o sufijo. Não repita o prefijo nem o sufijo. Não use markdown, não "
        "explique, não adicione comentários desnecessários. Retorne apenas o código que falta."
    )
    user = (
        f"Arquivo: {path}\nLinguagem: {language_id}\n\n"
        f"{ctx}"
        f"Prefixo (código ANTES do cursor):\n{prefix[-2400:]}\n\n"
        f"Sufixo (código DEPOIS do cursor):\n{suffix[:1200]}\n\n"
        "Complete o código no cursor (apenas o trecho faltante):"
    )
    try:
        text = chat_complete(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            base_url=COMPLETION_API_BASE,
            api_key=COMPLETION_API_KEY,
            model=COMPLETION_MODEL,
            temperature=0.1,
            max_tokens=COMPLETION_MAX_TOKENS,
        )
    except Exception:
        return {"success": False, "items": []}

    cleaned = _clean_completion(text, prefix, suffix)
    if not cleaned or not cleaned.strip():
        return {"success": False, "items": []}
    return {"success": True, "text": cleaned}

