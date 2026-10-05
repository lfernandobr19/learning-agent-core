"""Objetivo norte da Ravenna IDE — paridade Cursor + frontend impecável."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

from learning_agent.config import IDE_COMPLETION_STATE_PATH, PROJECT_ROOT

FE_ROOT = PROJECT_ROOT / "ravenna-ide" / "frontend"
FE_SRC = FE_ROOT / "src"

COMPLETION_RULES = {
    "cursor_parity_min_pct": 100.0,
    "frontend_polish_min_pct": 100.0,
    "all_must_objectives_met": True,
}

NORTH_STAR = (
    "A Ravenna IDE será equivalente ao VS Code/Cursor via fork Code-OSS + extensões Ravenna "
    "(AI, MCP, agentes) sobre learning-agent API — paridade funcional de ponta a ponta."
)


def _file(path: str) -> bool:
    return (PROJECT_ROOT / path.replace("/", "\\")).is_file() or (PROJECT_ROOT / path).is_file()


def _dir(path: str) -> bool:
    return (PROJECT_ROOT / path).is_dir()


def _grep(path: str, pattern: str) -> bool:
    p = PROJECT_ROOT / path
    if not p.is_file():
        return False
    try:
        return bool(re.search(pattern, p.read_text(encoding="utf-8", errors="replace")))
    except OSError:
        return False


def _pytest(rel_path: str) -> bool:
    target = PROJECT_ROOT / rel_path
    if not target.exists():
        return False
    try:
        # RAVENNA_CAPABILITY_PROBE quebra recursão: o smoke test chama
        # /api/agents/evolution, que reavalia capability e re-executaria probes.
        env = {**os.environ, "RAVENNA_CAPABILITY_PROBE": "1"}
        r = subprocess.run(
            [sys.executable, "-m", "pytest", str(target), "-q", "--tb=no"],
            capture_output=True,
            text=True,
            timeout=600,
            cwd=str(PROJECT_ROOT),
            env=env,
        )
        return r.returncode == 0
    except Exception:
        return False


ProbeFn = Callable[[], bool]

EXT = "ravenna-ide/extensions/ravenna-ai"


def _ext_file(rel: str) -> bool:
    return _file(f"{EXT}/{rel}")


def _ext_grep(rel: str, pattern: str) -> bool:
    return _grep(f"{EXT}/{rel}", pattern)


def _vscode_shell() -> bool:
    """Workbench nativo VS Code + extensão Ravenna empacotável."""
    return _ext_file("package.json") and _ext_grep("src/extension.ts", r"activate")


def _or(*fns: ProbeFn) -> bool:
    return any(fn() for fn in fns)


CURSOR_PARITY_OBJECTIVES: list[dict[str, Any]] = [
    {
        "id": "workbench_shell",
        "category": "shell",
        "tier": "must",
        "title": "Workbench (activity bar + painéis)",
        "cursor_equivalent": "Layout VS Code / Cursor",
        "owner": "frontend-lead",
        "probe": lambda: _or(
            lambda: _file("ravenna-ide/frontend/src/pages/App.tsx")
            and _file("ravenna-ide/frontend/src/layout/ActivityBar.tsx"),
            _vscode_shell,
        ),
    },
    {
        "id": "file_explorer",
        "category": "explorer",
        "tier": "must",
        "title": "Explorer de arquivos",
        "cursor_equivalent": "File tree + abrir arquivos",
        "owner": "frontend-lead",
        "probe": lambda: _or(
            lambda: _file("ravenna-ide/frontend/src/components/FileExplorer.tsx"),
            _vscode_shell,
        ),
        "test": "tests/test_workspace_api.py",
    },
    {
        "id": "monaco_editor",
        "category": "editor",
        "tier": "must",
        "title": "Editor Monaco com abas",
        "cursor_equivalent": "Editor com syntax highlight e tabs",
        "owner": "frontend-lead",
        "probe": lambda: _or(
            lambda: _file("ravenna-ide/frontend/src/components/MonacoEditorPane.tsx")
            and _file("ravenna-ide/frontend/src/components/EditorWorkbench.tsx"),
            _vscode_shell,
        ),
    },
    {
        "id": "editor_save",
        "category": "editor",
        "tier": "must",
        "title": "Salvar arquivos (Ctrl+S)",
        "cursor_equivalent": "PUT workspace + dirty state",
        "owner": "backend-lead",
        "probe": lambda: _or(
            lambda: _grep("ravenna-ide/frontend/src/pages/App.tsx", r"handleSave|savedContent"),
            _vscode_shell,
        ),
    },
    {
        "id": "integrated_terminal",
        "category": "terminal",
        "tier": "must",
        "title": "Terminal integrado",
        "cursor_equivalent": "xterm.js + PTY WebSocket",
        "owner": "backend-lead",
        "probe": lambda: _or(
            lambda: _file("ravenna-ide/frontend/src/components/TerminalPanel.tsx"),
            _vscode_shell,
        ),
        "test": "tests/test_terminal_backend.py",
    },
    {
        "id": "git_panel",
        "category": "git",
        "tier": "must",
        "title": "Painel Git (status, diff, commit)",
        "cursor_equivalent": "Source control básico",
        "owner": "backend-lead",
        "probe": lambda: _or(
            lambda: _file("ravenna-ide/frontend/src/components/GitPanel.tsx"),
            _vscode_shell,
        ),
        "test": "tests/test_git_api.py",
    },
    {
        "id": "ai_chat",
        "category": "ai",
        "tier": "must",
        "title": "Chat IA integrado",
        "cursor_equivalent": "Chat sidebar / painel",
        "owner": "frontend-lead",
        "probe": lambda: _or(
            lambda: _file("ravenna-ide/frontend/src/components/RavennaChatScreen.tsx"),
            lambda: _ext_grep("src/ravennaPanel.ts", r"chat|mainView|focusTab"),
        ),
    },
    {
        "id": "mcp_panel",
        "category": "mcp",
        "tier": "must",
        "title": "Painel MCP (tools embutidas)",
        "cursor_equivalent": "MCP tools list + invoke",
        "owner": "backend-lead",
        "probe": lambda: _or(
            lambda: _file("ravenna-ide/frontend/src/components/McpPanel.tsx"),
            lambda: _ext_grep("src/ravennaPanel.ts", r"'mcp'|invokeMcp"),
        ),
        "test": "tests/test_mcp_api.py",
    },
    {
        "id": "attachments_rag",
        "category": "context",
        "tier": "must",
        "title": "Anexos e indexação RAG",
        "cursor_equivalent": "@files / attachments",
        "owner": "data-engineer",
        "probe": lambda: _or(
            lambda: _file("ravenna-ide/frontend/src/components/AttachmentsPanel.tsx"),
            lambda: _ext_grep("src/ravennaPanel.ts", r"'attachments'|uploadAttachment"),
        ),
        "test": "tests/test_attachments.py",
    },
    {
        "id": "lsp_intellisense",
        "category": "editor",
        "tier": "must",
        "title": "LSP / IntelliSense",
        "cursor_equivalent": "Autocomplete, diagnostics, go-to-def",
        "owner": "frontend-lead",
        "probe": lambda: _or(
            lambda: _file("learning_agent/core/lsp_service.py")
            and _grep("learning_agent/api.py", r"/api/lsp/completion")
            and _grep("ravenna-ide/frontend/src/utils/lspBridge.ts", r"/api/lsp/completion"),
            lambda: _ext_grep("src/apiClient.ts", r"/api/lsp/completion"),
        ),
        "test": "tests/test_lsp_service.py",
    },
    {
        "id": "inline_completions",
        "category": "ai",
        "tier": "must",
        "title": "Completions inline (Tab)",
        "cursor_equivalent": "Copilot-style inline",
        "owner": "frontend-lead",
        "probe": lambda: _or(
            lambda: _file("ravenna-ide/frontend/src/components/InlineCompletionHost.tsx"),
            lambda: _ext_file("src/inlineCompletion.ts"),
        ),
    },
    {
        "id": "composer_agent",
        "category": "ai",
        "tier": "must",
        "title": "Modo Agent / Composer multi-arquivo",
        "cursor_equivalent": "Agent edita vários arquivos",
        "owner": "frontend-lead",
        "probe": lambda: _or(
            lambda: _grep(
                "ravenna-ide/frontend/src/components/ComposerPanel.tsx",
                r"applyEdits|parseFileBlocks|multi-arquivo",
            ),
            lambda: _ext_grep("src/agentRunner.ts", r"runAgentTask|maxTurns|agentChatStream"),
            lambda: _ext_grep("src/diffPreview.ts", r"computeLineDiff|buildDiffReviewItems"),
            lambda: _ext_grep("src/shellTools.ts", r"parseShellBlocks|runShellCommand"),
        ),
    },
    {
        "id": "agent_diff_inline",
        "category": "ai",
        "tier": "must",
        "title": "Diff inline antes de aplicar edits",
        "cursor_equivalent": "Preview diff no Agent",
        "owner": "frontend-lead",
        "probe": lambda: _ext_grep("src/diffPreview.ts", r"computeLineDiff|reviewViaNativeDiff")
        and _ext_grep("media/panel.js", r"renderDiffReview|diffReview"),
    },
    {
        "id": "agent_shell_tool",
        "category": "ai",
        "tier": "should",
        "title": "Shell tool no Agent (blocos ```shell```)",
        "cursor_equivalent": "Terminal tool no Agent",
        "owner": "reliability-lead",
        "probe": lambda: _ext_grep("src/shellTools.ts", r"runShellCommand")
        and _ext_grep("src/agentRunner.ts", r"runShellBlocksFromMessage|parseShellBlocks"),
    },
    {
        "id": "agent_delegate_manual",
        "category": "ai",
        "tier": "must",
        "title": "Delegação manual 1-clique (aba Agents)",
        "cursor_equivalent": "Subagent picker",
        "owner": "frontend-lead",
        "probe": lambda: _ext_grep("media/panel.js", r"selectDelegate|Delegar")
        and _ext_grep("src/ravennaPanel.ts", r"manualDelegate|selectDelegate"),
    },
    {
        "id": "agent_delegate_auto",
        "category": "ai",
        "tier": "should",
        "title": "Delegação automática por tarefa",
        "cursor_equivalent": "Auto subagent routing",
        "owner": "backend-lead",
        "probe": lambda: _file("learning_agent/core/agent_delegate.py")
        and _grep("learning_agent/api.py", r"/api/agents/delegate/route"),
    },
    {
        "id": "chat_context_files",
        "category": "ai",
        "tier": "must",
        "title": "@arquivo / @codebase no chat",
        "cursor_equivalent": "Context picker no composer",
        "owner": "frontend-lead",
        "probe": lambda: _or(
            lambda: _grep(
                "ravenna-ide/frontend/src/components/ChatInputBar.tsx",
                r"@file|contextFiles|attachContext",
            ),
            lambda: _ext_grep("src/apiClient.ts", r"@file|getActiveEditorContext"),
        ),
    },
    {
        "id": "command_palette",
        "category": "navigation",
        "tier": "must",
        "title": "Command palette (Ctrl+Shift+P)",
        "cursor_equivalent": "Paleta de comandos",
        "owner": "frontend-lead",
        "probe": lambda: _or(
            lambda: _file("ravenna-ide/frontend/src/components/CommandPalette.tsx"),
            _vscode_shell,
        ),
    },
    {
        "id": "global_search",
        "category": "navigation",
        "tier": "must",
        "title": "Busca global no workspace",
        "cursor_equivalent": "Search across files",
        "owner": "frontend-lead",
        "probe": lambda: _or(
            lambda: _file("ravenna-ide/frontend/src/components/GlobalSearchPanel.tsx"),
            _vscode_shell,
        ),
    },
    {
        "id": "file_watcher",
        "category": "explorer",
        "tier": "must",
        "title": "File watcher (árvore ao vivo)",
        "cursor_equivalent": "Auto-refresh explorer",
        "owner": "backend-lead",
        "probe": lambda: _or(
            lambda: _grep(
                "ravenna-ide/frontend/src/components/FileExplorer.tsx",
                r"file_changed|onFileChanged|onWorkspaceChange",
            )
            and _grep("learning_agent/ide.py", r"file_changed"),
            _vscode_shell,
        ),
    },
    {
        "id": "diff_editor",
        "category": "git",
        "tier": "must",
        "title": "Diff visual lado a lado",
        "cursor_equivalent": "Inline diff / gutter",
        "owner": "frontend-lead",
        "probe": lambda: _or(
            lambda: _file("ravenna-ide/frontend/src/components/DiffEditorPane.tsx")
            and _grep("ravenna-ide/frontend/src/components/DiffEditorPane.tsx", r"DiffEditor"),
            _vscode_shell,
        ),
    },
    {
        "id": "debugger",
        "category": "debug",
        "tier": "must",
        "title": "Debugger integrado",
        "cursor_equivalent": "Breakpoints + debug console",
        "owner": "backend-lead",
        "probe": lambda: _or(
            lambda: _file("ravenna-ide/frontend/src/components/DebugPanel.tsx"),
            _vscode_shell,
        ),
    },
    {
        "id": "extensions_host",
        "category": "extensions",
        "tier": "must",
        "title": "Sistema de extensões",
        "cursor_equivalent": "Extension host",
        "owner": "backend-lead",
        "probe": lambda: _dir("ravenna-ide/extensions"),
    },
    {
        "id": "external_mcp",
        "category": "mcp",
        "tier": "must",
        "title": "MCP externo (mcp.json)",
        "cursor_equivalent": "Spawn servidores MCP do usuário",
        "owner": "backend-lead",
        "probe": lambda: _file("learning_agent/core/mcp_external.py"),
    },
    {
        "id": "rules_skills_ui",
        "category": "agents",
        "tier": "must",
        "title": "Editor de Rules e Skills na IDE",
        "cursor_equivalent": ".cursor/rules UI",
        "owner": "frontend-lead",
        "probe": lambda: _or(
            lambda: _file("ravenna-ide/frontend/src/components/RulesSkillsPanel.tsx"),
            lambda: _ext_grep("src/ravennaPanel.ts", r"'rules'|getRulesSkills"),
        ),
    },
    {
        "id": "settings_keybindings",
        "category": "shell",
        "tier": "must",
        "title": "Configurações e atalhos",
        "cursor_equivalent": "Settings JSON + keybindings",
        "owner": "frontend-lead",
        "probe": lambda: _or(
            lambda: _file("ravenna-ide/frontend/src/components/SettingsPanel.tsx"),
            _vscode_shell,
        ),
    },
]

FRONTEND_POLISH_OBJECTIVES: list[dict[str, Any]] = [
    {
        "id": "ws_unsubscribe",
        "title": "WebSocket sem handlers duplicados",
        "probe": lambda: _grep("ravenna-ide/frontend/src/utils/websocket.ts", r"filter\(\(h\) => h !== handler\)"),
    },
    {
        "id": "observer_dedupe",
        "title": "Observador deduplica mensagens por id",
        "probe": lambda: _or(
            lambda: _grep("ravenna-ide/frontend/src/pages/App.tsx", r"prev\.some\(\(m\) => m\.id === msg\.id\)"),
            lambda: _ext_grep("src/ravennaPanel.ts", r"'observer'|getTheaterMessages"),
        ),
    },
    {
        "id": "chat_perf_cap",
        "title": "Chat limita mensagens renderizadas",
        "probe": lambda: _or(
            lambda: _grep("ravenna-ide/frontend/src/components/chat/ChatThread.tsx", r"slice\(-80\)"),
            lambda: _ext_grep("media/panel.js", r"slice\(-40\)"),
        ),
    },
    {
        "id": "completion_panel",
        "title": "Painel objetivo IDE (paridade Cursor)",
        "probe": lambda: _or(
            lambda: _file("ravenna-ide/frontend/src/components/IdeCompletionPanel.tsx"),
            lambda: _ext_grep("src/ravennaPanel.ts", r"'progress'|getIdeCompletion"),
        ),
    },
    {
        "id": "evolution_panel",
        "title": "Painel evolução dos agentes",
        "probe": lambda: _file("ravenna-ide/frontend/src/components/EvolutionPanel.tsx"),
    },
    {
        "id": "a11y_activity",
        "title": "Activity bar com aria-label",
        "probe": lambda: _grep("ravenna-ide/frontend/src/layout/ActivityBar.tsx", r"aria-label"),
    },
    {
        "id": "e2e_smoke",
        "title": "E2E smoke Playwright",
        "probe": lambda: _file("ravenna-ide/frontend/e2e/ide-smoke.spec.ts"),
    },
    {
        "id": "menubar",
        "title": "Menu bar estilo VS Code",
        "probe": lambda: _file("ravenna-ide/frontend/src/layout/MenuBar.tsx")
        and _grep("ravenna-ide/frontend/src/pages/App.tsx", r"MenuBar|menuGroups"),
    },
    {
        "id": "secondary_sidebar",
        "title": "Painel secundário AI (Cursor)",
        "probe": lambda: _or(
            lambda: _file("ravenna-ide/frontend/src/layout/SecondarySideBar.tsx"),
            lambda: _ext_grep("package.json", r"ravenna.mainView"),
        ),
    },
    {
        "id": "code_oss_fork",
        "title": "Fork Code-OSS + extensão Ravenna AI",
        "probe": lambda: _file("docs/ravenna-code-oss-fork.md")
        and _file("ravenna-ide/extensions/ravenna-ai/package.json")
        and _file("scripts/setup-code-oss-fork.ps1"),
    },
    {
        "id": "vscode_workbench_theme",
        "title": "Tema VS Code (workbench web ou Code-OSS)",
        "probe": lambda: _file("ravenna-ide/frontend/src/styles/vscode-workbench.css")
        and _grep("ravenna-ide/frontend/src/pages/App.tsx", r"ide-shell--vscode"),
    },
    {
        "id": "monaco_vs_dark",
        "title": "Monaco vs-dark (padrão VS Code)",
        "probe": lambda: _grep("ravenna-ide/frontend/src/components/MonacoEditorPane.tsx", r'vs-dark'),
    },
    {
        "id": "e2e_open_save",
        "title": "E2E open-save Playwright",
        "probe": lambda: _file("ravenna-ide/frontend/e2e/open-save.spec.ts"),
    },
    {
        "id": "ide_smoke_tests",
        "title": "Smoke backend da IDE",
        "probe": lambda: _file("tests/test_agent_ide_smoke.py"),
        "test": "tests/test_agent_ide_smoke.py",
    },
    {
        "id": "shell_css",
        "title": "CSS shell dedicado (ide-shell)",
        "probe": lambda: _file("ravenna-ide/frontend/src/styles/vscode-workbench.css"),
    },
    {
        "id": "responsive_chat",
        "title": "Textarea responsivo no chat",
        "probe": lambda: _or(
            lambda: _grep("ravenna-ide/frontend/src/components/ChatInputBar.tsx", r"<textarea"),
            lambda: _ext_grep("media/panel.js", r"textarea"),
        ),
    },
]


def _eval_objectives(
    items: list[dict[str, Any]],
    *,
    run_slow_probes: bool = False,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in items:
        probe: ProbeFn = item["probe"]
        try:
            met = bool(probe())
        except Exception:
            met = False
        test_path = item.get("test")
        if test_path and run_slow_probes:
            met = met and _pytest(test_path)
        row = {k: v for k, v in item.items() if k not in ("probe", "test")}
        row["met"] = met
        row["status"] = "done" if met else "pending"
        if test_path and not run_slow_probes:
            row["test_pending"] = True
        out.append(row)
    return out


def assess_completion(*, run_slow_probes: bool = False) -> dict[str, Any]:
    """Avalia paridade Cursor e polish do frontend."""
    cursor_items = _eval_objectives(CURSOR_PARITY_OBJECTIVES, run_slow_probes=run_slow_probes)
    polish_items = _eval_objectives(FRONTEND_POLISH_OBJECTIVES, run_slow_probes=run_slow_probes)

    must = [o for o in cursor_items if o.get("tier") == "must"]
    must_met = sum(1 for o in must if o["met"])
    must_total = len(must)
    cursor_pct = round(100.0 * sum(1 for o in cursor_items if o["met"]) / max(len(cursor_items), 1), 1)
    polish_pct = round(100.0 * sum(1 for o in polish_items if o["met"]) / max(len(polish_items), 1), 1)

    missing_must = [o["id"] for o in must if not o["met"]]
    missing_polish = [o["id"] for o in polish_items if not o["met"]]

    complete = (
        run_slow_probes
        and must_met == must_total
        and polish_pct >= COMPLETION_RULES["frontend_polish_min_pct"]
        and cursor_pct >= COMPLETION_RULES["cursor_parity_min_pct"]
    )

    by_category: dict[str, list[dict[str, Any]]] = {}
    for o in cursor_items:
        by_category.setdefault(o["category"], []).append(o)

    next_obj = next((o for o in cursor_items if not o["met"]), None)
    if not next_obj:
        next_obj = next((o for o in polish_items if not o["met"]), None)

    result = {
        "success": True,
        "complete": complete,
        "north_star": NORTH_STAR,
        "completion_rules": COMPLETION_RULES,
        "summary": {
            "cursor_parity_pct": cursor_pct,
            "frontend_polish_pct": polish_pct,
            "must_met": must_met,
            "must_total": must_total,
            "cursor_objectives_total": len(cursor_items),
            "polish_objectives_total": len(polish_items),
            "status_label": "CONCLUÍDA" if complete else "EM PROGRESSO",
        },
        "cursor_parity": cursor_items,
        "frontend_polish": polish_items,
        "by_category": by_category,
        "missing_must": missing_must,
        "missing_polish": missing_polish,
        "next_objective": next_obj,
        "recommended_owner": (next_obj or {}).get("owner", "frontend-lead"),
    }
    _persist_snapshot(result)
    return result


def get_next_objective() -> dict[str, Any]:
    report = assess_completion(run_slow_probes=False)
    nxt = report.get("next_objective")
    if not nxt:
        return {"success": True, "message": "Todos os objetivos atendidos — IDE concluída", "complete": True}
    return {
        "success": True,
        "complete": False,
        "objective": nxt,
        "owner": nxt.get("owner", "frontend-lead"),
        "cursor_equivalent": nxt.get("cursor_equivalent", ""),
    }


def run_ide_completion_sprint(
    *,
    broadcast_observer: bool = True,
) -> dict[str, Any]:
    """Sprint focado no próximo gap de paridade Cursor."""
    from learning_agent.core import agent_collaboration, agent_ide_practice, knowledge

    report = assess_completion()
    nxt = report.get("next_objective")
    if not nxt:
        return {
            "success": True,
            "action": "ide_completion_sprint",
            "complete": True,
            "message": "IDE já atende todos os critérios de conclusão",
        }

    owner = nxt.get("owner", "frontend-lead")
    obj_id = nxt["id"]
    title = nxt.get("title", obj_id)

    if broadcast_observer:
        agent_collaboration._broadcast_to_observer(
            owner,
            f"Objetivo IDE: implementar «{title}» (paridade: {nxt.get('cursor_equivalent', '')})",
            level="ide-completion",
        )

    improvement = agent_ide_practice.run_ide_improvement_sprint(
        owner, broadcast_observer=broadcast_observer
    )

    knowledge.add_note(
        f"[IDE objetivo] {title}",
        (
            f"## Gap\n{nxt.get('cursor_equivalent', '')}\n\n"
            f"## ID\n{obj_id}\n\n"
            f"## Progresso\n"
            f"Paridade Cursor: {report['summary']['cursor_parity_pct']}%\n"
            f"Polish frontend: {report['summary']['frontend_polish_pct']}%\n\n"
            f"## Proposta\n{improvement.get('proposal', '')[:1500]}"
        ),
        tags=["ide-completion", f"objective:{obj_id}", f"agent:{owner}", "cursor-parity"],
    )

    return {
        "success": True,
        "action": "ide_completion_sprint",
        "complete": False,
        "objective": nxt,
        "owner": owner,
        "improvement": improvement,
        "completion": report["summary"],
    }


def _persist_snapshot(report: dict[str, Any]) -> None:
    slim = {
        "complete": report["complete"],
        "north_star": report["north_star"],
        "summary": report["summary"],
        "missing_must": report["missing_must"][:12],
        "missing_polish": report["missing_polish"][:8],
        "next_objective_id": (report.get("next_objective") or {}).get("id"),
    }
    IDE_COMPLETION_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with IDE_COMPLETION_STATE_PATH.open("w", encoding="utf-8") as fh:
        json.dump(slim, fh, ensure_ascii=False, indent=2)


def load_completion_snapshot() -> dict[str, Any]:
    if not IDE_COMPLETION_STATE_PATH.is_file():
        return {"complete": False, "summary": {}}
    try:
        with IDE_COMPLETION_STATE_PATH.open(encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return {"complete": False, "summary": {}}
