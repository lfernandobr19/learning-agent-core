"""Cliente LLM unificado — OpenAI-compatible (OpenAI, Ollama, Groq, etc.)."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from typing import Any

import httpx

from learning_agent.config import (
    AGENT_TOOL_MAX_TURNS,
    CHAT_API_BASE,
    CHAT_API_KEY,
    CHAT_MAX_TOKENS,
    CHAT_MODEL,
    CHAT_TEMPERATURE,
    CHAT_TIMEOUT_SECONDS,
    DEEPSEEK_API_BASE,
    DEEPSEEK_API_KEY,
    DEEPSEEK_MODEL,
    DEEPSEEK_MODEL_FAST,
    MAINTENANCE_API_BASE,
    MAINTENANCE_API_KEY,
    MAINTENANCE_MODE,
    MAINTENANCE_MODEL,
    TEACHER_API_BASE,
    TEACHER_API_KEY,
    TEACHER_MODEL,
)

_META_THINKING_RE = re.compile(
    r"(?i)(the user (is|wants)|user expectation|i(?:'|')ll draft|question:)",
)


# Chaves OpenAI-compat válidas em uma mensagem. Qualquer chave extra (ex.: "media",
# metadado interno da Ravenna) vaza para Groq/DeepSeek/Ollama e causa 400 em APIs
# estritas (Groq rejeita "property 'media' is unsupported").
_ALLOWED_MSG_KEYS = {"role", "content", "name", "tool_calls", "tool_call_id", "function_call"}


def _sanitize_messages_for_api(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove chaves não-OpenAI das mensagens antes de enviar ao provedor."""
    cleaned: list[dict[str, Any]] = []
    for msg in messages:
        if not isinstance(msg, dict):
            cleaned.append(msg)
            continue
        kept = {k: v for k, v in msg.items() if k in _ALLOWED_MSG_KEYS}
        if "role" in kept:
            cleaned.append(kept)
        else:
            # Sem role não é uma mensagem válida; preserva o que der.
            cleaned.append(msg)
    return cleaned


def _extract_assistant_text(msg: dict[str, Any]) -> str:
    content = msg.get("content")
    if isinstance(content, str) and content.strip():
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str) and block.strip():
                parts.append(block.strip())
            elif isinstance(block, dict):
                text = block.get("text") or block.get("content")
                if isinstance(text, str) and text.strip():
                    parts.append(text.strip())
        joined = "\n".join(parts).strip()
        if joined:
            return joined
    for key in ("reasoning", "thinking"):
        alt = msg.get(key)
        if not isinstance(alt, str) or not alt.strip():
            continue
        if _META_THINKING_RE.search(alt):
            continue
        return alt.strip()
    raise ValueError("Resposta do modelo sem conteúdo textual")


def chat_complete(
    messages: list[dict[str, str]],
    *,
    base_url: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> str:
    url_base = (base_url or CHAT_API_BASE).rstrip("/")
    key = api_key if api_key is not None else CHAT_API_KEY
    mdl = model or CHAT_MODEL
    temp = temperature if temperature is not None else CHAT_TEMPERATURE

    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"

    payload: dict[str, Any] = {
        "model": mdl,
        "messages": _sanitize_messages_for_api(messages),
        "temperature": temp,
    }
    if mdl and "gemma4" in mdl.lower():
        payload["think"] = False
    # DeepSeek V4: thinking desabilitado por padrão em chat (menos tokens/latência;
    # reasoning_content é descartado pelo nosso extractor). Agente/raciocínio pode
    # habilitar explicitamente via thinking={"type": "enabled"}.
    if mdl and mdl.lower().startswith("deepseek-v4-"):
        payload["thinking"] = {"type": "disabled"}
    tokens = max_tokens if max_tokens is not None else CHAT_MAX_TOKENS
    if tokens > 0:
        payload["max_tokens"] = tokens

    # Conexão rápida — se Vast/Ollama offline, cai pro Groq em ~15s (não 600s)
    timeout = httpx.Timeout(15.0, read=float(CHAT_TIMEOUT_SECONDS))
    with httpx.Client(timeout=timeout) as client:
        response = client.post(f"{url_base}/chat/completions", json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()

    return _extract_assistant_text(data["choices"][0]["message"])


# Groq retirou llama-3.3-70b-versatile em 16/08/2026; tentamos sucessor + modelos vivos.
_TEACHER_FALLBACK_MODELS = (
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
    "llama-3.1-8b-instant",
)


_DEAD_TEACHER_MODELS = {
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
}


def _teacher_models(preferred: str | None = None) -> list[str]:
    ordered: list[str] = []
    for name in (preferred, TEACHER_MODEL, *_TEACHER_FALLBACK_MODELS):
        clean = (name or "").strip()
        if not clean or clean in _DEAD_TEACHER_MODELS or clean in ordered:
            continue
        ordered.append(clean)
    return ordered


def is_maintenance_configured() -> bool:
    return bool(MAINTENANCE_API_KEY) and bool(MAINTENANCE_API_BASE) and bool(MAINTENANCE_MODEL)


def is_deepseek_configured() -> bool:
    return bool(DEEPSEEK_API_KEY) and bool(DEEPSEEK_API_BASE) and bool(DEEPSEEK_MODEL)


def is_groq_configured() -> bool:
    return bool(TEACHER_API_KEY) and bool(TEACHER_API_BASE) and bool(TEACHER_MODEL)


def normalize_engine(engine: str | None) -> str:
    """Contrato IDE v1: groq | deepseek_pro (default groq)."""
    raw = (engine or "groq").strip().lower().replace("-", "_")
    if raw in {"deepseek", "deepseek_pro", "maintenance", "deepseek_v4_pro"}:
        return "deepseek_pro"
    if raw in {"groq", "teacher", "gpt_oss", "gpt_oss_120b"}:
        return "groq"
    return "groq"


def engines_status() -> dict[str, Any]:
    """Status seguro dos motores selecionáveis na IDE (sem keys)."""
    return {
        "groq": {
            "id": "groq",
            "label": "Groq (gpt-oss-120b)",
            "model": TEACHER_MODEL,
            "configured": is_groq_configured(),
            "reachable": None,
        },
        "deepseek_pro": {
            "id": "deepseek_pro",
            "label": "DeepSeek V4 Pro",
            "model": DEEPSEEK_MODEL,
            "configured": bool(DEEPSEEK_API_KEY) and bool(DEEPSEEK_MODEL),
            "reachable": None,
        },
        "deepseek_flash": {
            "id": "deepseek_flash",
            "label": "DeepSeek V4 Flash",
            "model": DEEPSEEK_MODEL_FAST,
            "configured": bool(DEEPSEEK_API_KEY) and bool(DEEPSEEK_MODEL_FAST),
            "reachable": None,
        },
    }


def maintenance_status() -> dict[str, Any]:
    """Status seguro (sem key) para /health e playbooks."""
    return {
        "maintenance_mode": MAINTENANCE_MODE,
        "maintenance_configured": is_maintenance_configured(),
        "maintenance_model": MAINTENANCE_MODEL,
        "maintenance_api_base": MAINTENANCE_API_BASE if is_maintenance_configured() else "",
    }


def chat_for_engine(
    messages: list[dict[str, str]],
    *,
    engine: str | None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> tuple[str, str]:
    """Rota explícita por engine (UI seletor). Persona/system já vêm em messages."""
    eng = normalize_engine(engine)
    if eng == "deepseek_pro":
        if not is_deepseek_configured():
            raise RuntimeError("DeepSeek V4 Pro não configurado (DEEPSEEK_API_KEY)")
        reply = chat_complete(
            messages,
            base_url=DEEPSEEK_API_BASE,
            api_key=DEEPSEEK_API_KEY,
            model=DEEPSEEK_MODEL,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return reply, DEEPSEEK_MODEL
    return _try_teacher_chain(messages, temperature=temperature, max_tokens=max_tokens)


def stream_for_engine(
    messages: list[dict[str, str]],
    *,
    engine: str | None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> tuple[Iterator[str], str]:
    eng = normalize_engine(engine)
    if eng == "deepseek_pro":
        if not is_deepseek_configured():
            raise RuntimeError("DeepSeek V4 Pro não configurado (DEEPSEEK_API_KEY)")
        return (
            chat_complete_stream(
                messages,
                base_url=DEEPSEEK_API_BASE,
                api_key=DEEPSEEK_API_KEY,
                model=DEEPSEEK_MODEL,
                temperature=temperature,
                max_tokens=max_tokens,
            ),
            DEEPSEEK_MODEL,
        )
    if not is_groq_configured():
        raise RuntimeError("Groq não configurado (TEACHER_API_KEY)")
    return (
        chat_complete_stream(
            messages,
            base_url=TEACHER_API_BASE,
            api_key=TEACHER_API_KEY,
            model=TEACHER_MODEL,
            temperature=temperature,
            max_tokens=max_tokens,
        ),
        TEACHER_MODEL,
    )


def _try_maintenance(
    messages: list[dict[str, str]],
    *,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> tuple[str, str]:
    if not is_maintenance_configured():
        raise RuntimeError("maintenance LLM não configurado")
    reply = chat_complete(
        messages,
        base_url=MAINTENANCE_API_BASE,
        api_key=MAINTENANCE_API_KEY,
        model=MAINTENANCE_MODEL,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return reply, MAINTENANCE_MODEL


def _try_teacher_chain(
    messages: list[dict[str, str]],
    *,
    temperature: float | None = None,
    max_tokens: int | None = None,
    preferred: str | None = None,
) -> tuple[str, str]:
    if not TEACHER_API_KEY:
        raise RuntimeError("teacher API não configurada")
    last_exc: Exception | None = None
    for teacher_model in _teacher_models(preferred):
        try:
            reply = chat_complete(
                messages,
                base_url=TEACHER_API_BASE,
                api_key=TEACHER_API_KEY,
                model=teacher_model,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return reply, teacher_model
        except Exception as teacher_exc:
            last_exc = teacher_exc
            continue
    if last_exc:
        raise last_exc
    raise RuntimeError("nenhum teacher model disponível")


def chat_with_fallback(
    messages: list[dict[str, str]],
    temperature: float | None = None,
    max_tokens: int | None = None,
    model: str | None = None,
) -> tuple[str, str]:
    """CHAT local → cloud. MAINTENANCE_MODE: DeepSeek primeiro; senão Groq → DeepSeek."""
    mdl = model or CHAT_MODEL

    if MAINTENANCE_MODE and is_maintenance_configured():
        try:
            return _try_maintenance(messages, temperature=temperature, max_tokens=max_tokens)
        except Exception:
            # Manutenção explícita: ainda tenta local + teacher se DeepSeek falhar
            pass

    try:
        return chat_complete(messages, model=mdl, temperature=temperature, max_tokens=max_tokens), mdl
    except Exception as student_exc:
        last_exc: Exception = student_exc
        if not MAINTENANCE_MODE and TEACHER_API_KEY:
            try:
                return _try_teacher_chain(
                    messages, temperature=temperature, max_tokens=max_tokens
                )
            except Exception as teacher_exc:
                last_exc = teacher_exc
        if is_maintenance_configured():
            try:
                return _try_maintenance(messages, temperature=temperature, max_tokens=max_tokens)
            except Exception as maint_exc:
                last_exc = maint_exc
        if MAINTENANCE_MODE and TEACHER_API_KEY:
            try:
                return _try_teacher_chain(
                    messages, temperature=temperature, max_tokens=max_tokens
                )
            except Exception as teacher_exc:
                last_exc = teacher_exc
        raise last_exc from student_exc


def _chat_completion_message(
    messages: list[dict[str, Any]],
    *,
    base_url: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    tools: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    url_base = (base_url or CHAT_API_BASE).rstrip("/")
    key = api_key if api_key is not None else CHAT_API_KEY
    mdl = model or CHAT_MODEL
    temp = temperature if temperature is not None else CHAT_TEMPERATURE
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    payload: dict[str, Any] = {
        "model": mdl,
        "messages": messages,
        "temperature": temp,
    }
    if mdl and "gemma4" in mdl.lower():
        payload["think"] = False
    if tools:
        payload["tools"] = tools
    tokens = max_tokens if max_tokens is not None else CHAT_MAX_TOKENS
    if tokens > 0:
        payload["max_tokens"] = tokens
    timeout = httpx.Timeout(15.0, read=float(CHAT_TIMEOUT_SECONDS))
    with httpx.Client(timeout=timeout) as client:
        response = client.post(f"{url_base}/chat/completions", json=payload, headers=headers)
        response.raise_for_status()
        return response.json()["choices"][0]["message"]


def _normalize_tool_calls(message: dict[str, Any]) -> list[dict[str, Any]]:
    raw = message.get("tool_calls") or []
    if not raw and message.get("tool_calls") is None:
        # Ollama legacy: single tool_call field
        single = message.get("tool_call")
        if single:
            raw = [single]
    return raw if isinstance(raw, list) else []


def chat_with_tools_loop(
    messages: list[dict[str, str]],
    *,
    temperature: float | None = None,
    max_tokens: int | None = None,
    model: str | None = None,
    max_turns: int | None = None,
    project_root: str | None = None,
    require_read_grounding: bool = False,
    required_read_paths: list[str] | None = None,
    tool_allowlist: list[str] | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
) -> tuple[str, str, list[dict[str, Any]]]:
    """Loop agente: tool_calls → executa → reenvia até resposta final."""
    from learning_agent.core import agent_tools

    mdl = model or CHAT_MODEL
    turns = max_turns if max_turns is not None else AGENT_TOOL_MAX_TURNS
    allow_token = agent_tools.set_tool_allowlist(tool_allowlist)
    working: list[dict[str, Any]] = [dict(m) for m in messages]
    tools = agent_tools.openai_tool_schemas(allowlist=tool_allowlist)
    if not tools:
        try:
            msg = chat_complete(
                working,
                temperature=temperature,
                max_tokens=max_tokens,
                model=mdl,
                base_url=base_url,
                api_key=api_key,
            )
            return _extract_assistant_text(msg), mdl, []
        finally:
            agent_tools.reset_tool_allowlist(allow_token)
    preflight_injected = False
    if require_read_grounding and project_root:
        from learning_agent.core.workspace_bootstrap import preflight_read_file_messages

        working.extend(preflight_read_file_messages(project_root, paths=required_read_paths))
        preflight_injected = True
    tool_log: list[dict[str, Any]] = []
    root_token = agent_tools.set_tool_project_root(project_root)
    forced_read_retries = 0
    required_reads = list(required_read_paths or [])
    if require_read_grounding and not required_reads:
        required_reads = ["package.json", "src/components/Chat.tsx"]

    def _read_paths_satisfied() -> bool:
        if preflight_injected:
            return True
        if not required_reads:
            return any(item.get("tool") == "read_file" for item in tool_log)
        read_args = [
            str((item.get("arguments") or {}).get("path", "")).replace("\\", "/").lower()
            for item in tool_log
            if item.get("tool") == "read_file"
        ]
        for rel in required_reads:
            rel_norm = rel.replace("\\", "/").lower()
            if not any(rel_norm in p or p.endswith(rel_norm.split("/")[-1]) for p in read_args):
                return False
        return True

    try:
        for _ in range(max(1, turns)):
            msg = _chat_completion_message(
                working,
                model=mdl,
                temperature=temperature,
                max_tokens=max_tokens,
                tools=tools,
                base_url=base_url,
                api_key=api_key,
            )
            tool_calls = _normalize_tool_calls(msg)
            content = msg.get("content")
            if isinstance(content, str) and content.strip() and not tool_calls:
                if (
                    require_read_grounding
                    and forced_read_retries < 3
                    and not _read_paths_satisfied()
                ):
                    forced_read_retries += 1
                    missing = ", ".join(required_reads) if required_reads else "package.json, Chat.tsx"
                    working.append(
                        {
                            "role": "user",
                            "content": (
                                "Pare. Antes de concluir Investigação/Diagnóstico, chame read_file "
                                f"em: {missing} (paths do GROUNDING)."
                            ),
                        }
                    )
                    continue
                return content.strip(), mdl, tool_log
            if not tool_calls:
                try:
                    return _extract_assistant_text(msg), mdl, tool_log
                except ValueError:
                    return "", mdl, tool_log

            assistant_msg: dict[str, Any] = {"role": "assistant", "content": content or ""}
            if tool_calls:
                assistant_msg["tool_calls"] = tool_calls
            working.append(assistant_msg)

            for tc in tool_calls:
                fn = tc.get("function") or {}
                name = fn.get("name") or tc.get("name") or ""
                args = agent_tools.parse_tool_arguments(fn.get("arguments"))
                result = agent_tools.execute_tool(name, args)
                tool_log.append(
                    {
                        "tool": name,
                        "arguments": args,
                        "result": result,
                        "result_preview": result[:600],
                    }
                )
                tool_msg: dict[str, Any] = {"role": "tool", "content": result}
                if tc.get("id"):
                    tool_msg["tool_call_id"] = tc["id"]
                if name:
                    tool_msg["name"] = name
                working.append(tool_msg)
    finally:
        agent_tools.reset_tool_project_root(root_token)
        agent_tools.reset_tool_allowlist(allow_token)

    return (
        "Limite de turnos de ferramentas atingido. Resuma Investigação, Diagnóstico e Solução com o que coletou.",
        mdl,
        tool_log,
    )


def is_chat_configured() -> bool:
    return bool(CHAT_MODEL) and bool(CHAT_API_BASE)


def chat_complete_stream(
    messages: list[dict[str, str]],
    *,
    base_url: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> Iterator[str]:
    """Stream de tokens OpenAI-compatible (Ollama, Groq, etc.)."""
    url_base = (base_url or CHAT_API_BASE).rstrip("/")
    key = api_key if api_key is not None else CHAT_API_KEY
    mdl = model or CHAT_MODEL
    temp = temperature if temperature is not None else CHAT_TEMPERATURE
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    payload: dict[str, Any] = {
        "model": mdl,
        "messages": _sanitize_messages_for_api(messages),
        "temperature": temp,
        "stream": True,
    }
    if mdl and "gemma4" in mdl.lower():
        payload["think"] = False
    if mdl and mdl.lower().startswith("deepseek-v4-"):
        payload["thinking"] = {"type": "disabled"}
    tokens = max_tokens if max_tokens is not None else CHAT_MAX_TOKENS
    if tokens > 0:
        payload["max_tokens"] = tokens

    timeout = httpx.Timeout(15.0, read=float(CHAT_TIMEOUT_SECONDS))
    with httpx.Client(timeout=timeout) as client, client.stream(
        "POST",
        f"{url_base}/chat/completions",
        json=payload,
        headers=headers,
    ) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            if not line or not line.startswith("data: "):
                continue
            data = line[6:].strip()
            if data == "[DONE]":
                break
            try:
                chunk = json.loads(data)
            except json.JSONDecodeError:
                continue
            delta = chunk.get("choices", [{}])[0].get("delta", {}).get("content")
            if isinstance(delta, str) and delta:
                yield delta


class FallbackStream:
    """Stream: local → teacher; MAINTENANCE_MODE prioriza DeepSeek; terciário se cloud falhar."""

    def __init__(
        self,
        messages: list[dict[str, str]],
        *,
        model: str,
        temperature: float | None,
        max_tokens: int | None,
    ) -> None:
        self.messages = messages
        self.model_name = model
        self.temperature = temperature
        self.max_tokens = max_tokens

    def __iter__(self) -> Iterator[str]:
        if MAINTENANCE_MODE and is_maintenance_configured():
            try:
                self.model_name = MAINTENANCE_MODEL
                yield from chat_complete_stream(
                    self.messages,
                    base_url=MAINTENANCE_API_BASE,
                    api_key=MAINTENANCE_API_KEY,
                    model=MAINTENANCE_MODEL,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                )
                return
            except Exception:
                pass

        try:
            yield from chat_complete_stream(
                self.messages,
                model=self.model_name,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )
            return
        except Exception as student_exc:
            cloud_exc: Exception = student_exc
            if TEACHER_API_KEY and not MAINTENANCE_MODE:
                try:
                    self.model_name = TEACHER_MODEL
                    yield from chat_complete_stream(
                        self.messages,
                        base_url=TEACHER_API_BASE,
                        api_key=TEACHER_API_KEY,
                        model=TEACHER_MODEL,
                        temperature=self.temperature,
                        max_tokens=self.max_tokens,
                    )
                    return
                except Exception as teacher_exc:
                    cloud_exc = teacher_exc
            if is_maintenance_configured():
                try:
                    self.model_name = MAINTENANCE_MODEL
                    yield from chat_complete_stream(
                        self.messages,
                        base_url=MAINTENANCE_API_BASE,
                        api_key=MAINTENANCE_API_KEY,
                        model=MAINTENANCE_MODEL,
                        temperature=self.temperature,
                        max_tokens=self.max_tokens,
                    )
                    return
                except Exception as maint_exc:
                    cloud_exc = maint_exc
            if TEACHER_API_KEY and MAINTENANCE_MODE:
                try:
                    self.model_name = TEACHER_MODEL
                    yield from chat_complete_stream(
                        self.messages,
                        base_url=TEACHER_API_BASE,
                        api_key=TEACHER_API_KEY,
                        model=TEACHER_MODEL,
                        temperature=self.temperature,
                        max_tokens=self.max_tokens,
                    )
                    return
                except Exception as teacher_exc:
                    cloud_exc = teacher_exc
            raise cloud_exc


def chat_stream_with_fallback(
    messages: list[dict[str, str]],
    temperature: float | None = None,
    max_tokens: int | None = None,
    model: str | None = None,
) -> FallbackStream:
    """Stream com fallback para teacher API (fallback na iteração, não só na abertura)."""
    mdl = model or CHAT_MODEL
    return FallbackStream(messages, model=mdl, temperature=temperature, max_tokens=max_tokens)
