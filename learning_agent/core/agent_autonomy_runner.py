"""Backend helpers for Ravenna Agent autonomy.

The frontend still owns review-mode previews. This module gives the API an
explicit autonomous path that can parse model write blocks, save them, and run
lightweight quality gates before a response is considered complete.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from learning_agent.core import workspace

try:
    from learning_agent.core.autonomy_patch import PATCH_BLOCK_RE
except ImportError:
    PATCH_BLOCK_RE = re.compile(r"```(?:patch|diff):?\s*([^\n`]*)\n([\s\S]*?)```", re.IGNORECASE)


FILE_BLOCK_RE = re.compile(r"```(?:write|file|canvas):?\s*([^\n`]+)\n([\s\S]*?)```", re.IGNORECASE)
SHELL_BLOCK_RE = re.compile(r"```(?:shell|bash|powershell|sh)\s*\n([\s\S]*?)```", re.IGNORECASE)
MALFORMED_WRITE_RE = re.compile(
    r'(?:"write|(?:^|\n)\s*write)\s+([a-zA-Z0-9_./\\-]+\.[a-zA-Z0-9]+)\s+([\s\S]*?)'
    r'(?=(?:"write|(?:^|\n)\s*write)\s+[a-zA-Z0-9_./\\-]+\.[a-zA-Z0-9]+|###\s|\*\*Alterações aplicadas|$)',
    re.IGNORECASE | re.MULTILINE,
)


@dataclass(frozen=True)
class FileBlock:
    path: str
    content: str


@dataclass(frozen=True)
class ShellBlock:
    command: str


def parse_write_blocks(text: str) -> list[FileBlock]:
    """Parse fenced and legacy write blocks from an agent reply."""
    blocks: dict[str, FileBlock] = {}
    for match in FILE_BLOCK_RE.finditer(text or ""):
        _push_block(blocks, match.group(1), match.group(2).rstrip("\n"))

    for match in MALFORMED_WRITE_RE.finditer(text or ""):
        _push_block(blocks, match.group(1), match.group(2).strip())

    return list(blocks.values())


def parse_shell_blocks(text: str) -> list[ShellBlock]:
    """Parse shell blocks and keep only non-empty single commands."""
    blocks: list[ShellBlock] = []
    shell_source = _strip_write_blocks(text or "")
    for match in SHELL_BLOCK_RE.finditer(shell_source):
        for command in _normalize_shell_commands(match.group(1)):
            blocks.append(ShellBlock(command=command))
    return blocks


def apply_write_blocks(
    text: str,
    *,
    base_path: str | None = None,
    spec: dict[str, Any] | None = None,
    allowed_paths: list[str] | None = None,
) -> dict[str, Any]:
    """Persist agent write blocks to the workspace."""
    from learning_agent.core import autonomy_guards
    from learning_agent.core.workspace_roots import canonical_workspace_ref

    scoped_base = canonical_workspace_ref(base_path) if base_path else None
    blocks = parse_write_blocks(text)
    applied: list[dict[str, Any]] = []
    blocked: list[dict[str, str]] = []
    for block in blocks:
        scoped_path = _scope_block_path(block.path, scoped_base)
        reason = autonomy_guards.should_block_write(
            scoped_path,
            block.content,
            spec=spec,
            allowed_paths=allowed_paths,
        )
        if reason:
            blocked.append({"path": scoped_path, "reason": reason})
            continue
        previous_content = ""
        existed = False
        try:
            previous_content = workspace.read_file(scoped_path).get("content") or ""
            existed = True
        except workspace.WorkspaceError:
            existed = False
        result = workspace.write_file(scoped_path, block.content)
        applied.append(
            {
                "path": result["path"],
                "size": result["size"],
                "root_id": result.get("root_id"),
                "previousContent": previous_content,
                "existed": existed,
            }
        )

    return {
        "applied": applied,
        "changedPaths": [item["path"] for item in applied],
        "blockCount": len(blocks),
        "blocked": blocked,
        "blockedCount": len(blocked),
    }


def apply_patch_blocks(
    text: str,
    *,
    base_path: str | None = None,
    spec: dict[str, Any] | None = None,
    allowed_paths: list[str] | None = None,
) -> dict[str, Any]:
    """Apply unified diff blocks from an agent reply."""
    from learning_agent.core import autonomy_patch
    from learning_agent.core.workspace_roots import canonical_workspace_ref

    scoped_base = canonical_workspace_ref(base_path) if base_path else None
    blocks = autonomy_patch.parse_patch_blocks(text)
    applied: list[dict[str, Any]] = []
    blocked: list[dict[str, str]] = []
    failed: list[dict[str, str]] = []

    for block in blocks:
        scoped_path = _scope_block_path(block.path, scoped_base)
        reason = autonomy_patch.should_allow_patch_path(
            scoped_path,
            spec=spec,
            allowed_paths=allowed_paths,
        )
        if reason:
            blocked.append({"path": scoped_path, "reason": reason})
            continue
        try:
            current = workspace.read_file(scoped_path)
            original = current.get("content") or ""
        except workspace.WorkspaceError as exc:
            failed.append({"path": scoped_path, "reason": exc.message})
            continue

        try:
            merged, warnings = autonomy_patch.apply_unified_patch(original, block.diff)
        except ValueError as exc:
            failed.append({"path": scoped_path, "reason": str(exc)})
            continue

        from learning_agent.core import autonomy_guards

        block_reason = autonomy_guards.should_block_write(
            scoped_path,
            merged,
            spec=spec,
            allowed_paths=allowed_paths,
        )
        if block_reason:
            blocked.append({"path": scoped_path, "reason": block_reason})
            continue

        result = workspace.write_file(scoped_path, merged)
        applied.append(
            {
                "path": result["path"],
                "size": result["size"],
                "root_id": result.get("root_id"),
                "kind": "patch",
                "warnings": warnings,
                "previousContent": original,
                "existed": True,
            }
        )

    return {
        "applied": applied,
        "changedPaths": [item["path"] for item in applied],
        "blockCount": len(blocks),
        "blocked": blocked,
        "blockedCount": len(blocked),
        "failed": failed,
        "failedCount": len(failed),
    }


def apply_autonomy_blocks(
    text: str,
    *,
    base_path: str | None = None,
    spec: dict[str, Any] | None = None,
    allowed_paths: list[str] | None = None,
    write_text: str | None = None,
) -> dict[str, Any]:
    """Apply patch blocks first, then write blocks."""
    patch_result = apply_patch_blocks(
        text,
        base_path=base_path,
        spec=spec,
        allowed_paths=allowed_paths,
    )
    write_result = apply_write_blocks(
        write_text if write_text is not None else text,
        base_path=base_path,
        spec=spec,
        allowed_paths=allowed_paths,
    )
    changed = list(dict.fromkeys(patch_result.get("changedPaths", []) + write_result.get("changedPaths", [])))
    return {
        "applied": patch_result.get("applied", []) + write_result.get("applied", []),
        "changedPaths": changed,
        "blockCount": patch_result.get("blockCount", 0) + write_result.get("blockCount", 0),
        "patchBlockCount": patch_result.get("blockCount", 0),
        "writeBlockCount": write_result.get("blockCount", 0),
        "blocked": patch_result.get("blocked", []) + write_result.get("blocked", []),
        "blockedCount": patch_result.get("blockedCount", 0) + write_result.get("blockedCount", 0),
        "failed": patch_result.get("failed", []),
        "failedCount": patch_result.get("failedCount", 0),
        "patches": patch_result,
        "writes": write_result,
    }


def run_safe_shell_blocks(
    text: str,
    *,
    changed_paths: list[str] | None = None,
    project_root: str | None = None,
    timeout_seconds: int = 90,
) -> dict[str, Any]:
    """Run allowlisted shell blocks emitted by the agent."""
    
    blocks = parse_shell_blocks(text)
    cwd = _resolve_project_root(changed_paths or [], project_root) or workspace.resolve_path("")
    results: list[dict[str, Any]] = []

    for block in blocks:
        cd_subdir, inner_command = _split_cd_prefix(block.command)
        run_cwd = cwd
        if cd_subdir:
            run_cwd = (cwd / cd_subdir.replace("\\", "/").strip("/")).resolve()
            command_to_check = inner_command
        else:
            command_to_check = block.command

        from learning_agent.core.ravenna_home_remote_ops import (
            try_run_ravenna_home_remote_shell,
        )

        remote_result = try_run_ravenna_home_remote_shell(block.command, project_root=project_root)
        if remote_result is not None:
            results.append(remote_result)
            continue

        remote_result = try_run_remoteapp_remote_shell(block.command, project_root=project_root)
        if remote_result is not None:
            results.append(remote_result)
            continue

        safety = _safe_shell_command(command_to_check)
        if not safety["ok"]:
            results.append(
                {
                    "command": block.command,
                    "cwd": str(run_cwd),
                    "exit_code": None,
                    "output": "",
                    "skipped": True,
                    "reason": safety["reason"],
                }
            )
            continue

        try:
            proc = subprocess.run(
                _relativize_args_for_cwd(safety["args"], run_cwd),
                cwd=run_cwd,
                env=_shell_env(run_cwd),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=timeout_seconds,
                check=False,
            )
            results.append(
                {
                    "command": block.command,
                    "cwd": str(run_cwd),
                    "exit_code": 2 if _node_test_zero_tests(block.command, proc.stdout or "") else proc.returncode,
                    "output": (proc.stdout or "")[-6000:],
                    "skipped": False,
                    "reason": "npm test rodou 0 testes" if _node_test_zero_tests(block.command, proc.stdout or "") else None,
                }
            )
        except subprocess.TimeoutExpired as exc:
            output = exc.stdout or ""
            results.append(
                {
                    "command": block.command,
                    "cwd": str(run_cwd),
                    "exit_code": 124,
                    "output": f"{output}\nTimeout após {timeout_seconds}s".strip()[-6000:],
                    "skipped": False,
                    "reason": "timeout",
                }
            )
        except OSError as exc:
            results.append(
                {
                    "command": block.command,
                    "cwd": str(run_cwd),
                    "exit_code": None,
                    "output": "",
                    "skipped": True,
                    "reason": f"Falha ao executar comando permitido: {exc}",
                }
            )

    failures = [
        f"{item['command']} exited {item['exit_code']}"
        for item in results
        if not item.get("skipped")
        and not (item.get("remote") and item.get("remote_ok"))
        and item.get("exit_code") not in (0, None)
    ]
    blocked = [item for item in results if item.get("skipped")]
    return {
        "ran": results,
        "blockCount": len(blocks),
        "ok": not failures,
        "failures": failures,
        "blocked": blocked,
    }


def build_repair_prompt(
    original_request: str,
    *,
    applied: dict[str, Any],
    validation: dict[str, Any],
    checklist: dict[str, Any],
    project_root: str | None = None,
) -> str:
    """Prompt sent back to the agent when validation fails."""
    from learning_agent.core import (
        agent_project_learning,
        agent_project_profiles,
        agent_spec_builder,
    )

    mini_spec = agent_spec_builder.build_spec(original_request, project_root=project_root)
    spec_hint = {
        "ravennaHome": agent_project_profiles.is_ravenna_home_root(project_root),
        "ravennaHomeDeploy": bool(mini_spec.get("ravennaHomeDeploy")),
    }
    validation_tail = _validation_tail(validation)
    shell_tail = _shell_tail(applied.get("shell") or {})
    checklist_items = list(checklist.get("failures", []))
    shell = applied.get("shell") or {}
    shell_failures = list(shell.get("failures") or [])
    shell_blocked = [item.get("reason") or item.get("command") for item in shell.get("blocked", [])]
    validation_failures = list(validation.get("failures") or [])
    critical = validation_failures + checklist_items + shell_failures + [f"Shell bloqueado: {item}" for item in shell_blocked if item]
    critical_failures = "\n".join(f"- {item}" for item in critical) or "- Falha não classificada; revalide arquivos e comandos."
    required_files = checklist.get("requiredFiles") or _infer_required_files(original_request)
    required_files_text = "\n".join(f"- {item}" for item in required_files) or "- Consulte o pedido original."
    checklist_failures = "\n".join(f"- {item}" for item in checklist_items) or "- none"
    changed = ", ".join(applied.get("changedPaths") or []) or "nenhum arquivo aplicado"
    lessons_tail = ""
    pid = agent_project_learning.project_id_from_root(project_root)
    lessons_block = agent_project_learning.format_lessons_block(pid, limit=6)
    if lessons_block:
        lessons_tail = f"\n\n{lessons_block}\n"
    return (
        "A implementação anterior não passou na validação autônoma. "
        "Reinvestigue (leia arquivos reais), atualize Diagnóstico e entregue correção completa "
        "com blocos ```write caminho``` ou ```patch caminho``` — não apenas explique.\n"
        "Antes de corrigir: `get_project_lessons` — após entender a falha: `record_project_lesson`.\n"
        f"{lessons_tail}\n"
        f"FALHAS CRÍTICAS A CORRIGIR AGORA:\n{critical_failures}\n\n"
        f"ARQUIVOS OBRIGATÓRIOS ESPERADOS:\n{required_files_text}\n\n"
        f"Pedido original:\n{original_request}\n\n"
        f"Arquivos aplicados: {changed}\n\n"
        f"Falhas de checklist:\n{checklist_failures}\n\n"
        f"Saída de shell seguro:\n{shell_tail}\n\n"
        f"Saída de validação:\n{validation_tail}\n\n"
        f"{agent_project_profiles.repair_rules_block(spec_hint)}"
    )


def check_project_requirements(
    prompt: str,
    changed_paths: list[str],
    project_root: str | None,
    spec: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Best-effort checklist for common autonomous project failures."""
    failures: list[str] = []
    warnings: list[str] = []
    spec = spec or {}
    if spec.get("cursorEquivalentDelivery"):
        from learning_agent.core import agent_delivery_standard

        failures.extend(
            agent_delivery_standard.integration_failures(
                [path.replace("\\", "/").strip("/") for path in changed_paths],
                project_root=project_root,
            )
        )
    inferred_required_files = _dedupe_strings(
        list(spec.get("requiredFiles") or []) + _infer_required_files(prompt)
    )
    normalized_changed = [path.replace("\\", "/").strip("/") for path in changed_paths]
    if inferred_required_files and len(normalized_changed) < min(len(inferred_required_files), 12):
        warnings.append(
            f"Entrega incompleta: {len(normalized_changed)} arquivo(s) aplicados para {len(inferred_required_files)} arquivo(s) obrigatórios inferidos."
        )
    root = _resolve_project_root(changed_paths, project_root)
    if spec.get("ravennaHomeDeploy") and root is not None:
        from learning_agent.core import ravenna_home_delivery

        frontend_root = root
        if not (frontend_root / "package.json").is_file() and (frontend_root / "frontend" / "package.json").is_file():
            frontend_root = frontend_root / "frontend"
        failures.extend(ravenna_home_delivery.validate_filesystem(frontend_root, spec=spec))
    lower_prompt = prompt.lower()

    if root is None:
        missing = _missing_from_changed_paths(inferred_required_files, normalized_changed)
        return {
            "ok": False,
            "projectRoot": None,
            "failures": [
                "Não encontrei package.json para checar requisitos do projeto.",
                *[f"Arquivo obrigatório inferido ausente: `{item}`." for item in missing],
            ],
            "warnings": [],
            "requiredFiles": inferred_required_files,
        }

    package_path = root / "package.json"
    package = _read_package(root, failures) if package_path.is_file() or _requires_package_json(prompt, spec) else None
    autonomy_config = _autonomy_config(package) if package else {}
    if package:
        scripts = package.get("scripts") if isinstance(package.get("scripts"), dict) else {}
        if autonomy_config.get("requireTestScript", True) and "test" not in scripts:
            failures.append("package.json não define script `test`.")
        if autonomy_config.get("requireSmokeOrStart", True) and "start" not in scripts and "smoke" not in scripts:
            warnings.append("package.json não define `start` nem `smoke` para validar CLI.")
        if package.get("type") != "module" and _looks_like_node_esm_request(prompt):
            failures.append("package.json deveria declarar `type: module` para ESM.")
        test_script = str(scripts.get("test", ""))
        if "node --test" in test_script:
            _check_native_node_tests(root, failures)
        if "sem dependências" in lower_prompt or "sem dependencias" in lower_prompt or "without dependencies" in lower_prompt:
            _check_no_external_node_dependencies(package, failures)

    semantic_rules = set(spec.get("semanticRules") or [])
    if autonomy_config.get("moneySafe") is True or (
        autonomy_config.get("moneySafe") is not False
        and any(token in lower_prompt for token in ("billing", "assinatura", "invoice", "finance"))
    ):
        _check_money_safe_project(root, failures, warnings)
    elif "integer-cents" in semantic_rules:
        _check_integer_cents_project(root, failures, warnings)
    _check_configured_requirements(root, autonomy_config, failures, warnings)
    _check_required_exports(root, spec.get("requiredExports"), failures)
    _check_inferred_required_files(root, inferred_required_files, failures)
    _check_semantic_requirements(prompt, root, package or {}, failures, warnings, spec=spec)
    _check_min_tests(root, spec, failures)

    return {
        "ok": not failures,
        "projectRoot": str(root),
        "failures": failures,
        "warnings": warnings,
        "requiredFiles": sorted(set(inferred_required_files + _configured_required_files(autonomy_config))),
    }


def _push_block(blocks: dict[str, FileBlock], raw_path: str, raw_content: str) -> None:
    path = _normalize_path(raw_path)
    content = (raw_content or "").strip()
    if not path or not content:
        return
    blocks[path] = FileBlock(path=path, content=content)


def _normalize_path(path: str) -> str:
    normalized = (path or "").strip().strip("\"'").replace("\\", "/").strip("/")
    if normalized.endswith(".canvas.tsx") and "/" not in normalized:
        return f"data/canvases/{normalized}"
    return normalized


def _scope_block_path(path: str, base_path: str | None) -> str:
    from learning_agent.core.workspace_roots import canonical_workspace_ref

    normalized = path.replace("\\", "/").strip("/")
    base = canonical_workspace_ref(base_path) if base_path else ""
    if not base or not normalized:
        return normalized
    if normalized.startswith("learning-agent/"):
        without_root = normalized.removeprefix("learning-agent/").strip("/")
        if without_root == base or without_root.startswith(f"{base}/"):
            return without_root
        normalized = without_root
    if normalized == base or normalized.startswith(f"{base}/"):
        return normalized
    base_tail = base.split("/", 1)[-1] if "/" in base else ""
    if base_tail and (normalized == base_tail or normalized.startswith(f"{base_tail}/")):
        inner = normalized[len(base_tail) :].strip("/") if normalized != base_tail else ""
        return base if not inner else f"{base}/{inner}"
    if normalized.startswith(("learning_agent/", "ravenna-ide/", "agents/", "data/", "pc-workspace/")):
        return normalized
    return f"{base}/{normalized}"


def _normalize_shell_command(raw: str) -> str:
    commands = _normalize_shell_commands(raw)
    return commands[0] if commands else ""


def _normalize_shell_commands(raw: str) -> list[str]:
    lines = [line.strip() for line in (raw or "").splitlines() if line.strip()]
    commands: list[str] = []
    current: list[str] = []
    for line in lines:
        if line.startswith("#"):
            continue
        if _looks_like_shell_command(line):
            if current:
                commands.append(" ".join(current))
            current = [line]
        elif current:
            current.append(line)
    if current:
        commands.append(" ".join(current))
    return commands


def _looks_like_shell_command(line: str) -> bool:
    first = line.split(maxsplit=1)[0].lower() if line.split() else ""
    if first in {"npm", "npm.cmd", "node", "node.exe", "py", "python", "python.exe", "pytest", "pytest.exe", "cd"}:
        return True
    lowered = line.lower()
    return any(token in lowered for token in ("npm test", "npm run", "py -m pytest", "py -m unittest", "python -m"))


def _strip_write_blocks(text: str) -> str:
    stripped = FILE_BLOCK_RE.sub("", text or "")
    stripped = PATCH_BLOCK_RE.sub("", stripped)
    return MALFORMED_WRITE_RE.sub("", stripped)


def _infer_required_files(prompt: str) -> list[str]:
    candidates: list[str] = []
    for match in re.finditer(
        r"(?<![\w@])([A-Za-z0-9_./\\-]+\.(?:jsonl|json|mjs|js|tsx|ts|css|md|py|yaml|yml|toml))",
        prompt or "",
    ):
        rel = match.group(1).replace("\\", "/").strip("/")
        if rel.startswith(("node:", "http:", "https:")):
            continue
        if "/" not in rel and rel not in {"package.json", "README.md"}:
            continue
        if rel not in candidates:
            candidates.append(rel)
    return candidates


def _missing_from_changed_paths(required_files: list[str], changed_paths: list[str]) -> list[str]:
    missing: list[str] = []
    for required in required_files:
        if not any(path.endswith(required) for path in changed_paths):
            missing.append(required)
    return missing


def _dedupe_strings(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _split_cd_prefix(command: str) -> tuple[str | None, str]:
    parts = [part.strip() for part in command.split("&&")]
    if len(parts) == 2 and parts[0].lower().startswith("cd "):
        return parts[0][3:].strip().strip("\"'"), parts[1]
    return None, command


def _safe_shell_command(command: str) -> dict[str, Any]:
    if not command or len(command) > 500:
        return {"ok": False, "reason": "Comando vazio ou longo demais", "args": []}
    lowered = command.lower()
    if any(token in lowered for token in ("||", ";", "|", ">", "<", "`", "$(", " rm ", " del ", " rmdir ", "format ")):
        return {"ok": False, "reason": "Comando contém operador ou ação bloqueada", "args": []}
    if any(token in lowered for token in (" --watch", " watch", " dev", " serve", " preview", "vitest --ui")):
        return {"ok": False, "reason": "Comando parece iniciar watcher/servidor", "args": []}

    try:
        args = shlex.split(command, posix=False)
    except ValueError as exc:
        return {"ok": False, "reason": f"Comando inválido: {exc}", "args": []}
    if not args:
        return {"ok": False, "reason": "Comando vazio", "args": []}

    exe = Path(args[0]).name.lower()
    if exe in {"npm", "npm.cmd"}:
        args[0] = _resolved_executable(("npm.cmd", "npm"), args[0])
        if len(args) >= 2 and args[1] == "test":
            return {"ok": True, "reason": None, "args": args}
        if len(args) >= 3 and args[1] == "run" and args[2] in {"build", "lint", "typecheck", "test", "smoke", "start"}:
            return {"ok": True, "reason": None, "args": args}
        return {"ok": False, "reason": "Somente scripts npm finitos são permitidos", "args": []}
    if exe in {"node", "node.exe"}:
        args[0] = _resolved_executable(("node.exe", "node"), args[0])
        if len(args) >= 2 and args[1].startswith(("-", "--")):
            return {"ok": False, "reason": "Flags diretas de node não são permitidas nesse fluxo", "args": []}
        return {"ok": True, "reason": None, "args": args}
    if exe in {"py", "python", "python.exe", "pytest", "pytest.exe"}:
        args[0] = _resolved_executable((exe, "py", "python.exe", "python") if not exe.startswith("pytest") else ("pytest.exe", "pytest"), args[0])
        if exe.startswith("pytest"):
            return {"ok": True, "reason": None, "args": args}
        if len(args) >= 3 and args[1] == "-m" and args[2] in {"pytest", "py_compile", "unittest"}:
            return {"ok": True, "reason": None, "args": args}
        return {"ok": False, "reason": "Somente `python -m pytest|unittest|py_compile` são permitidos", "args": []}
    if exe in {"docker", "docker.exe"}:
        if "ravenna-home-web" in lowered and "compose" in lowered and ("build" in lowered or " up" in lowered):
            return {"ok": True, "reason": None, "args": args}
        return {"ok": False, "reason": "Somente docker compose build/up do ravenna-home-web é permitido", "args": []}
    return {"ok": False, "reason": f"Executável não permitido: {args[0]}", "args": []}


def _resolved_executable(candidates: tuple[str, ...], fallback: str) -> str:
    for candidate in candidates:
        found = shutil.which(candidate)
        if found:
            return found
    return fallback


def _relativize_args_for_cwd(args: list[str], cwd: Path) -> list[str]:
    out: list[str] = []
    cwd_posix = cwd.as_posix().rstrip("/")
    for arg in args:
        normalized = str(arg).replace("\\", "/")
        if normalized.startswith(cwd_posix + "/"):
            out.append(normalized[len(cwd_posix) + 1 :])
            continue
        try:
            rel = workspace.resolve_path(normalized).relative_to(cwd)
            out.append(rel.as_posix())
        except (ValueError, workspace.WorkspaceError):
            out.append(arg)
    return out


def _shell_env(cwd: Path) -> dict[str, str]:
    env = os.environ.copy()
    current = env.get("PYTHONPATH", "")
    entries = [str(cwd), str(cwd / "src")]
    if current:
        entries.append(current)
    env["PYTHONPATH"] = os.pathsep.join(entries)
    return env


def _node_test_zero_tests(command: str, output: str) -> bool:
    if not re.match(r"^npm(?:\.cmd)?\s+test\b", command.strip(), re.IGNORECASE):
        return False
    text = output or ""
    return "tests 0" in text or ("pass 0" in text and "fail 0" in text)


def _resolve_project_root(changed_paths: list[str], project_root: str | None) -> Path | None:
    from learning_agent.core.workspace_roots import canonical_workspace_ref

    try:
        if project_root:
            candidate = workspace.resolve_path(canonical_workspace_ref(project_root))
            if candidate.exists():
                return candidate if candidate.is_dir() else candidate.parent
            return candidate

        for changed in changed_paths:
            target = workspace.resolve_path(changed)
            current = target if target.is_dir() else target.parent
            workspace_root = workspace.resolve_path("")
            while True:
                if (current / "package.json").is_file():
                    return current
                parent = current.parent
                if parent == current:
                    break
                try:
                    parent.relative_to(workspace_root)
                except ValueError:
                    break
                current = parent
    except workspace.WorkspaceError:
        return None
    return None


def _read_package(root: Path, failures: list[str]) -> dict[str, Any] | None:
    try:
        return json.loads((root / "package.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        failures.append(f"package.json inválido: {exc}")
        return None


def _autonomy_config(package: dict[str, Any] | None) -> dict[str, Any]:
    ravenna = package.get("ravenna") if isinstance(package, dict) else None
    if not isinstance(ravenna, dict):
        return {}
    autonomy = ravenna.get("autonomy")
    return autonomy if isinstance(autonomy, dict) else {}


def _check_configured_requirements(
    root: Path,
    config: dict[str, Any],
    failures: list[str],
    warnings: list[str],
) -> None:
    required_files = config.get("requiredFiles")
    if isinstance(required_files, list):
        for rel in required_files:
            if isinstance(rel, str) and not _file_exists_under_root(root, rel):
                failures.append(f"Arquivo obrigatório ausente: `{rel}`.")

    required_exports = config.get("requiredExports")
    if isinstance(required_exports, dict):
        _check_required_exports(root, required_exports, failures)

    warning_files = config.get("recommendedFiles")
    if isinstance(warning_files, list):
        for rel in warning_files:
            if isinstance(rel, str) and not _file_exists_under_root(root, rel):
                warnings.append(f"Arquivo recomendado ausente: `{rel}`.")


def _configured_required_files(config: dict[str, Any]) -> list[str]:
    required_files = config.get("requiredFiles")
    if not isinstance(required_files, list):
        return []
    return [rel for rel in required_files if isinstance(rel, str)]


def _check_required_exports(root: Path, required_exports: Any, failures: list[str]) -> None:
    if not isinstance(required_exports, dict):
        return
    for rel, exports in required_exports.items():
        if not isinstance(rel, str) or not isinstance(exports, list):
            continue
        path = root / rel
        if not path.is_file():
            failures.append(f"Arquivo de exports obrigatório ausente: `{rel}`.")
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for name in exports:
            if isinstance(name, str) and not re.search(rf"\bexport\s+(?:function|const|class)\s+{re.escape(name)}\b", text):
                failures.append(f"`{rel}` não exporta `{name}`.")


def _check_inferred_required_files(root: Path, required_files: list[str], failures: list[str]) -> None:
    for rel in required_files:
        if not _file_exists_under_root(root, rel):
            failures.append(f"Arquivo obrigatório inferido ausente: `{rel}`.")


def _file_exists_under_root(root: Path, rel: str) -> bool:
    normalized = rel.replace("\\", "/").strip("/")
    if (root / normalized).is_file():
        return True
    try:
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            inner = path.relative_to(root).as_posix()
            full = path.as_posix()
            if normalized.endswith(inner) or full.endswith(normalized):
                return True
    except OSError:
        return False
    return False


def _check_semantic_requirements(
    prompt: str,
    root: Path,
    package: dict[str, Any],
    failures: list[str],
    warnings: list[str],
    *,
    spec: dict[str, Any] | None = None,
) -> None:
    text = (prompt or "").lower()
    semantic_rules = set((spec or {}).get("semanticRules") or [])
    source_text = _project_text(root, ("src",))
    test_text = _project_text(root, ("test",))
    cli_text = (root / "src" / "cli.js").read_text(encoding="utf-8", errors="replace") if (root / "src" / "cli.js").is_file() else ""

    if package.get("type") == "module" and re.search(r"\brequire\s*\(", cli_text):
        failures.append("CLI ESM usa `require`; use `import`/`readFileSync` em projeto `type: module`.")

    if "event-sourcing" in semantic_rules or any(token in text for token in ("fulfillment", "event-sourced", "event sourced", "estoque", "order fulfillment")):
        required_tokens = {
            "commandId": "Fulfillment deve rastrear idempotência por `commandId`.",
            "processedCommandIds": "Fulfillment deve manter conjunto/registro de comandos processados.",
            "OrderReserved": "Fulfillment deve emitir/aplicar `OrderReserved`.",
            "PaymentCaptured": "Fulfillment deve emitir/aplicar `PaymentCaptured`.",
            "OrderShipped": "Fulfillment deve emitir/aplicar `OrderShipped`.",
            "OrderCancelled": "Fulfillment deve emitir/aplicar `OrderCancelled`.",
            "Rejected": "Fulfillment deve emitir eventos de rejeição sem corromper estado.",
            "totalCents": "Fulfillment deve calcular `totalCents`.",
            "unitPriceCents": "Fulfillment deve usar `unitPriceCents`.",
            "amountCents": "Fulfillment deve validar `amountCents`.",
            "replayEvents": "Fulfillment deve implementar replay de eventos.",
            "parseJsonl": "Fulfillment deve implementar parseJsonl.",
        }
        for token, message in required_tokens.items():
            if token not in source_text:
                failures.append(message)
        if "structuredClone" not in source_text and "snapshot" in text:
            warnings.append("Considere snapshot defensivo para evitar vazamento de estado mutável.")
        if not re.search(r"line|linha", source_text, re.IGNORECASE):
            failures.append("parseJsonl deve reportar linha inválida.")
        min_tests = int((spec or {}).get("minTests") or 0)
        if prompt.lower().count("teste") or "at least 7 tests" in text or "pelo menos 7 testes" in text or min_tests:
            test_count = len(re.findall(r"\btest\s*\(", test_text))
            expected = min_tests or 7
            if test_count < expected:
                failures.append(f"Suíte insuficiente: {test_count} teste(s) encontrados; esperado >= {expected}.")


def _project_text(root: Path, dirs: tuple[str, ...]) -> str:
    chunks: list[str] = []
    for dirname in dirs:
        base = root / dirname
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if path.is_file() and path.suffix in {".js", ".mjs", ".ts", ".tsx"}:
                chunks.append(path.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(chunks)


def _looks_like_node_esm_request(prompt: str) -> bool:
    text = prompt.lower()
    return "node" in text and ("type: module" in text or "esm" in text or "import.meta.url" in text)


def _requires_package_json(prompt: str, spec: dict[str, Any]) -> bool:
    text = (prompt or "").lower()
    if "package.json" in (spec.get("requiredFiles") or []):
        return True
    if any(str(command).startswith("npm ") for command in spec.get("validationCommands") or []):
        return True
    return "node" in text or "package.json" in text or "npm " in text


def _check_min_tests(root: Path, spec: dict[str, Any], failures: list[str]) -> None:
    min_tests = int(spec.get("minTests") or 0)
    if not min_tests:
        return
    count = 0
    for dirname in ("test", "tests"):
        test_root = root / dirname
        if not test_root.is_dir():
            continue
        for path in test_root.rglob("*"):
            if not path.is_file() or path.suffix not in {".py", ".js", ".mjs", ".ts", ".tsx"}:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            if path.suffix == ".py":
                count += len(re.findall(r"^\s*def\s+test_", text, flags=re.MULTILINE))
            else:
                count += len(re.findall(r"\btest\s*\(", text))
    if count < min_tests:
        failures.append(f"Suíte insuficiente: {count} teste(s) encontrados; esperado >= {min_tests}.")


def _check_native_node_tests(root: Path, failures: list[str]) -> None:
    test_dir = root / "test"
    test_files = list(test_dir.glob("**/*.mjs")) + list(test_dir.glob("**/*.js")) if test_dir.is_dir() else []
    if not test_files:
        failures.append("Nenhum arquivo de teste encontrado em `test/`.")
        return

    for test_file in test_files:
        text = test_file.read_text(encoding="utf-8", errors="replace")
        if re.search(r"\b(describe|it|expect)\s*\(", text) and "node:test" not in text:
            failures.append(
                f"{test_file.relative_to(root).as_posix()} usa globals de Jest com `node --test`."
            )
        if "node:test" not in text:
            failures.append(f"{test_file.relative_to(root).as_posix()} não importa `node:test`.")
        if "node:assert" not in text:
            failures.append(f"{test_file.relative_to(root).as_posix()} não usa assert nativo.")


def _check_no_external_node_dependencies(package: dict[str, Any], failures: list[str]) -> None:
    for key in ("dependencies", "devDependencies", "peerDependencies"):
        deps = package.get(key)
        if isinstance(deps, dict) and deps:
            failures.append(f"package.json declara `{key}` apesar de pedido sem dependências externas.")
    scripts = package.get("scripts") if isinstance(package.get("scripts"), dict) else {}
    blocked_tokens = ("eslint", "jest", "vitest", "module-alias", "ts-node", "tsx")
    for name, script in scripts.items():
        if isinstance(script, str) and any(token in script.lower() for token in blocked_tokens):
            failures.append(f"script `{name}` usa dependência externa não permitida: `{script}`.")


def _check_money_safe_project(root: Path, failures: list[str], warnings: list[str]) -> None:
    source_text = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in (root / "src").glob("**/*.js")
    ) if (root / "src").is_dir() else ""

    required_tokens = {
        "ledger": "Projeto de billing/finance deve retornar ledger/auditoria.",
        "Cents": "Projeto de billing/finance deve operar em centavos inteiros.",
        "totalCents": "Projeto de billing/finance deve expor total em centavos.",
    }
    for token, message in required_tokens.items():
        if token not in source_text:
            failures.append(message)
    readme_text = (root / "README.md").read_text(encoding="utf-8", errors="ignore").lower() if (root / "README.md").is_file() else ""
    if "parseUsageCsv" not in source_text and "csv" in readme_text:
        warnings.append("README menciona CSV, mas não encontrei `parseUsageCsv` no código.")
    if re.search(r"\b\d+\.\d+\b", source_text):
        warnings.append("Código contém literais decimais; confirme que dinheiro não usa float.")


def _check_integer_cents_project(root: Path, failures: list[str], warnings: list[str]) -> None:
    source_text = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in (root / "src").glob("**/*.js")
    ) if (root / "src").is_dir() else ""

    for token in ("Cents", "totalCents"):
        if token not in source_text:
            failures.append(f"Projeto deve operar valores monetários em centavos inteiros usando `{token}`.")
    if re.search(r"\b\d+\.\d+\b", source_text):
        warnings.append("Código contém literais decimais; confirme que dinheiro não usa float.")


def _validation_tail(validation: dict[str, Any]) -> str:
    if not validation:
        return "Sem validação executada."
    commands = validation.get("commands") or []
    if commands:
        last = commands[-1]
        return (
            f"Command: {last.get('command')}\n"
            f"Exit: {last.get('exit_code')}\n"
            f"{str(last.get('output') or '')[-3500:]}"
        ).strip()
    if validation.get("failures"):
        return "\n".join(str(item) for item in validation["failures"])
    return str(validation.get("skippedReason") or validation)[-3500:]


def _shell_tail(shell: dict[str, Any]) -> str:
    if not shell or not shell.get("blockCount"):
        return "Nenhum bloco shell executado."
    parts: list[str] = []
    for item in shell.get("ran", [])[-3:]:
        status = "blocked" if item.get("skipped") else f"exit {item.get('exit_code')}"
        parts.append(
            f"Command: {item.get('command')}\n"
            f"Status: {status}\n"
            f"{str(item.get('reason') or item.get('output') or '')[-1500:]}"
        )
    return "\n\n".join(parts).strip()
