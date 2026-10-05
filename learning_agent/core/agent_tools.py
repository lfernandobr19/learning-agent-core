"""Tools nativas do agente Gemma4 — Fase 3 (OpenAI-compatible + executor)."""

from __future__ import annotations

import contextvars
import json
from typing import Any

from learning_agent.core import (
    agent_investigate,
    agent_project_learning,
    codebase,
    context,
    errors,
    knowledge,
    workspace,
)

_TOOL_PROJECT_ROOT: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "tool_project_root",
    default=None,
)
_TOOL_ALLOWLIST: contextvars.ContextVar[frozenset[str] | None] = contextvars.ContextVar(
    "tool_allowlist",
    default=None,
)


def set_tool_project_root(project_root: str | None) -> contextvars.Token:
    """Define projectRoot ativo para read_file/list_files/grep (escopo da conversa)."""
    clean = (project_root or "").strip() or None
    return _TOOL_PROJECT_ROOT.set(clean)


def reset_tool_project_root(token: contextvars.Token) -> None:
    """Restaura projectRoot; tolera generator SSE fechado noutro contexto async."""
    try:
        _TOOL_PROJECT_ROOT.reset(token)
    except ValueError:
        # iter_chat_with_tools_loop pode ser fechado fora do contexto do .set().
        _TOOL_PROJECT_ROOT.set(None)


def set_tool_allowlist(allowlist: list[str] | None) -> contextvars.Token:
    clean = frozenset(allowlist) if allowlist is not None else None
    return _TOOL_ALLOWLIST.set(clean)


def reset_tool_allowlist(token: contextvars.Token) -> None:
    try:
        _TOOL_ALLOWLIST.reset(token)
    except ValueError:
        _TOOL_ALLOWLIST.set(None)


def active_tool_allowlist(extra: list[str] | None = None) -> frozenset[str] | None:
    if extra is not None:
        return frozenset(extra)
    return _TOOL_ALLOWLIST.get()


def _scope_tool_path(path: str) -> str:
    from learning_agent.core.workspace_bootstrap import scope_to_project_root

    raw = (path or "").replace("\\", "/").strip("/")
    if not raw:
        return raw
    root = _TOOL_PROJECT_ROOT.get()
    if root:
        return scope_to_project_root(root, raw)
    from learning_agent.core.workspace_roots import canonical_workspace_ref

    return canonical_workspace_ref(raw)

TOOL_NAMES = (
    "read_file",
    "write_file",
    "apply_patch",
    "run_terminal",
    "list_files",
    "search_code",
    "grep_workspace",
    "get_context_for_task",
    "get_related_errors",
    "search_knowledge",
    "get_project_lessons",
    "record_project_lesson",
    "expand_project_knowledge",
    "research_trusted_sources",
    "consult_specialist",
    "host_wake_display",
    "host_set_volume",
    "host_exec",
    "host_status",
    "windows_open_app",
    "windows_close_app",
    "windows_open_url",
    "windows_search_google",
    "windows_search_youtube",
    "windows_download_file",
    "windows_exec",
    "windows_status",
    "windows_wake",
    "windows_screenshot",
    "windows_record_screen",
    "windows_list_dir",
    "windows_list_windows",
    "windows_read_file",
    "windows_pull_file",
    "windows_find_files",
    "windows_transfer_to_debian",
    "windows_probe_media",
    "windows_convert_media",
    "windows_enrich_media",
    "windows_delete_file",
    "media_plan",
    "windows_send_media_to_pc",
    "android_status",
    "android_exec",
    "android_open_app",
    "android_close_app",
    "android_open_url",
    "android_list_dir",
    "android_find_files",
    "android_read_file",
    "android_pull_file",
    "android_battery",
    "android_notify",
    "android_toast",
    "android_clipboard_get",
    "android_clipboard_set",
    "android_location",
    "android_packages",
    "android_download_file",
    "android_write_file",
    "android_open_file",
    "android_adb_status",
    "android_adb_pair",
    "android_adb_connect",
    "android_adb_install",
    "android_adb_shell",
    "host_deploy_raven_link",
    "ha_list_lights",
    "ha_light_set",
    "cursor_list_targets",
    "cursor_bind_target",
    "cursor_notify_target",
    "cursor_enqueue_handoff",
    "list_mcp_servers",
    "call_mcp_tool",
    "browse_web",
    "web_search",
)


def openai_tool_schemas(*, allowlist: list[str] | None = None) -> list[dict[str, Any]]:
    effective = active_tool_allowlist(allowlist)
    schemas = [
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Lê um arquivo do workspace (path relativo, ex: learning_agent/core/llm.py).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Caminho relativo no workspace"},
                        "max_lines": {"type": "integer", "description": "Máximo de linhas (default 80)"},
                    },
                    "required": ["path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "write_file",
                "description": "Escreve ou sobrescreve um arquivo no workspace (path relativo ao project_root).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Caminho relativo no workspace"},
                        "content": {"type": "string", "description": "Conteúdo completo do arquivo"},
                    },
                    "required": ["path", "content"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "apply_patch",
                "description": "Aplica diff unificado a um arquivo existente no workspace.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Caminho relativo no workspace"},
                        "diff": {"type": "string", "description": "Diff unificado (formato patch)"},
                    },
                    "required": ["path", "diff"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "run_terminal",
                "description": "Executa comando shell allowlisted no project_root (pytest, npm, git status, etc.).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string", "description": "Comando shell completo"},
                    },
                    "required": ["command"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "list_files",
                "description": "Lista diretório do workspace.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "directory": {"type": "string", "description": "Pasta relativa (vazio = raiz)"},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "search_code",
                "description": "Busca semântica no código indexado.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "limit": {"type": "integer"},
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "grep_workspace",
                "description": "Grep regex nos arquivos de código do workspace.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "pattern": {"type": "string"},
                        "path_prefix": {"type": "string"},
                        "max_hits": {"type": "integer"},
                    },
                    "required": ["pattern"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_context_for_task",
                "description": "Agrega conhecimento, código, sessões e erros para a tarefa.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "task": {"type": "string"},
                        "limit": {"type": "integer"},
                    },
                    "required": ["task"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_related_errors",
                "description": "Erros passados relacionados ao tópico.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "limit": {"type": "integer"},
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "search_knowledge",
                "description": "Busca no conhecimento já indexado (notas, erros, pesquisas anteriores).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "limit": {"type": "integer"},
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_project_lessons",
                "description": "Lições essenciais do projeto (erros + regras compostas) — memória enxuta.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "project_id": {"type": "string", "description": "ex: ravenna-home"},
                        "limit": {"type": "integer"},
                    },
                    "required": ["project_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "record_project_lesson",
                "description": "Registra só falha/insight acionável e reutilizável (memória filtrada).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "project_id": {"type": "string"},
                        "error": {"type": "string"},
                        "fix": {"type": "string"},
                        "phase": {"type": "string"},
                        "kind": {"type": "string", "description": "failure | insight | pattern"},
                    },
                    "required": ["project_id", "error"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "expand_project_knowledge",
                "description": "Liga lições do projeto com novo tópico — aprendizado autodidata/flexível.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "project_id": {"type": "string"},
                        "topic": {"type": "string"},
                    },
                    "required": ["project_id", "topic"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "research_trusted_sources",
                "description": "Pesquisa fontes confiáveis (docs oficiais, MDN, FastAPI, etc.) e indexa.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "project_id": {"type": "string"},
                        "limit": {"type": "integer"},
                        "index": {"type": "boolean"},
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "consult_specialist",
                "description": "Consulta especialista (backend-lead, frontend-lead, qa-guardian, etc.) e absorve lições.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "specialist": {"type": "string"},
                        "topic": {"type": "string"},
                        "project_id": {"type": "string"},
                    },
                    "required": ["specialist", "topic"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "host_wake_display",
                "description": "Acorda a tela do host ligado (xset DPMS via SSH). WoL Windows fora de escopo.",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "host_set_volume",
                "description": "Ajusta volume do sink padrão no host (0.0–1.0) via wpctl/SSH.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "level": {
                            "type": "number",
                            "description": "Nível 0.0 (mudo) a 1.0 (100%)",
                        },
                    },
                    "required": ["level"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "host_exec",
                "description": (
                    "Executa comando shell no host do Luis via SSH (máquina ligada). "
                    "Use para baixar arquivos, tocar vídeo/áudio, abrir apps, scripts, etc. "
                    "DISPLAY=:0 e XDG_RUNTIME_DIR são injetados automaticamente. "
                    "Apps longos: nohup … >/tmp/ravenna-host-bg.log 2>&1 & echo BG_PID=$! "
                    "Denylist: rm -rf /, mkfs, dd em disco, wipefs."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string"},
                        "timeout": {"type": "integer", "description": "Timeout segundos (default 180)"},
                    },
                    "required": ["command"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "host_status",
                "description": "Status SSH do host (hostname/uname).",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "windows_open_app",
                "description": "Abre app no PC Windows (PC_DO_LUIS): chrome, discord, cursor, spotify, notepad, etc.",
                "parameters": {
                    "type": "object",
                    "properties": {"name": {"type": "string", "description": "Nome ou caminho do app"}},
                    "required": ["name"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "windows_close_app",
                "description": "Fecha app no PC Windows pelo nome do processo (chrome, discord, notepad, calc, etc.).",
                "parameters": {
                    "type": "object",
                    "properties": {"name": {"type": "string", "description": "Nome do app ou processo"}},
                    "required": ["name"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "windows_open_url",
                "description": "Abre URL no navegador padrão do Windows.",
                "parameters": {
                    "type": "object",
                    "properties": {"url": {"type": "string"}},
                    "required": ["url"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "windows_search_google",
                "description": "Pesquisa no Google no PC Windows.",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "windows_search_youtube",
                "description": "Pesquisa no YouTube no PC Windows.",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "windows_download_file",
                "description": "Baixa um arquivo http(s) para a pasta Downloads do Windows.",
                "parameters": {
                    "type": "object",
                    "properties": {"url": {"type": "string"}},
                    "required": ["url"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "windows_exec",
                "description": "Executa comando PowerShell no PC Windows (bloqueia format/shutdown destrutivo).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string"},
                        "timeout": {"type": "integer"},
                    },
                    "required": ["command"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "windows_screenshot",
                "description": "Captura screenshot do PC Windows (tela inteira ou janela pelo título).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "window_title": {"type": "string", "description": "Parte do título da janela (opcional)"},
                        "monitor": {"type": "integer", "description": "Índice do monitor (0=principal, -1=todos)"},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "windows_record_screen",
                "description": "Grava vídeo da tela do PC Windows (requer ffmpeg no PATH).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "seconds": {"type": "integer", "description": "Duração em segundos (1-120)"},
                    },
                    "required": ["seconds"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "windows_list_dir",
                "description": "Lista pasta ou arquivo no PC Windows.",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string", "description": "Caminho absoluto ou ~\\Documents"}},
                    "required": ["path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "windows_list_windows",
                "description": (
                    "Lista janelas top-level no Windows (visíveis e minimizadas/segundo plano) "
                    "e abas de navegador (Opera/Chrome/Edge/Firefox) via UI Automation. "
                    "Use para enxergar tudo que está aberto — não só a janela em foco."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Filtro opcional: opera, chrome, firefox, discord, cursor…",
                        },
                        "include_tabs": {
                            "type": "boolean",
                            "description": "Incluir abas dos navegadores (default true)",
                        },
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "windows_read_file",
                "description": "Lê conteúdo de arquivo de texto no PC Windows (imagens retornam mídia).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "max_bytes": {"type": "integer"},
                    },
                    "required": ["path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "windows_pull_file",
                "description": "Copia arquivo do PC Windows para a ravenna (sem limite de tamanho) e retorna URL de mídia.",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "windows_find_files",
                "description": "Busca arquivos no Windows (Downloads/Vídeos/Desktop) por nome. kind=video para filmes.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "kind": {"type": "string", "description": "video|any"},
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "windows_transfer_to_debian",
                "description": (
                    "Transfere vídeo/arquivo do Windows (pc-do-luis) para o Debian (ravenna) em background. "
                    "Retorna transfer id para acompanhar progresso 0–100% e ETA. "
                    "Passe query (nome do filme) ou windows_path absoluto. "
                    "Um filme por chamada — se o usuário pedir vários, chame esta tool N vezes "
                    "(uma por título). Depois do envio, se pediu biblioteca/Teatrinho, "
                    "use cursor_enqueue_handoff / cursor_notify_target no canal teatrinho."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Nome do vídeo/filme"},
                        "windows_path": {"type": "string", "description": "Caminho absoluto opcional"},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "windows_probe_media",
                "description": "Inspeciona faixas de áudio/legenda/vídeo de um arquivo no Windows via ffprobe.",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "windows_convert_media",
                "description": "Converte/remux arquivo no Windows para MKV (ffmpeg -c copy, preserva faixas).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "output_path": {"type": "string"},
                        "container": {"type": "string"},
                    },
                    "required": ["path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "windows_enrich_media",
                "description": (
                    "Completa MKV no Windows: áudio original de outra cópia local + legendas "
                    "(arquivo local ou OpenSubtitles), mux com ffmpeg."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "query": {"type": "string"},
                        "want_original_audio": {"type": "boolean"},
                        "want_subtitles": {"type": "boolean"},
                    },
                    "required": ["path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "windows_delete_file",
                "description": "Apaga arquivo no perfil do usuário Windows. Exige confirm=true.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "confirm": {"type": "boolean"},
                    },
                    "required": ["path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "media_plan",
                "description": (
                    "Inicia plano multi-etapas: achar → probe → enriquecer áudio/legenda → "
                    "converter MKV → transferir ao Debian → apagar cópia antiga."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "message": {"type": "string"},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "windows_send_media_to_pc",
                "description": "Envia mídia já hospedada na ravenna (upload do celular) para Downloads do Windows.",
                "parameters": {
                    "type": "object",
                    "properties": {"media_id": {"type": "string"}},
                    "required": ["media_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "windows_status",
                "description": "Status do Ravenna Windows Agent (PC_DO_LUIS).",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "windows_wake",
                "description": (
                    "Envia Wake-on-LAN para ligar o PC Windows (PC_DO_LUIS) quando desligado/suspendido. "
                    "Requer cabo/LAN e WoL habilitado na placa. Não funciona só via Tailscale se PC off."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "mac": {"type": "string", "description": "MAC opcional (default PC_DO_LUIS)"},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "android_status",
                "description": "Status do Ravenna Android Agent (m55 / Termux via Tailscale).",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "android_exec",
                "description": "Executa comando shell no Termux do celular m55.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string"},
                        "timeout": {"type": "integer", "description": "Segundos (default 120)"},
                    },
                    "required": ["command"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "android_open_app",
                "description": "Abre app no celular (whatsapp, chrome, youtube, settings, ou package name).",
                "parameters": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "android_close_app",
                "description": "Força parada de app no celular m55.",
                "parameters": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "android_open_url",
                "description": "Abre URL no navegador/apps do celular.",
                "parameters": {
                    "type": "object",
                    "properties": {"url": {"type": "string"}},
                    "required": ["url"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "android_list_dir",
                "description": "Lista pasta no celular (Termux home, ~/storage/shared/Download, /sdcard/...).",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "android_find_files",
                "description": "Busca arquivos no celular por nome (Download/DCIM/Pictures/Movies).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "kind": {
                            "type": "string",
                            "description": "any|image|video|audio|doc",
                        },
                        "max_results": {"type": "integer"},
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "android_read_file",
                "description": "Lê arquivo pequeno do celular (texto ou imagem base64).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "max_bytes": {"type": "integer"},
                    },
                    "required": ["path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "android_pull_file",
                "description": "Puxa arquivo do celular para mídia hospedada na Ravenna.",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "android_battery",
                "description": "Bateria do celular m55 (Termux:API).",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "android_notify",
                "description": "Envia notificação no celular.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "content": {"type": "string"},
                        "title": {"type": "string"},
                        "id": {"type": "string"},
                    },
                    "required": ["content"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "android_toast",
                "description": "Mostra toast curto na tela do celular.",
                "parameters": {
                    "type": "object",
                    "properties": {"text": {"type": "string"}},
                    "required": ["text"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "android_clipboard_get",
                "description": "Lê a área de transferência do celular.",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "android_clipboard_set",
                "description": "Define a área de transferência do celular.",
                "parameters": {
                    "type": "object",
                    "properties": {"text": {"type": "string"}},
                    "required": ["text"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "android_location",
                "description": "Localização aproximada do celular (rede).",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "android_packages",
                "description": "Lista packages instalados no celular (filtro opcional).",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "android_download_file",
                "description": (
                    "Baixa um arquivo no celular a partir de uma URL http(s) "
                    "(ex.: artefato Raven_Link em http://<RAVENNA_TAILSCALE_IP>:8100/artifacts/...)."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string"},
                        "dest": {"type": "string", "description": "Caminho opcional de destino"},
                        "timeout": {"type": "integer"},
                    },
                    "required": ["url"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "android_write_file",
                "description": "Escreve um arquivo no celular (utf8 ou base64).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "content": {"type": "string"},
                        "encoding": {"type": "string", "enum": ["utf8", "base64"]},
                    },
                    "required": ["path", "content"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "android_open_file",
                "description": (
                    "Abre um arquivo no celular. APK: usa adb install -r se ADB conectado; "
                    "senão fallback sideload intent (pode pedir toque Instalar)."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "android_adb_status",
                "description": (
                    "Status do ADB no M55 (wireless debugging via Termux): enabled, devices, connected."
                ),
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "android_adb_pair",
                "description": (
                    "Pareamento único ADB wireless: porta + código da tela Depuração sem fio no Galaxy."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "port": {"type": "integer"},
                        "code": {"type": "string"},
                        "host": {"type": "string", "description": "Default 127.0.0.1"},
                    },
                    "required": ["port", "code"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "android_adb_connect",
                "description": (
                    "Conecta adb ao porto de conexão da Depuração sem fio (persistido após sucesso)."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "port": {"type": "integer"},
                        "host": {"type": "string"},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "android_adb_install",
                "description": (
                    "Instala APK em silêncio via adb install -r (preferir após download do artefato)."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "android_adb_shell",
                "description": (
                    "Shell ADB allowlisted: am start/force-stop, input tap/swipe/text/keyevent, "
                    "settings a11y do Raven_Link, pm path/list/grant (pkgs Raven*), dumpsys package."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string"},
                        "timeout": {"type": "integer"},
                    },
                    "required": ["command"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "host_deploy_raven_link",
                "description": (
                    "No Debian ravenna: garante ~/Raven_Link, npm ci, build do core e pasta de artefatos."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "source_rsync_hint": {
                            "type": "string",
                            "description": "Opcional; se omitido só faz pull/npm no host",
                        }
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "ha_list_lights",
                "description": (
                    "Lista luzes do Home Assistant (quarto, etc.). "
                    "Use antes de controlar se não souber o entity_id."
                ),
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "ha_light_set",
                "description": (
                    "Controla luz do Home Assistant: ligar/desligar, brilho e COR. "
                    "Lâmpada do quarto default: light.meu_quarto. "
                    "Cores por color_name (vermelho, azul, verde, rosa, roxo, amarelo, "
                    "laranja, branco, ciano) ou rgb_color [r,g,b] 0-255, "
                    "ou color_temp_kelvin (2000-6500). Pedidos de cor → use esta tool."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "entity_id": {
                            "type": "string",
                            "description": "Ex: light.meu_quarto (default do quarto)",
                        },
                        "action": {
                            "type": "string",
                            "description": "on | off | toggle (default on)",
                        },
                        "brightness_pct": {
                            "type": "integer",
                            "description": "Brilho 0-100",
                        },
                        "color_name": {
                            "type": "string",
                            "description": "Nome da cor em PT (vermelho, azul, ...)",
                        },
                        "rgb_color": {
                            "type": "array",
                            "items": {"type": "integer"},
                            "description": "RGB [r,g,b] 0-255",
                        },
                        "color_temp_kelvin": {
                            "type": "integer",
                            "description": "Temperatura de cor em Kelvin",
                        },
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "cursor_list_targets",
                "description": (
                    "Lista canais Cursor nomeados (ex.: teatrinho). "
                    "Não são abas do Composer — são sessões SDK ligadas a um nome."
                ),
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "cursor_bind_target",
                "description": (
                    "Liga um nome (ex.: teatrinho) a um agent_id do Cursor SDK. "
                    "Use agent_id explícito, ou bind_current=true com user_id do Telegram."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "agent_id": {"type": "string"},
                        "bind_current": {"type": "boolean"},
                        "user_id": {"type": "string"},
                        "label": {"type": "string"},
                        "notes": {"type": "string"},
                    },
                    "required": ["name"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "cursor_notify_target",
                "description": (
                    "Notifica um canal Cursor nomeado (mensagem + inbox). "
                    "Use depois de enviar filme ao Debian para pedir importação na Biblioteca do Teatrinho."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Canal, ex.: teatrinho",
                        },
                        "message": {"type": "string"},
                        "user_id": {"type": "string"},
                        "kind": {"type": "string", "description": "notify|teatrinho_import"},
                        "title": {"type": "string"},
                        "payload": {"type": "object"},
                    },
                    "required": ["name", "message"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "cursor_enqueue_handoff",
                "description": (
                    "Só enfileira job no inbox do canal (sem chamar o agente agora). "
                    "Útil se o Cursor for processar a fila depois."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "kind": {"type": "string"},
                        "title": {"type": "string"},
                        "message": {"type": "string"},
                        "payload": {"type": "object"},
                    },
                    "required": ["name", "message"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "list_mcp_servers",
                "description": "Lista servidores MCP externos configurados (mcp.json do workspace/usuário).",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "call_mcp_tool",
                "description": "Invoca uma tool de um servidor MCP externo via stdio (JSON-RPC).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "server": {"type": "string", "description": "Nome do servidor MCP (ex: user-context7)"},
                        "tool": {"type": "string", "description": "Nome da tool no servidor"},
                        "arguments": {"type": "object", "description": "Argumentos da tool (JSON)"},
                    },
                    "required": ["server", "tool"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "browse_web",
                "description": "Abre uma URL em browser headless e extrai título + texto legível (suporta @web).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "URL http/https a buscar"},
                    },
                    "required": ["url"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "web_search",
                "description": "Busca web (DuckDuckGo HTML, sem API key) e retorna resultados em texto.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Termo de busca"},
                    },
                    "required": ["query"],
                },
            },
        },
    ]
    if effective is not None:
        schemas = [s for s in schemas if (s.get("function") or {}).get("name") in effective]
    return schemas


def execute_tool(name: str, arguments: dict[str, Any] | None = None) -> str:
    args = arguments or {}
    clean = (name or "").strip()
    if clean not in TOOL_NAMES:
        return json.dumps({"error": f"tool desconhecida: {clean}"}, ensure_ascii=False)

    allowed = _TOOL_ALLOWLIST.get()
    if allowed is not None and clean not in allowed:
        return json.dumps(
            {
                "error": (
                    f"tool `{clean}` bloqueada neste modo de entrega. "
                    f"Use: {', '.join(sorted(allowed))}."
                ),
            },
            ensure_ascii=False,
        )

    try:
        if clean == "read_file":
            path = _scope_tool_path(str(args.get("path") or ""))
            max_lines = int(args.get("max_lines") or 80)
            try:
                data = workspace.read_file(path)
            except workspace.WorkspaceError as exc:
                return json.dumps(
                    {"exists": False, "path": path, "error": exc.message},
                    ensure_ascii=False,
                )
            content = data.get("content") or ""
            lines = content.splitlines()
            head = "\n".join(lines[:max_lines])
            truncated = len(lines) > max_lines
            return json.dumps(
                {
                    "exists": True,
                    "path": data.get("path") or path,
                    "size": data.get("size"),
                    "truncated": truncated,
                    "total_lines": len(lines),
                    "content": head,
                },
                ensure_ascii=False,
            )

        if clean == "write_file":
            from learning_agent.core.agent_autonomy_runner import apply_write_blocks

            path = _scope_tool_path(str(args.get("path") or ""))
            content = str(args.get("content") or "")
            block_text = f"```write {path}\n{content}\n```"
            root = _TOOL_PROJECT_ROOT.get()
            result = apply_write_blocks(block_text, base_path=root)
            if result.get("applied"):
                result["previousContent"] = result["applied"][0].get("previousContent", "")
                result["existed"] = result["applied"][0].get("existed", False)
            return json.dumps(result, ensure_ascii=False)

        if clean == "apply_patch":
            from learning_agent.core.agent_autonomy_runner import apply_patch_blocks

            path = _scope_tool_path(str(args.get("path") or ""))
            diff = str(args.get("diff") or "")
            if diff.lstrip().startswith("@@"):
                diff = f"--- {path}\n+++ {path}\n{diff}"
            block_text = f"```patch {path}\n{diff}\n```"
            root = _TOOL_PROJECT_ROOT.get()
            result = apply_patch_blocks(block_text, base_path=root)
            if result.get("applied"):
                result["previousContent"] = result["applied"][0].get("previousContent", "")
                result["existed"] = result["applied"][0].get("existed", False)
            return json.dumps(result, ensure_ascii=False)

        if clean == "run_terminal":
            import subprocess

            from learning_agent.core import agent_autonomy_runner as autonomy_runner

            command = str(args.get("command") or "").strip()
            if not command:
                return json.dumps({"error": "command obrigatório"}, ensure_ascii=False)
            root = _TOOL_PROJECT_ROOT.get()
            cwd = autonomy_runner._resolve_project_root([], root) or workspace.resolve_path("")
            joined_cmd = command.replace("\\", "/")
            if any(
                token in joined_cmd
                for token in (
                    "scripts/restore_oficio_target_incontainer.sh",
                    "scripts/oficio_restore_and_judge.sh",
                    "scripts/oficio_golden_cp.sh",
                    "scripts/oficio_sim_login_dashboards.sh",
                    "scripts/oficio_acesse_aqui.sh",
                    "scripts/oficio_site_app_parity.sh",
                "scripts/oficio_blank_public_fix.sh",
                    "scripts/ravenna_rgb_state.sh",
                    "scripts/oficio_ui_regression_fix.sh",
                    "scripts/home_temp_sensors_fix.sh",
                    "scripts/oficio_login_download_fix.sh",
                    "scripts/oficio_android_apk_build.sh",
                    "scripts/_judge_oficio_restore.py",
                    "scripts/serve_oficio_tailscale.sh",
                )
            ):
                cwd = workspace.resolve_path("")
            safety = autonomy_runner._safe_shell_command(command)
            if not safety["ok"]:
                return json.dumps(
                    {
                        "ran": [],
                        "blockCount": 1,
                        "ok": False,
                        "failures": [],
                        "blocked": [{"command": command, "cwd": str(cwd), "reason": safety["reason"]}],
                    },
                    ensure_ascii=False,
                )
            timeout = 90
            if (
                "restore_oficio_target_incontainer.sh" in joined_cmd
                or "oficio_restore_and_judge.sh" in joined_cmd
                or "oficio_golden_cp.sh" in joined_cmd
                or "oficio_sim_login_dashboards.sh" in joined_cmd
                or "oficio_acesse_aqui.sh" in joined_cmd
                or "oficio_site_app_parity.sh" in joined_cmd
            ):
                timeout = 600
            try:
                proc = subprocess.run(
                    autonomy_runner._relativize_args_for_cwd(safety["args"], cwd),
                    cwd=cwd,
                    env=autonomy_runner._shell_env(cwd),
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    timeout=timeout,
                    check=False,
                )
                result = {
                    "ran": [
                        {
                            "command": command,
                            "cwd": str(cwd),
                            "exit_code": proc.returncode,
                            "output": (proc.stdout or "")[-6000:],
                            "skipped": False,
                            "reason": None,
                        }
                    ],
                    "blockCount": 1,
                    "ok": proc.returncode == 0,
                    "failures": [] if proc.returncode == 0 else [f"{command} exited {proc.returncode}"],
                    "blocked": [],
                }
                return json.dumps(result, ensure_ascii=False)
            except subprocess.TimeoutExpired as exc:
                return json.dumps(
                    {
                        "ran": [
                            {
                                "command": command,
                                "cwd": str(cwd),
                                "exit_code": 124,
                                "output": ((exc.stdout or "") + f"\nTimeout após {timeout}s").strip()[-6000:],
                                "skipped": False,
                                "reason": "timeout",
                            }
                        ],
                        "blockCount": 1,
                        "ok": False,
                        "failures": [f"{command} exited 124"],
                        "blocked": [],
                    },
                    ensure_ascii=False,
                )

        if clean == "list_files":
            directory = _scope_tool_path(str(args.get("directory") or ""))
            listing = workspace.list_directory(directory)
            entries = listing.get("entries") or []
            return json.dumps(
                {
                    "exists": True,
                    "path": listing.get("path") or directory or ".",
                    "entry_count": len(entries),
                    "entries": entries[:60],
                },
                ensure_ascii=False,
            )

        if clean == "search_code":
            query = str(args.get("query") or "")
            limit = int(args.get("limit") or 5)
            hits = codebase.search_code(query, limit=limit)
            slim = []
            for h in hits:
                meta = h.get("metadata") or {}
                slim.append(
                    {
                        "source": meta.get("source"),
                        "symbol": meta.get("symbol"),
                        "snippet": (h.get("content") or h.get("document") or "")[:500],
                    }
                )
            return json.dumps({"query": query, "results": slim}, ensure_ascii=False)

        if clean == "grep_workspace":
            pattern = str(args.get("pattern") or "")
            prefix = _scope_tool_path(str(args.get("path_prefix") or ""))
            max_hits = int(args.get("max_hits") or 8)
            hits = agent_investigate._grep_workspace(pattern, path_prefix=prefix, max_hits=max_hits)
            return json.dumps({"pattern": pattern, "hits": hits}, ensure_ascii=False)

        if clean == "get_context_for_task":
            task = str(args.get("task") or "")
            limit = int(args.get("limit") or 4)
            ctx = context.get_context_for_task(task, limit=limit)
            return json.dumps(ctx, ensure_ascii=False, default=str)

        if clean == "get_related_errors":
            query = str(args.get("query") or "")
            limit = int(args.get("limit") or 5)
            return json.dumps(
                {"query": query, "errors": errors.get_related_errors(query, limit=limit)},
                ensure_ascii=False,
            )

        if clean == "search_knowledge":
            query = str(args.get("query") or "")
            limit = int(args.get("limit") or 5)
            hits = knowledge.search(query, limit=limit)
            slim = [
                {
                    "id": h.get("id"),
                    "snippet": (h.get("content") or "")[:500],
                    "metadata": h.get("metadata"),
                }
                for h in hits
            ]
            return json.dumps({"query": query, "results": slim}, ensure_ascii=False)

        if clean == "get_project_lessons":
            project_id = str(args.get("project_id") or "").strip()
            limit = int(args.get("limit") or 8)
            lessons = agent_project_learning.list_lessons(project_id, limit=limit, min_utility=0.3)
            return json.dumps(
                {"project_id": project_id, "lessons": lessons},
                ensure_ascii=False,
            )

        if clean == "record_project_lesson":
            project_id = str(args.get("project_id") or "").strip()
            error_msg = str(args.get("error") or "").strip()
            fix = str(args.get("fix") or "").strip()
            phase = str(args.get("phase") or "").strip()
            kind = str(args.get("kind") or "failure").strip()
            entry = agent_project_learning.record_lesson(
                project_id,
                error=error_msg,
                fix=fix,
                phase=phase,
                kind=kind,
            )
            return json.dumps(entry, ensure_ascii=False)

        if clean == "expand_project_knowledge":
            project_id = str(args.get("project_id") or "").strip()
            topic = str(args.get("topic") or "").strip()
            payload = agent_project_learning.expand_knowledge_from_lessons(project_id, topic)
            return json.dumps(payload, ensure_ascii=False)

        if clean == "research_trusted_sources":
            query = str(args.get("query") or "").strip()
            project_id = str(args.get("project_id") or "").strip()
            limit = int(args.get("limit") or 3)
            index = args.get("index", True)
            if isinstance(index, str):
                index = index.lower() not in ("false", "0", "no")
            payload = agent_project_learning.research_trusted_sources(
                query,
                limit=limit,
                index=bool(index),
                project_id=project_id,
            )
            return json.dumps(payload, ensure_ascii=False)

        if clean == "consult_specialist":
            specialist = str(args.get("specialist") or "").strip()
            topic = str(args.get("topic") or "").strip()
            project_id = str(args.get("project_id") or "").strip()
            payload = agent_project_learning.consult_specialist(
                specialist,
                topic,
                project_id=project_id,
            )
            return json.dumps(payload, ensure_ascii=False)

        if clean in {"host_wake_display", "host_set_volume", "host_exec", "host_status"}:
            from learning_agent.core import ravenna_home_remote_ops as remote_ops

            _deny = ("rm -rf /", "mkfs", "dd of=/dev/sd", ":>/dev/sd", "wipefs")

            def _denied(cmd: str) -> bool:
                low = cmd.casefold()
                return any(tok.casefold() in low for tok in _deny)

            if clean == "host_wake_display":
                cmd = (
                    "bash -lc '"
                    "export DISPLAY=${DISPLAY:-:0}; "
                    "for a in \"$HOME/.Xauthority\" /run/user/$(id -u)/gdm/Xauthority /run/user/1000/gdm/Xauthority; do "
                    "[ -f \"$a\" ] && export XAUTHORITY=\"$a\" && break; done; "
                    "xset dpms force on 2>/dev/null || true; "
                    "xset s reset 2>/dev/null || true; "
                    "loginctl unlock-session 2>/dev/null || true; "
                    "(command -v xdotool >/dev/null && xdotool key Shift 2>/dev/null) || true; "
                    "echo WAKE_OK'"
                )
                return json.dumps(remote_ops.run_ssh_command(cmd, timeout=60), ensure_ascii=False)

            if clean == "host_set_volume":
                try:
                    level = float(args.get("level"))
                except (TypeError, ValueError):
                    return json.dumps({"ok": False, "error": "level inválido"}, ensure_ascii=False)
                pct = int(max(0.0, min(1.0, level)) * 100)
                cmd = (
                    f"bash -lc 'export XDG_RUNTIME_DIR=/run/user/1000; "
                    f"wpctl set-volume @DEFAULT_AUDIO_SINK@ {pct}%; echo VOL={pct}'"
                )
                return json.dumps(remote_ops.run_ssh_command(cmd, timeout=60), ensure_ascii=False)

            if clean == "host_status":
                cmd = "bash -lc 'hostname; uname -a; echo ---; who -b || true'"
                return json.dumps(remote_ops.run_ssh_command(cmd, timeout=30), ensure_ascii=False)

            command = str(args.get("command") or "").strip()
            if not command:
                return json.dumps({"ok": False, "error": "command obrigatório"}, ensure_ascii=False)
            if _denied(command):
                return json.dumps(
                    {
                        "ok": False,
                        "exit_code": 126,
                        "output": "comando bloqueado pela denylist",
                        "command": command,
                    },
                    ensure_ascii=False,
                )
            timeout = int(args.get("timeout") or 180)
            # GUI/session env for desktop actions (video, apps, audio).
            if "DISPLAY=" not in command and not command.lstrip().startswith("bash -lc"):
                escaped = command.replace("'", "'\"'\"'")
                command = (
                    "bash -lc '"
                    "export DISPLAY=${DISPLAY:-:0}; "
                    "export XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-/run/user/$(id -u)}; "
                    "export DBUS_SESSION_BUS_ADDRESS="
                    "${DBUS_SESSION_BUS_ADDRESS:-unix:path=$XDG_RUNTIME_DIR/bus}; "
                    f"{escaped}'"
                )
            return json.dumps(
                remote_ops.run_ssh_command(command, timeout=max(5, timeout)),
                ensure_ascii=False,
            )

        if clean.startswith("windows_"):
            from learning_agent.core import windows_agent_client as win

            if clean == "windows_status":
                return json.dumps(win.status(), ensure_ascii=False)
            if clean == "windows_open_app":
                return json.dumps(win.open_app(str(args.get("name") or "")), ensure_ascii=False)
            if clean == "windows_close_app":
                return json.dumps(win.close_app(str(args.get("name") or "")), ensure_ascii=False)
            if clean == "windows_open_url":
                return json.dumps(win.open_url(str(args.get("url") or "")), ensure_ascii=False)
            if clean == "windows_search_google":
                return json.dumps(win.search_google(str(args.get("query") or "")), ensure_ascii=False)
            if clean == "windows_search_youtube":
                return json.dumps(win.search_youtube(str(args.get("query") or "")), ensure_ascii=False)
            if clean == "windows_download_file":
                return json.dumps(win.download_url(str(args.get("url") or "")), ensure_ascii=False)
            if clean == "windows_exec":
                cmd = str(args.get("command") or "").strip()
                if not cmd:
                    return json.dumps({"ok": False, "error": "command obrigatório"}, ensure_ascii=False)
                timeout = int(args.get("timeout") or 120)
                return json.dumps(win.exec_command(cmd, timeout=timeout), ensure_ascii=False)
            if clean == "windows_screenshot":
                return json.dumps(
                    win.screenshot(
                        window_title=str(args.get("window_title") or ""),
                        monitor=int(args.get("monitor") or 0),
                    ),
                    ensure_ascii=False,
                )
            if clean == "windows_record_screen":
                return json.dumps(
                    win.record_screen(seconds=int(args.get("seconds") or 10)),
                    ensure_ascii=False,
                )
            if clean == "windows_list_dir":
                return json.dumps(win.list_dir(str(args.get("path") or "")), ensure_ascii=False)
            if clean == "windows_list_windows":
                return json.dumps(
                    win.list_windows(
                        str(args.get("name") or ""),
                        include_tabs=bool(args.get("include_tabs", True)),
                    ),
                    ensure_ascii=False,
                )
            if clean == "windows_read_file":
                return json.dumps(
                    win.read_file(
                        str(args.get("path") or ""),
                        max_bytes=int(args.get("max_bytes") or 512_000),
                    ),
                    ensure_ascii=False,
                )
            if clean == "windows_pull_file":
                return json.dumps(win.pull_file_to_media(str(args.get("path") or "")), ensure_ascii=False)
            if clean == "windows_find_files":
                return json.dumps(
                    win.find_files(
                        str(args.get("query") or ""),
                        kind=str(args.get("kind") or "video"),
                    ),
                    ensure_ascii=False,
                )
            if clean == "windows_transfer_to_debian":
                from learning_agent.core import file_transfer

                return json.dumps(
                    file_transfer.start_windows_video_transfer(
                        query=str(args.get("query") or ""),
                        windows_path=str(args.get("windows_path") or ""),
                    ),
                    ensure_ascii=False,
                )
            if clean == "windows_probe_media":
                return json.dumps(win.probe_media(str(args.get("path") or "")), ensure_ascii=False)
            if clean == "windows_convert_media":
                return json.dumps(
                    win.convert_media(
                        str(args.get("path") or ""),
                        output_path=str(args.get("output_path") or ""),
                        container=str(args.get("container") or "mkv"),
                    ),
                    ensure_ascii=False,
                )
            if clean == "windows_enrich_media":
                import os

                return json.dumps(
                    win.enrich_media(
                        str(args.get("path") or ""),
                        query=str(args.get("query") or ""),
                        want_original_audio=bool(args.get("want_original_audio", True)),
                        want_subtitles=bool(args.get("want_subtitles", True)),
                        opensubtitles_api_key=os.environ.get("OPENSUBTITLES_API_KEY", ""),
                        opensubtitles_username=os.environ.get("OPENSUBTITLES_USERNAME", ""),
                        opensubtitles_password=os.environ.get("OPENSUBTITLES_PASSWORD", ""),
                    ),
                    ensure_ascii=False,
                )
            if clean == "windows_delete_file":
                if not bool(args.get("confirm")):
                    return json.dumps(
                        {
                            "ok": False,
                            "needs_confirmation": True,
                            "path": str(args.get("path") or ""),
                            "error": (
                                "Confirmação necessária para apagar. "
                                "Chame de novo com confirm=true se o usuário autorizou."
                            ),
                        },
                        ensure_ascii=False,
                    )
                return json.dumps(win.delete_file(str(args.get("path") or "")), ensure_ascii=False)
            if clean == "media_plan":
                from learning_agent.core import media_plan

                return json.dumps(
                    media_plan.start_media_plan(
                        message=str(args.get("message") or ""),
                        query=str(args.get("query") or ""),
                        conversation_id=str(args.get("conversation_id") or ""),
                        channel=str(args.get("channel") or ""),
                    ),
                    ensure_ascii=False,
                )
            if clean == "windows_send_media_to_pc":
                return json.dumps(
                    win.send_media_to_downloads(str(args.get("media_id") or "")),
                    ensure_ascii=False,
                )

            if clean == "windows_wake":
                from learning_agent.core import ravenna_home_remote_ops as remote_ops
                from learning_agent.core import wol

                mac = str(args.get("mac") or wol.default_windows_mac()).strip()
                bcast = (os.environ.get("WOL_BROADCAST") or "192.168.18.255").strip()
                hexmac = mac.replace(":", "").replace("-", "")
                cmd = (
                    f"python3 -c \"import socket; m=bytes.fromhex('{hexmac}'); "
                    f"p=b'\\xff'*6+m*16; s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); "
                    f"s.setsockopt(socket.SOL_SOCKET,socket.SO_BROADCAST,1); "
                    f"s.sendto(p,('{bcast}',9)); print('WOL_OK', '{mac}')\""
                )
                result = remote_ops.run_ssh_command(cmd, timeout=30)
                result["mac"] = mac
                result["broadcast"] = bcast
                result["target"] = "windows"
                return json.dumps(result, ensure_ascii=False)

        if clean.startswith("android_"):
            from learning_agent.core import android_agent_client as android

            if clean == "android_status":
                return json.dumps(android.status(), ensure_ascii=False)
            if clean == "android_exec":
                cmd = str(args.get("command") or "").strip()
                if not cmd:
                    return json.dumps({"ok": False, "error": "command obrigatorio"}, ensure_ascii=False)
                timeout = int(args.get("timeout") or 120)
                return json.dumps(android.exec_command(cmd, timeout=timeout), ensure_ascii=False)
            if clean == "android_open_app":
                return json.dumps(android.open_app(str(args.get("name") or "")), ensure_ascii=False)
            if clean == "android_close_app":
                return json.dumps(android.close_app(str(args.get("name") or "")), ensure_ascii=False)
            if clean == "android_open_url":
                return json.dumps(android.open_url(str(args.get("url") or "")), ensure_ascii=False)
            if clean == "android_list_dir":
                return json.dumps(android.list_dir(str(args.get("path") or "")), ensure_ascii=False)
            if clean == "android_find_files":
                return json.dumps(
                    android.find_files(
                        str(args.get("query") or ""),
                        kind=str(args.get("kind") or "any"),
                        max_results=int(args.get("max_results") or 20),
                    ),
                    ensure_ascii=False,
                )
            if clean == "android_read_file":
                return json.dumps(
                    android.read_file(
                        str(args.get("path") or ""),
                        max_bytes=int(args.get("max_bytes") or 512_000),
                    ),
                    ensure_ascii=False,
                )
            if clean == "android_pull_file":
                return json.dumps(
                    android.pull_file_to_media(str(args.get("path") or "")),
                    ensure_ascii=False,
                )
            if clean == "android_battery":
                return json.dumps(android.battery(), ensure_ascii=False)
            if clean == "android_notify":
                return json.dumps(
                    android.notify(
                        str(args.get("content") or ""),
                        title=str(args.get("title") or "Ravenna"),
                        id=str(args.get("id") or "ravenna"),
                    ),
                    ensure_ascii=False,
                )
            if clean == "android_toast":
                return json.dumps(android.toast(str(args.get("text") or "")), ensure_ascii=False)
            if clean == "android_clipboard_get":
                return json.dumps(android.clipboard_get(), ensure_ascii=False)
            if clean == "android_clipboard_set":
                return json.dumps(android.clipboard_set(str(args.get("text") or "")), ensure_ascii=False)
            if clean == "android_location":
                return json.dumps(android.location(), ensure_ascii=False)
            if clean == "android_packages":
                return json.dumps(android.packages(str(args.get("query") or "")), ensure_ascii=False)
            if clean == "android_download_file":
                return json.dumps(
                    android.download_url(
                        str(args.get("url") or ""),
                        dest=str(args.get("dest") or ""),
                        timeout=int(args.get("timeout") or 300),
                    ),
                    ensure_ascii=False,
                )
            if clean == "android_write_file":
                return json.dumps(
                    android.write_file(
                        str(args.get("path") or ""),
                        str(args.get("content") or ""),
                        encoding=str(args.get("encoding") or "utf8"),
                    ),
                    ensure_ascii=False,
                )
            if clean == "android_open_file":
                return json.dumps(android.open_file(str(args.get("path") or "")), ensure_ascii=False)
            if clean.startswith("android_adb_"):
                from learning_agent.core import android_adb_client as adb

                if clean == "android_adb_status":
                    return json.dumps(adb.status(), ensure_ascii=False)
                if clean == "android_adb_pair":
                    return json.dumps(
                        adb.pair(
                            port=int(args.get("port") or 0),
                            code=str(args.get("code") or ""),
                            host=str(args.get("host") or "127.0.0.1"),
                        ),
                        ensure_ascii=False,
                    )
                if clean == "android_adb_connect":
                    port = args.get("port")
                    return json.dumps(
                        adb.connect(
                            port=int(port) if port is not None else None,
                            host=str(args.get("host") or "127.0.0.1"),
                        ),
                        ensure_ascii=False,
                    )
                if clean == "android_adb_install":
                    return json.dumps(adb.install(str(args.get("path") or "")), ensure_ascii=False)
                if clean == "android_adb_shell":
                    return json.dumps(
                        adb.shell(
                            str(args.get("command") or ""),
                            timeout=int(args.get("timeout") or 45),
                        ),
                        ensure_ascii=False,
                    )

        if clean == "host_deploy_raven_link":
            from learning_agent.core.ravenna_home_remote_ops import deploy_raven_link

            return json.dumps(deploy_raven_link(), ensure_ascii=False)

        if clean.startswith("ha_"):
            from learning_agent.core import homeassistant_client as ha

            if clean == "ha_list_lights":
                return json.dumps(ha.list_lights(), ensure_ascii=False)
            if clean == "ha_light_set":
                rgb = args.get("rgb_color")
                if isinstance(rgb, str):
                    try:
                        rgb = json.loads(rgb)
                    except json.JSONDecodeError:
                        rgb = None
                return json.dumps(
                    ha.set_light(
                        entity_id=str(args.get("entity_id") or "") or None,
                        action=str(args.get("action") or "on"),
                        brightness_pct=(
                            int(args["brightness_pct"])
                            if args.get("brightness_pct") is not None
                            else None
                        ),
                        color_name=str(args.get("color_name") or "") or None,
                        rgb_color=rgb if isinstance(rgb, list) else None,
                        color_temp_kelvin=(
                            int(args["color_temp_kelvin"])
                            if args.get("color_temp_kelvin") is not None
                            else None
                        ),
                    ),
                    ensure_ascii=False,
                )

        if clean.startswith("cursor_"):
            from learning_agent.core import cursor_targets

            if clean == "cursor_list_targets":
                return json.dumps(
                    {"ok": True, "targets": cursor_targets.list_targets()},
                    ensure_ascii=False,
                )
            if clean == "cursor_bind_target":
                bind_current = bool(args.get("bind_current"))
                return json.dumps(
                    cursor_targets.bind_target(
                        str(args.get("name") or ""),
                        agent_id=str(args.get("agent_id") or "") or None,
                        label=str(args.get("label") or "") or None,
                        notes=str(args.get("notes") or "") or None,
                        bind_current_session_user_id=(
                            str(args.get("user_id") or "") if bind_current else None
                        ),
                    ),
                    ensure_ascii=False,
                )
            if clean == "cursor_notify_target":
                payload = args.get("payload")
                if isinstance(payload, str):
                    try:
                        payload = json.loads(payload)
                    except json.JSONDecodeError:
                        payload = {"raw": payload}
                return json.dumps(
                    cursor_targets.notify_target(
                        str(args.get("name") or ""),
                        str(args.get("message") or ""),
                        user_id=str(args.get("user_id") or "mobile"),
                        also_inbox=True,
                        inbox_kind=str(args.get("kind") or "notify"),
                        inbox_title=str(args.get("title") or ""),
                        inbox_payload=payload if isinstance(payload, dict) else None,
                    ),
                    ensure_ascii=False,
                )
            if clean == "cursor_enqueue_handoff":
                payload = args.get("payload")
                if isinstance(payload, str):
                    try:
                        payload = json.loads(payload)
                    except json.JSONDecodeError:
                        payload = {"raw": payload}
                return json.dumps(
                    cursor_targets.enqueue_handoff(
                        str(args.get("name") or ""),
                        kind=str(args.get("kind") or "task"),
                        title=str(args.get("title") or ""),
                        message=str(args.get("message") or ""),
                        payload=payload if isinstance(payload, dict) else None,
                    ),
                    ensure_ascii=False,
                )
            if clean == "list_mcp_servers":
                from learning_agent.core.mcp_external import load_external_mcp

                return json.dumps(load_external_mcp(), ensure_ascii=False)
            if clean == "call_mcp_tool":
                from learning_agent.core.mcp_external import call_mcp_tool

                call_args = args.get("arguments")
                if isinstance(call_args, str):
                    try:
                        call_args = json.loads(call_args)
                    except json.JSONDecodeError:
                        call_args = {"raw": call_args}
                if not isinstance(call_args, dict):
                    call_args = {}
                return json.dumps(
                    call_mcp_tool(
                        str(args.get("server") or ""),
                        str(args.get("tool") or ""),
                        call_args,
                    ),
                    ensure_ascii=False,
                )
            if clean == "browse_web":
                from learning_agent.core.browser_tool import browse_web

                return json.dumps(
                    browse_web(str(args.get("url") or "")),
                    ensure_ascii=False,
                )
            if clean == "web_search":
                from learning_agent.core.browser_tool import fetch_web_search

                return json.dumps(
                    fetch_web_search(str(args.get("query") or "")),
                    ensure_ascii=False,
                )

    except workspace.WorkspaceError as exc:
        return json.dumps({"error": exc.message}, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)

    return json.dumps({"error": "tool não executada"}, ensure_ascii=False)


def parse_tool_arguments(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}
