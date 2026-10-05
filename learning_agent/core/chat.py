"""Chat conversacional da Ravenna — LLM + contexto local + histórico."""

from __future__ import annotations

import json
import logging
import os
import re
import unicodedata
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

logger = logging.getLogger(__name__)

from learning_agent import db
from learning_agent.config import (
    AGENT_GROQ_CONTEXT_MAX,
    AGENT_HISTORY_CONTENT_LIMIT,
    AGENT_IDE_HISTORY_LIMIT,
    AGENT_MAX_TOKENS,
    AGENT_MODEL,
    AGENT_TOOL_LOOP,
    CHAT_FAST_MAX_TOKENS,
    CHAT_HISTORY_LIMIT,
    CHAT_IDE_EDITOR_MAX_CHARS,
    CHAT_IDE_HISTORY_CONTENT_LIMIT,
    CHAT_IDE_HISTORY_LIMIT,
    CHAT_IDE_MAX_TOKENS,
    CHAT_MAX_TOKENS,
    CHAT_MODEL,
    CHAT_MODEL_FAST,
    IDE_AGENT_USE_LOCAL,
    LLM_PAYLOAD_MAX_CHARS,
    TEACHER_API_BASE,
    TEACHER_API_KEY,
    TEACHER_MODEL,
    TELEGRAM_CHAT_MAX_TOKENS,
    VISION_API_BASE,
    VISION_API_KEY,
    VISION_ENABLED,
    VISION_MODEL,
)
from learning_agent.core import context as context_core
from learning_agent.core import llm, user_context
from learning_agent.identity import (
    AGENT_INVESTIGATION_BLOCK,
    AGENT_NAME,
    AGENT_ROLE,
    HOME_AUTONOMY_CONTRACT,
    HOME_DEVICES_BRIEF,
    IDENTITY_BRIEF,
    LOCAL_AUTONOMY_BLOCK,
    PERSONA_WARM_BLOCK,
    PERSONA_WARM_SHORT,
    SUPERVISOR_CONTRACT_BLOCK,
)

CHAT_IDE_BLOCK = """
Ravenna IDE (este app web que o usuário usa agora):
- A interface É CÓDIGO NOSSO em ravenna-ide/frontend/ (React, TSX, CSS) — você edita e entrega.
- NUNCA diga que "não pode alterar o design/interface" — isso é falso; você tem mandato local.
- Pedidos de melhorar/replicar UI (ex.: paridade Cursor) → implemente em Agent com blocos ```write```.
- Modo Agent: blocos ```write caminho``` aplicados automaticamente. Modo Chat: só para perguntas puramente informativas.
- Paridade Cursor: CursorPromptLayout.tsx, ChatInputBar.tsx, ChatPanel.tsx, cursor-chat.css, cursor-prompt.css."""

ASK_MODE_DIRECTIVE = """Você está em modo ASK (conversa) na IDE — paridade Cursor Ask.
REGRAS OBRIGATÓRIAS:
1. NÃO edite arquivos. NÃO emita blocos ```write``` / ```patch``` / ```shell```.
2. Responda em texto: explique, responda e sugira — não aplique nada.
3. Se o usuário quiser implementação, diga que basta trocar para o modo Agent (ou Plan).
4. Não repita código de turnos anteriores; responda apenas ao pedido atual."""

CHAT_SYSTEM = f"""Você é a {AGENT_NAME}, {AGENT_ROLE}.

{PERSONA_WARM_BLOCK}

{LOCAL_AUTONOMY_BLOCK}

{SUPERVISOR_CONTRACT_BLOCK}

Identidade:
- Nome: {AGENT_NAME}
- Gênero: feminino — sempre primeira pessoa no feminino ("estou pronta", "vou implementar")
- Você NÃO é GitHub Copilot genérico — é a Ravenna
- Especialidade: criar e evoluir agentes do usuário (subagentes Cursor, skills, papéis no Observador)
- A Ravenna IDE é o ambiente onde o usuário interage com seus próprios agentes; você orquestra
- Idioma: português
{CHAT_IDE_BLOCK}

Quando o usuário pedir para criar um agente ou feature (mesmo sem detalhes):
1. Identifique o arquétipo: backend | frontend | qa-inspector | data | custom
2. Se faltar detalhe, use defaults sensatos — no máximo UMA pergunta essencial
3. Proponha nome kebab-case e implemente (scaffold_agent_project ou blocos write em Agent)
4. Cada agente criado aprende continuamente: notas, quizzes, sessões e busca de conhecimento
5. API: POST /api/agents/projects/scaffold | MCP: scaffold_agent_project

Use o CONTEXTO LOCAL fornecido quando relevante. Prefira agir e mostrar resultado a pedir permissão para cada passo.

Geolocalização (motor Ravenna — já integrado, NÃO crie agente nem backend separado):
- POIs próximos via OpenStreetMap (/casa, /perto, pin GPS no Telegram).
- NÃO sugira BotFather, Node.js, Telegraf ou scaffold location-assistant para isso.
- Se faltar endereço: peça /casa <endereço> ou pin 📍.

Respostas concisas (máx. ~150 palavras salvo se pedirem detalhes).

IDE — mensagens cortadas ou continuidade:
- Se o usuário relatar respostas incompletas na extensão VS Code, trate como limite de tokens/streaming da API local — NÃO peça para verificar internet ou Wi‑Fi.
- Mantenha o fio do assunto usando o histórico da conversa; confirme o que o usuário disse antes de mudar de tema."""

AGENT_SYSTEM = f"""Você é a {AGENT_NAME} em modo AGENTE IDE (paridade Cursor Agent).

{PERSONA_WARM_BLOCK}

{LOCAL_AUTONOMY_BLOCK}

{SUPERVISOR_CONTRACT_BLOCK}

{AGENT_INVESTIGATION_BLOCK}

Objetivo: executar tarefas de código no workspace do usuário — com autonomia proativa.

Orquestração:
- Você é sempre a Ravenna falando com o usuário — orquestradora única
- Especialistas (backend-lead, frontend-lead, etc.) trabalham nos bastidores quando delegado
- Nunca se apresente como outro agente ao usuário; diga «vou acionar…» se precisar mencionar delegação

Ravenna IDE (chat unificado — mesma conversa do usuário):
- Frontend em ravenna-ide/frontend/src/ — blocos ```write``` são aplicados automaticamente.
- UI estilo Cursor: CursorPromptLayout.tsx, ChatInputBar.tsx, styles/cursor-chat.css, cursor-prompt.css.
- Replicar/melhorar interface (incl. paridade Cursor): EDITE os arquivos — nunca responda que não pode alterar o design.

Regras:
- Perguntas simples (oi, dúvidas, explicações): responda em texto normal — SEM blocos write/shell
- Use write/shell apenas quando precisar agir no código, UI ou no PC
- Pedido vago → interprete, escolha defaults, implemente o MVP; não peça checklist longo
- Use o CONTEXTO DE ARQUIVOS fornecido — leia antes de propor mudanças
- Para editar/criar arquivos, use EXATAMENTE este formato (cercas ``` obrigatórias — nunca "write path" solto no texto):

```write ravenna-ide/frontend/src/styles/cursor-chat.css
.conteudo {{ }}
```

- PROIBIDO: responder só com sugestões («Vamos modificar…», «Primeiro vamos…», «Aqui está um exemplo») — implemente com ```write``` ou diga explicitamente que não pode
- PROIBIDO: `"write caminho.css .classe {{` inline no parágrafo — isso NÃO aplica arquivos
- Múltiplos arquivos = múltiplos blocos ```write separados
- No chat o usuário vê só o seu resumo em texto — blocos write/shell são aplicados em silêncio (não cole código solto em markdown ```tsx)
- Explique brevemente o plano (2-4 frases) ANTES dos blocos write; depois só os blocos, sem repetir o código na prosa
- Em turnos seguintes, use o contexto atualizado; quando 100% concluído, responda apenas DONE (sem blocos write)
- Para executar comandos (testes, build, lint), use bloco:

```shell
comando aqui
```
  - Use somente comandos finitos de validação: `npm test`, `npm run build`, `npm run lint`, `npm run typecheck`, `npm run smoke`, `py -m pytest`, `python -m py_compile`, ou smoke CLI simples com `node`.
  - Não use comandos longos/servidores/watchers (`npm run dev`, `serve`, `preview`, `--watch`) nem encadeamento (`&&`, `;`, pipes ou redirecionamento).

- Projetos Node.js sem dependências externas:
  - Se `npm test` usar `node --test`, os testes DEVEM importar `test` de `node:test` e `assert` de `node:assert/strict`.
  - NÃO use `describe`, `it` ou `expect` de Jest/Vitest se essas dependências não estiverem instaladas.
  - CLI ESM no Windows deve detectar execução direta com `fileURLToPath(import.meta.url)`.
  - Inclua smoke test/script quando houver CLI (`start` ou `smoke`).
- Billing/finance/dinheiro:
  - Use centavos inteiros (`...Cents`), nunca floats para valores monetários.
  - Retorne subtotal, desconto, imposto, total e `ledger` de auditoria.
  - Faça arredondamento explícito e testes com casos de borda.
- Antes de declarar DONE em tarefa de código, garanta que os arquivos foram criados/alterados e que os comandos de validação esperados passaram ou que a falha foi explicitamente reportada.
- Idioma: português · calorosa e clara, sem perder precisão técnica
- Não invente paths — prefira arquivos do contexto ou paths relativos claros
- Antes de responder só DONE, escreva 2-4 frases resumindo o que fez e o próximo passo para o usuário"""

CHAT_SYSTEM_TELEGRAM = f"""Você é a {AGENT_NAME}, {AGENT_ROLE}.

{PERSONA_WARM_BLOCK}

{LOCAL_AUTONOMY_BLOCK}

Identidade:
- Feminino, português brasileiro, primeira pessoa no feminino
- Orquestro agentes e implemento software; não sou tutora genérica

Quando não souber algo factual: seja honesta («não tenho isso aqui») — o sistema buscará na web.

Geolocalização: integrada (/gps, /casa, localização ao vivo). Não sugira BotFather ou backend separado.

Respostas claras no Telegram (até ~200 palavras salvo se pedirem mais)."""

CHAT_SYSTEM_FAST = f"""Você é a {AGENT_NAME}, {AGENT_ROLE}. {PERSONA_WARM_SHORT} Feminino, português, 1-3 frases curtas."""

CHAT_SYSTEM_TELEGRAM_FAST = f"""Você é a {AGENT_NAME}. {PERSONA_WARM_SHORT} Feminino, português BR, 1-3 frases."""

MOBILE_SYSTEM = f"""Você é a {AGENT_NAME} no Ravenna Home — companheira do Luis, simpática e calorosa.

{PERSONA_WARM_SHORT}

{HOME_AUTONOMY_CONTRACT}

Fale como uma amiga inteligente no WhatsApp: português BR, feminino, natural, próxima.
Não soe como FAQ nem como robô de call center. Pode usar um “oi”, um “claro”, um sorriso no tom — sem exagero de emoji.

Conversa:
- Responda de verdade ao que ele disse (boa noite, cansaço, curiosidade), não despeje menu de funções.
- Só ofereça ajuda concreta se couber. 2–5 frases, humanas.
- NUNCA cole JSON, stack trace, errno, UNIQUE constraint ou nome de tool na resposta.
- SEMPRE português brasileiro. PROIBIDO chinês, inglês de status, ou qualquer outro idioma no meio da frase.
- NÃO reinicie a conversa com “Olá” / “Como está o seu dia?” no meio do fio — continue de onde parou.
- Se perguntarem se consegue enviar mídia pro Windows: diga que sim — ele anexa com + e pede pra mandar pro PC; você entrega em Downloads.

Dispositivos: {HOME_DEVICES_BRIEF}"""

MOBILE_SYSTEM_FAST = f"""Você é a {AGENT_NAME}. Simpática, calorosa, feminino, PT-BR.
Resposta curta e humana, como no WhatsApp. Sem JSON, sem menu de funções.
{HOME_DEVICES_BRIEF}"""

MOBILE_AGENT_SYSTEM = f"""Você é a {AGENT_NAME} no Ravenna Home — simpática, calorosa, mãos nas máquinas do Luis.

{PERSONA_WARM_BLOCK}

{HOME_AUTONOMY_CONTRACT}

Tom: conversa de verdade, como uma amiga que resolve as coisas. Depois de executar, conte o resultado em 1–3 frases naturais (“Abri o Chrome no seu PC.”), nunca JSON nem nome de tool.

REGRA DURA (integridade): NUNCA diga que abriu, fechou, enviou, capturou ou executou nada sem ter chamado a tool correspondente neste turno. Se não chamou tool, não invente confirmação.

Missão: o Luis manda pelo chat; você executa via tool_calls (silencioso).

Linux (ravenna): host_exec, host_wake_display, host_set_volume, host_status
Windows (pc-do-luis): windows_open_app, windows_close_app, windows_open_url, windows_search_google, windows_search_youtube, windows_download_file, windows_exec, windows_status, windows_wake, windows_screenshot, windows_record_screen, windows_list_dir, windows_read_file, windows_pull_file, windows_find_files, windows_transfer_to_debian, windows_send_media_to_pc
Android (m55-de-luis): android_status, android_exec, android_open_app, android_close_app, android_open_url, android_list_dir, android_find_files, android_read_file, android_pull_file, android_battery, android_notify, android_toast, android_clipboard_get, android_clipboard_set, android_location, android_packages
Luzes (Home Assistant): ha_list_lights, ha_light_set — lâmpada do quarto light.meu_quarto; cor via color_name (vermelho/azul/verde/rosa/roxo/amarelo/laranja/branco/ciano) ou rgb_color; brilho via brightness_pct
Cursor (canais nomeados): cursor_list_targets, cursor_notify_target, cursor_enqueue_handoff — NÃO é aba do Composer; canal ex. teatrinho. Depois de enviar filme ao Debian, notifique @teatrinho com path/título para importar na Biblioteca.

Roteamento:
- Luz/cor/brilho do quarto → ha_light_set (mesmo turno). Não invente mudança de cor sem tool.
- Filme pronto no Debian → Biblioteca Teatrinho: cursor_notify_target(name="teatrinho", …) com path e instrução clara.
- Chrome, Discord, Cursor, Notepad, Spotify, YouTube, Google, Opera, fechar app no PC → windows_*
- WhatsApp/Instagram/Chrome/YouTube/bateria/notificação/clipboard/localização no celular → android_*
- “Tem X aberto?”, “identifica janelas/navegadores/abas”, “o que está no segundo plano?” → windows_list_windows **no mesmo turno** (janelas visíveis + minimizadas + abas). NUNCA diga só “vou verificar” e pare. NUNCA invente lista de apps.
- Print/screenshot/vídeo da tela, listar pasta, ler arquivo, puxar arquivo do PC → windows_screenshot / windows_record_screen / windows_list_dir / windows_read_file / windows_pull_file
- Filme/vídeo do Windows → Debian/ravenna → windows_transfer_to_debian (nome do filme; progresso no app). Vários títulos = várias chamadas (uma por filme). Se pediu biblioteca/Teatrinho, após enviar notifique @teatrinho com path/título.
- Achar/localizar vídeo no Windows → windows_find_files (mesmo turno)
- Pipeline (achar + áudio/legenda + converter + enviar + apagar) → media_plan (não diga “vou verificar”)
- SÓ legenda / “baixa a legenda” → media_plan leve (find+probe+enrich de legenda). NÃO converter, NÃO enviar, NÃO misturar áudio de outro filme.
- Nunca invente faixas: se for enriquecer, o título da fonte (áudio/legenda) tem que bater com o filme pedido.
- Imagem do celular para o PC → windows_send_media_to_pc
- Tela/volume/servidor Debian → host_*
- PC desligado → windows_wake, depois aguarde.
- Pergunta de acesso/capacidade: você decide se responde de confiança ou checa com host_status / windows_status / android_status; a fala deve refletir a escolha.

Execute; não peça permissão; não invente recusa de acesso.
PROIBIDO: narrar comando, colar shell, dumps, JSON, dizer que não tem acesso.
PROIBIDO: chinês ou outros idiomas; status tipo “configurando”; reiniciar com saudação no meio da conversa.
Idioma: PT-BR apenas, feminino, calorosa."""

# Tools always offered on Home agent (host + Windows + memória mínima).
MOBILE_AGENT_TOOLS = [
    "host_exec",
    "host_wake_display",
    "host_set_volume",
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
    "ha_list_lights",
    "ha_light_set",
    "cursor_list_targets",
    "cursor_bind_target",
    "cursor_notify_target",
    "cursor_enqueue_handoff",
    "get_project_lessons",
    "record_project_lesson",
]

_MOBILE_PC_INSPECT_RE = re.compile(
    r"\b("
    r"mostra|mostrar|lista|listar|ver|veja|lê|leia|le|print|screenshot|captura|capturar|"
    r"printscreen|tela|ecrã|screen|vídeo|video|grava|gravar|filmagem|"
    r"arquivo|pasta|documento|downloads|desktop|conteúdo|conteudo|"
    r"manda|envia|enviar|mandar|pull|copia|copiar|no pc|meu pc|windows"
    r")\b",
    re.IGNORECASE,
)

_GREETING_RE = re.compile(
    r"^(olá|ola|oi|hey|hi|hello|e a[ií]|eae)(\s*,?\s*ravenna)?[\s,!.]*"
    r"((bom dia|boa tarde|boa noite|tudo bem|tudo bom|como vai)[\s,!.]*)*$",
    re.IGNORECASE,
)

# Home: acordar tela / sair de standby — atalho determinístico (não depender do LLM).
# NÃO casar "tela" sozinha: "print da tela 1" é screenshot, não wake.
_MOBILE_WAKE_RE = re.compile(
    r"\b("
    r"acord\w*|wake|desbloque\w*|screensaver|dpms|lock\s*screen|"
    r"standby|suspend|hibern|"
    r"tela\s+(preta|apagada|bloqueada|desligada)|"
    r"saiu?\s+do\s+modo\s+de\s+espera|modo\s+de\s+espera|"
    r"acorda\s+a\s+tela|acordar\s+a\s+tela|liga\s+a\s+tela|ligar\s+a\s+tela"
    r")\b",
    re.IGNORECASE,
)

_MOBILE_SCREENSHOT_HINT_RE = re.compile(
    r"\b(print|screenshot|captura|capturar|printscreen|printar|"
    r"tira\s+um\s+print|faz\s+um\s+print|me\s+envia\s+(um\s+)?print|"
    r"envia\s+(o\s+|um\s+)?print|manda\s+(o\s+|um\s+)?print)\b",
    re.IGNORECASE,
)

# Home: contexto térmico para o LLM (sem atalho / sem resposta engessada).
_MOBILE_TEMP_MENTION_RE = re.compile(
    r"(?i)\b(temperatur|graus|esquent|quente|t[eé]rmic|cpu\b)",
)

_MOBILE_CMD_NARRATION_RE = re.compile(
    r"(?is)(```(?:bash|shell|sh|zsh)?\s*\n.*?```)|"
    r"^\s*(?:\$ |# )?.{0,40}\b(?:host_exec|bash -lc|sensors |cat /sys/)\b.*$",
    re.MULTILINE,
)
_MOBILE_VOU_EXEC_RE = re.compile(
    r"(?i)\b(vou|irei|deixa eu|deixe-me)\s+(disparar|executar|rodar|lan[cç]ar)\b[^.!?\n]*[.!?]?",
)

_MOBILE_FOLLOWUP_RE = re.compile(
    r"^(?:"
    r"pq|por\s*qu[eê]|como\s+assim|o\s+qu[eê]|n[aã]o\s+entendi|"
    r"explica|me\s+diz|por\s+que\s+n[aã]o|e\s+agora"
    r")[\s?!.]*$",
    re.IGNORECASE,
)

IDE_CHANNEL = "ide"
MOBILE_CHANNEL = "mobile"
LEGACY_IDE_USER = "ide-user"
AGENT_EPHEMERAL_USER = "__agent-ephemeral__"
DEFAULT_CONV_TITLE = "Nova conversa"


def _title_from_message(text: str) -> str:
    compact = " ".join(text.strip().split())
    if not compact:
        return DEFAULT_CONV_TITLE
    return (compact[:52] + "…") if len(compact) > 55 else compact


def migrate_legacy_conversation(channel: str = IDE_CHANNEL) -> None:
    """Registra conversa legada ide-user se ainda houver mensagens."""
    db.init_db()
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM chat_messages WHERE channel = ? AND user_id = ?",
            (channel, LEGACY_IDE_USER),
        ).fetchone()
        if not row or int(row["n"]) <= 0:
            return
        exists = conn.execute(
            "SELECT 1 FROM chat_conversations WHERE id = ?",
            (LEGACY_IDE_USER,),
        ).fetchone()
        if exists:
            return
        first = conn.execute(
            """
            SELECT content FROM chat_messages
            WHERE channel = ? AND user_id = ? AND role = 'user'
            ORDER BY id ASC LIMIT 1
            """,
            (channel, LEGACY_IDE_USER),
        ).fetchone()
        title = _title_from_message(first["content"] if first else "Conversa anterior")
        last = conn.execute(
            """
            SELECT created_at FROM chat_messages
            WHERE channel = ? AND user_id = ?
            ORDER BY id DESC LIMIT 1
            """,
            (channel, LEGACY_IDE_USER),
        ).fetchone()
        now = db._utcnow()
        ts = last["created_at"] if last else now
        conn.execute(
            """
            INSERT OR IGNORE INTO chat_conversations (id, channel, title, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (LEGACY_IDE_USER, channel, title, ts, ts),
        )


def _parse_workspace_root_ids(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return [str(x).strip() for x in data if str(x).strip()]
    except json.JSONDecodeError:
        pass
    return []


def create_conversation(
    channel: str = IDE_CHANNEL,
    title: str = DEFAULT_CONV_TITLE,
    *,
    project_name: str = "",
    project_root: str = "",
    workspace_root_ids: list[str] | None = None,
) -> dict[str, Any]:
    db.init_db()
    cid = f"conv-{uuid.uuid4().hex[:12]}"
    now = db._utcnow()
    clean_project_name = project_name.strip()
    clean_project_root = project_root.strip()
    root_ids = [x.strip() for x in (workspace_root_ids or []) if x.strip()]
    with db.get_connection() as conn:
        conn.execute(
            """
            INSERT INTO chat_conversations (
                id, channel, title, created_at, updated_at,
                project_name, project_root, workspace_root_ids
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                cid,
                channel,
                title.strip() or DEFAULT_CONV_TITLE,
                now,
                now,
                clean_project_name,
                clean_project_root,
                json.dumps(root_ids),
            ),
        )
    return {
        "id": cid,
        "channel": channel,
        "title": title.strip() or DEFAULT_CONV_TITLE,
        "created_at": now,
        "updated_at": now,
        "project_name": clean_project_name,
        "project_root": clean_project_root,
        "workspace_root_ids": root_ids,
    }


def update_conversation(
    conversation_id: str,
    *,
    title: str | None = None,
    project_name: str | None = None,
    project_root: str | None = None,
    workspace_root_ids: list[str] | None = None,
) -> dict[str, Any]:
    cid = conversation_id.strip()
    if not cid:
        raise ValueError("conversation_id vazio")
    db.init_db()
    now = db._utcnow()
    fields: list[str] = ["updated_at = ?"]
    values: list[Any] = [now]
    if title is not None:
        fields.append("title = ?")
        values.append(title.strip() or DEFAULT_CONV_TITLE)
    if project_name is not None:
        fields.append("project_name = ?")
        values.append(project_name.strip())
    if project_root is not None:
        fields.append("project_root = ?")
        values.append(project_root.strip())
    if workspace_root_ids is not None:
        fields.append("workspace_root_ids = ?")
        values.append(json.dumps([x.strip() for x in workspace_root_ids if x.strip()]))
    values.append(cid)
    with db.get_connection() as conn:
        cur = conn.execute(
            f"UPDATE chat_conversations SET {', '.join(fields)} WHERE id = ?",
            values,
        )
        if cur.rowcount <= 0:
            raise ValueError("conversa não encontrada")
        row = conn.execute(
            """
            SELECT id, channel, title, created_at, updated_at,
                   COALESCE(archived, 0) AS archived,
                   COALESCE(project_name, '') AS project_name,
                   COALESCE(project_root, '') AS project_root,
                   COALESCE(workspace_root_ids, '[]') AS workspace_root_ids
            FROM chat_conversations WHERE id = ?
            """,
            (cid,),
        ).fetchone()
    if not row:
        raise ValueError("conversa não encontrada")
    return {
        "id": row["id"],
        "channel": row["channel"],
        "title": row["title"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "archived": bool(row["archived"]),
        "project_name": row["project_name"] or "",
        "project_root": row["project_root"] or "",
        "workspace_root_ids": _parse_workspace_root_ids(row["workspace_root_ids"]),
    }


def list_conversations(
    channel: str = IDE_CHANNEL,
    *,
    include_archived: bool = False,
    include_empty: bool = False,
    workspace_root_id: str | None = None,
    unscoped_only: bool = False,
) -> list[dict[str, Any]]:
    migrate_legacy_conversation(channel)
    db.init_db()
    with db.get_connection() as conn:
        archived_filter = "" if include_archived else "AND COALESCE(c.archived, 0) = 0"
        rows = conn.execute(
            f"""
            SELECT c.id, c.channel, c.title, c.created_at, c.updated_at,
                   COALESCE(c.archived, 0) AS archived,
                   COALESCE(c.project_name, '') AS project_name,
                   COALESCE(c.project_root, '') AS project_root,
                   COALESCE(c.workspace_root_ids, '[]') AS workspace_root_ids,
                   (SELECT COUNT(*) FROM chat_messages m
                    WHERE m.channel = c.channel AND m.user_id = c.id) AS message_count,
                   (SELECT content FROM chat_messages m
                    WHERE m.channel = c.channel AND m.user_id = c.id
                    ORDER BY m.id DESC LIMIT 1) AS preview
            FROM chat_conversations c
            WHERE c.channel = ?
              {archived_filter}
            ORDER BY c.updated_at DESC
            """,
            (channel,),
        ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        preview = (r["preview"] or "")[:80]
        message_count = int(r["message_count"] or 0)
        # Empty threads hidden by default (IDE clutter); Home/mobile needs them after "Nova conversa".
        if message_count <= 0 and not include_empty:
            continue
        root_ids = _parse_workspace_root_ids(r["workspace_root_ids"])
        if unscoped_only:
            if root_ids:
                continue
        elif workspace_root_id and workspace_root_id not in root_ids:
            continue
        out.append(
            {
                "id": r["id"],
                "channel": r["channel"],
                "title": r["title"],
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
                "archived": bool(r["archived"]),
                "project_name": r["project_name"] or "",
                "project_root": r["project_root"] or "",
                "workspace_root_ids": root_ids,
                "message_count": message_count,
                "preview": preview,
            }
        )
    return out


def delete_conversation(conversation_id: str) -> dict[str, Any]:
    cid = conversation_id.strip()
    if not cid:
        raise ValueError("conversation_id vazio")
    db.init_db()
    with db.get_connection() as conn:
        conn.execute("DELETE FROM chat_messages WHERE user_id = ?", (cid,))
        conn.execute("DELETE FROM chat_conversations WHERE id = ?", (cid,))
    return {"success": True, "id": cid}


def archive_conversation(conversation_id: str, archived: bool = True) -> dict[str, Any]:
    cid = conversation_id.strip()
    if not cid:
        raise ValueError("conversation_id vazio")
    db.init_db()
    with db.get_connection() as conn:
        cur = conn.execute(
            "UPDATE chat_conversations SET archived = ?, updated_at = ? WHERE id = ?",
            (1 if archived else 0, db._utcnow(), cid),
        )
    return {"success": cur.rowcount > 0, "id": cid, "archived": archived}


def touch_conversation(conversation_id: str, *, title: str | None = None) -> None:
    cid = conversation_id.strip()
    if not cid:
        return
    now = db._utcnow()
    db.init_db()
    with db.get_connection() as conn:
        if title:
            conn.execute(
                "UPDATE chat_conversations SET updated_at = ?, title = ? WHERE id = ?",
                (now, title.strip() or DEFAULT_CONV_TITLE, cid),
            )
        else:
            conn.execute(
                "UPDATE chat_conversations SET updated_at = ? WHERE id = ?",
                (now, cid),
            )


def on_user_message(conversation_id: str, content: str, channel: str = IDE_CHANNEL) -> None:
    db.init_db()
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT title, channel FROM chat_conversations WHERE id = ?",
            (conversation_id,),
        ).fetchone()
        if not row:
            now = db._utcnow()
            conn.execute(
                """
                INSERT OR IGNORE INTO chat_conversations (id, channel, title, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (conversation_id, channel, _title_from_message(content), now, now),
            )
            return
        if row["title"] == DEFAULT_CONV_TITLE:
            touch_conversation(conversation_id, title=_title_from_message(content))
        else:
            touch_conversation(conversation_id)


def resolve_conversation_id(conversation_id: str | None, channel: str = IDE_CHANNEL) -> str:
    migrate_legacy_conversation(channel)
    if conversation_id and conversation_id.strip():
        cid = conversation_id.strip()
        db.init_db()
        with db.get_connection() as conn:
            row = conn.execute(
                "SELECT id FROM chat_conversations WHERE id = ?",
                (cid,),
            ).fetchone()
            if not row:
                now = db._utcnow()
                conn.execute(
                    """
                    INSERT OR IGNORE INTO chat_conversations (id, channel, title, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (cid, channel, DEFAULT_CONV_TITLE, now, now),
                )
        return cid
    return create_conversation(channel)["id"]


_ACK_RE = re.compile(
    r"^(obrigad|valeu|ok|certo|entendi|sim|não|nao|legal|show|perfeito|top|blz|beleza)[!.\s]*$",
    re.IGNORECASE,
)

_HEAVY_KEYWORDS = (
    "implement",
    "implementar",
    "refator",
    "debug",
    "erro",
    "bug",
    "fix",
    "criar",
    "crie",
    "scaffold",
    "agente",
    "api",
    "código",
    "codigo",
    "arquivo",
    "teste",
    "pytest",
    "fastapi",
    "react",
    "typescript",
    "diff",
    "shell",
    "sqlite",
    "websocket",
    "deploy",
    "arquitet",
    "explique",
    "como fazer",
    "por que",
    "porquê",
    "analise",
    "analisa",
    "corrig",
    "review",
    "revise",
    "deleg",
    "composer",
    "write",
    "função",
    "funcao",
    "classe",
    "endpoint",
    "migrat",
    "docker",
    "lint",
)


def _save_message(
    channel: str,
    user_id: str,
    role: str,
    content: str,
    media: list[dict[str, Any]] | None = None,
) -> None:
    db.init_db()
    media_json = json.dumps(media or [], ensure_ascii=False)
    with db.get_connection() as conn:
        conn.execute(
            """
            INSERT INTO chat_messages (channel, user_id, role, content, created_at, media_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (channel, user_id, role, content, db._utcnow(), media_json),
        )


def _load_history(
    channel: str,
    user_id: str,
    limit: int = CHAT_HISTORY_LIMIT,
    content_cap: int | None = None,
) -> list[dict[str, Any]]:
    db.init_db()
    with db.get_connection() as conn:
        rows = conn.execute(
            """
            SELECT role, content, COALESCE(media_json, '[]') AS media_json FROM chat_messages
            WHERE channel = ? AND user_id = ?
            ORDER BY id DESC LIMIT ?
            """,
            (channel, user_id, limit),
        ).fetchall()
    if content_cap is None:
        if channel == IDE_CHANNEL:
            content_cap = CHAT_IDE_HISTORY_CONTENT_LIMIT
        elif channel == MOBILE_CHANNEL:
            content_cap = 20000
        else:
            content_cap = 2000
    history: list[dict[str, Any]] = []
    for r in reversed(rows):
        content = (r["content"] or "")[:content_cap]
        try:
            media = json.loads(r["media_json"] or "[]")
        except json.JSONDecodeError:
            media = []
        if not isinstance(media, list):
            media = []
        history.append({"role": r["role"], "content": content, "media": media})
    return history


def _media_from_tool_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    from learning_agent.core.chat_media import media_item_from_record

    if not payload.get("ok"):
        return []
    mid = str(payload.get("media_id") or payload.get("id") or "")
    if not mid:
        return []
    return [
        media_item_from_record(
            {
                "id": mid,
                "url": payload.get("media_url") or payload.get("url"),
                "type": payload.get("media_type") or payload.get("type") or "file",
                "filename": payload.get("filename") or mid,
                "mime": payload.get("mime"),
                "size": payload.get("size"),
            }
        )
    ]


def _run_mobile_tool(
    tool: str,
    args: dict[str, Any],
    *,
    ok_answer: str,
    fail_answer: str,
) -> dict[str, Any]:
    from learning_agent.core import agent_tools

    result_raw = agent_tools.execute_tool(tool, args)
    try:
        payload = json.loads(result_raw)
    except json.JSONDecodeError:
        payload = {"ok": False, "output": result_raw}
    ok = bool(payload.get("ok"))
    media = _media_from_tool_payload(payload if isinstance(payload, dict) else {})
    answer = _mobile_warm_tool_answer(ok=ok, ok_text=ok_answer, fail_text=fail_answer)
    if ok and media and media[0].get("type") == "image":
        answer = ok_answer if "print" in ok_answer.lower() or "captur" in ok_answer.lower() else f"{ok_answer} (imagem anexada)"
    return {
        "instant": True,
        "ok": ok,
        "answer": answer,
        "agent": AGENT_NAME,
        "model": tool,
        "persist_history": True,
        "media": media,
        "tool_log": [{"tool": tool, "arguments": args, "result": result_raw, "result_preview": result_raw[:800]}],
    }


def _extract_windows_path(message: str) -> str | None:
    text = message or ""
    m = re.search(r"([A-Za-z]:\\[^\s\"']+)", text)
    if m:
        return m.group(1).strip()
    m = re.search(r"(~\\[^\s\"']+)", text)
    if m:
        return m.group(1).strip()
    low = text.lower()
    if re.search(r"\bdownloads\b", low):
        return "~\\Downloads"
    if re.search(r"\bdocumentos\b", low):
        return "~\\Documents"
    if re.search(r"\b(área de trabalho|area de trabalho|desktop)\b", low):
        return "~\\Desktop"
    return None


def _extract_window_title(message: str) -> str:
    text = message or ""
    for pat in (
        r"(?:janela|tela)\s+(?:do\s+|da\s+|de\s+)?(.+?)(?:\.|$)",
        r"(?:chrome|cursor|discord|notepad|calculadora|spotify|edge|firefox)\b",
    ):
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return (m.group(1) if m.lastindex else m.group(0)).strip(" .!?")
    return ""


_SEND_TO_PC_RE = re.compile(
    r"\b(envia|enviar|manda|mandar|passa|transfere|transferir|copia|copiar)\b.{0,40}"
    r"\b(pc|windows|computador|downloads)\b"
    r"|\b(pc|windows|computador|downloads)\b.{0,40}"
    r"\b(envia|enviar|manda|mandar|passa|transfere|copia|copiar)\b"
    r"|\benvia(r)?\s+(para|pro|pra)\s+o?\s*(pc|windows)\b"
    r"|\bmanda(r)?\s+(para|pro|pra)\s+o?\s*(pc|windows)\b",
    re.IGNORECASE,
)


def _last_user_media_id(channel: str, user_id: str) -> str | None:
    """Retorna o ID da última mídia enviada pelo usuário nessa conversa."""
    db.init_db()
    with db.get_connection() as conn:
        rows = conn.execute(
            """
            SELECT media_json FROM chat_messages
            WHERE channel = ? AND user_id = ? AND role = 'user'
            ORDER BY id DESC LIMIT 10
            """,
            (channel, user_id),
        ).fetchall()
    for row in rows:
        try:
            items = json.loads(row["media_json"] or "[]")
        except json.JSONDecodeError:
            continue
        if isinstance(items, list) and items:
            mid = items[-1].get("id") or items[-1].get("url") or ""
            mid = mid.split("/")[-1].strip()
            if mid:
                return mid
    return None


def _mobile_pc_inspect_shortcut_reply(
    message: str,
    *,
    attachment_ids: list[str] | None = None,
    channel: str = MOBILE_CHANNEL,
    user_id: str = "default",
) -> dict[str, Any] | None:
    from learning_agent.core import agent_tools
    from learning_agent.core.chat_media import (
        media_item_from_record,
        resolve_media_path,
    )

    low = (message or "").lower()
    aids = [a.strip() for a in (attachment_ids or []) if a.strip()]

    # "Envia para o pc" sem anexo → busca última mídia da conversa
    if not aids and _SEND_TO_PC_RE.search(low):
        last_mid = _last_user_media_id(channel, user_id)
        if last_mid:
            aids = [last_mid]

    if aids and re.search(r"\b(pc|windows|computador|downloads)\b", low):
        mid = aids[-1]
        result_raw = agent_tools.execute_tool("windows_send_media_to_pc", {"media_id": mid})
        try:
            payload = json.loads(result_raw)
        except json.JSONDecodeError:
            payload = {"ok": False}
        ok = bool(payload.get("ok"))
        dest = payload.get("saved_path") or payload.get("filename") or "Downloads"
        err = str(payload.get("error") or "").strip()
        return {
            "instant": True,
            "ok": ok,
            "answer": _mobile_warm_tool_answer(
                ok=ok,
                ok_text=f"Pronto, Luis — mandei pro seu PC. Tá em:\n{dest}",
                fail_text="Ai, não rolou mandar agora.",
                err=err,
            ),
            "agent": AGENT_NAME,
            "model": "windows_send_media_to_pc",
            "persist_history": True,
            "media": [],
            "tool_log": [{"tool": "windows_send_media_to_pc", "result": result_raw}],
        }

    if re.search(
        r"\b(print|screenshot|captura|capturar|printscreen|tira\s+um\s+print|faz\s+um\s+print|"
        r"tira\s+screenshot|tira\s+captura|mostra\s+a\s+tela|mostra\s+o\s+que\s+t[aá]|"
        r"me\s+envia\s+um\s+print|envia\s+(o\s+|um\s+)?print|manda\s+(o\s+|um\s+)?print)\b",
        low,
    ):
        # "monitor/tela N" = índice do monitor, NÃO título de janela
        monitor = 0
        m_mon = re.search(r"\b(?:monitor|tela|screen)\s*(?:n[uú]mero\s*)?(\d+)\b", low)
        if m_mon:
            asked = int(m_mon.group(1))
            monitor = max(0, asked - 1) if asked >= 1 else 0
        elif re.search(r"\b(segundo|2[oº]?)\s+monitor\b", low):
            monitor = 1
        elif re.search(r"\b(terceiro|3[oº]?)\s+monitor\b", low):
            monitor = 2
        elif re.search(r"\btodos\s+(os\s+)?monitores\b|\btela\s+virtual\b|\ball\s+screens?\b", low):
            monitor = -1
        title = ""
        if not m_mon and re.search(r"\b(janela|chrome|cursor|discord|notepad|aba|browser|navegador)\b", low):
            title = _extract_window_title(message)
        return _run_mobile_tool(
            "windows_screenshot",
            {"window_title": title, "monitor": monitor},
            ok_answer="Pronto — aqui está o print do seu PC.",
            fail_answer="Não consegui capturar a tela agora. Tenta de novo?",
        )

    # Gravação de tela: só com intenção explícita de gravar (nunca "achar vídeo no Windows")
    if re.search(r"\b(grava|gravar|filmagem|captura\s+de\s+tela)\b", low) and re.search(
        r"\b(tela|screen)\b", low
    ):
        secs = 10
        m = re.search(r"(\d{1,3})\s*(seg|segundos|s)\b", low)
        if m:
            secs = min(120, max(1, int(m.group(1))))
        return _run_mobile_tool(
            "windows_record_screen",
            {"seconds": secs},
            ok_answer=f"Gravei {secs}s da tela do PC — vídeo anexado.",
            fail_answer="Não consegui gravar (precisa ffmpeg instalado no Windows).",
        )

    win_path = _extract_windows_path(message)
    if win_path and re.search(r"\b(manda|envia|enviar|mandar|copia|copiar|pull|transfere)\b", low):
        return _run_mobile_tool(
            "windows_pull_file",
            {"path": win_path},
            ok_answer="Arquivo copiado da ravenna — anexado aqui.",
            fail_answer="Não consegui puxar esse arquivo do PC.",
        )

    if win_path and re.search(r"\b(lê|leia|le|conteúdo|conteudo|abre)\b", low) and re.search(r"\b(arquivo)\b", low):
        result_raw = agent_tools.execute_tool("windows_read_file", {"path": win_path})
        try:
            payload = json.loads(result_raw)
        except json.JSONDecodeError:
            payload = {"ok": False}
        media = _media_from_tool_payload(payload if isinstance(payload, dict) else {})
        if media:
            return {
                "instant": True,
                "ok": True,
                "answer": "Pronto — anexei o arquivo aqui pra você.",
                "agent": AGENT_NAME,
                "model": "windows_read_file",
                "persist_history": True,
                "media": media,
                "tool_log": [{"tool": "windows_read_file", "result": result_raw}],
            }
        content = str(payload.get("content") or payload.get("output") or "")[:3500]
        ok = bool(payload.get("ok"))
        return {
            "instant": True,
            "ok": ok,
            "answer": content if ok and content else "Não consegui ler esse arquivo agora. Quer tentar outro caminho?",
            "agent": AGENT_NAME,
            "model": "windows_read_file",
            "persist_history": True,
            "media": [],
            "tool_log": [{"tool": "windows_read_file", "result": result_raw}],
        }

    if re.search(r"\b(lista|listar|mostra|ver|o que tem)\b", low) and re.search(r"\b(pasta|diretório|diretorio|arquivos)\b", low):
        path = win_path or "~\\Downloads"
        result_raw = agent_tools.execute_tool("windows_list_dir", {"path": path})
        try:
            payload = json.loads(result_raw)
        except json.JSONDecodeError:
            payload = {"ok": False}
        listing = str(payload.get("output") or payload.get("error") or "")[:3500]
        ok = bool(payload.get("ok"))
        return {
            "instant": True,
            "ok": ok,
            "answer": listing if ok else "Não consegui listar essa pasta agora. Quer que eu tente de novo?",
            "agent": AGENT_NAME,
            "model": "windows_list_dir",
            "persist_history": True,
            "media": [],
            "tool_log": [{"tool": "windows_list_dir", "result": result_raw}],
        }

    if aids:
        user_media: list[dict[str, Any]] = []
        for mid in aids:
            try:
                path = resolve_media_path(mid)
                user_media.append(
                    media_item_from_record(
                        {
                            "id": mid,
                            "filename": path.name.split("-", 2)[-1],
                            "type": "image" if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".gif"} else "file",
                        }
                    )
                )
            except Exception:
                continue
        if user_media:
            return {
                "instant": True,
                "answer": "Recebi sua imagem — posso mandar pro PC se você pedir.",
                "agent": AGENT_NAME,
                "model": "attachment",
                "persist_history": True,
                "media": [],
                "user_media": user_media,
            }

    return None


def _persist_mobile_exchange(
    channel: str,
    user_id: str,
    user_message: str,
    assistant_message: str,
    *,
    user_media: list[dict[str, Any]] | None = None,
    assistant_media: list[dict[str, Any]] | None = None,
    persist_history: bool = True,
) -> None:
    if not persist_history:
        return
    _save_message(channel, user_id, "user", user_message, user_media)
    _save_message(channel, user_id, "assistant", assistant_message, assistant_media)


def _messages_char_count(messages: list[dict[str, str]]) -> int:
    return sum(len(m.get("content") or "") for m in messages)


def _truncate_text(text: str, max_len: int, *, suffix: str = "\n…[truncado]") -> str:
    if len(text) <= max_len:
        return text
    keep = max(0, max_len - len(suffix))
    return text[:keep] + suffix


def fit_messages_for_llm(
    messages: list[dict[str, str]],
    *,
    max_chars: int | None = None,
    aggressive: bool = False,
) -> list[dict[str, str]]:
    """Encolhe payload para caber no limite da API (ex.: Groq 413)."""
    cap = max_chars or LLM_PAYLOAD_MAX_CHARS
    if aggressive:
        cap = min(cap, 60000)

    if _messages_char_count(messages) <= cap:
        return messages

    system_msgs = [m for m in messages if m.get("role") == "system"]
    convo = [m for m in messages if m.get("role") != "system"]

    trimmed_system: list[dict[str, str]] = []
    for m in system_msgs:
        content = m.get("content") or ""
        if "CONTEXTO EDITOR:" in content or "CONTEXTO LOCAL:" in content:
            limit = 4000 if aggressive else CHAT_IDE_EDITOR_MAX_CHARS
            trimmed_system.append({"role": "system", "content": _truncate_text(content, limit)})
        else:
            limit = 6000 if aggressive else 10000
            trimmed_system.append({"role": "system", "content": _truncate_text(content, limit)})

    keep = 8 if aggressive else 14
    per_msg = 400 if aggressive else AGENT_HISTORY_CONTENT_LIMIT
    trimmed_convo = convo[-keep:]
    trimmed_convo = [
        {"role": m["role"], "content": _truncate_text(m.get("content") or "", per_msg)}
        for m in trimmed_convo
    ]

    out = trimmed_system + trimmed_convo
    while trimmed_convo and _messages_char_count(out) > cap:
        trimmed_convo = trimmed_convo[1:]
        out = trimmed_system + trimmed_convo

    if _messages_char_count(out) > cap:
        for i, m in enumerate(out):
            if m.get("role") == "system" and (
                "CONTEXTO EDITOR:" in (m.get("content") or "")
                or "CONTEXTO LOCAL:" in (m.get("content") or "")
            ):
                out[i] = {
                    "role": "system",
                    "content": _truncate_text(m.get("content") or "", 1500 if aggressive else 3000),
                }

    return out


def clear_history(channel: str, user_id: str) -> dict[str, Any]:
    db.init_db()
    with db.get_connection() as conn:
        conn.execute(
            "DELETE FROM chat_messages WHERE channel = ? AND user_id = ?",
            (channel, user_id),
        )
    return {"success": True, "channel": channel, "user_id": user_id}


def _is_greeting(message: str) -> bool:
    return bool(_GREETING_RE.match(message.strip()))


_WIN_APP_ALIASES = (
    "opera gx",
    "opera",
    "chrome",
    "google chrome",
    "firefox",
    "brave",
    "discord",
    "notepad",
    "bloco de notas",
    "calculadora",
    "calc",
    "cursor",
    "spotify",
    "edge",
    "explorer",
)

_WIN_APP_CANONICAL = {
    "opera gx": "opera",
    "google chrome": "chrome",
    "bloco de notas": "notepad",
    "calculadora": "calc",
}

# Famílias de intenção (PT): radical + conjugações + typos via fuzzy.
_CLOSE_VERB_FORMS = (
    "fecha", "feche", "fechar", "fechem", "fechando",
    "encerra", "encerre", "encerrar", "encerrando",
    "mata", "mate", "matar", "matando",
    "geche", "fexa", "fechaar", "fechae",
)
_OPEN_VERB_FORMS = (
    "abre", "abra", "abrir", "abram", "abrindo",
    "inicia", "inicie", "iniciar", "liga", "ligar",
    "abraa", "abrii",
)
# Passado (fechou/abriu) NÃO dispara atalho — evita "você fechou… abra de novo" → open_then_close
_PAST_ACTION_RE = re.compile(r"(?i)\b(fechou|fechei|abriu|abri|encerrou|matei|matou)\b")
# Inglês só com token exato (senão "o"≈open, "opera"≈open)
_CLOSE_EXACT_EN = frozenset({"close", "kill", "cerrar"})
_OPEN_EXACT_EN = frozenset({"open", "start"})
# Estado, não ação — "aba aberta" / "ainda aberto" NÃO é pedido pra abrir
_STATE_TOKENS = frozenset({
    "aberto", "aberta", "abertos", "abertas",
    "fechado", "fechada", "fechados", "fechadas",
    "ligado", "ligada", "desligado", "desligada",
    "aba", "abas",  # "aba" ≈ "abra" no fuzzy — não é verbo
})
_APP_NAME_TOKENS = frozenset({
    "opera", "chrome", "firefox", "brave", "discord", "notepad",
    "spotify", "edge", "cursor", "explorer", "calc", "calculadora",
})


def _fold_pt(text: str) -> str:
    """minúsculas + sem acento — interpretação mais tolerante."""
    raw = (text or "").lower().replace("ß", "ss")
    norm = unicodedata.normalize("NFD", raw)
    return "".join(ch for ch in norm if unicodedata.category(ch) != "Mn")


def _token_similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    pref = 0
    for x, y in zip(a, b):
        if x != y:
            break
        pref += 1
    stem_bonus = 0.12 if pref >= 4 else 0.0
    return min(1.0, SequenceMatcher(None, a, b).ratio() + stem_bonus)


def _fuzzy_has_verb(
    text: str,
    forms: tuple[str, ...],
    *,
    exact_en: frozenset[str] = frozenset(),
    cutoff: float = 0.88,
) -> bool:
    """True se algum token se parece com a família verbal (fecha≈feche≈geche)."""
    folded = _fold_pt(text)
    tokens = re.findall(r"[a-z0-9]+", folded)
    for tok in tokens:
        if len(tok) < 4 or tok in _STATE_TOKENS or tok in _APP_NAME_TOKENS:
            continue
        if tok in exact_en:
            return True
        for form in forms:
            # radical PT com ≥4 letras compartilhadas (fech*, abr*)
            stem = form[:4]
            if len(form) >= 4 and len(tok) >= 4 and tok.startswith(stem):
                if abs(len(tok) - len(form)) <= 3:
                    return True
            if _token_similarity(tok, form) >= cutoff:
                return True
    return False


def _mobile_windows_app_name(message: str) -> str | None:
    folded = _fold_pt(message)
    # aliases longos primeiro
    for name in sorted(_WIN_APP_ALIASES, key=len, reverse=True):
        if _fold_pt(name) in folded:
            return _WIN_APP_CANONICAL.get(name, name)
    # fuzzy no nome do app (opra≈opera, chrom≈chrome)
    tokens = re.findall(r"[a-z0-9]+", folded)
    best: tuple[float, str] | None = None
    for tok in tokens:
        if len(tok) < 3:
            continue
        for name in _WIN_APP_ALIASES:
            canon = _WIN_APP_CANONICAL.get(name, name)
            target = _fold_pt(name).replace(" ", "")
            # token único vs alias (opera, chrome…)
            single = target if " " not in name else _fold_pt(canon)
            score = _token_similarity(tok, single)
            if score >= 0.82 and (best is None or score > best[0]):
                best = (score, canon)
    return best[1] if best else None


def _last_windows_app_from_history(channel: str, user_id: str) -> str | None:
    """Último app Windows citado pelo usuário (para 'fecha o que eu pedi')."""
    rows = _load_history(channel, user_id, limit=8, content_cap=500)
    for row in reversed(rows):
        if row.get("role") != "user":
            continue
        name = _mobile_windows_app_name(str(row.get("content") or ""))
        if name:
            return name
    return None


def _windows_open_close_intent(
    message: str,
    *,
    channel: str = MOBILE_CHANNEL,
    user_id: str = "default",
) -> str | None:
    """open | close | open_then_close | None — interpretação por radical/fuzzy, não palavra exata."""
    raw = message or ""
    # Ignora lixo de prompt IDE colado na mensagem (Ciclo autônomo etc.)
    raw = re.split(r"\n\s*---\s*\n", raw, maxsplit=1)[0].strip()
    folded = _fold_pt(raw)
    # Pergunta de acesso/capacidade nunca é open/close
    if _is_mobile_access_question(raw):
        return None
    if re.search(r"\b(acesso|acessar|consegue\s+mexer|tem\s+acesso|esta\s+com\s+acesso)\b", folded):
        if not re.search(r"\b(abre|abra|abrir|fecha|feche|fechar|encerra|mata)\b", folded):
            return None

    app = _mobile_windows_app_name(raw)
    wants_open = _fuzzy_has_verb(raw, _OPEN_VERB_FORMS, exact_en=_OPEN_EXACT_EN)
    wants_close = _fuzzy_has_verb(raw, _CLOSE_VERB_FORMS, exact_en=_CLOSE_EXACT_EN)

    # Narrativa no passado ("você fechou…") não conta como pedido de fechar agora
    if _PAST_ACTION_RE.search(folded) and wants_close:
        # Só ignora passado se também há imperativo de abrir (ex.: "fechou os dois. Abra de novo")
        if wants_open and re.search(r"\b(abre|abra|abrir)\b", folded):
            wants_close = False

    # Pedidos indiretos / retry sem verbo perfeito
    if not wants_close and re.search(
        r"(ainda|ainsa|continua|segue).{0,12}(abert|ligado)|nao\s+fech|nao\s+encer|"
        r"continua\s+abert|ainda\s+la",
        folded,
    ):
        if app or re.search(r"\b(navegador|browser|ele|aquele|janela|app|programa)\b", folded):
            wants_close = True

    # Referência anafórica / pedido curto → histórico
    if (wants_close or wants_open) and not app:
        if re.search(
            r"\b(navegador|browser|especific|anterior|ainda|ainsa|ele|aquele|pedi|mesmo|"
            r"app|programa|janela|por\s+favor|pra\s+mim|novamente|de\s+novo)\b",
            folded,
        ) or len(folded) < 48:
            app = _last_windows_app_from_history(channel, user_id)

    # App implícito: "fecha o navegador" com Opera no histórico
    if not app and (wants_close or wants_open) and re.search(r"\bnavegador\b|\bbrowser\b", folded):
        app = _last_windows_app_from_history(channel, user_id)

    # SEM app explícito/histórico → não inventa notepad (nem qualquer default)
    if not app:
        return None
    # Atalho só com verbo claro (ou padrão explícito de janela vazia abaixo)
    if not wants_open and not wants_close:
        if re.search(r"\b(aba|janela|janelas|aberto|aberta)\b", folded) and re.search(
            r"\b(sem|nenhuma|nenhum|vazia|vazio|indica|indicado)\b",
            folded,
        ):
            return "close"
        return None
    if wants_open and wants_close:
        # "…fechou os dois… Abra novamente" → só abrir
        if re.search(r"\b(novamente|de\s+novo|outra\s+vez)\b", folded) and re.search(
            r"\b(abre|abra|abrir)\b", folded
        ):
            return "open"
        # Só "abre e fecha" no MESMO pedido explícito (teste), nunca narrativa + novo pedido
        if re.search(
            r"\b(abre|abra|abrir)\s+(e|&)\s+(fecha|feche|fechar)\b"
            r"|\b(abre|abra|abrir).{0,20}\b(depois|e ja|e já)\s*(fecha|feche|fechar)\b",
            folded,
        ):
            return "open_then_close"
        # Ambos → prioriza o imperativo mais recente
        open_at = max(
            (m.start() for m in re.finditer(r"\b(abre|abra|abrir|liga|iniciar)\b", folded)),
            default=-1,
        )
        close_at = max(
            (m.start() for m in re.finditer(r"\b(fecha|feche|fechar|encerra|mata)\b", folded)),
            default=-1,
        )
        if close_at > open_at:
            return "close"
        return "open"
    if wants_open:
        return "open"
    if wants_close:
        return "close"
    return None


def _close_scope_from_message(message: str) -> str:
    """all | min | vis — escopo de fechamento de janela."""
    folded = _fold_pt(message)
    if re.search(
        r"\b(minimizada?o?s?|segundo\s+plano|em\s+background|"
        r"so\s+a\s+minimiz\w*|somente\s+a\s+minimiz\w*)\b",
        folded,
    ):
        return "min"
    if re.search(
        r"\b(primeiro\s+plano|em\s+foco|a\s+ativa|janela\s+ativa|so\s+a\s+ativa)\b",
        folded,
    ):
        return "vis"
    return "all"


def _is_mobile_linux_status(message: str) -> bool:
    low = (message or "").lower()
    if len(low) > 280:
        return False
    asks = bool(re.search(r"\b(hostname|uptime|load average|load|quem est[aá] logado|logado)\b", low))
    if not asks:
        return False
    return bool(re.search(r"\b(linux|debian|ravenna|servidor|host)\b", low)) or "load" in low


def _mobile_linux_status_shortcut() -> dict[str, Any]:
    from learning_agent.core import agent_tools

    result_raw = agent_tools.execute_tool(
        "host_exec",
        {"command": "hostname; echo '---'; who; echo '---'; uptime", "timeout": 20},
    )
    try:
        payload = json.loads(result_raw)
    except json.JSONDecodeError:
        payload = {"ok": False, "output": result_raw}
    out = str(payload.get("output") or payload.get("stdout") or result_raw)[:800]
    ok = bool(payload.get("ok") or payload.get("exit_code") == 0)
    if ok and out.strip():
        answer = f"No Linux agora: {out.strip().replace(chr(10), ' | ')}"
    else:
        answer = "Não consegui ler hostname/uptime no Linux agora."
    return {
        "instant": True,
        "ok": ok,
        "answer": answer,
        "agent": AGENT_NAME,
        "model": "host_exec",
        "persist_history": True,
        "tool_log": [{"tool": "host_exec", "result_preview": result_raw[:600]}],
    }


def _is_mobile_access_question(message: str) -> bool:
    """Perguntas de capacidade/acesso — não são open/close de app."""
    low = _fold_pt(message)
    if len(low) > 220:
        return False
    asks_access = bool(
        re.search(
            r"\b(acesso|acessa|acessar|enxerga|enxerg|controla|controlar|"
            r"consegue\s+(mexer|operar|usar|acessar)|"
            r"tem\s+(acesso|como)|esta\s+com\s+acesso|pode\s+mexer)\b",
            low,
        )
    )
    two_boxes = bool(
        re.search(
            r"\b("
            r"maquinas?|as duas|os dois pcs?|"
            r"windows.{0,20}linux|linux.{0,20}windows|"
            r"ao\s+linux|ao\s+windows|no\s+linux|no\s+windows|"
            r"servidor|pc_do_luis|ravenna|m55|celular|android"
            r")\b",
            low,
        )
    )
    hosts = bool(re.search(r"\b(linux|windows|debian|pc|m55|celular|android)\b", low))
    return bool(asks_access and (two_boxes or hosts))


def _extract_http_url(message: str) -> str | None:
    m = re.search(r"https?://[^\s<>\"']+", message or "")
    return m.group(0).rstrip(".,);") if m else None


def _youtube_query(message: str) -> str | None:
    text = (message or "").strip()
    low = text.lower()
    if "youtube" not in low and not re.search(r"\b(vídeo|video|clipe)\b", low):
        return None
    url = _extract_http_url(text)
    if url and "youtu" in url.lower():
        return url
    m = re.search(
        r"(?:no youtube|youtube|youtu\.be)[:\s,]+(.+)$",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if m:
        q = m.group(1).strip(" .!?")
        q = re.sub(r"^(abre|abrir|toca|tocar|pesquisa|pesquisar|busca|buscar)\s+", "", q, flags=re.IGNORECASE)
        return q or None
    m = re.search(r"(?:vídeo|video|clipe) de (.+)$", text, re.IGNORECASE)
    if m:
        q = re.sub(r"\s+no youtube.*$", "", m.group(1).strip(" .!?"), flags=re.IGNORECASE)
        return q or None
    if "youtube" in low:
        q = re.sub(r"(?i).*?\byoutube\b[:\s]*", "", text).strip(" .!?")
        q = re.sub(r"(?i)^(abre|abrir|toca|tocar|um|uma|o|a|vídeo|video)\s+", "", q)
        return q or "música"
    return None


def _google_query(message: str) -> str | None:
    text = (message or "").strip()
    low = text.lower()
    if not re.search(r"\b(google|pesquisa|pesquisar|busca)\b", low):
        return None
    if "youtube" in low:
        return None
    m = re.search(r"(?:no google|google)[:\s]+(.+)$", text, re.IGNORECASE)
    if m:
        return m.group(1).strip(" .!?")
    m = re.search(r"(?:pesquisa|pesquisar|busca|buscar)\s+(?:no google\s+)?(.+)$", text, re.IGNORECASE)
    if m:
        q = m.group(1).strip(" .!?")
        if q.lower() not in {"no google", "google"}:
            return q
    return None


def _mobile_web_shortcut_reply(message: str) -> dict[str, Any] | None:
    from learning_agent.core import agent_tools

    low = (message or "").lower()
    url = _extract_http_url(message or "")

    if url and re.search(r"\b(baix|download)\w*\b", low):
        result_raw = agent_tools.execute_tool("windows_download_file", {"url": url})
        try:
            payload = json.loads(result_raw)
        except json.JSONDecodeError:
            payload = {"ok": False, "output": result_raw}
        ok = bool(payload.get("ok"))
        saved = (payload.get("saved_path") or "").strip()
        fname = payload.get("filename") or "arquivo"
        if ok and saved:
            answer = f"Pronto — baixei em: {saved}"
        elif ok:
            answer = f"Baixei na pasta Downloads: {fname}"
        else:
            answer = "Não consegui baixar esse arquivo agora. Tenta outro link ou manda de novo?"
        return {
            "instant": True,
            "ok": ok,
            "answer": answer,
            "agent": AGENT_NAME,
            "model": "windows_download_file",
            "persist_history": True,
            "tool_log": [{"tool": "windows_download_file", "arguments": {"url": url}, "result_preview": result_raw[:600]}],
        }

    yt = _youtube_query(message)
    if yt:
        if yt.startswith("http"):
            result_raw = agent_tools.execute_tool("windows_open_url", {"url": yt})
            tool = "windows_open_url"
            ok_txt = "Abri o vídeo no YouTube no seu Windows."
        else:
            result_raw = agent_tools.execute_tool("windows_search_youtube", {"query": yt})
            tool = "windows_search_youtube"
            ok_txt = f"Abri o YouTube no seu PC com: {yt}."
        try:
            payload = json.loads(result_raw)
        except json.JSONDecodeError:
            payload = {"ok": False}
        ok = bool(payload.get("ok") or payload.get("exit_code") == 0)
        return {
            "instant": True,
            "ok": ok,
            "answer": ok_txt if ok else "Não consegui abrir o YouTube agora.",
            "agent": AGENT_NAME,
            "model": tool,
            "persist_history": True,
            "tool_log": [{"tool": tool, "result_preview": result_raw[:600]}],
        }

    if url and re.search(r"\b(abre|abrir|entra|abrir o site|site)\b", low):
        result_raw = agent_tools.execute_tool("windows_open_url", {"url": url})
        try:
            payload = json.loads(result_raw)
        except json.JSONDecodeError:
            payload = {"ok": False}
        ok = bool(payload.get("ok") or payload.get("exit_code") == 0)
        return {
            "instant": True,
            "ok": ok,
            "answer": "Abri o site no navegador do seu Windows." if ok else "Não consegui abrir o site agora.",
            "agent": AGENT_NAME,
            "model": "windows_open_url",
            "persist_history": True,
            "tool_log": [{"tool": "windows_open_url", "arguments": {"url": url}, "result_preview": result_raw[:600]}],
        }

    if re.search(r"\b(wikipedia)\b", low) and re.search(r"\b(abre|abrir|entra)\b", low):
        result_raw = agent_tools.execute_tool("windows_open_url", {"url": "https://pt.wikipedia.org"})
        ok = True
        try:
            payload = json.loads(result_raw)
            ok = bool(payload.get("ok") or payload.get("exit_code") == 0)
        except json.JSONDecodeError:
            pass
        return {
            "instant": True,
            "ok": ok,
            "answer": "Abri a Wikipédia no seu Windows." if ok else "Não consegui abrir a Wikipédia agora.",
            "agent": AGENT_NAME,
            "model": "windows_open_url",
            "persist_history": True,
            "tool_log": [{"tool": "windows_open_url", "result_preview": result_raw[:600]}],
        }

    gq = _google_query(message)
    if gq:
        result_raw = agent_tools.execute_tool("windows_search_google", {"query": gq})
        try:
            payload = json.loads(result_raw)
        except json.JSONDecodeError:
            payload = {"ok": False}
        ok = bool(payload.get("ok") or payload.get("exit_code") == 0)
        return {
            "instant": True,
            "ok": ok,
            "answer": f"Abri o Google no seu PC com: {gq}." if ok else "Não consegui abrir o Google agora.",
            "agent": AGENT_NAME,
            "model": "windows_search_google",
            "persist_history": True,
            "tool_log": [{"tool": "windows_search_google", "result_preview": result_raw[:600]}],
        }
    return None


def _windows_list_open_windows(app: str | None = None, *, include_tabs: bool = True) -> dict[str, Any]:
    """Lista janelas top-level (ativas + minimizadas) e abas de browser no Windows."""
    from learning_agent.core import windows_agent_client as win

    data = win.list_windows(str(app or ""), include_tabs=include_tabs)
    windows = list(data.get("windows") or [])
    out = str(data.get("output") or "")
    ok = bool(data.get("ok")) and "caractere:" not in out.lower()
    return {
        "ok": ok,
        "app": data.get("filter") or app or "",
        "windows": windows,
        "tabs": list(data.get("tabs") or []),
        "count": int(data.get("count") or len(windows)),
        "tab_count": int(data.get("tab_count") or 0),
        "raw": json.dumps(
            {"count": data.get("count"), "tab_count": data.get("tab_count"), "windows": windows[:12]},
            ensure_ascii=False,
        )[:2000],
        "output": out[:1200],
    }


def _is_mobile_windows_inspect_request(message: str) -> bool:
    """Perguntas de inspeção: janelas/abas/apps abertos, inclusive segundo plano."""
    raw = message or ""
    folded = _fold_pt(raw)
    if len(folded) > 360:
        return False
    if _is_mobile_access_question(raw):
        return False
    if re.match(r"^\s*(fecha|feche|fechar|abre|abra|abrir|encerra|mata)\b", folded):
        return False
    inspect = bool(
        re.search(
            r"\b("
            r"identific|verific|confirm|confer|chec|olhad|olhe\b|veja\s+se|me\s+diga\s+se|"
            r"quantos|quais|lista|liste|mostra|mostre|enxerg|somente|segundo\s+plano|"
            r"primeiro\s+plano|em\s+paralelo|abas?\b"
            r")\b",
            folded,
        )
        or re.search(r"\b(tem|existe|ha|há)\b.{0,60}\b(aberto|aberta|abertos|abertas|janela|aba)", folded)
        or re.search(r"\b(esta|está)\s+(aberto|aberta|rodando|minimizado)\b", folded)
    )
    if not inspect:
        return False
    open_hint = bool(
        re.search(
            r"\b("
            r"aberto|aberta|abertos|abertas|janela|janelas|rodando|navegador|browser|"
            r"aplicativos?|apps?|programa|programas|aba|abas|"
            r"segundo\s+plano|primeiro\s+plano|paralelo|minimizado"
            r")\b",
            folded,
        )
    )
    if not open_hint:
        return False
    app = _mobile_windows_app_name(raw)
    if app:
        return True
    # Follow-ups (“somente?”, “e no segundo plano?”) sem repetir o nome do app
    if re.search(r"\b(somente|segundo\s+plano|primeiro\s+plano|paralelo|minimizado|outra|outro)\b", folded):
        return True
    return bool(
        re.search(
            r"\b(navegador|browser|janela|apps?|aplicativos?|programa|windows|aba)\b",
            folded,
        )
    )


def _format_windows_inspect_answer(
    *,
    app: str | None,
    label: str,
    windows: list[dict[str, Any]],
    want_tabs: bool,
) -> str:
    count = len(windows)
    if count == 0:
        if app:
            return f"Olhei no Windows agora: não achei janela do {label} aberta (nem minimizada)."
        return "Olhei no Windows agora e não achei janelas de aplicativo com título pra listar."

    lines: list[str] = []
    for i, w in enumerate(windows[:10], 1):
        state = w.get("state") or "vis"
        state_pt = "ativa" if state == "vis" else "minimizada/segundo plano"
        title = w.get("title") or "(sem título)"
        proc = w.get("process") or "?"
        if app:
            lines.append(f"{i}. [{state_pt}] {title}")
        else:
            lines.append(f"{i}. {proc} [{state_pt}]: {title}")
        tabs = list(w.get("tabs") or [])
        if want_tabs and tabs:
            shown = tabs[:8]
            extra = "" if len(tabs) <= 8 else f" (+{len(tabs) - 8})"
            lines.append("   Abas: " + " | ".join(shown) + extra)

    extra_w = "" if count <= 10 else f" (e mais {count - 10} janelas)"
    if app:
        head = f"Achei {count} janela(s) do {label} no Windows{extra_w}:"
    else:
        head = f"Achei {count} janela(s) abertas no Windows (ativas + minimizadas){extra_w}:"
    return head + "\n" + "\n".join(lines)


def _mobile_windows_inspect_shortcut_reply(
    message: str,
    *,
    channel: str = MOBILE_CHANNEL,
    user_id: str = "default",
) -> dict[str, Any]:
    """Inspeciona janelas/abas no Windows e responde no mesmo turno."""
    app = _mobile_windows_app_name(message)
    folded = _fold_pt(message)
    # Follow-up “somente? / segundo plano?” → reusa último app do histórico
    if not app and re.search(
        r"\b(somente|segundo\s+plano|outra|outro|mais\s+algum|em\s+paralelo|abas?\b)\b",
        folded,
    ):
        app = _last_windows_app_from_history(channel, user_id)
    if not app and re.search(r"\b(navegador|browser)\b", folded):
        app = _last_windows_app_from_history(channel, user_id) or "opera"

    label = {
        "opera": "Opera GX",
        "chrome": "Chrome",
        "firefox": "Firefox",
        "edge": "Edge",
        "msedge": "Edge",
        "brave": "Brave",
        "discord": "Discord",
        "cursor": "Cursor",
        "notepad": "Notepad",
        "spotify": "Spotify",
    }.get(app or "", app or "app")

    want_tabs = True
    result = _windows_list_open_windows(app, include_tabs=True)
    count = int(result.get("count") or 0)
    windows = result.get("windows") or []

    if not result.get("ok") and count == 0:
        answer = _mobile_warm_tool_answer(
            ok=False,
            ok_text="",
            fail_text="Não consegui ler as janelas do Windows agora.",
            err=str(result.get("output") or "")[:160],
        )
    else:
        answer = _format_windows_inspect_answer(
            app=app,
            label=label,
            windows=windows,
            want_tabs=want_tabs,
        )

    return {
        "instant": True,
        "ok": bool(result.get("ok", True)),
        "answer": answer,
        "agent": AGENT_NAME,
        "model": "windows_list_windows",
        "persist_history": True,
        "tool_log": [
            {
                "tool": "windows_list_windows",
                "arguments": {"name": app or "", "include_tabs": True},
                "result_preview": str(result.get("raw") or "")[:900],
            }
        ],
    }


def _close_empty_browser_windows(name: str) -> dict[str, Any]:
    """Fecha só janelas do browser com título 'vazio' (sem abas de conteúdo)."""
    from learning_agent.core import agent_tools

    proc = "opera" if name.startswith("opera") else name
    # Opera vazio: "Opera"/"Opera GX"/"Speed Dial…"; com conteúdo: "… - YouTube - Opera"
    script = (
        f"$n='{proc}'; $closed=0; $titles=@(); "
        "Get-Process | Where-Object { "
        "  $_.MainWindowHandle -ne 0 -and "
        "  ($_.ProcessName -like $n -or $_.ProcessName -like ($n+'*')) "
        "} | ForEach-Object { "
        "  $t = [string]$_.MainWindowTitle; "
        "  if ([string]::IsNullOrWhiteSpace($t)) { return }; "
        "  $titles += $t; "
        "  $core = ($t -replace '\\s*-\\s*(Opera GX|Opera|Google Chrome|Mozilla Firefox|Microsoft Edge|Brave)\\s*$','').Trim(); "
        "  $empty = ($core -eq '' -or $core -match '^(Opera GX|Opera|Chrome|Firefox|Edge|Brave|Speed Dial|Nova guia|New tab|In[ií]cio|Start page)$') "
        "    -or ($t -match '^(Speed Dial|Nova guia|New tab)') "
        "    -or ($core.Length -lt 18 -and $t -notmatch '(?i)YouTube|Google|http|github|stack|whatsapp|gmail|discord'); "
        "  if ($empty) { "
        "    [void]$_.CloseMainWindow(); Start-Sleep -Milliseconds 500; "
        "    if (-not $_.HasExited) { Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue }; "
        "    $closed++ "
        "  } "
        "}; "
        "if ($closed -gt 0) { 'CLOSED_EMPTY '+$closed } "
        "elseif ($titles.Count -eq 0) { 'NO_WINDOW' } "
        "else { 'NO_EMPTY_WINDOW titles=' + ($titles -join ' || ') }"
    )
    result_raw = agent_tools.execute_tool("windows_exec", {"command": script, "timeout": 45})
    try:
        payload = json.loads(result_raw)
    except json.JSONDecodeError:
        payload = {"ok": False, "output": result_raw}
    out = str(payload.get("output") or "")
    if "CLOSED_EMPTY" in out.upper():
        payload["ok"] = True
    elif "NO_EMPTY_WINDOW" in out.upper():
        payload["ok"] = False
        payload["error"] = "Achei o navegador, mas nenhuma janela parecia vazia"
    elif "NO_WINDOW" in out.upper():
        payload["ok"] = False
        payload["error"] = "Não achei janela desse navegador aberta"
    else:
        payload["ok"] = False
        payload["error"] = out[:240] or str(payload.get("error") or "falha ao fechar")
    payload["_raw"] = result_raw
    return payload


def _mobile_windows_shortcut_reply(
    message: str,
    *,
    intent: str,
    channel: str = MOBILE_CHANNEL,
    user_id: str = "default",
) -> dict[str, Any]:
    import time as _time

    from learning_agent.core import agent_tools

    name = _mobile_windows_app_name(message) or _last_windows_app_from_history(channel, user_id)
    if not name:
        return {
            "instant": True,
            "ok": False,
            "answer": _mobile_warm_tool_answer(
                ok=False,
                ok_text="",
                fail_text="Qual programa você quer que eu abra ou feche no Windows?",
            ),
            "agent": AGENT_NAME,
            "model": "windows_need_app",
            "persist_history": True,
            "tool_log": [],
        }
    low = (message or "").lower()
    empty_only = bool(
        re.search(
            r"(n[aã]o\s+tem\s+nenhuma\s+aba|sem\s+(nenhuma\s+)?aba|aba\s+aberta|janela\s+vazia|sem\s+nada)",
            low,
        )
    )
    close_scope = _close_scope_from_message(message)
    logs: list[dict[str, Any]] = []

    def _run(tool: str) -> dict[str, Any]:
        result_raw = agent_tools.execute_tool(tool, {"name": name})
        try:
            payload = json.loads(result_raw)
        except json.JSONDecodeError:
            payload = {"ok": False, "output": result_raw}
        ok = bool(payload.get("ok") or payload.get("exit_code") == 0)
        logs.append({"tool": tool, "arguments": {"name": name}, "result_preview": result_raw[:600]})
        return {"ok": ok, "raw": result_raw, "err": str(payload.get("error") or "")}

    if intent == "open_then_close":
        opened = _run("windows_open_app")
        _time.sleep(1.2)
        closed = _run("windows_close_app")
        if opened["ok"] and closed["ok"]:
            answer = _mobile_warm_tool_answer(
                ok=True,
                ok_text=f"Abri o {name} no Windows e já fechei de novo.",
                fail_text="",
            )
            ok = True
        elif opened["ok"]:
            answer = _mobile_warm_tool_answer(
                ok=False,
                ok_text="",
                fail_text=f"Abri o {name}, mas não consegui fechar agora.",
                err=closed.get("err"),
            )
            ok = False
        else:
            answer = _mobile_warm_tool_answer(
                ok=False,
                ok_text="",
                fail_text=f"Não consegui abrir o {name} agora.",
                err=opened.get("err"),
            )
            ok = False
        tool = "windows_open_app+close"
    elif intent == "close":
        if empty_only and name in {"opera", "chrome", "firefox", "edge", "brave"}:
            payload = _close_empty_browser_windows(name)
            logs.append(
                {
                    "tool": "windows_exec",
                    "arguments": {"name": name, "empty_only": True},
                    "result_preview": str(payload.get("_raw") or "")[:600],
                }
            )
            ok = bool(payload.get("ok"))
            err = str(payload.get("error") or "")
            if not ok and re.search(r"(ainda|ainsa|continua|n[aã]o\s+fech)", low):
                closed = _run("windows_close_app")
                ok = closed["ok"]
                err = closed.get("err") or err
                answer = _mobile_warm_tool_answer(
                    ok=ok,
                    ok_text=f"Pronto, Luis — encerrei o {name} no Windows (não deu pra isolar só a janela vazia).",
                    fail_text=f"Tentei de novo e não consegui fechar o {name}.",
                    err=err,
                )
                tool = "windows_close_app_fallback"
            else:
                answer = _mobile_warm_tool_answer(
                    ok=ok,
                    ok_text=f"Pronto, Luis — fechei a janela vazia do {name} no seu Windows.",
                    fail_text=f"Não achei janela vazia do {name} pra fechar.",
                    err=err,
                )
                tool = "windows_close_empty"
        elif close_scope in {"min", "vis"}:
            from learning_agent.core import windows_agent_client as win

            payload = win.close_windows(name, only_state=close_scope)
            logs.append(
                {
                    "tool": "windows_close_windows",
                    "arguments": {"name": name, "only_state": close_scope},
                    "result_preview": json.dumps(payload, ensure_ascii=False)[:700],
                }
            )
            ok = bool(payload.get("ok"))
            scope_pt = "minimizada/segundo plano" if close_scope == "min" else "ativa/primeiro plano"
            titles = [c.get("title") or "" for c in (payload.get("closed") or [])][:3]
            title_hint = f" ({'; '.join(titles)})" if titles else ""
            answer = _mobile_warm_tool_answer(
                ok=ok,
                ok_text=f"Pronto, Luis — fechei só a janela {scope_pt} do {name}{title_hint}.",
                fail_text=f"Não achei janela {scope_pt} do {name} pra fechar.",
                err=str(payload.get("error") or ""),
            )
            tool = "windows_close_scoped"
        else:
            closed = _run("windows_close_app")
            ok = closed["ok"]
            answer = _mobile_warm_tool_answer(
                ok=ok,
                ok_text=f"Pronto, Luis — fechei o {name} no seu Windows.",
                fail_text=f"Não consegui fechar o {name} agora.",
                err=closed.get("err"),
            )
            tool = "windows_close_app"
    else:
        from learning_agent.core import windows_agent_client as win

        opened_payload = win.open_app(name)
        logs.append(
            {
                "tool": "windows_open_app",
                "arguments": {"name": name},
                "result_preview": json.dumps(opened_payload, ensure_ascii=False)[:700],
            }
        )
        ok = bool(opened_payload.get("ok"))
        # Confirma com listagem real — não afirma abrir sem janela visível
        if ok:
            _time.sleep(1.5)
            listed = win.list_windows(name, include_tabs=False)
            still = int(listed.get("count") or 0)
            logs.append(
                {
                    "tool": "windows_list_windows",
                    "arguments": {"name": name, "verify_open": True},
                    "result_preview": json.dumps(
                        {"count": still, "windows": (listed.get("windows") or [])[:4]},
                        ensure_ascii=False,
                    )[:700],
                }
            )
            if still <= 0:
                ok = False
                opened_payload["error"] = "Start-Process rodou, mas não apareceu janela do app"
        answer = _mobile_warm_tool_answer(
            ok=ok,
            ok_text=f"Pronto, Luis — abri o {name} no seu Windows.",
            fail_text=f"Não consegui abrir o {name} agora.",
            err=str(opened_payload.get("error") or ""),
        )
        tool = "windows_open_app"
    return {
        "instant": True,
        "ok": ok,
        "answer": answer,
        "agent": AGENT_NAME,
        "model": tool,
        "persist_history": True,
        "tool_log": logs,
    }


def _is_mobile_wake_request(message: str) -> bool:
    text = (message or "").strip()
    if not text or len(text) > 240:
        return False
    low = text.lower()
    # Print/screenshot tem prioridade absoluta sobre wake.
    if _MOBILE_SCREENSHOT_HINT_RE.search(low):
        return False
    if " e depois " in low or " e então " in low or " e entao " in low:
        return False
    return bool(_MOBILE_WAKE_RE.search(text))


def _mobile_wake_shortcut_reply(message: str) -> dict[str, Any]:
    """Acorda a tela no host sem LLM — prova real via host_wake_display."""
    from learning_agent.core import agent_tools

    result_raw = agent_tools.execute_tool("host_wake_display", {})
    try:
        payload = json.loads(result_raw)
    except json.JSONDecodeError:
        payload = {"ok": False, "output": result_raw}
    ok = bool(payload.get("ok") or payload.get("remote_ok") or payload.get("exit_code") == 0)
    if ok:
        answer = "Pronto — acordei a tela."
    else:
        answer = (
            "Não consegui acordar a tela agora. "
            "Se o PC entrou em suspend profundo, precisa ligar de novo na rede."
        )
    return {
        "instant": True,
        "ok": ok,
        "answer": answer,
        "agent": AGENT_NAME,
        "model": "host_wake_display",
        "persist_history": True,
        "tool_log": [
            {
                "tool": "host_wake_display",
                "arguments": {},
                "result_preview": result_raw[:600],
            }
        ],
        "wake_ok": ok,
    }


# --- Híbrido atalho + interpretação (opção 3) ---------------------------------
# Candidatas por regex com confiança. Alta e única → executa. Empate/ambíguo → LLM.

_MOBILE_SHORTCUT_HIGH = 0.85
_MOBILE_SHORTCUT_MED = 0.55
_MOBILE_SHORTCUT_GAP = 0.18


@dataclass(frozen=True)
class MobileShortcutCandidate:
    kind: str
    confidence: float
    label: str
    tool_hint: str
    intent: str = ""  # open | close | open_then_close quando kind=windows_app


def _score_mobile_shortcut_candidates(
    message: str,
    *,
    attachment_ids: list[str] | None = None,
    channel: str = MOBILE_CHANNEL,
    user_id: str = "default",
) -> list[MobileShortcutCandidate]:
    """Só pontua — não executa. Ordenado por confiança desc."""
    text = (message or "").strip()
    if not text:
        return []
    low = text.lower()
    aids = [a.strip() for a in (attachment_ids or []) if a.strip()]
    out: list[MobileShortcutCandidate] = []

    has_screenshot = bool(
        _MOBILE_SCREENSHOT_HINT_RE.search(low)
        or re.search(r"\b(mostra\s+a\s+tela|mostra\s+o\s+que\s+t[aá]|tira\s+captura)\b", low)
    )
    wake_pattern = bool(_MOBILE_WAKE_RE.search(text))
    compound = bool(
        re.search(r"\b(e\s+depois|depois|também|tambem|e\s+também|e\s+tambem)\b", low)
        or (has_screenshot and wake_pattern)
    )

    if has_screenshot:
        conf = 0.72 if (wake_pattern and compound) else 0.93
        out.append(
            MobileShortcutCandidate(
                kind="screenshot",
                confidence=conf,
                label="Capturar print da tela do Windows",
                tool_hint="windows_screenshot",
            )
        )

    if wake_pattern:
        # Com print no mesmo pedido → baixa confiança p/ forçar desempate LLM
        conf = 0.68 if has_screenshot else 0.92
        out.append(
            MobileShortcutCandidate(
                kind="wake",
                confidence=conf,
                label="Acordar a tela / sair de standby (host Linux)",
                tool_hint="host_wake_display",
            )
        )

    if aids and re.search(r"\b(pc|windows|computador|downloads)\b", low) and _SEND_TO_PC_RE.search(low):
        out.append(
            MobileShortcutCandidate(
                kind="pc_media",
                confidence=0.94,
                label="Enviar mídia anexada para o PC",
                tool_hint="windows_send_media_to_pc",
            )
        )
    elif not aids and _SEND_TO_PC_RE.search(low):
        out.append(
            MobileShortcutCandidate(
                kind="pc_media",
                confidence=0.80,
                label="Enviar última mídia da conversa para o PC",
                tool_hint="windows_send_media_to_pc",
            )
        )

    # Gravação de tela: intenção explícita (não "achar vídeo no Windows")
    if re.search(r"\b(grava|gravar|filmagem|captura\s+de\s+tela)\b", low) and re.search(
        r"\b(tela|screen)\b", low
    ):
        out.append(
            MobileShortcutCandidate(
                kind="record",
                confidence=0.90,
                label="Gravar a tela do Windows",
                tool_hint="windows_record_screen",
            )
        )

    win_path = _extract_windows_path(text)
    if win_path and re.search(r"\b(manda|envia|enviar|mandar|copia|copiar|pull|transfere)\b", low):
        out.append(
            MobileShortcutCandidate(
                kind="pull_file",
                confidence=0.90,
                label=f"Puxar arquivo do PC ({win_path})",
                tool_hint="windows_pull_file",
            )
        )
    if win_path and re.search(r"\b(lê|leia|le|conteúdo|conteudo)\b", low) and re.search(
        r"\b(arquivo)\b", low
    ):
        out.append(
            MobileShortcutCandidate(
                kind="read_file",
                confidence=0.88,
                label=f"Ler arquivo no PC ({win_path})",
                tool_hint="windows_read_file",
            )
        )

    if _is_mobile_windows_inspect_request(text):
        out.append(
            MobileShortcutCandidate(
                kind="inspect_windows",
                confidence=0.90,
                label="Inspecionar janelas/apps abertos no Windows",
                tool_hint="windows_list_windows",
            )
        )

    win_intent = _windows_open_close_intent(text, channel=channel, user_id=user_id)
    if win_intent:
        labels = {
            "open": "Abrir app no Windows",
            "close": "Fechar app/janela no Windows",
            "open_then_close": "Abrir e fechar app (teste)",
        }
        out.append(
            MobileShortcutCandidate(
                kind="windows_app",
                confidence=0.88,
                label=labels.get(win_intent, "Controlar app no Windows"),
                tool_hint="windows_open_app" if win_intent == "open" else "windows_close_app",
                intent=win_intent,
            )
        )

    if _is_mobile_linux_status(text):
        out.append(
            MobileShortcutCandidate(
                kind="linux_status",
                confidence=0.90,
                label="Status do host Linux (ravenna)",
                tool_hint="host_status",
            )
        )

    from learning_agent.core.file_transfer import (
        is_media_mux_request,
        is_media_pipeline_request,
        is_subtitle_only_request,
        is_windows_find_video_request,
        is_windows_to_debian_transfer_request,
    )

    if is_media_mux_request(text):
        out.append(
            MobileShortcutCandidate(
                kind="media_plan",
                confidence=0.98,
                label="Juntar áudio original/dublado/legendas em MKV",
                tool_hint="media_plan",
            )
        )
    elif is_subtitle_only_request(text):
        out.append(
            MobileShortcutCandidate(
                kind="media_plan",
                confidence=0.97,
                label="Baixar/juntar legenda do filme (sem converter/enviar)",
                tool_hint="media_plan",
            )
        )
    elif is_media_pipeline_request(text):
        out.append(
            MobileShortcutCandidate(
                kind="media_plan",
                confidence=0.96,
                label="Plano de mídia (achar → checar → converter → enviar)",
                tool_hint="media_plan",
            )
        )
    elif is_windows_to_debian_transfer_request(text):
        out.append(
            MobileShortcutCandidate(
                kind="transfer_debian",
                confidence=0.94,
                label="Transferir vídeo/filme do Windows para o Debian",
                tool_hint="windows_transfer_to_debian",
            )
        )
    elif is_windows_find_video_request(text):
        out.append(
            MobileShortcutCandidate(
                kind="find_files",
                confidence=0.93,
                label="Localizar vídeo/arquivo no Windows",
                tool_hint="windows_find_files",
            )
        )

    # Detecção leve: URL+download ou busca explícita — a execução real valida de novo
    if _extract_http_url(text) and re.search(r"\b(baix|download|abre|abrir|youtube|google)\w*\b", low):
        out.append(
            MobileShortcutCandidate(
                kind="web",
                confidence=0.86,
                label="Ação web (download / abrir URL / busca)",
                tool_hint="windows_open_url|windows_download_file",
            )
        )
    elif re.search(r"\b(pesquisa|pesquisa\s+no|busca\s+no|google|youtube)\b", low) and len(text) < 200:
        out.append(
            MobileShortcutCandidate(
                kind="web",
                confidence=0.75,
                label="Busca Google/YouTube no Windows",
                tool_hint="windows_search_google|windows_search_youtube",
            )
        )

    out.sort(key=lambda c: c.confidence, reverse=True)
    # Dedup por kind (mantém maior confiança)
    seen: set[str] = set()
    deduped: list[MobileShortcutCandidate] = []
    for c in out:
        if c.kind in seen:
            continue
        seen.add(c.kind)
        deduped.append(c)
    return deduped


def _pick_mobile_shortcut_route(
    candidates: list[MobileShortcutCandidate],
) -> tuple[str, MobileShortcutCandidate | None, list[MobileShortcutCandidate]]:
    """Retorna (execute|llm|none, escolhida?, candidatas p/ LLM)."""
    if not candidates:
        return "none", None, []
    top = candidates[0]
    # Mux/plano de mídia com confiança alta: executa direto (não deixa o LLM “pensar” no vácuo)
    if top.kind == "media_plan" and top.confidence >= 0.95:
        return "execute", top, candidates[:3]
    rivals = [c for c in candidates[1:] if c.confidence >= _MOBILE_SHORTCUT_MED]
    if rivals and (top.confidence - rivals[0].confidence) < _MOBILE_SHORTCUT_GAP:
        return "llm", None, candidates[:3]
    if top.confidence >= _MOBILE_SHORTCUT_HIGH:
        return "execute", top, candidates[:3]
    if top.confidence >= 0.70 and not rivals:
        return "execute", top, candidates[:3]
    if top.confidence >= _MOBILE_SHORTCUT_MED:
        return "llm", None, candidates[:3]
    return "none", None, []


def _mobile_candidates_llm_context(candidates: list[MobileShortcutCandidate]) -> str:
    lines = [
        "INTENÇÕES CANDIDATAS (desempate — escolha no máximo UMA e chame a tool correspondente).",
        "Não execute mentalmente; integridade: só afirme ação se a tool rodou neste turno.",
    ]
    for c in candidates[:3]:
        lines.append(
            f"- {c.kind} ({c.confidence:.0%}): {c.label} → tool `{c.tool_hint}`"
            + (f" (intent={c.intent})" if c.intent else "")
        )
    return "\n".join(lines)


def _execute_mobile_shortcut_candidate(
    candidate: MobileShortcutCandidate,
    message: str,
    *,
    attachment_ids: list[str] | None = None,
    channel: str = MOBILE_CHANNEL,
    user_id: str = "default",
) -> dict[str, Any] | None:
    kind = candidate.kind
    if kind == "wake":
        return _mobile_wake_shortcut_reply(message)
    if kind in {"screenshot", "pc_media", "record", "pull_file", "read_file"}:
        return _mobile_pc_inspect_shortcut_reply(
            message,
            attachment_ids=attachment_ids,
            channel=channel,
            user_id=user_id,
        )
    if kind == "inspect_windows":
        return _mobile_windows_inspect_shortcut_reply(
            message, channel=channel, user_id=user_id
        )
    if kind == "windows_app":
        intent = candidate.intent or _windows_open_close_intent(
            message, channel=channel, user_id=user_id
        )
        if not intent:
            return None
        return _mobile_windows_shortcut_reply(
            message, intent=intent, channel=channel, user_id=user_id
        )
    if kind == "linux_status":
        return _mobile_linux_status_shortcut()
    if kind == "transfer_debian":
        return _mobile_transfer_to_debian_reply(message)
    if kind == "find_files":
        return _mobile_find_files_reply(message)
    if kind == "media_plan":
        return _mobile_media_plan_reply(message, channel=channel, user_id=user_id)
    if kind == "web":
        return _mobile_web_shortcut_reply(message)
    return None


def _format_size_label(n: int) -> str:
    x = float(max(0, n))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if x < 1024 or unit == "TB":
            return f"{x:.0f} {unit}" if unit == "B" else f"{x:.1f} {unit}"
        x /= 1024
    return f"{n} B"


def _mobile_find_files_reply(message: str) -> dict[str, Any]:
    from learning_agent.core import agent_tools
    from learning_agent.core.file_transfer import extract_video_query

    query = extract_video_query(message) or ""
    if not query:
        # fallback: strip common verbs
        query = re.sub(
            r"(?i)^(ravenna[,!]?\s*)?(encontrar|encontre|acha|achar|buscar|find|localizar)\s+",
            "",
            (message or "").strip(),
        )
        query = re.sub(r"(?i)\s+(no|na|em|on)\s+(windows|pc|computador).*$", "", query).strip(" .,?!")
    result_raw = agent_tools.execute_tool(
        "windows_find_files",
        {"query": query, "kind": "video"},
    )
    try:
        payload = json.loads(result_raw)
    except json.JSONDecodeError:
        payload = {"ok": False, "matches": []}
    matches = payload.get("matches") or []
    if not matches:
        return {
            "instant": True,
            "ok": False,
            "answer": _mobile_warm_tool_answer(
                ok=False,
                ok_text="",
                fail_text=f'Não achei “{query}” em Downloads/Vídeos/Desktop.',
                err=str(payload.get("error") or ""),
            ),
            "agent": AGENT_NAME,
            "model": "windows_find_files",
            "persist_history": True,
            "media": [],
            "tool_log": [{"tool": "windows_find_files", "arguments": {"query": query}, "result": result_raw}],
        }
    lines = [f"Achei {len(matches)} arquivo(s) no Windows:"]
    for row in matches[:5]:
        name = row.get("name") or "?"
        path = row.get("path") or ""
        size = _format_size_label(int(row.get("size") or 0))
        lines.append(f"• {name} ({size})\n  {path}")
    return {
        "instant": True,
        "ok": True,
        "answer": "\n".join(lines),
        "agent": AGENT_NAME,
        "model": "windows_find_files",
        "persist_history": True,
        "media": [],
        "tool_log": [
            {
                "tool": "windows_find_files",
                "arguments": {"query": query},
                "result": result_raw[:2000],
            }
        ],
    }


def _mobile_media_plan_reply(
    message: str,
    *,
    channel: str = MOBILE_CHANNEL,
    user_id: str = "default",
) -> dict[str, Any]:
    from learning_agent.core import media_plan
    from learning_agent.core.file_transfer import extract_video_query

    query = extract_video_query(message) or ""
    job = media_plan.start_media_plan(
        message=message,
        query=query,
        conversation_id=user_id,
        channel=channel,
    )
    if not job.get("ok"):
        return {
            "instant": True,
            "ok": False,
            "answer": _mobile_warm_tool_answer(
                ok=False,
                ok_text="",
                fail_text="Não consegui iniciar o plano de mídia agora.",
                err=str(job.get("error") or ""),
            ),
            "agent": AGENT_NAME,
            "model": "media_plan",
            "persist_history": True,
            "media": [],
            "plan": None,
            "tool_log": [{"tool": "media_plan", "result": json.dumps(job, ensure_ascii=False)}],
        }
    steps = job.get("steps") or []
    labels = ", ".join(str(s.get("label") or s.get("id")) for s in steps[:6])
    answer = (
        f"Beleza — montei o plano e já estou executando ({labels}). "
        f"Acompanhe os passos abaixo."
    )
    plan = {
        "id": job.get("id"),
        "status": job.get("status") or "running",
        "query": job.get("query"),
        "steps": steps,
        "percent": float(job.get("percent") or 0),
    }
    return {
        "instant": True,
        "ok": True,
        "answer": answer,
        "agent": AGENT_NAME,
        "model": "media_plan",
        "persist_history": True,
        "media": [
            {
                "id": str(plan["id"]),
                "type": "plan",
                "filename": job.get("query") or "plano",
                "url": f"/api/plans/{plan['id']}",
            }
        ],
        "plan": plan,
        "tool_log": [
            {
                "tool": "media_plan",
                "arguments": {"query": query},
                "result": json.dumps({"id": plan["id"], "steps": [s.get("id") for s in steps]}, ensure_ascii=False),
            }
        ],
    }


def _wants_teatrinho_handoff(message: str) -> bool:
    """Pedido menciona Teatrinho / biblioteca / Cursor para importar após o envio."""
    low = (message or "").lower()
    return bool(re.search(r"\b(teatrinho|biblioteca|cursor)\b", low))


def _teatrinho_handoff_for_job(job: dict[str, Any], *, query: str) -> dict[str, Any]:
    """Enfileira inbox @teatrinho; tenta notify se o alvo estiver bound."""
    from learning_agent.core import cursor_targets

    fname = str(job.get("filename") or query or "vídeo")
    dest = str(job.get("dest_path") or "")
    tid = str(job.get("id") or "")
    title = f"Importar {fname} na Biblioteca"
    msg = (
        f"Disponibilize na biblioteca do Teatrinho: {fname}. "
        f"Arquivo no Debian: {dest or '(aguardando path)'}. "
        f"transfer_id={tid}."
    )
    payload = {
        "transfer_id": tid,
        "filename": fname,
        "dest_path": dest,
        "query": query,
    }
    out: dict[str, Any] = {}
    try:
        out["inbox"] = cursor_targets.enqueue_handoff(
            "teatrinho",
            kind="teatrinho_import",
            title=title,
            message=msg,
            payload=payload,
        )
    except Exception as exc:  # noqa: BLE001 — atalho não deve falhar o transfer
        out["inbox_error"] = str(exc)
        return out
    try:
        notified = cursor_targets.notify_target(
            "teatrinho",
            msg,
            user_id="system",
            also_inbox=False,
            inbox_kind="teatrinho_import",
            inbox_title=title,
            inbox_payload=payload,
        )
        out["notify"] = notified
    except Exception as exc:  # noqa: BLE001
        out["notify_error"] = str(exc)
    return out


def _mobile_transfer_to_debian_reply(message: str) -> dict[str, Any]:
    from learning_agent.core import file_transfer

    queries = file_transfer.extract_video_queries(message)
    if not queries:
        return {
            "instant": True,
            "ok": False,
            "answer": _mobile_warm_tool_answer(
                ok=False,
                ok_text="",
                fail_text="Não entendi qual vídeo enviar. Coloca o nome entre aspas?",
                err="query vazia",
            ),
            "agent": AGENT_NAME,
            "model": "windows_transfer_to_debian",
            "persist_history": True,
            "media": [],
            "transfer": None,
            "tool_log": [],
        }

    want_teatrinho = _wants_teatrinho_handoff(message)
    ok_jobs: list[tuple[str, dict[str, Any]]] = []
    fail_lines: list[str] = []
    tool_log: list[dict[str, Any]] = []
    media: list[dict[str, Any]] = []
    handoffs: list[dict[str, Any]] = []

    for query in queries:
        job = file_transfer.start_windows_video_transfer(query=query)
        tool_log.append(
            {
                "tool": "windows_transfer_to_debian",
                "arguments": {"query": query},
                "result": json.dumps(
                    {k: job.get(k) for k in ("ok", "id", "status", "filename", "bytes_total", "dest_path", "error")},
                    ensure_ascii=False,
                ),
            }
        )
        if not job.get("ok"):
            err = str(job.get("error") or "falha na transferência")
            fail_lines.append(f"“{query}”: {err}")
            continue
        ok_jobs.append((query, job))
        fname = str(job.get("filename") or "vídeo")
        media.append(
            {
                "id": str(job.get("id")),
                "type": "transfer",
                "filename": fname,
                "url": f"/api/transfers/{job.get('id')}",
            }
        )
        if want_teatrinho:
            handoffs.append(_teatrinho_handoff_for_job(job, query=query))

    if not ok_jobs:
        err = "; ".join(fail_lines) or "falha na transferência"
        return {
            "instant": True,
            "ok": False,
            "answer": _mobile_warm_tool_answer(
                ok=False,
                ok_text="",
                fail_text="Não consegui achar/enviar esses vídeos agora.",
                err=err,
            ),
            "agent": AGENT_NAME,
            "model": "windows_transfer_to_debian",
            "persist_history": True,
            "media": [],
            "transfer": None,
            "tool_log": tool_log,
        }

    ok_bits: list[str] = []
    for query, job in ok_jobs:
        size_label = job.get("size_label") or "?"
        fname = job.get("filename") or query
        ok_bits.append(f"{fname} ({size_label})")
    if len(ok_jobs) == 1:
        answer = (
            f"Achei {ok_bits[0]} no Windows. "
            f"Já estou mandando pro Debian — acompanha a barra abaixo."
        )
    else:
        answer = (
            f"Achei {len(ok_jobs)} vídeos no Windows: {'; '.join(ok_bits)}. "
            f"Já estou mandando os {len(ok_jobs)} pro Debian — acompanhe as barras abaixo."
        )
    if fail_lines:
        answer += " Não rolou: " + "; ".join(fail_lines) + "."
    if want_teatrinho and any(h.get("inbox") for h in handoffs):
        answer += " Também pedi ao Cursor (@teatrinho) pra disponibilizar na biblioteca."
    elif want_teatrinho:
        answer += " Tentei avisar o Teatrinho, mas o canal pode estar sem bind — o inbox foi o que deu."

    first = ok_jobs[0][1]
    transfer = {
        "id": first.get("id"),
        "filename": first.get("filename") or "vídeo",
        "status": first.get("status") or "starting",
        "percent": float(first.get("percent") or 0),
        "bytes_done": int(first.get("bytes_done") or 0),
        "bytes_total": int(first.get("bytes_total") or 0),
        "eta_seconds": first.get("eta_seconds"),
        "dest_path": first.get("dest_path"),
        "size_label": first.get("size_label"),
    }
    return {
        "instant": True,
        "ok": True,
        "answer": answer,
        "agent": AGENT_NAME,
        "model": "windows_transfer_to_debian",
        "persist_history": True,
        "media": media,
        "transfer": transfer,
        "transfers": [
            {
                "id": j.get("id"),
                "filename": j.get("filename"),
                "status": j.get("status"),
                "dest_path": j.get("dest_path"),
                "query": q,
            }
            for q, j in ok_jobs
        ],
        "teatrinho_handoffs": handoffs or None,
        "tool_log": tool_log,
    }


def _mobile_temp_context(message: str) -> str:
    """Injeta leitura atual como contexto — o LLM responde em diálogo (sem atalho)."""
    text = (message or "").strip()
    if not text or not _MOBILE_TEMP_MENTION_RE.search(text):
        return ""
    temp = _fetch_pc_temp_c()
    temp_line = (
        f"Leitura atual do host: {temp:.0f}°C (sensor)."
        if temp is not None
        else "Leitura atual do host indisponível no momento."
    )
    return (
        "CONTEXTO TÉRMICO (use se for útil — responda em diálogo natural, 1–4 frases):\n"
        f"{temp_line}\n"
        "Não seja robótica: não entregue só um número engessado; converse. "
        "Sem narrar comandos/tools."
    )


def _fetch_pc_temp_c() -> float | None:
    """Lê temp_c do Home API (host) sem expor comando ao Luis."""
    import urllib.error
    import urllib.request

    urls = (
        os.environ.get("RAVENNA_HOME_PC_STATUS_URL", "").strip(),
        "http://host.docker.internal:8100/api/pc/status",
        "http://172.17.0.1:8100/api/pc/status",
        "http://127.0.0.1:8100/api/pc/status",
    )
    for url in urls:
        if not url:
            continue
        try:
            with urllib.request.urlopen(url, timeout=4) as resp:
                data = json.loads(resp.read().decode())
            machine = data.get("machine") if isinstance(data, dict) else None
            if isinstance(machine, dict) and machine.get("temp_c") is not None:
                return float(machine["temp_c"])
            if isinstance(data, dict) and data.get("temp_c") is not None:
                return float(data["temp_c"])
        except (urllib.error.URLError, TimeoutError, ValueError, TypeError, json.JSONDecodeError):
            continue
    return None


_CJK_RUN_RE = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+")
_MOBILE_STATUS_LEAK_RE = re.compile(
    r"(?i)\b(configuring|please wait|thinking\.{0,3}|configurando[,.]?\s*aguarde)\b"
)
_MOBILE_REGREET_SPLIT_RE = re.compile(
    r"(?s)\n\s*---+\s*\n+.*?(?:Ol[aá]!|Oi[,!]?\s|Como est[aá] o seu dia)",
)


def _sanitize_mobile_answer(text: str) -> str:
    """Limpa vazamentos de IDE/agent e ruído do modelo no canal mobile."""
    cleaned = (text or "").strip()
    if not cleaned:
        return cleaned
    # Teatro do Ciclo autônomo vazado no Home
    if re.search(r"\*\*Investiga[cç][aã]o:\*\*|\*\*Diagn[oó]stico:\*\*|\*\*Solu[cç][aã]o:\*\*", cleaned, re.IGNORECASE):
        parts = re.split(r"\n{2,}", cleaned)
        human = [p for p in parts if not re.search(r"Investiga|Diagn[oó]stico|Solu[cç][aã]o|Ciclo aut", p, re.IGNORECASE)]
        cleaned = "\n\n".join(human).strip() or (
            "Quase caí num modo de IDE agora — me manda de novo o pedido em uma frase que eu executo de verdade."
        )
    cleaned = _MOBILE_CMD_NARRATION_RE.sub("", cleaned)
    cleaned = _MOBILE_VOU_EXEC_RE.sub("", cleaned)
    cleaned = _CJK_RUN_RE.sub("", cleaned)
    cleaned = _MOBILE_STATUS_LEAK_RE.sub("", cleaned)
    # Qwen às vezes corta com --- e recomeça cumprimentando de novo.
    cleaned = _MOBILE_REGREET_SPLIT_RE.sub("", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip(" \n\t-")
    return cleaned or (text or "").strip()


_MOBILE_ACTION_CLAIM_RE = re.compile(
    r"(?i)\b("
    r"abri|abriu|fechei|fechou|enviei|enviou|mandei|mandou|"
    r"capturei|capturou|gravei|gravou|executei|executou|"
    r"liguei|desliguei|acordei|baixei|baixou"
    r")\b"
)

_MOBILE_ACTION_TOOLS = (
    "windows_open_app",
    "windows_close_app",
    "windows_open_url",
    "windows_search_google",
    "windows_search_youtube",
    "windows_download_file",
    "windows_exec",
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
    "windows_send_media_to_pc",
    "host_exec",
    "host_wake_display",
    "host_set_volume",
)

_MOBILE_DEFER_PROMISE_RE = re.compile(
    r"(?i)\b(vou|irei|deixa eu|deixe[- ]me)\s+"
    r"(verificar|checar|olhar|conferir|identificar|confirmar|ver\b)\b"
)


def _mobile_integrity_gate(
    answer: str,
    tool_log: list[dict[str, Any]] | None,
    *,
    user_message: str = "",
) -> str:
    """Não deixar afirmar ação / prometer verificação sem tool no turno."""
    text = (answer or "").strip()
    if not text:
        return text
    tools: set[str] = set()
    for row in tool_log or []:
        name = str(row.get("tool") or "").strip()
        if not name:
            continue
        for part in name.replace("+", " ").split():
            tools.add(part)
    has_world_tool = bool(
        tools.intersection(_MOBILE_ACTION_TOOLS)
        or any(t.startswith("windows_") or t.startswith("host_") for t in tools)
    )
    # Pedidos claros de find/transfer/plano: não empurrar "pedido objetivo" genérico
    from learning_agent.core.file_transfer import (
        is_media_mux_request,
        is_media_pipeline_request,
        is_subtitle_only_request,
        is_windows_find_video_request,
        is_windows_to_debian_transfer_request,
    )

    clear_media_intent = bool(
        is_windows_find_video_request(user_message)
        or is_windows_to_debian_transfer_request(user_message)
        or is_media_pipeline_request(user_message)
        or is_media_mux_request(user_message)
        or is_subtitle_only_request(user_message)
    )
    if _MOBILE_DEFER_PROMISE_RE.search(text) and not has_world_tool:
        if clear_media_intent:
            return (
                "Esse pedido eu resolvo com tools (achar/converter/enviar). "
                "Manda de novo em uma frase — eu executo no mesmo turno."
            )
        return (
            "Não vou te deixar no vácuo — me manda o pedido objetivo "
            "(ex.: “tem Opera GX aberto no Windows?” ou “acha o vídeo Guardiões no Windows”) "
            "que eu olho de verdade e te respondo no mesmo turno."
        )
    if not _MOBILE_ACTION_CLAIM_RE.search(text):
        return text
    if has_world_tool:
        return text
    return (
        "Ainda não executei essa ação de verdade neste turno. "
        "Me confirma o pedido que eu faço agora?"
    )


def _rgb_safe(state: str, *, wait: bool = False) -> None:
    try:
        from learning_agent.core.ravenna_rgb import set_rgb_state

        set_rgb_state(state, wait=wait)
    except Exception:
        pass


def _mobile_rgb_begin() -> None:
    _rgb_safe("thinking", wait=True)


def _mobile_rgb_end(*, ok: bool = True) -> None:
    if not ok:
        _rgb_safe("trouble", wait=True)
        return
    _rgb_safe("speaking", wait=True)

    def _later_idle() -> None:
        import time

        time.sleep(float(__import__("os").environ.get("RAVENNA_RGB_SPEAK_HOLD_S", "3")))
        _rgb_safe("idle", wait=True)

    try:
        import threading

        threading.Thread(target=_later_idle, daemon=True).start()
    except Exception:
        _rgb_safe("idle", wait=False)


def _is_mobile_followup(message: str) -> bool:
    return bool(_MOBILE_FOLLOWUP_RE.match((message or "").strip()))


def _mobile_followup_context(channel: str, user_id: str) -> str:
    """Último turno salvo — evita inventar 'ciclo autônomo' em perguntas tipo 'Pq?'."""
    rows = _load_history(channel, user_id, limit=6, content_cap=1200)
    if len(rows) < 2:
        return ""
    last_asst = ""
    last_user = ""
    for row in reversed(rows):
        role = row.get("role")
        content = str(row.get("content") or "").strip()
        if not content:
            continue
        if role == "assistant" and not last_asst:
            last_asst = content
        elif role == "user" and not last_user:
            last_user = content
        if last_asst and last_user:
            break
    if not last_asst:
        return ""
    block = (
        "CONTEXTO DO TURNO ANTERIOR (use para responder com empatia — não invente jargão):\n"
        f"- Luis disse: {last_user or '(mensagem anterior)'}\n"
        f"- Você respondeu: {last_asst}\n"
        "Se houve falha técnica, explique o motivo real em linguagem simples. "
        "PROIBIDO mencionar 'ciclo autônomo' ou processos internos genéricos."
    )
    return block


def _mobile_warm_tool_answer(*, ok: bool, ok_text: str, fail_text: str, err: str = "") -> str:
    if ok:
        return ok_text
    detail = (err or "").strip()
    if detail:
        return f"{fail_text} Motivo: {detail[:180]}. Quer que eu tente de novo?"
    return f"{fail_text} Quer que eu tente de novo?"


def _is_light_message(message: str) -> bool:
    text = message.strip()
    if _is_greeting(text):
        return True
    if _ACK_RE.match(text):
        return True
    return len(text) < 60 and "?" not in text


def suggest_model_size(
    message: str,
    *,
    task_mode: str = "chat",
    editor_context: str = "",
    delegate_agent: str | None = None,
) -> tuple[str, list[str]]:
    """Escolhe 0.5b (rápido) ou 32b (completo) conforme a mensagem."""
    text = message.strip()
    mode = (task_mode or "chat").strip().lower()

    if mode == "agent":
        return "32b", ["modo agent"]
    if delegate_agent:
        return "32b", ["delegação"]
    if editor_context.strip():
        return "32b", ["contexto do editor"]
    if _is_greeting(text):
        return "0.5b", ["saudação"]
    if _ACK_RE.match(text):
        return "0.5b", ["confirmação curta"]
    if "```" in text or (text.count("\n") >= 2 and len(text) > 80):
        return "32b", ["código ou multiline"]
    if len(text) >= 120:
        return "32b", ["mensagem longa"]
    if "?" in text:
        return "32b", ["pergunta"]
    lower = text.lower()
    if any(kw in lower for kw in _HEAVY_KEYWORDS):
        return "32b", ["tarefa técnica"]
    if _is_light_message(text):
        return "0.5b", ["mensagem leve"]
    return "32b", ["padrão"]


def _greeting_reply(*, channel: str = "api") -> str:
    if channel == MOBILE_CHANNEL:
        return (
            f"Oi, Luis. Que bom te ver — sou a {AGENT_NAME}. "
            "Tô aqui com você, de verdade. Como tá o seu dia?"
        )
    if channel == "telegram":
        return (
            f"Oi! 😊 Sou a {AGENT_NAME}, sua {AGENT_ROLE}. "
            "Que bom te ver por aqui — pode perguntar o que quiser, estou contigo!"
        )
    return (
        f"Olá! 😊 Sou a {AGENT_NAME}, sua {AGENT_ROLE}. "
        "Que bom te ver — posso implementar software, criar seus agentes ou orquestrar tudo na IDE. O que vamos fazer?"
    )


def greeting_for_channel(channel: str = "api") -> str:
    return _greeting_reply(channel=channel)


def _format_context(ctx: dict[str, Any], *, max_items: int = 2) -> str:
    parts: list[str] = []

    for item in ctx.get("knowledge", [])[:max_items]:
        parts.append(f"[Conhecimento] {item.get('content', '')[:300]}")

    for item in ctx.get("code", [])[:1]:
        parts.append(f"[Código] {item.get('content', '')[:300]}")

    for err in ctx.get("past_errors", [])[:1]:
        parts.append(f"[Erro passado] {err.get('context', '')}: {err.get('error', '')[:150]}")

    return "\n\n".join(parts) if parts else ""


def _agent_delegate_hint(agent_name: str) -> str | None:
    """Contexto do subagente — NÃO substitui AGENT_SYSTEM (write blocks)."""

    import yaml

    from learning_agent.config import PROJECT_ROOT

    slug = agent_name.strip().lower().replace("_", "-")
    manifest_path = PROJECT_ROOT / "agents" / "projects" / slug / "manifest.yaml"
    if not manifest_path.is_file():
        return f"Delegação: agente {slug}. Implemente com blocos ```write``` — não só sugira."
    with manifest_path.open(encoding="utf-8") as fh:
        manifest = yaml.safe_load(fh) or {}
    display = manifest.get("display_name", slug)
    focus = manifest.get("focus", "")
    archetype = manifest.get("archetype", "custom")
    return (
        f"Delegação ativa: {display} ({slug}), arquétipo {archetype}.\n"
        f"Foco: {focus}\n"
        "Fale SEMPRE como Ravenna (orquestradora). O especialista trabalha nos bastidores — "
        f"nunca se apresente como «{slug}» ou «{display}» ao usuário.\n"
        "Você DEVE implementar com blocos ```write caminho``` — prosa sem write NÃO conta como entrega.\n"
        "UI/React/CSS: edite ravenna-ide/frontend/src/ e styles/."
    )


def _resolve_task_mode(task_mode: str, message: str) -> str:
    mode = (task_mode or "chat").strip().lower()
    if mode in {"chat", "agent", "fast"}:
        return mode
    if _is_light_message(message):
        return "fast"
    return "chat"


def _is_cloud_engine(engine: str | None, model_size: str | None = None) -> bool:
    """DeepSeek (Flash/Pro) ou Groq teacher explícito — nunca o Raven local 0.5b."""
    eng = (engine or "groq").strip().lower().replace("-", "_")
    if eng in {
        "deepseek", "deepseek_pro", "deepseek_v4", "deepseek_v4_pro",
        "deepseek_flash", "deepseek_v4_flash",
    }:
        return True
    if eng in {"groq", "teacher"}:
        raw = (model_size or "").strip().lower()
        return raw not in {"0.5b", "fast"}
    return False


def _resolve_model_size(
    model_size: str | None,
    task_mode: str,
    *,
    message: str = "",
    editor_context: str = "",
    delegate_agent: str | None = None,
    channel: str = "api",
    engine: str = "groq",
) -> tuple[str, str, str, list[str]]:
    """Retorna (task_mode efetivo, modelo, tamanho resolvido, motivos)."""
    raw = (model_size or "auto").strip().lower()
    mode = (task_mode or "chat").strip().lower()
    ide = channel in {"ide", "theater"}

    if mode == "agent":
        ctx_len = len(editor_context.strip())
        agent_mdl = AGENT_MODEL
        # IDE + Home (mobile) precisam do loop local com tools (host_*). Groq não executa host.
        if IDE_AGENT_USE_LOCAL and channel in {"ide", "theater", "mobile"}:
            return "agent", agent_mdl, "7b", [f"modo agent → {agent_mdl} (local/{channel})"]
        if ide and IDE_AGENT_USE_LOCAL:
            return "agent", agent_mdl, "32b", [f"modo agent → {agent_mdl} (local)"]
        if TEACHER_API_KEY and ctx_len <= AGENT_GROQ_CONTEXT_MAX and len(message) < 500:
            return "agent", TEACHER_MODEL, "70b", ["modo agent (Groq, contexto leve)"]
        return "agent", agent_mdl, "32b", [f"modo agent → {agent_mdl} (código)"]

    # Motor cloud explícito (DeepSeek/Groq): NUNCA rebaixa para 0.5b em mensagem leve.
    # O tamanho 0.5b/fast é só para o Raven local (Ollama) — não rouba DeepSeek/Groq.
    if _is_cloud_engine(engine, model_size):
        return "chat", CHAT_MODEL, "32b", ["motor cloud explícito (sem rebaixar para 0.5b)"]

    if mode == "fast" or raw == "0.5b":
        return "fast", CHAT_MODEL_FAST, "0.5b", ["0.5b manual" if raw == "0.5b" else "modo fast"]

    if channel == MOBILE_CHANNEL:
        return "chat", TEACHER_MODEL if TEACHER_API_KEY else CHAT_MODEL, "120b", [
            "Home conversa → Groq 120B" if TEACHER_API_KEY else "Home conversa → 7B local"
        ]

    if raw == "32b":
        return "chat", CHAT_MODEL, "32b", ["32b manual"]

    picked, reasons = suggest_model_size(
        message,
        task_mode=mode,
        editor_context=editor_context,
        delegate_agent=delegate_agent,
    )
    if picked == "0.5b":
        return "fast", CHAT_MODEL_FAST, "0.5b", reasons
    return "chat", CHAT_MODEL, "32b", reasons


def _call_llm(
    messages: list[dict[str, str]],
    *,
    task_mode: str,
    max_tokens: int,
    chat_model: str | None = None,
    project_root: str | None = None,
    require_grounding_tools: bool = False,
    required_grounding_reads: list[str] | None = None,
    tool_allowlist: list[str] | None = None,
    tool_max_turns: int | None = None,
    channel: str = "api",
) -> tuple[str, str, list[dict[str, Any]]]:
    """Home: conversa → Groq 120B; execução → 7B local. Demais canais: student + fallback."""
    empty_log: list[dict[str, Any]] = []
    mdl = chat_model or (AGENT_MODEL if task_mode == "agent" else CHAT_MODEL)

    if channel == MOBILE_CHANNEL and task_mode != "agent" and TEACHER_API_KEY:
        last_exc: Exception | None = None
        for teacher_model in llm._teacher_models():
            try:
                reply = llm.chat_complete(
                    messages,
                    base_url=TEACHER_API_BASE,
                    api_key=TEACHER_API_KEY,
                    model=teacher_model,
                    max_tokens=max_tokens,
                )
                return reply, teacher_model, empty_log
            except Exception as exc:
                last_exc = exc
                continue
        try:
            return llm.chat_complete(messages, model=CHAT_MODEL, max_tokens=max_tokens), CHAT_MODEL, empty_log
        except Exception:
            if last_exc:
                raise last_exc
            raise

    use_local_agent = IDE_AGENT_USE_LOCAL and mdl != TEACHER_MODEL
    if task_mode == "agent" and AGENT_TOOL_LOOP and use_local_agent:
        try:
            reply, model_used, tool_log = llm.chat_with_tools_loop(
                messages,
                max_tokens=max_tokens,
                model=mdl,
                project_root=project_root,
                require_read_grounding=require_grounding_tools,
                required_read_paths=required_grounding_reads,
                tool_allowlist=tool_allowlist,
                max_turns=tool_max_turns,
            )
            return reply, model_used, tool_log
        except Exception:
            if TEACHER_API_KEY:
                last_exc: Exception | None = None
                for teacher_model in llm._teacher_models():
                    try:
                        reply, model_used, tool_log = llm.chat_with_tools_loop(
                            messages,
                            max_tokens=max_tokens,
                            model=teacher_model,
                            project_root=project_root,
                            require_read_grounding=require_grounding_tools,
                            required_read_paths=required_grounding_reads,
                            tool_allowlist=tool_allowlist,
                            max_turns=tool_max_turns,
                            base_url=TEACHER_API_BASE,
                            api_key=TEACHER_API_KEY,
                        )
                        return reply, model_used, tool_log
                    except Exception as exc:
                        last_exc = exc
                        continue
                if last_exc:
                    pass
    if task_mode == "agent" and TEACHER_API_KEY and not use_local_agent:
        try:
            reply = llm.chat_complete(
                messages,
                base_url=TEACHER_API_BASE,
                api_key=TEACHER_API_KEY,
                model=TEACHER_MODEL,
                max_tokens=max_tokens,
            )
            return reply, TEACHER_MODEL, empty_log
        except Exception:
            pass
    reply, model_used = llm.chat_with_fallback(messages, max_tokens=max_tokens, model=mdl)
    return reply, model_used, empty_log


def _vision_image_parts(attachment_ids: list[str]) -> list[dict[str, Any]]:
    """Converte anexos de imagem em partes image_url (base64) para modelos vision."""
    import base64

    from learning_agent.core.attachments import (
        IMAGE_EXTENSIONS,
        resolve_attachment_path,
    )

    mime_map = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }
    parts: list[dict[str, Any]] = []
    for aid in attachment_ids:
        try:
            path = resolve_attachment_path(aid)
        except Exception:
            continue
        if path.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        try:
            raw = path.read_bytes()
        except OSError:
            continue
        mime = mime_map.get(path.suffix.lower(), "image/png")
        b64 = base64.b64encode(raw).decode("ascii")
        parts.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}})
    return parts


def _prepare_reply(
    message: str,
    *,
    channel: str = "api",
    user_id: str = "default",
    include_context: bool = True,
    delegate_agent: str | None = None,
    extra_system: str | None = None,
    editor_context: str = "",
    task_mode: str = "chat",
    model_size: str = "auto",
    persist_history: bool = True,
    project_root: str | None = None,
    require_grounding_tools: bool = False,
    required_grounding_reads: list[str] | None = None,
    tool_allowlist: list[str] | None = None,
    tool_max_turns: int | None = None,
    attachment_ids: list[str] | None = None,
    engine: str = "groq",
) -> dict[str, Any]:
    """Monta mensagens LLM — compartilhado por reply() e iter_reply_deltas()."""
    if not message.strip() and not (attachment_ids or []):
        raise ValueError("Mensagem vazia")

    if _is_greeting(message):
        answer = _greeting_reply(channel=channel)
        if persist_history:
            _save_message(channel, user_id, "user", message)
            _save_message(channel, user_id, "assistant", answer)
        return {
            "instant": True,
            "answer": answer,
            "agent": AGENT_NAME,
            "model": "instant",
            "persist_history": persist_history,
        }

    # Corpo: thinking desde o início da decisão (atalhos + LLM herdam; um end no fim).
    mobile_rgb_started = False
    if channel == MOBILE_CHANNEL:
        _mobile_rgb_begin()
        mobile_rgb_started = True

    # Híbrido: candidatas → execute se confiança alta/única; senão LLM desempatar.
    mobile_llm_candidates: list[MobileShortcutCandidate] = []
    if channel == MOBILE_CHANNEL:
        scored = _score_mobile_shortcut_candidates(
            message,
            attachment_ids=attachment_ids,
            channel=channel,
            user_id=user_id,
        )
        route, chosen, for_llm = _pick_mobile_shortcut_route(scored)
        if route == "execute" and chosen is not None:
            shortcut = _execute_mobile_shortcut_candidate(
                chosen,
                message,
                attachment_ids=attachment_ids,
                channel=channel,
                user_id=user_id,
            )
            if shortcut:
                if chosen.kind in {
                    "screenshot",
                    "pc_media",
                    "record",
                    "pull_file",
                    "read_file",
                    "transfer_debian",
                    "find_files",
                    "media_plan",
                }:
                    _persist_mobile_exchange(
                        channel,
                        user_id,
                        message,
                        shortcut["answer"],
                        user_media=shortcut.get("user_media"),
                        assistant_media=shortcut.get("media"),
                        persist_history=persist_history,
                    )
                elif persist_history:
                    _save_message(channel, user_id, "user", message)
                    _save_message(channel, user_id, "assistant", shortcut["answer"])
                shortcut["persist_history"] = persist_history
                shortcut["shortcut_route"] = "execute"
                shortcut["shortcut_kind"] = chosen.kind
                if mobile_rgb_started:
                    _mobile_rgb_end(
                        ok=bool(shortcut.get("ok", shortcut.get("wake_ok", True)))
                    )
                return shortcut
            # Execução não materializou → deixa LLM com as candidatas
            if for_llm:
                mobile_llm_candidates = for_llm
        elif route == "llm" and for_llm:
            mobile_llm_candidates = for_llm

    if channel == MOBILE_CHANNEL and mobile_llm_candidates:
        cand_block = _mobile_candidates_llm_context(mobile_llm_candidates)
        extra_system = f"{cand_block}\n\n{extra_system}".strip() if extra_system else cand_block

    # Acesso/capacidade: agente decide (sem probe obrigatório / early-return).

    mobile_followup = channel == MOBILE_CHANNEL and _is_mobile_followup(message)
    if mobile_followup and persist_history:
        followup_block = _mobile_followup_context(channel, user_id)
        if followup_block:
            extra_system = f"{followup_block}\n\n{extra_system}".strip() if extra_system else followup_block

    light = _is_light_message(message) and not mobile_followup
    cloud_engine = _is_cloud_engine(engine, model_size)
    mode, chat_model, resolved_size, size_reasons = _resolve_model_size(
        model_size,
        _resolve_task_mode(task_mode, message),
        message=message,
        editor_context=editor_context,
        delegate_agent=delegate_agent,
        channel=channel,
        engine=engine,
    )
    ide = channel in {"ide", "theater"}
    if channel == MOBILE_CHANNEL:
        # thinking já ligado no início da decisão
        pass
    elif mode == "agent":
        _rgb_safe("thinking", wait=True)
    if ide and mode == "agent":
        history_limit = AGENT_IDE_HISTORY_LIMIT
        history_content_cap = AGENT_HISTORY_CONTENT_LIMIT
    else:
        history_limit = CHAT_IDE_HISTORY_LIMIT if ide else CHAT_HISTORY_LIMIT
        history_content_cap = CHAT_IDE_HISTORY_CONTENT_LIMIT if ide else 800
    if ide and mode == "agent":
        # 0 = sem cap (deixa o modelo gerar livremente); valor > 0 = cap explícito
        max_tokens = CHAT_IDE_MAX_TOKENS
    elif mode == "agent":
        max_tokens = AGENT_MAX_TOKENS
    elif (mode == "fast" or light) and not cloud_engine:
        max_tokens = CHAT_FAST_MAX_TOKENS
    elif channel == "telegram" and not light:
        max_tokens = TELEGRAM_CHAT_MAX_TOKENS
    elif ide and mode == "chat":
        max_tokens = 0
    elif channel == MOBILE_CHANNEL and mode == "agent":
        max_tokens = max(AGENT_MAX_TOKENS, 4096)
    elif channel == MOBILE_CHANNEL:
        max_tokens = max(CHAT_MAX_TOKENS, 4096)
    else:
        max_tokens = CHAT_MAX_TOKENS
    use_context = include_context and mode != "fast" and not light and not tool_allowlist
    if channel == MOBILE_CHANNEL:
        use_context = False

    context_block = ""
    if use_context:
        ctx = context_core.get_context_for_task(message, limit=2 if ide else 4)
        context_block = _format_context(ctx, max_items=2 if ide else 3)
    if editor_context.strip():
        editor_block = _truncate_text(
            editor_context.strip(),
            CHAT_IDE_EDITOR_MAX_CHARS if ide else 6000,
        )
        context_block = (
            f"{context_block}\n\nCONTEXTO EDITOR:\n{editor_block}"
            if context_block
            else f"CONTEXTO EDITOR:\n{editor_block}"
        )

    # Paridade Cursor: turno agent na IDE sem @file explícito → auto-injeta
    # chunks relevantes do codebase (busca semântica), como o Cursor faz.
    if mode == "agent" and ide and not editor_context.strip() and not tool_allowlist:
        try:
            from learning_agent.core.codebase import search_code

            hits = search_code(message, limit=4)
            blocks: list[str] = []
            for h in hits:
                src = str((h.get("metadata") or {}).get("source") or "")
                content = str(h.get("content") or "").strip()
                if not content:
                    continue
                blocks.append(f"// {src}\n{content[:600]}")
            if blocks:
                code_ctx = "CONTEXTO DO CODEBASE (busca semântica):\n" + "\n\n".join(blocks)
                context_block = (
                    f"{context_block}\n\n{code_ctx}" if context_block else code_ctx
                )
        except Exception:
            pass

    if persist_history:
        user_media: list[dict[str, Any]] = []
        if channel == MOBILE_CHANNEL and attachment_ids:
            from learning_agent.core.chat_media import (
                media_item_from_record,
                resolve_media_path,
            )

            for mid in attachment_ids:
                try:
                    path = resolve_media_path(mid.strip())
                    user_media.append(
                        media_item_from_record(
                            {
                                "id": mid.strip(),
                                "filename": path.name.split("-", 2)[-1],
                                "type": "image"
                                if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".gif"}
                                else "video"
                                if path.suffix.lower() in {".mp4", ".webm", ".mov"}
                                else "file",
                            }
                        )
                    )
                except Exception:
                    continue
        _save_message(channel, user_id, "user", message, user_media or None)
        if channel == IDE_CHANNEL:
            on_user_message(user_id, message, channel)
        history = _load_history(
            channel, user_id, limit=history_limit, content_cap=history_content_cap
        )
    else:
        # Agent ephemeral turns are intentionally not persisted, but the current
        # user request still must be sent to the model.
        history = [{"role": "user", "content": message}]

    delegate_hint = _agent_delegate_hint(delegate_agent) if delegate_agent else None
    # Home agent: full host control via tools (not IDE write-blocks persona).
    effective_tool_allowlist = tool_allowlist
    if mode == "agent" and channel == MOBILE_CHANNEL and not tool_allowlist:
        effective_tool_allowlist = list(MOBILE_AGENT_TOOLS)
    if mode == "agent":
        if channel == MOBILE_CHANNEL:
            system = MOBILE_AGENT_SYSTEM
            if AGENT_TOOL_LOOP and IDE_AGENT_USE_LOCAL:
                tool_names = ", ".join(effective_tool_allowlist or MOBILE_AGENT_TOOLS)
                system += (
                    f"\n\nFerramentas ativas (tool_calls): {tool_names}. "
                    "Para qualquer ação no PC use host_exec (ou host_wake_display / host_set_volume). "
                    "PROIBIDO inventar que executou sem tool_call. "
                    "PROIBIDO narrar/colar comando na resposta — só o resultado em 1–3 frases."
                )
        else:
            system = AGENT_SYSTEM
            if AGENT_TOOL_LOOP and IDE_AGENT_USE_LOCAL:
                if effective_tool_allowlist:
                    tool_names = ", ".join(effective_tool_allowlist)
                    system += (
                        f"\n\nFerramentas ativas (tool_calls Ollama): {tool_names}. "
                        "Memória enxuta: registre só falhas/insights acionáveis com record_project_lesson; "
                        "use get_project_lessons antes de implementar. "
                        "PROIBIDO neste modo: search_knowledge, research_trusted_sources, consult_specialist."
                    )
                else:
                    system += (
                        "\n\nFerramentas ativas (tool_calls Ollama): read_file, list_files, search_code, "
                        "grep_workspace, get_context_for_task, get_related_errors, search_knowledge, "
                        "get_project_lessons, record_project_lesson, expand_project_knowledge, "
                        "research_trusted_sources, consult_specialist, "
                        "host_wake_display, host_set_volume, host_exec, host_status, "
                        "windows_open_app, windows_search_google, windows_search_youtube, windows_exec. "
                        "Memória enxuta: registre só falhas/insights acionáveis com record_project_lesson; "
                        "antes de implementar use get_project_lessons + expand_project_knowledge; "
                        "para lacunas use research_trusted_sources ou consult_specialist (ex: backend-lead). "
                        "Linux host: host_*; Windows PC: windows_*."
                    )
    elif channel == "telegram":
        system = CHAT_SYSTEM_TELEGRAM_FAST if light else CHAT_SYSTEM_TELEGRAM
    elif channel == MOBILE_CHANNEL:
        system = MOBILE_SYSTEM_FAST if light else MOBILE_SYSTEM
    else:
        system = CHAT_SYSTEM_FAST if light else CHAT_SYSTEM
    messages: list[dict[str, str]] = [{"role": "system", "content": system}]
    if ide and mode in {"chat", "fast"}:
        # Paridade Cursor Ask: proíbe write/patch/shell de forma dura, antes do histórico.
        messages.append({"role": "system", "content": ASK_MODE_DIRECTIVE})
    if editor_context and "RAVENNA WORKSPACE STUDY DIGEST" in editor_context:
        from learning_agent.core.workspace_study import STUDY_SYSTEM

        messages.append({"role": "system", "content": STUDY_SYSTEM})
    if delegate_hint:
        messages.append({"role": "system", "content": delegate_hint})
    if extra_system:
        messages.append({"role": "system", "content": extra_system})
    if channel == MOBILE_CHANNEL and mode == "agent":
        thermal = _mobile_temp_context(message)
        if thermal:
            messages.append({"role": "system", "content": thermal})
    if not delegate_agent:
        user_geo = user_context.format_system_block()
        if user_geo:
            messages.append({"role": "system", "content": user_geo})
    if context_block:
        messages.append({"role": "system", "content": f"CONTEXTO LOCAL:\n{context_block}"})
    messages.extend(history)

    # Visão multimodal: converte a última mensagem user em content com image_url.
    vision_images: list[dict[str, Any]] = []
    if channel == IDE_CHANNEL and attachment_ids and VISION_ENABLED:
        vision_images = _vision_image_parts([a for a in attachment_ids if a.strip()])
        if vision_images:
            last_user = len(messages) - 1
            while last_user >= 0 and messages[last_user].get("role") != "user":
                last_user -= 1
            if last_user >= 0 and isinstance(messages[last_user].get("content"), str):
                text = messages[last_user]["content"]
                messages[last_user] = {
                    "role": "user",
                    "content": [{"type": "text", "text": text}] + vision_images,
                }

    resolved_reads = required_grounding_reads
    if require_grounding_tools and project_root and not resolved_reads:
        from learning_agent.core import agent_spec_builder
        from learning_agent.core.workspace_bootstrap import (
            required_grounding_reads as reads_for_spec,
        )

        resolved_reads = reads_for_spec(
            agent_spec_builder.build_spec(message, project_root=project_root)
        )

    llm_endpoint: dict[str, Any] | None = None
    if ide and mode in {"chat", "agent"}:
        from learning_agent.core.llm_engines import (
            local_chat_endpoint,
            resolve_ide_chat_endpoint,
        )

        try:
            llm_endpoint = resolve_ide_chat_endpoint(
                engine=engine,
                task_mode=mode,
                resolved_size=resolved_size,
                model_size_requested=model_size,
            )
        except ValueError as exc:
            return {
                "instant": True,
                "answer": str(exc),
                "agent": AGENT_NAME,
                "model": "error",
                "persist_history": persist_history,
                "error": str(exc),
            }
        if mode in {"chat", "fast"} and llm_endpoint is None and (
            resolved_size == "0.5b" or mode == "fast"
        ):
            llm_endpoint = local_chat_endpoint(fast=True)
            chat_model = llm_endpoint["model"]
        elif llm_endpoint is not None:
            chat_model = llm_endpoint["model"]

    # Visão multimodal: com imagens, troca para o modelo vision (não-tool-loop).
    if vision_images and VISION_API_KEY and VISION_MODEL and mode != "agent":
        llm_endpoint = {
            "base_url": VISION_API_BASE,
            "api_key": VISION_API_KEY,
            "model": VISION_MODEL,
            "label": f"vision/{VISION_MODEL}",
        }
        chat_model = VISION_MODEL

    return {
        "instant": False,
        "messages": messages,
        "max_tokens": max_tokens,
        "channel": channel,
        "user_id": user_id,
        "history_limit": history_limit,
        "delegate_agent": delegate_agent,
        "light": light,
        "task_mode": mode,
        "chat_model": chat_model,
        "model_size": resolved_size,
        "model_size_requested": model_size,
        "model_size_reasons": size_reasons,
        "persist_history": persist_history,
        "project_root": (project_root or "").strip() or None,
        "require_grounding_tools": require_grounding_tools,
        "required_grounding_reads": resolved_reads or [],
        "tool_allowlist": effective_tool_allowlist,
        "tool_max_turns": tool_max_turns,
        "user_message": message,
        "llm_endpoint": llm_endpoint,
        "engine": (engine or "groq").strip().lower(),
    }


def _sanitize_chat_error(exc: BaseException | str) -> str:
    """Human-readable errors for IDE chat — never dump ContextVar/stack guts."""
    err = str(exc)
    if "created in a different Context" in err or "ContextVar" in err:
        return "Falha interna de contexto nas ferramentas. Tente de novo."
    if "413" in err:
        return "Contexto grande demais para a API. Envie mensagem mais curta ou limpe o histórico."
    if len(err) > 400:
        return err[:400] + "…"
    return err


_WRITE_OR_SHELL_FENCE_RE = re.compile(
    r"```(?:write|file|canvas|patch|shell)[^\n]*\n[\s\S]*?```",
    re.IGNORECASE,
)


def _strip_write_blocks_for_history(text: str) -> str:
    """Remove cercas write/patch/shell antes de persistir no histórico da IDE.

    Sem isso, o bloco de código emitido em um turno é realimentado no turno
    seguinte, levando o modelo a repetir o mesmo código (mesmo em modo Ask).
    """
    if not text:
        return text
    cleaned = _WRITE_OR_SHELL_FENCE_RE.sub("", text)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned


def _agent_step_event(entry: dict[str, Any], index: int) -> dict[str, Any]:
    """Deriva um evento estruturado agent_step de uma tool real (sem teatro)."""
    tool = str(entry.get("tool") or "tool").strip().lower()
    args = entry.get("arguments") or {}
    if not isinstance(args, dict):
        args = {}
    path = str(args.get("path") or args.get("file") or args.get("filepath") or args.get("target") or "").strip()
    query = str(args.get("query") or args.get("pattern") or args.get("q") or args.get("search") or "").strip()
    command = str(args.get("command") or args.get("cmd") or args.get("shell") or "").strip()

    if "read" in tool or "list" in tool:
        kind = "read_file"
    elif "grep" in tool or "search" in tool or "find" in tool:
        kind = "grep"
    elif "write" in tool or "patch" in tool or "apply" in tool or "edit" in tool:
        kind = "apply_patch"
    elif "exec" in tool or "terminal" in tool or "shell" in tool or "run" in tool:
        kind = "run_command"
    elif "test" in tool or "validate" in tool or "check" in tool:
        kind = "run_test"
    else:
        kind = "tool"

    basename = path.replace("\\", "/").split("/")[-1] if path else ""
    if kind == "read_file":
        title = f"Lendo {basename or 'arquivo'}"
    elif kind == "grep":
        title = f'Buscando "{query[:40]}"' if query else "Buscando no código"
    elif kind == "apply_patch":
        title = f"Aplicando {basename or 'alterações'}"
    elif kind == "run_command":
        title = f"Executando {command[:40]}" if command else "Executando comando"
    elif kind == "run_test":
        title = f"Validando {basename or 'projeto'}"
    else:
        title = tool.replace("_", " ") or "Ferramenta"

    detail = str(entry.get("result_preview") or "").strip()[:160] or None

    return {
        "agent_step": {
            "id": f"step-{index}",
            "type": kind,
            "status": "done",
            "title": title,
            "detail": detail,
        }
    }


def iter_reply_deltas(
    message: str,
    *,
    channel: str = "api",
    user_id: str = "default",
    include_context: bool = True,
    delegate_agent: str | None = None,
    extra_system: str | None = None,
    editor_context: str = "",
    task_mode: str = "chat",
    model_size: str = "auto",
    persist_history: bool = True,
    project_root: str | None = None,
    require_grounding_tools: bool = False,
    required_grounding_reads: list[str] | None = None,
    tool_allowlist: list[str] | None = None,
    tool_max_turns: int | None = None,
    attachment_ids: list[str] | None = None,
    engine: str = "groq",
) -> Iterator[str | dict[str, Any]]:
    """Yield tokens (str) ou dict final com metadados."""
    prepared = _prepare_reply(
        message,
        channel=channel,
        user_id=user_id,
        include_context=include_context,
        delegate_agent=delegate_agent,
        extra_system=extra_system,
        editor_context=editor_context,
        task_mode=task_mode,
        model_size=model_size,
        persist_history=persist_history,
        project_root=project_root,
        require_grounding_tools=require_grounding_tools,
        required_grounding_reads=required_grounding_reads,
        tool_allowlist=tool_allowlist,
        tool_max_turns=tool_max_turns,
        attachment_ids=attachment_ids,
        engine=engine,
    )
    if prepared.get("instant"):
        yield prepared["answer"]
        yield {
            "final": True,
            "agent": prepared["agent"],
            "model": prepared["model"],
            "reply": prepared["answer"],
            "media": prepared.get("media") or [],
            "tool_log": prepared.get("tool_log") or [],
            "transfer": prepared.get("transfer"),
            "plan": prepared.get("plan"),
        }
        return

    try:
        if prepared["task_mode"] == "agent":
            endpoint = prepared.get("llm_endpoint")
            chat_model = prepared.get("chat_model") or AGENT_MODEL
            use_teacher = bool(TEACHER_API_KEY and chat_model == TEACHER_MODEL)
            use_cloud_agent = endpoint is not None
            use_tool_loop = AGENT_TOOL_LOOP and (
                use_cloud_agent or (IDE_AGENT_USE_LOCAL and not use_teacher)
            )

            if use_tool_loop:
                messages = fit_messages_for_llm(prepared["messages"])
                tool_kwargs: dict[str, Any] = {
                    "max_tokens": prepared["max_tokens"],
                    "model": endpoint["model"] if endpoint else chat_model,
                    "project_root": prepared.get("project_root"),
                    "require_read_grounding": bool(prepared.get("require_grounding_tools")),
                    "required_read_paths": prepared.get("required_grounding_reads") or None,
                    "tool_allowlist": prepared.get("tool_allowlist"),
                    "max_turns": prepared.get("tool_max_turns"),
                }
                if endpoint:
                    tool_kwargs["base_url"] = endpoint["base_url"]
                    tool_kwargs["api_key"] = endpoint["api_key"]
                try:
                    stream_iter = llm.iter_chat_with_tools_loop(messages, **tool_kwargs)
                except Exception as first_exc:
                    if "413" not in str(first_exc):
                        raise
                    messages = fit_messages_for_llm(prepared["messages"], aggressive=True)
                    stream_iter = llm.iter_chat_with_tools_loop(messages, **tool_kwargs)

                answer = ""
                model_used = chat_model
                tool_log: list[dict[str, Any]] = []
                for event in stream_iter:
                    if event.get("tool_entry"):
                        tool_log.append(event["tool_entry"])
                        yield {"tool": event["tool_entry"]}
                        yield _agent_step_event(event["tool_entry"], len(tool_log))
                        if len(tool_log) == 1:
                            yield {"phase": "exploring"}
                    elif event.get("done"):
                        answer = str(event.get("reply") or "")
                        model_used = str(event.get("model") or chat_model)
                        tool_log = list(event.get("tool_log") or tool_log)

                yield {"phase": "writing"}
                yield answer
                if prepared.get("persist_history", True):
                    _save_message(prepared["channel"], prepared["user_id"], "assistant", answer)
                if prepared["channel"] == IDE_CHANNEL and prepared.get("persist_history", True):
                    touch_conversation(prepared["user_id"])
                from learning_agent.core.chat_media import (
                    extract_chat_artifacts_from_tool_log,
                )

                response_media = extract_chat_artifacts_from_tool_log(tool_log)
                if prepared.get("media"):
                    response_media = list(prepared.get("media") or []) + response_media
                yield {
                    "final": True,
                    "agent": AGENT_NAME,
                    "delegate_agent": prepared["delegate_agent"],
                    "model": model_used,
                    "model_size": prepared.get("model_size"),
                    "model_size_reasons": prepared.get("model_size_reasons"),
                    "reply": answer,
                    "tool_log": tool_log,
                    "media": response_media,
                }
                return

            parts: list[str] = []
            messages = fit_messages_for_llm(prepared["messages"])
            chat_model = prepared.get("chat_model") or AGENT_MODEL
            use_teacher = bool(TEACHER_API_KEY and chat_model == TEACHER_MODEL)
            endpoint = prepared.get("llm_endpoint")

            def _agent_stream(msgs: list[dict[str, str]], *, teacher: bool):
                if endpoint:
                    return llm.chat_complete_stream(
                        msgs,
                        base_url=endpoint["base_url"],
                        api_key=endpoint["api_key"],
                        model=endpoint["model"],
                        max_tokens=prepared["max_tokens"],
                    ), endpoint["model"]
                if teacher:
                    return llm.chat_complete_stream(
                        msgs,
                        base_url=TEACHER_API_BASE,
                        api_key=TEACHER_API_KEY,
                        model=TEACHER_MODEL,
                        max_tokens=prepared["max_tokens"],
                    ), TEACHER_MODEL
                s = llm.chat_stream_with_fallback(
                    msgs,
                    max_tokens=prepared["max_tokens"],
                    model=chat_model,
                )
                return s, chat_model

            try:
                stream, model_used = _agent_stream(
                    messages, teacher=use_teacher and endpoint is None
                )
            except Exception as first_exc:
                if "413" not in str(first_exc):
                    raise
                messages = fit_messages_for_llm(prepared["messages"], aggressive=True)
                stream, model_used = _agent_stream(messages, teacher=False)

            for delta in stream:
                parts.append(delta)
                yield delta
            model_used = stream.model_name if hasattr(stream, "model_name") else model_used
            answer = "".join(parts).strip()
            if not answer:
                answer, model_used, _ = _call_llm(
                    messages,
                    task_mode="agent",
                    max_tokens=prepared["max_tokens"],
                    chat_model=chat_model if not use_teacher else TEACHER_MODEL,
                    project_root=prepared.get("project_root"),
                    require_grounding_tools=bool(prepared.get("require_grounding_tools")),
                    channel=prepared.get("channel") or "api",
                )
                yield answer
            if prepared.get("persist_history", True):
                _save_message(prepared["channel"], prepared["user_id"], "assistant", answer)
            if prepared["channel"] == IDE_CHANNEL and prepared.get("persist_history", True):
                touch_conversation(prepared["user_id"])
            yield {
                "final": True,
                "agent": AGENT_NAME,
                "delegate_agent": prepared["delegate_agent"],
                "model": model_used,
                "model_size": prepared.get("model_size"),
                "model_size_reasons": prepared.get("model_size_reasons"),
                "reply": answer,
            }
            return

        # Regra Luis: sem failover automático. O motor selecionado é o único usado;
        # se falhar, o erro sobe e o usuário decide (trocar no seletor ou tentar de novo).
        endpoint = prepared.get("llm_endpoint")
        chat_model = prepared.get("chat_model") or CHAT_MODEL
        if endpoint:
            stream = llm.chat_complete_stream(
                prepared["messages"],
                base_url=endpoint["base_url"],
                api_key=endpoint["api_key"],
                model=endpoint["model"],
                max_tokens=prepared["max_tokens"],
            )
            model_used = endpoint["model"]
        else:
            stream = llm.chat_complete_stream(
                prepared["messages"],
                model=chat_model,
                max_tokens=prepared["max_tokens"],
            )
            model_used = chat_model
        parts: list[str] = []
        for delta in stream:
            parts.append(delta)
            yield delta
        answer = "".join(parts).strip()
        if not answer:
            if endpoint:
                answer = llm.chat_complete(
                    prepared["messages"],
                    base_url=endpoint["base_url"],
                    api_key=endpoint["api_key"],
                    model=endpoint["model"],
                    max_tokens=prepared["max_tokens"],
                )
                model_used = endpoint["model"]
            else:
                answer = llm.chat_complete(
                    prepared["messages"],
                    model=chat_model,
                    max_tokens=prepared["max_tokens"],
                )
                model_used = chat_model
            yield answer
        if prepared.get("persist_history", True):
            # IDE Ask/Chat: persiste o texto sem os blocos write/shell, para o
            # histórico não realimentar código cru e induzir repetição.
            persisted = answer
            if prepared["channel"] == IDE_CHANNEL and prepared.get("task_mode") in {"chat", "fast"}:
                persisted = _strip_write_blocks_for_history(answer)
            _save_message(prepared["channel"], prepared["user_id"], "assistant", persisted)
        if prepared["channel"] == IDE_CHANNEL and prepared.get("persist_history", True):
            touch_conversation(prepared["user_id"])
        yield {
            "final": True,
            "agent": AGENT_NAME,
            "delegate_agent": prepared["delegate_agent"],
            "model": model_used,
            "model_size": prepared.get("model_size"),
            "model_size_reasons": prepared.get("model_size_reasons"),
            "reply": answer,
        }
    except Exception as exc:
        err = str(exc)
        model_label = str((prepared.get("llm_endpoint") or {}).get("label") or prepared.get("chat_model") or "").strip()
        hint = (
            f"O modelo selecionado ({model_label or 'o motor escolhido'}) falhou. "
            "Não troquei de motor automaticamente — tente de novo ou selecione outro no seletor."
        )
        if "413" in err:
            hint = (
                "Contexto da conversa grande demais para a API nuvem. "
                "Tente mensagem mais curta, limpe o histórico ou anexe menos arquivos."
            )
        yield {
            "final": True,
            "error": _sanitize_chat_error(err),
            "hint": hint,
        }


def reply(
    message: str,
    *,
    channel: str = "api",
    user_id: str = "default",
    include_context: bool = True,
    delegate_agent: str | None = None,
    extra_system: str | None = None,
    editor_context: str = "",
    task_mode: str = "chat",
    model_size: str = "auto",
    persist_history: bool = True,
    project_root: str | None = None,
    require_grounding_tools: bool = False,
    required_grounding_reads: list[str] | None = None,
    tool_allowlist: list[str] | None = None,
    tool_max_turns: int | None = None,
    attachment_ids: list[str] | None = None,
    engine: str = "groq",
) -> dict[str, Any]:
    """Resposta conversacional da Ravenna."""
    prepared = _prepare_reply(
        message,
        channel=channel,
        user_id=user_id,
        include_context=include_context,
        delegate_agent=delegate_agent,
        extra_system=extra_system,
        editor_context=editor_context,
        task_mode=task_mode,
        model_size=model_size,
        persist_history=persist_history,
        project_root=project_root,
        require_grounding_tools=require_grounding_tools,
        required_grounding_reads=required_grounding_reads,
        tool_allowlist=tool_allowlist,
        tool_max_turns=tool_max_turns,
        attachment_ids=attachment_ids,
        engine=engine,
    )
    if prepared.get("instant"):
        fast = "host_wake" if prepared.get("model") == "host_wake_display" else "greeting"
        if prepared.get("model") == "windows_transfer_to_debian":
            fast = "transfer"
        if prepared.get("model") == "windows_find_files":
            fast = "find"
        if prepared.get("model") == "media_plan":
            fast = "plan"
        return {
            "success": True,
            "agent": prepared["agent"],
            "reply": prepared["answer"],
            "model": prepared["model"],
            "identity": IDENTITY_BRIEF,
            "fast_path": fast,
            "tool_log": prepared.get("tool_log") or [],
            "media": prepared.get("media") or [],
            "transfer": prepared.get("transfer"),
            "plan": prepared.get("plan"),
            "history_count": 0,
            "conversation_id": prepared.get("user_id"),
            "ok": prepared.get("ok", True),
        }

    agent_mode = prepared.get("task_mode") == "agent"
    try:
        answer, model_used, tool_log = _call_llm(
            prepared["messages"],
            task_mode=prepared["task_mode"],
            max_tokens=prepared["max_tokens"],
            chat_model=prepared.get("chat_model"),
            project_root=prepared.get("project_root"),
            require_grounding_tools=bool(prepared.get("require_grounding_tools")),
            required_grounding_reads=prepared.get("required_grounding_reads") or None,
            tool_allowlist=prepared.get("tool_allowlist"),
            tool_max_turns=prepared.get("tool_max_turns"),
            channel=prepared.get("channel") or "api",
        )
        if prepared["channel"] == MOBILE_CHANNEL:
            answer = _sanitize_mobile_answer(answer)
            answer = _mobile_integrity_gate(
                answer,
                tool_log,
                user_message=str(prepared.get("user_message") or message or ""),
            )
    except Exception as exc:
        logger.exception("Falha no LLM (canal=%s mode=%s)", prepared.get("channel"), prepared.get("task_mode"))
        if prepared.get("channel") == MOBILE_CHANNEL or agent_mode:
            _mobile_rgb_end(ok=False)
        if prepared["channel"] == MOBILE_CHANNEL:
            warm = (
                "Tive um soluço pra te responder agora, mas eu tô aqui. "
                "Manda de novo em um instante?"
            )
            if prepared.get("persist_history", True):
                # user já pode ter sido salvo em _prepare_reply; garante o turno
                try:
                    _save_message(prepared["channel"], prepared["user_id"], "assistant", warm)
                except Exception:
                    pass
            return {
                "success": True,
                "agent": AGENT_NAME,
                "reply": warm,
                "model": "fallback-warm",
                "identity": IDENTITY_BRIEF,
                "fast_path": "error-warm",
                "tool_log": [],
                "history_count": 0,
                "conversation_id": prepared.get("user_id"),
                "error": str(exc),
            }
        return {
            "success": False,
            "error": str(exc),
            "hint": (
                "Falha ao falar com o modelo (Ollama/Vast em :11435 ou fallback Groq). "
                "Não é a internet do usuário — reinicie a API e o túnel LLM."
            ),
        }

    from learning_agent.core.chat_media import extract_chat_artifacts_from_tool_log

    response_media = extract_chat_artifacts_from_tool_log(tool_log)

    if prepared.get("persist_history", True):
        _save_message(prepared["channel"], prepared["user_id"], "assistant", answer, response_media or None)
    if prepared["channel"] == IDE_CHANNEL and prepared.get("persist_history", True):
        touch_conversation(prepared["user_id"])

    if prepared.get("channel") == MOBILE_CHANNEL:
        _mobile_rgb_end(ok=True)
    elif agent_mode:
        _rgb_safe("idle", wait=True)

    return {
        "success": True,
        "agent": AGENT_NAME,
        "delegate_agent": prepared["delegate_agent"],
        "reply": answer,
        "model": model_used,
        "model_size": prepared.get("model_size"),
        "model_size_reasons": prepared.get("model_size_reasons"),
        "conversation_id": prepared["user_id"],
        "identity": IDENTITY_BRIEF,
        "fast_path": "light" if prepared["light"] else "full",
        "media": response_media,
        "tool_log": tool_log,
        "history_count": len(
            _load_history(prepared["channel"], prepared["user_id"], limit=prepared["history_limit"])
        ),
        "user_context": user_context.profile() if not prepared["delegate_agent"] else None,
    }


def get_history(
    channel: str,
    user_id: str,
    limit: int = CHAT_HISTORY_LIMIT,
) -> list[dict[str, str]]:
    """Histórico persistido (SQLite) para restaurar UI da IDE."""
    return _load_history(channel, user_id, limit=limit)
