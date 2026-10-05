"""Unified diff patch application for Ravenna auto_apply."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

PATCH_BLOCK_RE = re.compile(
    r"```(?:patch|diff):?\s*([^\n`]*)\n([\s\S]*?)```",
    re.IGNORECASE,
)
HUNK_HEADER_RE = re.compile(r"^@@\s+-(\d+)(?:,(\d+))?\s+\+(\d+)(?:,(\d+))?\s+@@")


@dataclass(frozen=True)
class PatchBlock:
    path: str
    diff: str


@dataclass(frozen=True)
class PatchHunk:
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: tuple[str, ...]


def parse_patch_blocks(text: str) -> list[PatchBlock]:
    blocks: dict[str, PatchBlock] = {}
    for match in PATCH_BLOCK_RE.finditer(text or ""):
        raw_path = (match.group(1) or "").strip().strip("\"'")
        diff = (match.group(2) or "").strip("\n")
        if not diff.strip():
            continue
        path = raw_path or _path_from_diff(diff)
        if not path:
            continue
        normalized = path.replace("\\", "/").strip("/")
        blocks[normalized] = PatchBlock(path=normalized, diff=diff)
    return list(blocks.values())


def _path_from_diff(diff: str) -> str:
    for line in diff.splitlines():
        if line.startswith("+++ "):
            raw = line[4:].strip()
            if raw.startswith("b/"):
                raw = raw[2:]
            return raw.strip().strip("'\"")
        if line.startswith("--- "):
            raw = line[4:].strip()
            if raw.startswith("a/"):
                raw = raw[2:]
            return raw.strip().strip("'\"")
    return ""


def parse_hunks(diff: str) -> list[PatchHunk]:
    hunks: list[PatchHunk] = []
    current_lines: list[str] = []
    header: re.Match[str] | None = None

    def flush() -> None:
        nonlocal header, current_lines
        if header is None:
            return
        hunks.append(
            PatchHunk(
                old_start=int(header.group(1)),
                old_count=int(header.group(2) or "1"),
                new_start=int(header.group(3)),
                new_count=int(header.group(4) or "1"),
                lines=tuple(current_lines),
            )
        )
        header = None
        current_lines = []

    for line in diff.splitlines():
        if line.startswith("@@"):
            flush()
            match = HUNK_HEADER_RE.match(line.strip())
            if not match:
                raise ValueError(f"Cabeçalho de hunk inválido: {line}")
            header = match
            continue
        if header is not None and (line.startswith((" ", "+", "-", "\\")) or line == ""):
            current_lines.append(line)
    flush()
    if not hunks:
        raise ValueError("Nenhum hunk unified diff encontrado")
    return hunks


def apply_unified_patch(original: str, diff: str, *, fuzzy: bool = True) -> tuple[str, list[str]]:
    """Apply unified diff to original text. Returns (new_content, warnings)."""
    hunks = parse_hunks(diff)
    lines = original.splitlines()
    warnings: list[str] = []

    offset = 0
    for index, hunk in enumerate(hunks):
        start = max(0, hunk.old_start - 1 + offset)
        if fuzzy:
            located = _locate_hunk(lines, hunk, start_hint=start)
            if located is None:
                raise ValueError(f"Hunk {index + 1} não encontrou contexto compatível")
            if located != start:
                warnings.append(f"Hunk {index + 1} realocado de linha {start + 1} para {located + 1}")
            start = located

        new_segment, consumed = _apply_hunk_at(lines, hunk, start)
        if consumed < 0:
            raise ValueError(f"Hunk {index + 1} falhou ao aplicar na linha {start + 1}")
        lines = lines[:start] + new_segment + lines[start + consumed :]
        offset += len(new_segment) - consumed

    trailing_newline = original.endswith("\n")
    merged = "\n".join(lines)
    if trailing_newline and merged and not merged.endswith("\n"):
        merged += "\n"
    return merged, warnings


def _apply_hunk_at(lines: list[str], hunk: PatchHunk, start: int) -> tuple[list[str], int]:
    idx = start
    output: list[str] = []
    consumed = 0
    for raw in hunk.lines:
        if raw.startswith("\\"):
            continue
        if raw.startswith(" "):
            expected = raw[1:]
            if idx >= len(lines) or lines[idx] != expected:
                return [], -1
            output.append(expected)
            idx += 1
            consumed += 1
        elif raw.startswith("-"):
            expected = raw[1:]
            if idx >= len(lines) or lines[idx] != expected:
                return [], -1
            idx += 1
            consumed += 1
        elif raw.startswith("+"):
            output.append(raw[1:])
        elif raw == "":
            continue
        else:
            return [], -1
    return output, consumed


def _locate_hunk(lines: list[str], hunk: PatchHunk, start_hint: int) -> int | None:
    needle = _expected_original_sequence(hunk)
    if not needle:
        return start_hint if 0 <= start_hint < len(lines) else None

    window = 80
    low = max(0, start_hint - window)
    high = min(len(lines) - len(needle) + 1, start_hint + window + 1)
    for candidate in range(low, high):
        if lines[candidate : candidate + len(needle)] == needle:
            return candidate
    return None


def _expected_original_sequence(hunk: PatchHunk) -> list[str]:
    seq: list[str] = []
    for raw in hunk.lines:
        if raw.startswith(" ") or raw.startswith("-"):
            seq.append(raw[1:])
    return seq


def should_allow_patch_path(
    relative_path: str,
    *,
    spec: dict[str, Any] | None = None,
    allowed_paths: list[str] | None = None,
) -> str | None:
    from learning_agent.core import autonomy_guards

    rel = relative_path.replace("\\", "/").strip("/")
    spec = spec or {}
    patch_mode = spec.get("patchMode") == "surgical"
    whitelist = allowed_paths or spec.get("allowedPaths") or []
    if patch_mode and whitelist and not autonomy_guards.path_allowed(rel, whitelist):
        return f"Patch `{rel}` fora da whitelist cirúrgica."
    return None
