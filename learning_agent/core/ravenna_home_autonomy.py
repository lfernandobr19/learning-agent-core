"""Modos de entrega Ravenna Home — seed-pass, refine-only, allowlist de tools."""

from __future__ import annotations

from pathlib import Path
from typing import Any

# Tools com evidência no disco — baixo risco de alucinação.
DELIVERY_TOOLS_REFINE: frozenset[str] = frozenset(
    {
        "read_file",
        "list_files",
        "grep_workspace",
        "get_project_lessons",
        "record_project_lesson",
    }
)

# Tools que injetam contexto não verificado — bloqueadas em delivery UI.
DELIVERY_TOOLS_RISKY: frozenset[str] = frozenset(
    {
        "search_code",
        "get_context_for_task",
        "get_related_errors",
        "search_knowledge",
        "expand_project_knowledge",
        "research_trusted_sources",
        "consult_specialist",
    }
)

DELIVERY_TOOLS_VISTORIA: frozenset[str] = frozenset(
    {
        "read_file",
        "list_files",
        "grep_workspace",
        "get_project_lessons",
    }
)

VISTORIA_PROMPT_BLOCK = """\
MODO VISTORIA (somente diagnóstico — evidências já coletadas):
- Backend já rodou checks determinísticos (filesystem + :5174). NÃO invente gaps.
- Use read_file/list_files/grep_workspace SOMENTE para confirmar paths citados no JSON.
- PROIBIDO: write/patch/shell, search_code, get_context_for_task, afirmar "ausente" sem read_file.
- Entregue o relatório markdown fornecido; pode enriquecer com 1–2 read_file se necessário.
- Se contradizer GROUNDING/evidências → resposta REJEITADA.
"""

REFINE_RH14_FULLSCREEN_BLOCK = """\
MODO REFINE RH-14 FULL-VIEWPORT (base patch-D + gemini-chat já no disco):
- **Chat.tsx BLOQUEADO** — patch-D aplicado; NÃO re-patch, NÃO write em Chat.
- PRÉ-LEITURA: `theme/gemini-space-index.css`, `theme/tokens.css`, `src/index.css` — **NÃO chame read_file** se já injetado.
- No **primeiro turno de texto** emita **dois** blocos ```write```:
  1. `theme/tokens.css` — variáveis espaço/neon (--ravenna-*)
  2. `src/index.css` — `@import '../theme/tokens.css';` + layout full-viewport (≥ gemini-space-index.css: .space-bg, .neon-glow, .chat-fullscreen, 100dvh, .chat-input-dock)
- Opcional 3º bloco: `src/Layout.tsx` — shell sem competir com chat na aba inicial.
- PROIBIDO: App.tsx, package.json, Chat.tsx, npm build, narrar arquivos ausentes.
- Depois: `record_project_lesson`.
"""

REFINE_PROMPT_BLOCK = """\
MODO REFINE-ONLY (entrega rápida — sem investigação longa):
- Baseline já seedado no disco. **PRÉ-LEITURA já no contexto** — NÃO chame read_file/list_files/grep.
- Emita SOMENTE blocos ```write``` ou ```patch``` nos paths permitidos **no primeiro turno de texto**.
- Foque em CSS/UX: `src/index.css`, opcional `src/Layout.tsx` / `InstallPrompt.tsx`.
- PROIBIDO: pytest, backend, package.json, narrar arquivos como ausentes.
- Máximo 1–2 arquivos por resposta. Não peça confirmação.
- Ao final: `record_project_lesson` com o que funcionou.
"""

REFINE_VISUAL_IDENTITY_BLOCK = """\
MODO REFINE VISUAL-IDENTITY (rh-10):
- PRÉ-LEITURA inclui `theme/visual-identity-index.css` (referência) — **NÃO chame tools**.
- No **primeiro turno de texto** emita **dois** blocos ```write```:
  1. `theme/tokens.css` — variáveis `--ravenna-*`
  2. `src/index.css` — `@import '../theme/tokens.css';` + layout Concierge Orbital
- PROIBIDO narrar arquivos ausentes. PROIBIDO App.tsx/Chat.tsx/package.json.
- Depois: `record_project_lesson` — o que aplicou na identidade.
"""

REFINE_GEMINI_SPACE_BLOCK = """\
MODO REFINE GEMINI-SPACE (rh-11):
- PRÉ-LEITURA: `theme/gemini-space-index.css`, `theme/gemini-space-chat-reference.tsx`, `src/components/Chat.tsx` — **NÃO chame read_file** se já injetado.
- **Paths relativos** ao projectRoot: `src/components/Chat.tsx` (NUNCA `ravenna-home/frontend/...`).
- No primeiro turno de texto emita **até 4** blocos ```write```:
  1. `theme/tokens.css`
  2. `src/index.css` — `@import` + CSS completo (≥ referência gemini-space-index.css)
  3. `src/components/Chat.tsx` — adaptar referência preservando `api`, `localStorage`, `conversation_id`
  4. `src/Layout.tsx` — AuthProvider + `.space-bg` + `.starfield` (sem Layout.css)
- PROIBIDO demo/stub, mensagens fake, import Chat.css, default export no Chat.
- Depois: `record_project_lesson`.
"""

REFINE_BACKEND_TESTS_BLOCK = """\
MODO REFINE BACKEND-TESTS (rh-12b-v2):
- PRÉ-LEITURA: `main.py`, `tests/test_health.py`, `tests/test_chat_reference.py` — **NÃO chame read_file** se já injetado.
- **main.py LOCK** — não write/patch em main.py.
- No **primeiro turno de texto** emita **exatamente 1** bloco ```write```:
  - `tests/test_chat.py` — adaptar `test_chat_reference.py` (≥3 `def test_`, TestClient, mock httpx/patch)
- Investigação: **máx 3 linhas**, depois o write. PROIBIDO npm/node/frontend.
- PROIBIDO narrar instalação pytest — pytest já existe no container.
- Depois: `record_project_lesson`.
"""

REFINE_CHAT_HISTORY_BLOCK = """\
MODO REFINE CHAT-HISTORY (rh-12c):
- PRÉ-LEITURA: `theme/gemini-space-chat-reference.tsx`, `src/components/Chat.tsx` — **NÃO chame read_file** se já injetado.
- **CSS, Layout, backend LOCK** — não write/patch fora de Chat.tsx.
- **Path relativo:** `src/components/Chat.tsx` (NUNCA `ravenna-home/frontend/...`).
- No **primeiro turno de texto** emita **exatamente 1** bloco ```write```:
  - `src/components/Chat.tsx` — adaptar referência Gemini preservando `api`, `localStorage`, `conversation_id`, collapse/histórico
- Investigação: **máx 3 linhas**, depois o write. PROIBIDO npm/node/backend/CSS.
- Depois: `record_project_lesson`.
"""

REFINE_CHAT_AUTONOMY_BLOCK = """\
MODO REFINE AUTONOMIA PURA (rh-12c-v2 — repair OFF, tools OFF):
- **Ferramentas desligadas** — read_file já foi injetado abaixo; NÃO chame tools.
- **1ª resposta = 1 bloco ```write src/components/Chat.tsx``` COMPLETO** (adaptar referência).
- PROIBIDO: Investigação longa, narrar plano, list_files, get_project_lessons antes do write.
- `export function Chat` (named export) — App importa `{ Chat }` de `./components`.
- Repair determinístico **desligado** — só conta se VOCÊ escrever nesta resposta.
- Depois do write: `record_project_lesson` numa linha.
"""

REFINE_CHAT_PATCH_D1_GOLDEN_BLOCK = """\
MODO MICRO-PATCH D1 GOLDEN (rh-12l-golden — 1 hunk, tools OFF, repair OFF):
- **Somente clearHistory** — NAO reescreva o arquivo.
- **Sua resposta inteira = SOMENTE 1 bloco ```patch src/components/Chat.tsx```** (zero texto fora).
  Copie o GOLDEN PATCH D1 abaixo **sem alterar uma linha**.
- PROIBIDO: ```write```, arrow component, narrativa.
"""

REFINE_CHAT_PATCH_D2_GOLDEN_BLOCK = """\
MODO MICRO-PATCH D2 GOLDEN (rh-12n-golden — 1 hunk, tools OFF, repair OFF):
- **Somente send** — NAO reescreva clearHistory/layout.
- **Sua resposta inteira = SOMENTE 1 bloco ```patch```** — copie GOLDEN PATCH D2 integralmente.
"""

REFINE_CHAT_PATCH_D1_BLOCK = """\
MODO MICRO-PATCH D1 (rh-12l — STRICT, 1 hunk, tools OFF, repair OFF):
- **Somente clearHistory** — adicione `setHistoryExpanded(false)` apos `setMessages([])`.
- **Fence obrigatorio:** ```patch src/components/Chat.tsx``` (NAO ravenna-ide, NAO ChatInputBar).
- **1 bloco patch somente** — unified diff, zero texto fora do fence.
- `export function Chat` / `function clearHistory` — NAO invente arrow component nem handleClearHistory.
"""

REFINE_CHAT_PATCH_D2_BLOCK = """\
MODO MICRO-PATCH D2 (rh-12m — STRICT, 1 hunk, tools OFF, repair OFF):
- **Somente send** — adicione `setHistoryExpanded(false)` apos `setMessage('')`.
- clearHistory ja corrigido — nao altere.
- **1 bloco ```patch``` somente** — contexto real do baseline d1.
"""

REFINE_CHAT_PATCH_D_BLOCK = """\
MODO REFINE PATCH D (rh-12j — autonomia SEM golden diff, tools OFF, repair OFF):
- **Chat.tsx ja tem layout Gemini completo** (patch A+B+C) — `export function Chat`, NAO arrow component.
- Adicione `setHistoryExpanded(false)` em `clearHistory` (apos setMessages) e em `send` (apos setMessage).
- **Sua resposta inteira = SOMENTE 1 bloco ```patch src/components/Chat.tsx```** (unified diff, zero texto fora).
- Use os trechos EXATOS abaixo no diff — contexto inventado (const Chat, setNewMessage) REJEITADO.
- Repair OFF — so conta se o patch aplicar no baseline patch-C.
"""

REFINE_CHAT_PATCH_C_BLOCK = """\
MODO REFINE PATCH C (rh-12h — 1 patch, tools OFF, repair OFF):
- **Chat.tsx ja tem pickCollapsedMessages + historyExpanded** — NAO reescreva o arquivo.
- **Sua resposta inteira = SOMENTE 1 bloco ```patch src/components/Chat.tsx```** (zero texto fora).
  Copie o GOLDEN PATCH C abaixo **sem alterar uma linha**.
- PROIBIDO: Investigacao, narrativa, npm, backend, CSS, fetch https externo.
- Repair OFF — so conta se VOCE emitir o patch e ele aplicar no disco.
"""

REFINE_CHAT_PATCH_B_BLOCK = """\
MODO REFINE PATCH B (rh-12g — 1 patch, tools OFF, repair OFF):
- **Chat.tsx ja tem pickCollapsedMessages** (baseline patch-A) — NAO reescreva o arquivo.
- **Sua resposta inteira = SOMENTE 1 bloco ```patch src/components/Chat.tsx```** (zero texto fora).
  Copie o GOLDEN PATCH B abaixo **sem alterar uma linha**.
- PROIBIDO: Investigacao, narrativa, npm, backend, CSS, fetch https externo.
- Repair OFF — so conta se VOCE emitir o patch e ele aplicar no disco.
"""

REFINE_CHAT_PATCH_A_BLOCK = """\
MODO REFINE PATCH A (rh-12f — 1 patch, tools OFF, repair OFF):
- **Scaffold ja tem api + historico** — NAO reescreva o arquivo.
- **Sua resposta inteira = SOMENTE 1 bloco ```patch src/components/Chat.tsx```** (zero texto fora).
  Copie o GOLDEN PATCH abaixo **sem alterar uma linha** (@@, ---, +++, pickCollapsedMessages).
- PROIBIDO: Investigacao, narrativa, npm, backend, CSS, fetch https externo, inventar imports/Message.
- Repair OFF — so conta se VOCE emitir o patch e ele aplicar no disco.
"""

REFINE_CHAT_PATCH_BLOCK = """\
MODO REFINE PATCH GEMINI (rh-12e — scaffold pronto, tools OFF):
- **Scaffold ja tem api + historico** — NAO reescreva tudo do zero.
- **1a resposta = 1 a 3 blocos ```patch src/components/Chat.tsx```** (unified diff).
  Patch A: funcao pickCollapsedMessages (copiar da referencia)
  Patch B: historyExpanded + logRef + useEffects scroll
  Patch C: return JSX gemini-chat + chat-input-dock
- Alternativa: 1 ```write src/components/Chat.tsx``` completo adaptando scaffold.
- PROIBIDO: Investigacao longa, npm, backend, CSS, fetch https externo.
- Repair OFF — so conta se VOCE aplicar patch/write nesta resposta.
"""

REFINE_DEFAULT_TOOL_TURNS = 2
REFINE_VISUAL_IDENTITY_TOOL_TURNS = 3


def resolve_delivery_mode(request_mode: str | None, spec: dict[str, Any] | None) -> str:
    clean = (request_mode or "auto").strip().lower()
    if clean not in {"auto", "refine", "full", "seed-only", "vistoria"}:
        clean = "auto"
    if clean != "auto":
        return clean
    ui = (spec or {}).get("ravennaHomeUiMode")
    if ui in {"voice-pwa", "space-chat", "visual-identity", "gemini-space", "backend-tests-only", "chat-history-gemini", "chat-history-autonomy", "chat-patch-gemini", "chat-patch-a-gemini", "chat-patch-b-gemini", "chat-patch-c-gemini", "chat-patch-d-gemini", "chat-patch-d1-gemini", "chat-patch-d2-gemini", "chat-patch-d1-strict-gemini", "chat-patch-d2-strict-gemini"}:
        return "refine"
    return "full"


def tools_allowlist_for_spec(spec: dict[str, Any] | None) -> list[str] | None:
    if not spec:
        return None
    if spec.get("ravennaHomeUiMode") in {"chat-history-autonomy", "chat-patch-gemini", "chat-patch-a-gemini", "chat-patch-b-gemini", "chat-patch-c-gemini", "chat-patch-d-gemini", "chat-patch-d1-gemini", "chat-patch-d2-gemini", "chat-patch-d1-strict-gemini", "chat-patch-d2-strict-gemini"}:
        return []
    explicit = spec.get("toolAllowlist")
    if explicit is not None:
        return list(explicit)
    mode = spec.get("deliveryMode")
    if mode == "vistoria":
        return list(DELIVERY_TOOLS_VISTORIA)
    if mode in {"refine", "seed-only"}:
        return list(DELIVERY_TOOLS_REFINE) if mode == "refine" else []
    if spec.get("ravennaHome") and spec.get("ravennaHomeUiMode") in {
        "voice-pwa",
        "space-chat",
        "visual-identity",
        "gemini-space",
        "backend-tests-only",
        "chat-history-gemini",
        "chat-history-autonomy",
        "chat-patch-gemini",
        "chat-patch-a-gemini",
        "chat-patch-b-gemini",
        "chat-patch-c-gemini",
        "chat-patch-d-gemini",
        "chat-patch-d1-gemini",
        "chat-patch-d2-gemini",
        "chat-patch-d1-strict-gemini",
        "chat-patch-d2-strict-gemini",
    }:
        return list(DELIVERY_TOOLS_REFINE)
    return None


def apply_delivery_settings(request: Any, spec: dict[str, Any]) -> str:
    """Aplica refine/seed-only ao request + spec. Retorna modo resolvido."""
    mode = resolve_delivery_mode(getattr(request, "delivery_mode", None), spec)
    spec["deliveryMode"] = mode

    if mode == "refine":
        if spec.get("ravennaHomeUiMode") in {"chat-history-autonomy", "chat-patch-gemini", "chat-patch-a-gemini", "chat-patch-b-gemini", "chat-patch-c-gemini", "chat-patch-d-gemini", "chat-patch-d1-gemini", "chat-patch-d2-gemini", "chat-patch-d1-strict-gemini", "chat-patch-d2-strict-gemini"}:
            spec["toolAllowlist"] = []
            spec["toolMaxTurns"] = 0
        else:
            spec["toolAllowlist"] = list(DELIVERY_TOOLS_REFINE)
            default_turns = (
                REFINE_VISUAL_IDENTITY_TOOL_TURNS
                if spec.get("ravennaHomeUiMode") in {"visual-identity", "gemini-space"}
                else REFINE_DEFAULT_TOOL_TURNS
            )
            spec["toolMaxTurns"] = int(getattr(request, "tool_max_turns", None) or default_turns)
        if getattr(request, "max_repair_attempts", 2) > 0:
            request.max_repair_attempts = 0
        request.run_checklist = False
    elif mode == "seed-only":
        spec["toolAllowlist"] = []
        request.max_repair_attempts = 0
        request.run_checklist = False
    elif mode == "vistoria":
        spec["toolAllowlist"] = list(DELIVERY_TOOLS_VISTORIA)
        spec["toolMaxTurns"] = int(getattr(request, "tool_max_turns", None) or 1)
        request.max_repair_attempts = 0
        request.run_checklist = False
        spec["requireGroundingTools"] = True
    elif mode == "full":
        if getattr(request, "tool_max_turns", None):
            spec["toolMaxTurns"] = int(request.tool_max_turns)

    if spec.get("ravennaHome") and mode in {"refine", "auto"}:
        if spec.get("ravennaHomeUiMode") not in {
            "chat-history-autonomy",
            "chat-patch-gemini",
            "chat-patch-a-gemini",
            "chat-patch-b-gemini",
            "chat-patch-c-gemini",
            "chat-patch-d-gemini",
            "chat-patch-d1-strict-gemini",
            "chat-patch-d2-strict-gemini",
        }:
            spec.setdefault("requireGroundingTools", True)

    return mode


def _frontend_root() -> Path:
    from learning_agent.core import workspace_bootstrap

    return workspace_bootstrap.ravenna_home_dir() / "frontend"


def _run_seed(ui_mode: str, root: Path, *, force: bool = True) -> list[str]:
    from learning_agent.core import ravenna_home_delivery

    if ui_mode == "voice-pwa":
        return ravenna_home_delivery.seed_voice_pwa_baseline(root, force=force)
    if ui_mode == "space-chat":
        return ravenna_home_delivery.seed_space_chat_baseline(root, force=force)
    return []


def seed_and_validate(spec: dict[str, Any], *, force: bool = True) -> dict[str, Any]:
    """Seed determinístico + validate_filesystem — fonte de verdade pré-LLM."""
    from learning_agent.core import ravenna_home_delivery

    ui_mode = spec.get("ravennaHomeUiMode")
    root = _frontend_root()
    seeded: list[str] = []
    if ui_mode == "visual-identity" and root.is_dir():
        scaffold = ravenna_home_delivery.seed_tokens_scaffold(root)
        if scaffold:
            seeded.append(scaffold)
    if ui_mode in {"voice-pwa", "space-chat"} and root.is_dir():
        seeded = _run_seed(ui_mode, root, force=force)
    failures = (
        ravenna_home_delivery.validate_filesystem(root, spec=spec)
        if root.is_dir()
        else ["projectRoot do frontend não encontrado."]
    )
    return {
        "root": str(root),
        "ui_mode": ui_mode,
        "seeded": seeded,
        "failures": failures,
        "ok": not failures,
    }


def try_seed_pass_short_circuit(
    request: Any,
    spec: dict[str, Any],
    delivery_mode: str,
) -> dict[str, Any] | None:
    """Se seed + validate passam, retorna payload de resposta sem LLM."""
    if delivery_mode == "full" or delivery_mode == "refine":
        return None
    if not spec.get("ravennaHome"):
        return None
    ui_mode = spec.get("ravennaHomeUiMode")
    if ui_mode not in {"voice-pwa", "space-chat"}:
        return None

    check = seed_and_validate(spec, force=True)
    if not check["ok"]:
        return None

    deploy: dict[str, Any] = {"skipped": True, "reason": "seed-pass — build omitido"}
    visual_failures: list[str] = []
    if spec.get("ravennaHomeDeploy") or ui_mode in {"voice-pwa", "space-chat"}:
        try:
            from learning_agent.core.ravenna_home_remote_ops import run_home_web_deploy

            deploy = run_home_web_deploy(preclean=False, fast_build=True)
        except Exception as exc:
            deploy = {"ok": False, "failures": [str(exc)], "buildSkipped": True}

    if deploy.get("ok"):
        try:
            import httpx
            from learning_agent.core import ravenna_home_delivery

            home_url = __import__("os").environ.get("RAVENNA_HOME_URL", "http://ravenna-vm:5174")
            html = httpx.get(home_url, timeout=20).text
            visual_failures = ravenna_home_delivery.validate_production_visual(
                html, home_url=home_url
            )
        except Exception as exc:
            visual_failures = [f"Check visual produção falhou: {exc}"]

    if visual_failures:
        return None

    reply = (
        f"### Entrega seed-pass ({ui_mode})\n"
        f"Baseline determinístico aplicado ({len(check['seeded'])} arquivos). "
        "validate_filesystem OK — sem chamada LLM.\n\n"
        f"Deploy: {'OK (up)' if deploy.get('ok') else deploy.get('failures', deploy)}\n\n"
        "Investigação/Diagnóstico/Solução: infra + GROUNDING; Ravenna refine CSS numa próxima "
        "rodada `delivery_mode=refine` se necessário."
    )
    applied = {
        "applied": True,
        "blockCount": len(check["seeded"]),
        "changedPaths": [p.replace("\\", "/") for p in check["seeded"]],
        "seedPass": True,
        "deploy": deploy,
    }
    autonomy = {
        "enabled": True,
        "passed": check["ok"],
        "seedPass": True,
        "deliveryMode": delivery_mode,
        "attempts": [{"phase": "seed-pass", "applied": applied, "passed": check["ok"]}],
        "finalReply": reply,
        "spec": spec,
    }
    return {
        "result": {
            "success": True,
            "reply": reply,
            "agent": "Ravenna",
            "model": "seed-pass",
        },
        "autonomy": autonomy,
    }


def build_refine_autonomy_message(
    message: str,
    spec: dict[str, Any],
    project_root: str | None,
) -> str:
    """Prompt enxuto para refine — grounding + pré-leitura, sem RAG/web."""
    from learning_agent.core import agent_spec_builder
    from learning_agent.core.workspace_bootstrap import (
        build_file_existence_grounding,
        preflight_read_file_messages,
        required_grounding_reads,
    )

    contract = agent_spec_builder.format_spec_for_prompt(spec)
    reads = spec.get("requiredGroundingReads") or required_grounding_reads(spec)
    grounding = build_file_existence_grounding(project_root or spec.get("projectRoot"))
    preflight = preflight_read_file_messages(project_root, paths=reads or None)
    preflight_text = preflight[0]["content"] if preflight else ""

    from learning_agent.core import ravenna_home_delivery

    blueprint = ravenna_home_delivery.blueprint_for_prompt(spec)
    ui_mode = spec.get("ravennaHomeUiMode")
    if ui_mode == "visual-identity":
        refine_block = REFINE_VISUAL_IDENTITY_BLOCK
    elif ui_mode == "gemini-space":
        refine_block = REFINE_GEMINI_SPACE_BLOCK
    elif ui_mode == "backend-tests-only":
        refine_block = REFINE_BACKEND_TESTS_BLOCK
    elif ui_mode == "chat-history-gemini":
        refine_block = REFINE_CHAT_HISTORY_BLOCK
    elif ui_mode == "chat-patch-d1-gemini":
        refine_block = REFINE_CHAT_PATCH_D1_GOLDEN_BLOCK
        golden = ravenna_home_delivery.build_chat_patch_d1_golden_diff()
        baseline = ravenna_home_delivery.build_chat_patch_c_baseline()
        if golden:
            refine_block += (
                "\n\nGOLDEN PATCH D1 (copie integralmente no 1o bloco ```patch```):\n"
                f"```patch src/components/Chat.tsx\n{golden.strip()}\n```"
            )
        if baseline:
            refine_block += (
                "\n\nBASELINE (patch-C — contexto do diff):\n"
                f"```tsx\n{baseline.strip()[:3500]}\n```"
            )
    elif ui_mode == "chat-patch-d2-gemini":
        refine_block = REFINE_CHAT_PATCH_D2_GOLDEN_BLOCK
        golden = ravenna_home_delivery.build_chat_patch_d2_golden_diff()
        baseline = ravenna_home_delivery.build_chat_patch_d1_baseline()
        if golden:
            refine_block += (
                "\n\nGOLDEN PATCH D2 (copie integralmente no 1o bloco ```patch```):\n"
                f"```patch src/components/Chat.tsx\n{golden.strip()}\n```"
            )
        if baseline:
            refine_block += (
                "\n\nBASELINE (patch-D1 — contexto do diff):\n"
                f"```tsx\n{baseline.strip()[:3500]}\n```"
            )
    elif ui_mode == "chat-patch-d1-strict-gemini":
        refine_block = REFINE_CHAT_PATCH_D1_BLOCK
        hint = ravenna_home_delivery.build_chat_patch_d1_context_hint()
        baseline = ravenna_home_delivery.build_chat_patch_c_baseline()
        if hint:
            refine_block += f"\n\n{hint.strip()}\n"
        if baseline:
            refine_block += (
                "\n\nBASELINE (patch-C — diff so em clearHistory):\n"
                f"```tsx\n{baseline.strip()[:4000]}\n```"
            )
    elif ui_mode == "chat-patch-d2-strict-gemini":
        refine_block = REFINE_CHAT_PATCH_D2_BLOCK
        hint = ravenna_home_delivery.build_chat_patch_d2_context_hint()
        baseline = ravenna_home_delivery.build_chat_patch_d1_baseline()
        if hint:
            refine_block += f"\n\n{hint.strip()}\n"
        if baseline:
            refine_block += (
                "\n\nBASELINE (patch-D1 — diff so em send):\n"
                f"```tsx\n{baseline.strip()[:4000]}\n```"
            )
    elif ui_mode == "chat-patch-d-gemini":
        refine_block = REFINE_CHAT_PATCH_D_BLOCK
        if spec.get("ravennaHomeStrictAutonomy"):
            refine_block += (
                "\n**STRICT (rh-12k):** Sem golden diff em reprompt — métrica = autonomia no 1º turno.\n"
            )
        hint = ravenna_home_delivery.build_chat_patch_d_context_hint()
        baseline = ravenna_home_delivery.build_chat_patch_c_baseline()
        if hint:
            refine_block += f"\n\n{hint.strip()}\n"
        if baseline:
            refine_block += (
                "\n\nBASELINE COMPLETO (patch-C — leia clearHistory/send antes do diff):\n"
                f"```tsx\n{baseline.strip()[:4500]}\n```"
            )
    elif ui_mode == "chat-patch-c-gemini":
        refine_block = REFINE_CHAT_PATCH_C_BLOCK
        golden = ravenna_home_delivery.build_chat_patch_c_golden_diff()
        baseline = ravenna_home_delivery.build_chat_patch_b_baseline()
        if golden:
            refine_block += (
                "\n\nGOLDEN PATCH C (copie integralmente no 1o bloco ```patch```):\n"
                f"```patch src/components/Chat.tsx\n{golden.strip()}\n```"
            )
        if baseline:
            refine_block += (
                "\n\nBASELINE ATUAL (patch-B — nao destrua api/historico/collapse):\n"
                f"```tsx\n{baseline.strip()[:2500]}\n```"
            )
    elif ui_mode == "chat-patch-b-gemini":
        refine_block = REFINE_CHAT_PATCH_B_BLOCK
        golden = ravenna_home_delivery.build_chat_patch_b_golden_diff()
        baseline = ravenna_home_delivery.build_chat_patch_a_baseline()
        if golden:
            refine_block += (
                "\n\nGOLDEN PATCH B (copie integralmente no 1o bloco ```patch```):\n"
                f"```patch src/components/Chat.tsx\n{golden.strip()}\n```"
            )
        if baseline:
            refine_block += (
                "\n\nBASELINE ATUAL (patch-A — nao destrua api/historico/pickCollapsedMessages):\n"
                f"```tsx\n{baseline.strip()[:3000]}\n```"
            )
    elif ui_mode == "chat-patch-a-gemini":
        refine_block = REFINE_CHAT_PATCH_A_BLOCK
        golden = ravenna_home_delivery.build_chat_patch_a_golden_diff()
        scaffold = ravenna_home_delivery.build_chat_patch_scaffold()
        if golden:
            refine_block += (
                "\n\nGOLDEN PATCH (copie integralmente no 1o bloco ```patch```):\n"
                f"```patch src/components/Chat.tsx\n{golden.strip()}\n```"
            )
        if scaffold:
            refine_block += (
                "\n\nSCAFFOLD ATUAL (contexto do diff — nao destrua api/historico):\n"
                f"```tsx\n{scaffold.strip()[:2500]}\n```"
            )
    elif ui_mode == "chat-patch-gemini":
        refine_block = REFINE_CHAT_PATCH_BLOCK
        chat_ref = ravenna_home_delivery.build_chat_history_bundle()
        scaffold = ravenna_home_delivery.build_chat_patch_scaffold()
        if chat_ref:
            refine_block += (
                "\n\nREFERENCIA Gemini (copie pickCollapsedMessages + return JSX):\n"
                f"```tsx\n{chat_ref.strip()[:6000]}\n```"
            )
        if scaffold:
            refine_block += (
                "\n\nSCAFFOLD ATUAL (nao destrua api/historico):\n"
                f"```tsx\n{scaffold.strip()[:4000]}\n```"
            )
    elif ui_mode == "chat-history-autonomy":
        refine_block = REFINE_CHAT_AUTONOMY_BLOCK
        chat_ref = ravenna_home_delivery.build_chat_history_bundle()
        if chat_ref:
            refine_block += (
                "\n\nREFERÊNCIA COMPLETA `gemini-space-chat-reference.tsx` "
                "(copie/adapte para `src/components/Chat.tsx`):\n"
                f"```tsx\n{chat_ref.strip()}\n```"
            )
    elif ui_mode == "space-chat" and "rh-14" in message.lower():
        refine_block = REFINE_RH14_FULLSCREEN_BLOCK
        try:
            ref_index = (
                Path(project_root or spec.get("projectRoot") or "")
                / "theme"
                / "gemini-space-index.css"
            )
            if ref_index.is_file():
                refine_block += (
                    "\n\nREFERÊNCIA CSS (base do write em index.css):\n"
                    f"```css\n{ref_index.read_text(encoding='utf-8')[:5000]}\n```"
                )
        except OSError:
            pass
    else:
        refine_block = REFINE_PROMPT_BLOCK

    parts = [
        message,
        refine_block,
        blueprint,
        grounding,
        preflight_text,
        contract,
    ]
    return "\n\n---\n\n".join(p for p in parts if p)


def build_deterministic_grounding_reply(
    violations: list[str],
    project_root: str | None,
    spec: dict[str, Any],
    *,
    original_message: str = "",
) -> str | None:
    """Substitui diagnóstico alucinado — em refine inclui ```write``` aplicável."""
    if not violations:
        return None
    from learning_agent.core import ravenna_home_delivery
    from learning_agent.core.workspace_bootstrap import build_file_existence_grounding

    grounding = build_file_existence_grounding(project_root or spec.get("projectRoot"))
    ui_mode = spec.get("ravennaHomeUiMode")
    delivery_mode = (spec.get("deliveryMode") or "full").strip().lower()
    issues = "\n".join(f"- {v}" for v in violations[:4])

    write_block = ""
    if delivery_mode == "refine" and ui_mode == "visual-identity":
        tokens, index = ravenna_home_delivery.build_visual_identity_css_bundle()
        write_block = (
            f"\n\n```write theme/tokens.css\n{tokens}\n```\n"
            f"```write src/index.css\n{index}\n```"
        )
    elif delivery_mode == "refine" and ui_mode == "gemini-space":
        tokens, index, chat = ravenna_home_delivery.build_gemini_space_bundle()
        write_block = (
            f"\n\n```write theme/tokens.css\n{tokens}\n```\n"
            f"```write src/index.css\n{index}\n```\n"
            f"```write src/components/Chat.tsx\n{chat}\n```"
        )
    elif delivery_mode == "refine" and ui_mode == "backend-tests-only":
        tests_body = ravenna_home_delivery.build_backend_tests_bundle()
        write_block = f"\n\n```write tests/test_chat.py\n{tests_body}\n```"
    elif delivery_mode == "refine" and ui_mode == "chat-history-gemini":
        chat_body = ravenna_home_delivery.build_chat_history_bundle()
        write_block = f"\n\n```write src/components/Chat.tsx\n{chat_body}\n```"
    elif delivery_mode == "refine" and ui_mode == "chat-history-autonomy":
        write_block = ""
    elif delivery_mode == "refine" and ui_mode == "space-chat" and "rh-14" in original_message.lower():
        tokens, index, _ = ravenna_home_delivery.build_gemini_space_bundle()
        write_block = (
            f"\n\n```write theme/tokens.css\n{tokens}\n```\n"
            f"```write src/index.css\n{index}\n```"
        )
    elif delivery_mode == "refine" and ui_mode in {"voice-pwa", "space-chat"}:
        css_body = ravenna_home_delivery._default_index_css()
        if ui_mode == "voice-pwa":
            css_body += ravenna_home_delivery._voice_pwa_css_extras()
        write_block = f"\n\n```write src/index.css\n{css_body}\n```"

    css_hint = (
        "CSS aplicado deterministicamente abaixo — deploy automático após apply."
        if write_block
        else "Emita ```write src/index.css``` com `.mic-button.pulse`, `.install-pwa-banner` e neon/espaço do rh-08."
    )

    return (
        "---\n"
        "### Investigação\n"
        "GROUNDING confirma arquivos no disco (baseline seedado). Diagnóstico 'ausente' REJEITADO.\n\n"
        "### Diagnóstico\n"
        f"{issues}\n\n"
        "### Solução\n"
        f"{css_hint}\n"
        f"{grounding}\n"
        f"{write_block}"
    )


def verify_seed_report(spec: dict[str, Any], *, force: bool = True) -> dict[str, Any]:
    """Relatório pós-seed para supervisor (P4)."""
    from learning_agent.core import ravenna_home_delivery

    check = seed_and_validate(spec, force=force)
    paths: list[str] = []
    root = Path(check["root"])
    css_bytes = 0
    min_css = ravenna_home_delivery.MIN_SOURCE_CSS_BYTES
    if root.is_dir():
        _, css_bytes = ravenna_home_delivery._read_css_chunks(root)
        for rel in (
            "src/components/Chat.tsx",
            "src/components/InstallPrompt.tsx",
            "public/manifest.webmanifest",
            "public/icon-192.png",
            "public/icon-512.png",
            "index.html",
            "package.json",
            "src/index.css",
        ):
            p = root / rel
            paths.append(f"{'OK' if p.is_file() else 'MISSING'} {rel}")
    return {
        "ok": check["ok"],
        "failures": check["failures"],
        "seeded_count": len(check["seeded"]),
        "paths": paths,
        "root": check["root"],
        "css_source_bytes": css_bytes,
        "visual_refine_pending": css_bytes < min_css if root.is_dir() else True,
    }


def build_vistoria_autonomy_message(
    message: str,
    spec: dict[str, Any],
    audit: dict[str, Any],
    project_root: str | None,
) -> str:
    """Prompt vistoria — evidências determinísticas + grounding."""
    from learning_agent.core import agent_spec_builder
    from learning_agent.core import ravenna_home_delivery
    from learning_agent.core.workspace_bootstrap import (
        build_file_existence_grounding,
        preflight_read_file_messages,
        required_grounding_reads,
    )

    contract = agent_spec_builder.format_spec_for_prompt(spec)
    reads = spec.get("requiredGroundingReads") or required_grounding_reads(spec)
    grounding = build_file_existence_grounding(project_root or spec.get("projectRoot"))
    preflight = preflight_read_file_messages(project_root, paths=reads or None)
    preflight_text = preflight[0]["content"] if preflight else ""
    report = ravenna_home_delivery.format_vistoria_report(audit, auditor="Ravenna")
    evidence_json = __import__("json").dumps(
        {
            "verdict": audit.get("verdict"),
            "gaps": audit.get("gaps"),
            "root_cause": audit.get("root_cause"),
            "evidence": audit.get("evidence"),
        },
        ensure_ascii=False,
        indent=2,
    )
    parts = [
        message,
        VISTORIA_PROMPT_BLOCK,
        f"EVIDÊNCIAS DETERMINÍSTICAS (fonte de verdade — não contradizer):\n```json\n{evidence_json}\n```",
        report,
        grounding,
        preflight_text,
        contract,
    ]
    return "\n\n---\n\n".join(p for p in parts if p)


def run_vistoria_delivery(
    request: Any,
    spec: dict[str, Any],
    *,
    narrate: bool = False,
) -> dict[str, Any]:
    """Vistoria 100% determinística; LLM opcional só para narrar."""
    from learning_agent.core import ravenna_home_delivery

    root = _frontend_root()
    audit = ravenna_home_delivery.run_visual_vistoria(
        root if root.is_dir() else None,
        spec=spec,
    )
    report = ravenna_home_delivery.format_vistoria_report(audit, auditor="Ravenna")
    return {
        "audit": audit,
        "report": report,
        "passed": audit.get("verdict") == "APROVADO",
        "narrate": narrate,
        "spec": spec,
        "root": str(root),
    }
