"""Bot Telegram — conversa completa com a Ravenna no celular."""

from __future__ import annotations

import atexit
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import httpx

from learning_agent.config import (
    API_HOST,
    API_PORT,
    PROJECT_ROOT,
    RAVENNA_API_BASE,
    TELEGRAM_ALLOWED_USERS,
    TELEGRAM_BOT_TOKEN,
)
from learning_agent.core import active_learning, chat, context, progress
from learning_agent.core import finance_status
from learning_agent.core import finance_training_directives
from learning_agent.core import cursor_agent_bridge

TELEGRAM_CHANNEL = "telegram"
MAX_MSG_LEN = 4000
_CURSOR_PENDING = "__CURSOR_ASYNC__"
_CURSOR_TARGET_PENDING = "__CURSOR_TARGET__:"
_GPS_REQUEST = "__GPS_KEYBOARD__"
_LOCATION_BUTTON_TEXTS = frozenset(
    {
        "📍 Enviar GPS do celular",
        "Enviar GPS do celular",
        "📍 Enviar localização",
    }
)
_PID_FILE = PROJECT_ROOT / "data" / "scheduled" / "telegram_bot.pid"
_UPDATE_EXECUTOR = ThreadPoolExecutor(max_workers=3, thread_name_prefix="tg-update")


def _assert_single_instance() -> None:
    """Evita duas instancias competindo no getUpdates."""
    _PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    my_pid = os.getpid()
    if _PID_FILE.is_file():
        try:
            old = int(_PID_FILE.read_text(encoding="ascii").strip())
        except ValueError:
            old = 0
        if old and old != my_pid:
            try:
                import psutil

                if psutil.pid_exists(old):
                    cmd = " ".join(psutil.Process(old).cmdline())
                    if "telegram_bot" in cmd:
                        raise SystemExit(f"Bot Telegram ja ativo (PID {old}). Use run-telegram-bot.ps1 -Stop")
            except ImportError:
                pass
    _PID_FILE.write_text(str(my_pid), encoding="ascii")

    def _cleanup() -> None:
        if _PID_FILE.is_file() and _PID_FILE.read_text(encoding="ascii").strip() == str(my_pid):
            _PID_FILE.unlink(missing_ok=True)

    atexit.register(_cleanup)


def _api_base() -> str:
    if RAVENNA_API_BASE:
        return RAVENNA_API_BASE
    return f"http://{API_HOST}:{API_PORT}"


def _chat_reply_remote(message: str, user_id: str, *, context: str = "") -> str:
    """Chat via API remota (VM) — mesma memória/LLM da IDE."""
    payload = {
        "message": message,
        "mode": "chat",
        "model_size": "auto",
        "channel": TELEGRAM_CHANNEL,
        "user_id": user_id,
        "persist_history": True,
    }
    if context.strip():
        payload["context"] = context.strip()
    with httpx.Client(timeout=120.0) as client:
        r = client.post(f"{_api_base()}/api/chat", json=payload)
        r.raise_for_status()
        data = r.json()
    text = (data.get("message") or "").strip()
    if not text:
        raise ValueError(data.get("reasoning") or "Resposta vazia da API")
    agent = data.get("agent") or "Ravenna"
    model = (data.get("reasoning") or "").replace("Modelo: ", "").strip() or "vm"
    return f"{text}\n\n— {agent} ({model})"


def _allowed(user_id: int | None) -> bool:
    if user_id is None:
        return False
    if not TELEGRAM_ALLOWED_USERS:
        return True
    return user_id in TELEGRAM_ALLOWED_USERS


def _send_message(chat_id: int, text: str, *, reply_markup: dict[str, Any] | None = None) -> None:
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    chunks = [text[i : i + MAX_MSG_LEN] for i in range(0, len(text), MAX_MSG_LEN)] or [""]
    with httpx.Client(timeout=60.0) as client:
        for i, chunk in enumerate(chunks):
            payload: dict[str, Any] = {"chat_id": chat_id, "text": chunk}
            if reply_markup and i == len(chunks) - 1:
                payload["reply_markup"] = reply_markup
            client.post(url, json=payload)


def _send_gps_request(chat_id: int) -> None:
    """Teclado nativo do Telegram — lê GPS real do celular (não é pin no mapa)."""
    _send_message(
        chat_id,
        "Toque no botão abaixo — o Telegram pede permissão e envia o GPS "
        "do seu celular (coordenadas reais).\n\n"
        "Para GPS contínuo enquanto se move:\n"
        "📎 → Localização → Compartilhar ao vivo",
        reply_markup={
            "keyboard": [[{"text": "📍 Enviar GPS do celular", "request_location": True}]],
            "resize_keyboard": True,
            "one_time_keyboard": True,
        },
    )


def _is_gps_message(message: dict[str, Any]) -> bool:
    """Mensagem cujo payload principal é localização (pin, botão GPS ou ao vivo)."""
    if not message.get("location"):
        return False
    text = (message.get("text") or "").strip()
    if not text:
        return True
    return text in _LOCATION_BUTTON_TEXTS


def _remove_keyboard(chat_id: int, text: str = "GPS recebido.") -> None:
    _send_message(
        chat_id,
        text,
        reply_markup={"remove_keyboard": True},
    )


def _send_typing(chat_id: int) -> None:
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendChatAction"
    with httpx.Client(timeout=10.0) as client:
        client.post(url, json={"chat_id": chat_id, "action": "typing"})


def handle_command(command: str, args: str, user_id: str) -> str:
    cmd = command.lower().split("@", 1)[0]
    if cmd in ("/start", "/help"):
        from learning_agent.core import chat as chat_core

        return (
            f"{chat_core.greeting_for_channel(TELEGRAM_CHANNEL)}\n\n"
            "Converse comigo em texto livre — respondo como engenheira.\n\n"
            "Comandos:\n"
            "/status — progresso geral\n"
            "/finance — andamento e nivel finance-lead (Prove + qualidade)\n"
            "/decision — decisoes paper (ou responda ao alerta: sim/registrar)\n"
            "/portfolio — carteira paper (caixa + posicoes)\n"
            "/performance — PnL paper + graduação live\n"
            "/apply — aplicar sugestoes recentes de treino (motor local)\n"
            "/directives — fila de diretivas de treino\n"
            "/cursor <pergunta> — consultar agente Cursor no repo (resposta real)\n"
            "/cursor reset — nova sessao Cursor\n"
            "/web <pergunta> — busca na web (DuckDuckGo, resposta rapida)\n"
            "/location — local e fuso configurados (motor Ravenna)\n"
            "/casa <endereco> — salvar endereco base (geolocalizacao)\n"
            "/endereco — endereco/localizacao atual (GPS ou .env)\n"
            "/gps — botao para enviar GPS do celular (1 toque)\n"
            "📎 Localizacao ao vivo — GPS continuo do celular (Telegram)\n"
            "/perto [tipo] — mercado/farmacia/etc. perto (OpenStreetMap)\n"
            "🎤 mensagem de voz — transcrevo e respondo (Whisper/Groq)\n"
            "/context <tarefa> — dados do contexto\n"
            "/search <query> — busca no conhecimento\n"
            "/learn — active learning\n"
            "/reset — limpar histórico do chat"
        )
    if cmd == "/reset":
        chat.clear_history(TELEGRAM_CHANNEL, user_id)
        return "Histórico limpo. Podemos começar de novo."
    if cmd == "/finance":
        return finance_status.format_finance_telegram_message(fast=True)
    if cmd == "/portfolio":
        from learning_agent.core import finance_decision_loop

        return finance_decision_loop.format_paper_portfolio()
    if cmd == "/performance":
        from learning_agent.core import finance_paper_performance

        return finance_paper_performance.format_performance_telegram()
    if cmd == "/decision":
        from learning_agent.core import finance_decision_loop

        parts = args.split()
        if not parts:
            return finance_decision_loop.format_pending_telegram()
        sub = parts[0].lower()
        if sub in {"approve", "register"} and len(parts) >= 2:
            ref = parts[1].lstrip("#")
            result = finance_decision_loop.approve_decision(ref, mode=sub)
            if result.get("success"):
                seq = result.get("seq")
                label = f"#{seq}" if seq else ref
                return (
                    f"OK — {sub} {label}\n"
                    f"Portfolio atualizado: {result.get('portfolio_updated')}\n"
                    f"Trades no journal: {result.get('journal_trades')}"
                )
            return f"Falhou: {result.get('error', 'erro')}"
        return "Uso: /decision | /decision approve <#> | /decision register <#>"
    if cmd == "/apply":
        result = finance_training_directives.apply_from_chat(
            TELEGRAM_CHANNEL, user_id, user_message=f"/apply {args}".strip()
        )
        return finance_training_directives.format_apply_reply(result)
    if cmd == "/directives":
        return finance_training_directives.format_directives_message()
    if cmd == "/cursor":
        from learning_agent.core import cursor_targets

        raw = args.strip()
        low = raw.lower()
        if low in {"reset", "new"}:
            cursor_agent_bridge.reset_session(user_id)
            return "Sessão Cursor reiniciada. Use /cursor <pergunta>."
        if low in {"", "help", "targets", "canais"}:
            if low in {"targets", "canais"}:
                return cursor_targets.format_targets_help()
            hint = cursor_agent_bridge.configuration_hint()
            base = (
                "Consulta o agente Cursor no repositório (resposta real).\n"
                "Uso: /cursor <pergunta>\n"
                "/cursor reset — nova sessão\n"
                "/cursor targets — canais nomeados (ex.: teatrinho)\n"
                "/cursor bind <nome> current — liga canal à sessão atual\n"
                "/cursor @<nome>: <msg> — notifica canal\n\n"
                "Ou diga: «fala com o cursor: …»"
            )
            if low == "":
                return f"{base}\n\n{hint}" if hint and not cursor_agent_bridge.is_configured() else base
            return cursor_targets.format_targets_help()
        if low.startswith("bind "):
            parts = raw.split(maxsplit=2)
            if len(parts) < 3:
                return "Uso: /cursor bind <nome> current | /cursor bind <nome> <agent_id>"
            name, rest = parts[1], parts[2].strip()
            if rest.lower() == "current":
                result = cursor_targets.bind_target(
                    name, bind_current_session_user_id=user_id
                )
            else:
                result = cursor_targets.bind_target(name, agent_id=rest)
            if not result.get("ok"):
                return f"Bind falhou: {result.get('error')}"
            return (
                f"Canal `{result['name']}` ligado ao agent "
                f"`{str(result.get('agent_id', ''))[:16]}…`.\n"
                f"Notifique com: /cursor @{result['name']}: <mensagem>"
            )
        if low.startswith("unbind "):
            name = raw.split(maxsplit=1)[1].strip()
            result = cursor_targets.unbind_target(name)
            return (
                f"Canal `{result.get('removed')}` removido."
                if result.get("ok")
                else f"Falha: {result.get('error')}"
            )
        if low.startswith("inbox "):
            name = raw.split(maxsplit=1)[1].strip()
            jobs = cursor_targets.list_pending(name)
            if not jobs:
                return f"Inbox `{name}` vazia."
            lines = [f"Pendentes em `{name}` ({len(jobs)}):"]
            for j in jobs[-10:]:
                lines.append(f"- [{j.get('kind')}] {j.get('title') or j.get('id')}")
            return "\n".join(lines)
        # /cursor @teatrinho: mensagem
        at = re.match(r"^@([a-zA-Z0-9_-]+)\s*[:：]\s*(.+)$", raw, re.DOTALL)
        if at:
            channel, msg = at.group(1), at.group(2).strip()
            if not msg:
                return f"Uso: /cursor @{channel}: <mensagem>"
            # async path — mark pending with special prefix for process_update
            return f"{_CURSOR_TARGET_PENDING}{channel}\n{msg}"
        return _CURSOR_PENDING  # handled async in process_update
    if cmd == "/status":
        prog = progress.get_progress()
        s = prog.get("summary", {})
        return (
            f"Notas: {s.get('total_notes', 0)} | "
            f"Quizzes: {s.get('total_quizzes', 0)} | "
            f"Revisões: {s.get('due_reviews', 0)}"
        )
    if cmd == "/context":
        if not args:
            return "Uso: /context <tarefa>"
        ctx = context.get_context_for_task(args, limit=3)
        lines = [
            f"Contexto: {args}",
            f"Conhecimento: {len(ctx.get('knowledge', []))} hits",
            f"Código: {len(ctx.get('code', []))} hits",
        ]
        if ctx.get("past_errors"):
            lines.append(f"Erros passados: {len(ctx['past_errors'])}")
        return "\n".join(lines)
    if cmd == "/learn":
        result = active_learning.run_active_learning(max_items=2)
        return f"Active learning: {result.get('learned_count', 0)} tópico(s)"
    if cmd == "/web":
        from learning_agent.core import web as web_core

        if not args.strip():
            return "Uso: /web <pergunta>\nEx.: /web cotação dólar hoje"
        return web_core.format_web_search_telegram(args.strip())
    if cmd == "/location":
        from learning_agent.core import user_context

        return user_context.format_telegram_summary()
    if cmd == "/gps":
        return _GPS_REQUEST
    if cmd in {"/casa", "/perto", "/nearby", "/endereco", "/endereço"}:
        from learning_agent.core import user_geolocation

        if cmd in {"/endereco", "/endereço"}:
            return user_geolocation.format_current_address(user_id)
        if cmd == "/casa":
            query = f"/casa {args}".strip()
        else:
            query = f"/perto {args}".strip() if args else "/perto"
        result = user_geolocation.handle_location_query(query, user_id)
        return result or "Uso: /casa <endereço> ou /perto [supermercado|farmacia|...]"
    if cmd == "/search":
        if not args:
            return "Uso: /search <query>"
        try:
            with httpx.Client(timeout=30.0) as client:
                r = client.get(f"{_api_base()}/knowledge/search", params={"q": args, "limit": 3})
                data = r.json()
        except Exception:
            from learning_agent.core import knowledge

            data = {"results": knowledge.search(args, limit=3)}
        hits = data.get("results", [])
        if not hits:
            return "Nenhum resultado."
        return "\n\n".join(f"- {h.get('content', '')[:200]}" for h in hits)
    return "Comando desconhecido. /help"


def _dispatch_cursor_target(
    chat_id: int, user_id: str, channel: str, message: str
) -> None:
    from learning_agent.core import cursor_targets

    _send_message(
        chat_id,
        f"Notificando canal Cursor `@{channel}` (pode levar 1–3 min)…",
    )
    _send_typing(chat_id)

    def _run() -> None:
        try:
            result = cursor_targets.notify_target(
                channel,
                message,
                user_id=user_id,
                also_inbox=True,
                inbox_kind="notify",
                inbox_title=f"Telegram → @{channel}",
            )
            if not result.get("ok"):
                _send_message(
                    chat_id,
                    f"Falha ao notificar `@{channel}`: {result.get('error')}",
                )
                return
            consult = result.get("consult") or {}
            if consult.get("skipped"):
                inbox = (result.get("inbox") or {}).get("inbox", "")
                _send_message(
                    chat_id,
                    f"Job enfileirado no inbox de `@{channel}`"
                    + (f"\n{inbox}" if inbox else "")
                    + "\n(sem agent_id — só inbox)",
                )
                return
            _send_message(
                chat_id,
                cursor_agent_bridge.format_consult_reply(consult)
                if isinstance(consult, dict)
                else str(consult),
            )
        except Exception as exc:
            _send_message(chat_id, f"Erro no canal `@{channel}`: {exc}")

    _UPDATE_EXECUTOR.submit(_run)


def _dispatch_cursor_consult(chat_id: int, user_id: str, message: str, *, reset: bool = False) -> None:
    _send_message(
        chat_id,
        "Consultando agente Cursor no repositório (pode levar 1–3 min)…",
    )
    _send_typing(chat_id)

    def _finish(result: dict[str, Any]) -> None:
        try:
            _send_message(chat_id, cursor_agent_bridge.format_consult_reply(result))
        except Exception as exc:
            _send_message(chat_id, f"Erro ao enviar resposta Cursor: {exc}")

    _UPDATE_EXECUTOR.submit(
        cursor_agent_bridge.run_consult_async,
        user_id,
        message,
        on_complete=_finish,
        reset=reset,
    )


def _chat_reply(message: str, user_id: str) -> str:
    from learning_agent.core import factual_tools
    from learning_agent.core import user_geolocation
    from learning_agent.core import web as web_core

    if cursor_agent_bridge.is_consult_request(message):
        return _CURSOR_PENDING

    geo_reply = user_geolocation.handle_location_query(message, user_id)
    if geo_reply:
        return geo_reply + "\n\n— Ravenna (OpenStreetMap)"

    factual_reply = factual_tools.handle_factual_query(message, user_id)
    if factual_reply:
        return factual_reply

    is_web, web_query = web_core.is_web_consult_request(message)
    if is_web:
        if not web_query:
            return "Uso: /web <pergunta> ou «pesquise na web: …»"
        return web_core.format_web_search_telegram(web_query)

    if finance_training_directives.is_apply_request(message, channel=TELEGRAM_CHANNEL, user_id=user_id):
        result = finance_training_directives.apply_from_chat(
            TELEGRAM_CHANNEL, user_id, user_message=message
        )
        return finance_training_directives.format_apply_reply(result)

    extra_context = ""
    if finance_status.is_finance_status_query(message):
        extra_context = finance_status.finance_context_for_chat()

    if RAVENNA_API_BASE:
        try:
            return _chat_reply_remote(message, user_id, context=extra_context)
        except Exception as exc:
            return (
                f"Poxa, não consegui falar com a Ravenna na VM. 😔\n\n"
                f"Erro: {exc}\n\n"
                f"Dica: confira se ravenna-vm:8000 está no ar e Tailscale conectado."
            )

    result = chat.reply(
        message,
        channel=TELEGRAM_CHANNEL,
        user_id=user_id,
        delegate_agent="finance-lead" if finance_status.is_finance_status_query(message) else None,
        extra_system=extra_context or None,
    )
    if not result.get("success"):
        try:
            web_answer = web_core.format_trusted_web_telegram(message.strip())
            return (
                "Não consegui falar com o modelo agora, então busquei na web:\n\n"
                f"{web_answer}\n\n— Ravenna (busca web)"
            )
        except Exception:
            pass
        return (
            f"Poxa, não consegui responder agora. 😔\n\n"
            f"Erro: {result.get('error', 'desconhecido')}\n\n"
            f"Dica: {result.get('hint', 'verifique Ollama ou TEACHER_API_KEY')}"
        )

    answer = result.get("reply", "")
    from learning_agent.core import telegram_web_fallback

    if telegram_web_fallback.should_web_fallback(message, answer):
        try:
            web_answer = web_core.format_trusted_web_telegram(message.strip())
            answer = (
                "Não tinha isso na ponta da língua, então busquei em fontes confiáveis:\n\n"
                f"{web_answer}"
            )
        except Exception as exc:
            answer = f"{answer}\n\n(Tentei buscar na web mas falhou: {exc})"

    model = result.get("model", "?")
    footer = f"\n\n— {result.get('agent', 'Ravenna')} ({model})"
    return answer + footer


def _handle_telegram_location(
    chat_id: int,
    user_id: str,
    location: dict[str, Any],
    message: dict[str, Any],
    *,
    is_edit: bool,
) -> None:
    from learning_agent.core import user_geolocation

    live_period = location.get("live_period")
    msg_ts = message.get("edit_date") or message.get("date")
    saved = user_geolocation.save_telegram_location(
        user_id,
        float(location["latitude"]),
        float(location["longitude"]),
        live_period=int(live_period) if live_period else None,
        message_date=int(msg_ts) if msg_ts else None,
        horizontal_accuracy=location.get("horizontal_accuracy"),
        silent_update=is_edit,
    )

    if is_edit or saved.get("silent_update"):
        return

    ack = (
        f"📡 GPS ao vivo do celular (~{max(1, int((saved.get('live_period') or 900) // 60))} min).\n"
        if saved.get("live_active")
        else "📍 GPS do celular recebido.\n"
    )
    body = (
        f"{ack}{saved.get('display_name', '')}\n\n"
        "Pergunte «mercado mais próximo» — uso essas coordenadas.\n"
        "/endereco — ver status."
    )
    if saved.get("live_active"):
        _remove_keyboard(chat_id, body)
    else:
        _remove_keyboard(
            chat_id,
            body + "\n\nDica: 📎 → Localização → Compartilhar ao vivo = GPS contínuo.",
        )


def process_update(update: dict[str, Any]) -> None:
    is_edit = "edited_message" in update
    message = update.get("message") or update.get("edited_message") or {}
    chat_info = message.get("chat") or {}
    chat_id = chat_info.get("id")
    user = message.get("from") or {}
    user_id = user.get("id")
    text = (message.get("text") or "").strip()
    location = message.get("location")
    voice = message.get("voice")
    audio = message.get("audio")

    if not chat_id or not _allowed(user_id):
        return

    uid = str(user_id)

    if _is_gps_message(message):
        _send_typing(chat_id)
        _handle_telegram_location(chat_id, uid, location, message, is_edit=is_edit)
        return

    if (voice or audio) and not text:
        from learning_agent.core import speech

        _send_typing(chat_id)
        file_id = (voice or audio)["file_id"]
        tr = speech.transcribe_telegram_voice(file_id)
        if not tr.get("success"):
            _send_message(chat_id, f"Não entendi o áudio.\n\n{tr.get('error', 'erro')}")
            return
        text = tr["text"]
        _send_message(chat_id, f"🎤 Ouvi: «{text}»")
        # segue para _chat_reply abaixo

    if not text:
        return

    reply_to = message.get("reply_to_message")
    if reply_to and text:
        from learning_agent.core import finance_telegram_replies

        decision_reply = finance_telegram_replies.handle_decision_reply(reply_to, text)
        if decision_reply:
            _send_message(chat_id, decision_reply)
            return

    if text.startswith("/"):
        parts = text.split(maxsplit=1)
        cmd = parts[0].split("@", 1)[0]
        args = parts[1] if len(parts) > 1 else ""
        _send_typing(chat_id)
        try:
            reply = handle_command(cmd, args, uid)
            if isinstance(reply, str) and reply.startswith(_CURSOR_TARGET_PENDING):
                rest = reply[len(_CURSOR_TARGET_PENDING) :]
                channel, _, msg = rest.partition("\n")
                _dispatch_cursor_target(chat_id, uid, channel.strip(), msg.strip())
                return
            if reply == _CURSOR_PENDING:
                _dispatch_cursor_consult(chat_id, uid, text)
                return
            if reply == _GPS_REQUEST:
                _send_gps_request(chat_id)
                return
        except Exception as exc:
            reply = f"Erro ao processar {cmd}: {exc}"
    else:
        from learning_agent.core import finance_telegram_replies

        shortcut = finance_telegram_replies.handle_decision_shortcut(text)
        if shortcut:
            _send_message(chat_id, shortcut)
            return
        _send_typing(chat_id)
        try:
            reply = _chat_reply(text, uid)
            if reply == _CURSOR_PENDING:
                _dispatch_cursor_consult(chat_id, uid, text)
                return
        except Exception as exc:
            reply = f"Erro ao responder: {exc}"

    _send_message(chat_id, reply)


def _process_update_safe(update: dict[str, Any]) -> None:
    try:
        process_update(update)
    except Exception as exc:
        print(f"Erro ao processar update: {exc}")


def run_polling(offset: int = 0, interval: float = 1.0) -> None:
    if not TELEGRAM_BOT_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN não configurado no .env")

    _assert_single_instance()
    print("Ravenna Telegram — chat completo ativo...")

    def _warm_cache() -> None:
        try:
            finance_status.build_finance_status(fast=False)
            print("Cache Prove finance-lead atualizado.")
        except Exception as exc:
            print(f"Aviso: cache finance-lead não atualizado: {exc}")

    threading.Thread(target=_warm_cache, daemon=True).start()

    current_offset = offset
    while True:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
        params = {"timeout": 30, "offset": current_offset}
        with httpx.Client(timeout=40.0) as client:
            response = client.get(url, params=params)
            data = response.json()

        for update in data.get("result", []):
            current_offset = update["update_id"] + 1
            _UPDATE_EXECUTOR.submit(_process_update_safe, update)

        time.sleep(interval)


def main() -> None:
    run_polling()


if __name__ == "__main__":
    main()
