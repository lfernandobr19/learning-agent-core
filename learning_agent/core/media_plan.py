"""Plano multi-etapas de mídia: find → probe → convert → transfer → delete Debian old."""

from __future__ import annotations

import json
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from learning_agent.config import DATA_DIR
from learning_agent.core.file_transfer import (
    VIDEOS_DIR,
    extract_video_query,
    get_transfer,
    start_windows_video_transfer,
)

PLANS_DIR = DATA_DIR / "plans"

_plans_lock = threading.Lock()
_plans: dict[str, dict[str, Any]] = {}
_cancel: set[str] = set()


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _plan_path(plan_id: str) -> Path:
    PLANS_DIR.mkdir(parents=True, exist_ok=True)
    return PLANS_DIR / f"{plan_id}.json"


def _persist(plan: dict[str, Any]) -> None:
    path = _plan_path(str(plan["id"]))
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def get_plan(plan_id: str) -> dict[str, Any] | None:
    pid = (plan_id or "").strip()
    if not pid:
        return None
    with _plans_lock:
        if pid in _plans:
            return dict(_plans[pid])
    path = _plan_path(pid)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if isinstance(data, dict):
        with _plans_lock:
            _plans[pid] = data
        return dict(data)
    return None


def cancel_plan(plan_id: str) -> dict[str, Any]:
    pid = (plan_id or "").strip()
    if not pid:
        return {"ok": False, "error": "id obrigatório"}
    _cancel.add(pid)
    plan = _update(pid, status="cancelling")
    if not plan:
        return {"ok": False, "error": "plan not found"}
    return {"ok": True, **plan}


def confirm_delete_plan(plan_id: str, *, confirm: bool = True) -> dict[str, Any]:
    """Confirma ou pula exclusão de cópias antigas no Debian."""
    pid = (plan_id or "").strip()
    if not pid:
        return {"ok": False, "error": "id obrigatório"}
    plan = get_plan(pid)
    if not plan:
        return {"ok": False, "error": "plan not found"}
    if confirm:
        updated = _update(pid, delete_confirmed=True, delete_skipped=False, status="running")
    else:
        updated = _update(pid, delete_confirmed=False, delete_skipped=True, status="running")
    return {"ok": True, **(updated or plan)}


def _update(plan_id: str, **fields: Any) -> dict[str, Any] | None:
    with _plans_lock:
        plan = dict(_plans.get(plan_id) or {})
        if not plan:
            path = _plan_path(plan_id)
            if path.is_file():
                try:
                    loaded = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    loaded = None
                if isinstance(loaded, dict):
                    plan = loaded
        if not plan:
            return None
        plan.update(fields)
        plan["updated_at"] = _utcnow()
        # percent from steps
        steps = plan.get("steps") or []
        if steps:
            done_n = sum(1 for s in steps if s.get("status") in {"done", "skipped"})
            running = next((s for s in steps if s.get("status") == "running"), None)
            base = 100.0 * done_n / max(1, len(steps))
            if running and running.get("percent") is not None:
                base = 100.0 * done_n / max(1, len(steps)) + (
                    float(running["percent"]) / max(1, len(steps))
                )
            plan["percent"] = round(min(100.0, base), 1)
        _plans[plan_id] = plan
        _persist(plan)
        return dict(plan)


def _set_step(plan_id: str, step_id: str, **fields: Any) -> None:
    with _plans_lock:
        plan = dict(_plans.get(plan_id) or get_plan(plan_id) or {})
        steps = list(plan.get("steps") or [])
        for i, s in enumerate(steps):
            if s.get("id") == step_id:
                steps[i] = {**s, **fields, "updated_at": _utcnow()}
                break
        plan["steps"] = steps
        plan["updated_at"] = _utcnow()
        _plans[plan_id] = plan
        _persist(plan)


def _cancelled(plan_id: str) -> bool:
    return plan_id in _cancel


def _wants(message: str, *patterns: str) -> bool:
    low = (message or "").lower()
    return any(re.search(p, low) for p in patterns)


def _fmt_bytes(n: Any) -> str:
    try:
        b = float(n)
    except (TypeError, ValueError):
        return ""
    if b <= 0:
        return ""
    units = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    while b >= 1024 and i < len(units) - 1:
        b /= 1024
        i += 1
    return f"{b:.1f} {units[i]}"


def _audio_track_label(a: dict[str, Any]) -> str:
    codec = str(a.get("codec") or "?")
    lang = str(a.get("language") or "und")
    title = str(a.get("title") or "").strip()
    bits = [codec, lang]
    if title:
        bits.append(f'"{title}"')
    return " ".join(bits)


def _step_note(sid: str, *, status: str, result: Any = None, error: str | None = None) -> str:
    """Texto humano PT-BR para cada fase do plano."""
    res = result if isinstance(result, dict) else {}
    err = (error or "").strip()

    if sid == "find":
        if status == "error":
            return f"Não achei o arquivo no Windows{f': {err}' if err else ''}."
        name = str(res.get("name") or Path(str(res.get("path") or "")).name or "vídeo")
        path = str(res.get("path") or "")
        size = _fmt_bytes(res.get("size"))
        extra = f" (~{size})" if size else ""
        where = f" em `{path}`" if path else ""
        return f"Achei {name}{where}{extra}."

    if sid == "probe":
        if status == "skipped":
            warn = str(res.get("warning") or err or "ffprobe indisponível")
            return f"Não consegui inspecionar áudio/legendas ({warn}) — segui sem esse detalhe."
        if status == "error":
            return f"Falha ao checar áudio/legendas{f': {err}' if err else ''}."
        audio = res.get("audio") if isinstance(res.get("audio"), list) else []
        subs = res.get("subtitles") if isinstance(res.get("subtitles"), list) else []
        tracks = ", ".join(_audio_track_label(a) for a in audio[:6] if isinstance(a, dict)) or "nenhuma"
        dubbed = res.get("has_dubbed_pt_guess")
        original = res.get("has_original_audio_guess")
        has_subs = bool(res.get("has_subtitles") or subs)
        dub_txt = "sim" if dubbed else "não"
        orig_txt = "sim" if original else "não"
        if has_subs:
            sub_bits = []
            for s in subs[:4]:
                if not isinstance(s, dict):
                    continue
                lang = str(s.get("language") or "und")
                title = str(s.get("title") or "").strip()
                sub_bits.append(f"{lang}" + (f' "{title}"' if title else ""))
            sub_txt = ", ".join(sub_bits) if sub_bits else f"{len(subs)} faixa(s)"
        else:
            sub_txt = "nenhuma"
        return (
            f"Checagem: {len(audio)} faixa(s) de áudio ({tracks}). "
            f"Dublado PT: {dub_txt}; áudio original (guess): {orig_txt}; legendas: {sub_txt}."
        )

    if sid == "convert":
        if status == "skipped":
            return "Já era MKV — pulei a conversão."
        if status == "error":
            return f"Falha na conversão{f': {err}' if err else ''}."
        out = str(res.get("output_path") or res.get("path") or "")
        return f"Converti para MKV{f' → `{out}`' if out else ''}."

    if sid == "enrich":
        if status == "skipped":
            note = str(res.get("note") or "Nada a enriquecer (já completo ou sem fonte).")
            low = note.lower()
            if "opensubtitles_api_key" in low or "não configurada" in low:
                note += " Dica: coloque OPENSUBTITLES_API_KEY no .env do motor e reinicie o backend."
            if "outra cópia local" in low or "áudio original" in low:
                note += " Se tiver um arquivo ENG no PC, manda o caminho que eu junto."
            return note
        if status == "error":
            tip = ""
            low = (err or "").lower()
            if "ffmpeg" in low:
                tip = " Confira o FFmpeg no agent Windows."
            elif "opensubtitles" in low:
                tip = " Confira a API key do OpenSubtitles."
            return f"Falha ao juntar áudio/legendas{f': {err}' if err else ''}.{tip}"
        note = str(res.get("note") or "")
        out = str(res.get("output_path") or "")
        if note:
            return note
        return f"Enriqueci o MKV{f' → `{out}`' if out else ''}."

    if sid == "transfer":
        if status == "error":
            return f"Falha no envio para o Debian{f': {err}' if err else ''}."
        dest = str(res.get("dest_path") or "")
        size = _fmt_bytes(res.get("bytes_total") or res.get("bytes_done"))
        size_txt = f" ({size})" if size else ""
        if dest:
            return f"Enviei para o Debian: `{dest}`{size_txt}."
        return f"Enviei para o Debian{size_txt}."

    if sid == "delete_debian_old":
        if status == "error":
            return f"Falha ao apagar cópia antiga{f': {err}' if err else ''}."
        deleted = res.get("deleted") if isinstance(res.get("deleted"), list) else []
        if not deleted:
            return "Não havia cópia antiga no Debian para apagar."
        if len(deleted) == 1:
            return f"Apaguei a cópia antiga: `{deleted[0]}`."
        return f"Apaguei {len(deleted)} cópia(s) antiga(s) no Debian."

    if status == "error" and err:
        return f"Erro em {sid}: {err}"
    return f"Passo {sid}: {status}."


def _narrate(plan_id: str, text: str, *, step_id: str | None = None) -> None:
    """Anexa note ao plano, lista narrations e persiste mensagem no chat (best-effort)."""
    note = (text or "").strip()
    if not note:
        return
    channel = ""
    conversation_id = ""
    with _plans_lock:
        plan = dict(_plans.get(plan_id) or {})
        if not plan:
            path = _plan_path(plan_id)
            if path.is_file():
                try:
                    loaded = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    loaded = None
                if isinstance(loaded, dict):
                    plan = loaded
        if not plan:
            return
        narrations = list(plan.get("narrations") or [])
        if any(n.get("step_id") == step_id and n.get("text") == note for n in narrations):
            return
        narrations.append({"at": _utcnow(), "text": note, "step_id": step_id})
        plan["narrations"] = narrations
        if step_id and step_id != "__summary__":
            steps = list(plan.get("steps") or [])
            for i, s in enumerate(steps):
                if s.get("id") == step_id:
                    steps[i] = {**s, "note": note}
                    break
            plan["steps"] = steps
        elif step_id == "__summary__":
            plan["summary"] = note
        plan["updated_at"] = _utcnow()
        _plans[plan_id] = plan
        _persist(plan)
        channel = str(plan.get("channel") or "")
        conversation_id = str(plan.get("conversation_id") or "")

    if channel and conversation_id:
        try:
            from learning_agent.core.chat import _save_message

            _save_message(channel, conversation_id, "assistant", note)
        except Exception:
            pass


def _finish_note(plan_id: str, status: str) -> str:
    plan = get_plan(plan_id) or {}
    query = str(plan.get("query") or "vídeo")
    probe = plan.get("probe") if isinstance(plan.get("probe"), dict) else {}
    err = str(plan.get("error") or "").strip()

    if status == "cancelled":
        return f"Cancelei o plano de “{query}”."
    if status == "error":
        tip = ""
        low = err.lower()
        if "opensubtitles" in low or "api_key" in low:
            tip = " Confira OPENSUBTITLES_API_KEY no .env (e senha se precisar)."
        elif "ffmpeg" in low or "ffprobe" in low:
            tip = " Confira se o FFmpeg está no PATH do agent Windows."
        elif any(x in low for x in ("tailscale", "connect", "10061", "timed out", "refused")):
            tip = " Confira se o Tailscale/agent Windows (:8780) está online."
        return f"O plano de “{query}” falhou{f': {err}' if err else ''}.{tip}"

    dest = None
    tid = plan.get("transfer_id")
    if tid:
        xfer = get_transfer(str(tid)) or {}
        dest = xfer.get("dest_path")
    dubbed = "sim" if probe.get("has_dubbed_pt_guess") else "não"
    original = "sim" if probe.get("has_original_audio_guess") else "não"
    subs = "sim" if probe.get("has_subtitles") else "não"
    bits = [f"dublado PT {dubbed}", f"original {original}", f"legendas {subs}"]
    where = f" no Debian em `{dest}`" if dest else ""
    msg = f"Pronto{where} — “{query}” · " + " · ".join(bits) + "."
    if not probe.get("has_original_audio_guess") and not probe.get("warning"):
        msg += (
            " Se tiver outra cópia com áudio ENG no PC, me diga o caminho ou o nome do arquivo "
            "que eu junto na próxima."
        )
    return msg


def _complete_step(
    plan_id: str,
    sid: str,
    *,
    status: str,
    result: Any = None,
    error: str | None = None,
    percent: float | None = None,
) -> None:
    fields: dict[str, Any] = {"status": status}
    if result is not None:
        fields["result"] = result
    if error is not None:
        fields["error"] = error
    if percent is not None:
        fields["percent"] = percent
    note = _step_note(sid, status=status, result=result, error=error)
    fields["note"] = note
    _set_step(plan_id, sid, **fields)
    if status in {"done", "skipped", "error"}:
        _narrate(plan_id, note, step_id=sid)


def start_media_plan(
    *,
    message: str = "",
    query: str = "",
    conversation_id: str = "",
    channel: str = "",
) -> dict[str, Any]:
    """Cria e inicia plano em background no processo uvicorn."""
    msg = (message or "").strip()
    q = (query or extract_video_query(msg) or "").strip()
    q = re.sub(
        r"\b(LEG|WEB[\s\-]?DL|WEBRip|BluRay|1080p|720p|2160p|Dual|Dublado|Legendado)\b",
        " ",
        q,
        flags=re.IGNORECASE,
    )
    q = re.sub(r"\s+", " ", q).strip(" -_.") or (query or extract_video_query(msg) or "").strip()
    if not q and not msg:
        return {"ok": False, "error": "informe o nome do vídeo"}

    want_find = True
    from learning_agent.core.file_transfer import is_media_mux_request, is_subtitle_only_request

    subtitle_only = is_subtitle_only_request(msg)
    mux_request = is_media_mux_request(msg) and not subtitle_only
    want_probe = _wants(msg, r"\b(áudio|audio|dublad\w*|original|legenda|subtitle|faixa|probe|checa|verificar)\b") or True
    # "mkv" sozinho não implica converter (ex.: "preparando um mkv"); "junte em MKV" sim
    want_convert = (
        _wants(msg, r"\b(conver\w*|transcod\w*|ffmpeg|handbrake)\b") or mux_request
    ) and not subtitle_only
    # Transferência exige verbo de envio + destino — NÃO dispare só porque a mensagem cita "Ravenna"
    want_transfer = (
        bool(
            re.search(r"\b(envia|enviar|manda|mandar|transfere|transferir|upload|sobe)\b", msg.lower())
            and re.search(r"\b(debian|linux)\b", msg.lower())
        )
        and not subtitle_only
    )
    want_delete_old = _wants(msg, r"\b(apaga|apagar|deleta|deletar|remove|remover|exclui|antiga|antigo)\b") and not subtitle_only
    want_original_audio = _wants(msg, r"\b(áudio\s+original|audio\s+original|faixa\s+original|eng\b|english)\b") and not subtitle_only
    want_dubbed_audio = _wants(msg, r"\b(dublad\w*|áudio\s+dublado|audio\s+dublado)\b") and not subtitle_only
    if mux_request or (
        _wants(msg, r"\b(junt\w*|mescl\w*|combin\w*)\b")
        and _wants(msg, r"\b(dois|2|tr[eê]s|3|ambos|dublad\w*|original|vídeos|videos|arquivos|mkv)\b")
    ):
        want_original_audio = True
        want_dubbed_audio = True
    want_subtitles = _wants(msg, r"\b(legenda|legendas|subtitle|subtitles)\b") or (want_probe and not want_original_audio)
    if subtitle_only:
        want_probe = True
        want_subtitles = True
        want_original_audio = False
        want_convert = False
        want_transfer = False
        want_delete_old = False
    # Pipeline completo só se multi-intenção REAL (sem subtitle-only)
    if not subtitle_only and sum([want_convert, want_transfer, want_delete_old]) >= 1 and want_probe:
        if want_transfer and _wants(msg, r"\b(conver)\b"):
            want_convert = True
    # Flags para o passo enrich
    enrich_flags = {
        "want_original_audio": bool(want_original_audio) if not subtitle_only else False,
        "want_dubbed_audio": bool(want_dubbed_audio) if not subtitle_only else False,
        "want_subtitles": bool(want_subtitles) if subtitle_only or want_subtitles else True,
    }

    steps: list[dict[str, Any]] = []
    if want_find:
        steps.append({"id": "find", "label": "Localizar no Windows", "status": "pending", "tool": "windows_find_files"})
    if want_probe:
        steps.append({"id": "probe", "label": "Checar áudio/legendas", "status": "pending", "tool": "windows_probe_media"})
        steps.append(
            {
                "id": "enrich",
                "label": "Baixar/juntar legendas" if subtitle_only else "Completar áudio original/legendas",
                "status": "pending",
                "tool": "windows_enrich_media",
            }
        )
    if want_convert:
        steps.append({"id": "convert", "label": "Converter para MKV", "status": "pending", "tool": "windows_convert_media"})
    if want_transfer:
        steps.append({"id": "transfer", "label": "Enviar para o Debian", "status": "pending", "tool": "windows_transfer_to_debian", "percent": 0})
    if want_delete_old:
        steps.append({"id": "delete_debian_old", "label": "Apagar cópia antiga no Debian", "status": "pending", "tool": "host_delete_video"})

    if not steps:
        steps = [
            {"id": "find", "label": "Localizar no Windows", "status": "pending", "tool": "windows_find_files"},
        ]

    plan_id = f"plan-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
    plan = {
        "id": plan_id,
        "ok": True,
        "status": "starting",
        "query": q or msg[:80],
        "message": msg,
        "conversation_id": (conversation_id or "").strip(),
        "channel": (channel or "").strip(),
        "steps": steps,
        "percent": 0.0,
        "windows_path": None,
        "converted_path": None,
        "transfer_id": None,
        "probe": None,
        "enrich_flags": enrich_flags,
        "subtitle_only": subtitle_only,
        "narrations": [],
        "summary": None,
        "error": None,
        "created_at": _utcnow(),
        "updated_at": _utcnow(),
    }
    with _plans_lock:
        _plans[plan_id] = plan
        _persist(plan)

    threading.Thread(
        target=_run_plan,
        args=(plan_id,),
        name=f"plan-{plan_id}",
        daemon=True,
    ).start()
    return dict(plan)


def _run_plan(plan_id: str) -> None:
    from learning_agent.core import windows_agent_client as win

    _update(plan_id, status="running")
    plan = get_plan(plan_id) or {}
    query = str(plan.get("query") or "")
    windows_path = ""
    converted_path = ""

    try:
        for step in list(plan.get("steps") or []):
            if _cancelled(plan_id):
                summary = _finish_note(plan_id, "cancelled")
                _update(plan_id, status="cancelled", error="cancelado", summary=summary)
                _narrate(plan_id, summary, step_id="__summary__")
                return
            sid = str(step.get("id"))
            _set_step(plan_id, sid, status="running")
            _update(plan_id, current_step=sid)

            if sid == "find":
                found = win.find_files(query, kind="video")
                matches = found.get("matches") or []
                if not matches:
                    _complete_step(
                        plan_id,
                        sid,
                        status="error",
                        result=found,
                        error=str(found.get("error") or "não encontrado"),
                    )
                    summary = f'Não achei “{query}” no Windows.'
                    _update(plan_id, status="error", error=summary, summary=summary)
                    _narrate(plan_id, summary, step_id="__summary__")
                    return
                best = matches[0]
                windows_path = str(best.get("path") or "")
                _complete_step(
                    plan_id,
                    sid,
                    status="done",
                    result={
                        "path": windows_path,
                        "name": best.get("name"),
                        "size": best.get("size"),
                        "matches": len(matches),
                    },
                )
                _update(plan_id, windows_path=windows_path)

            elif sid == "probe":
                path = windows_path or str((get_plan(plan_id) or {}).get("windows_path") or "")
                if not path:
                    _complete_step(plan_id, sid, status="error", error="sem path")
                    summary = "Probe sem arquivo."
                    _update(plan_id, status="error", error=summary, summary=summary)
                    _narrate(plan_id, summary, step_id="__summary__")
                    return
                probe = win.probe_media(path)
                if not probe.get("ok"):
                    err = str(probe.get("error") or "probe falhou")
                    # Sem ffprobe: não mata o plano — reporta e segue
                    if "ffprobe" in err.lower() or "não encontrado" in err.lower():
                        _complete_step(
                            plan_id,
                            sid,
                            status="skipped",
                            error=err,
                            result={"warning": err, "path": path},
                        )
                        _update(plan_id, probe={"warning": err})
                    else:
                        _complete_step(plan_id, sid, status="error", error=err, result=probe)
                        summary = _finish_note(plan_id, "error")
                        _update(plan_id, status="error", error=err, summary=summary)
                        _narrate(plan_id, summary, step_id="__summary__")
                        return
                else:
                    probe_summary = {
                        "audio_count": len(probe.get("audio") or []),
                        "subtitle_count": len(probe.get("subtitles") or []),
                        "has_dubbed_pt_guess": probe.get("has_dubbed_pt_guess"),
                        "has_original_audio_guess": probe.get("has_original_audio_guess"),
                        "has_subtitles": probe.get("has_subtitles"),
                        "audio": probe.get("audio"),
                        "subtitles": probe.get("subtitles"),
                    }
                    _complete_step(plan_id, sid, status="done", result=probe_summary)
                    _update(plan_id, probe=probe_summary)

            elif sid == "enrich":
                import os

                path = windows_path or str((get_plan(plan_id) or {}).get("windows_path") or "")
                if not path:
                    _complete_step(plan_id, sid, status="error", error="sem path")
                    summary = "Enrich sem arquivo."
                    _update(plan_id, status="error", error=summary, summary=summary)
                    _narrate(plan_id, summary, step_id="__summary__")
                    return
                plan_now = get_plan(plan_id) or {}
                probe = plan_now.get("probe") if isinstance(plan_now.get("probe"), dict) else {}
                flags = plan_now.get("enrich_flags") if isinstance(plan_now.get("enrich_flags"), dict) else {}
                subtitle_only = bool(plan_now.get("subtitle_only"))
                # Respeita pedido: só legenda NÃO tenta roubar áudio ENG de outro filme
                want_audio = bool(flags.get("want_original_audio", not subtitle_only)) and not bool(
                    probe.get("has_original_audio_guess")
                )
                want_dub = bool(flags.get("want_dubbed_audio", False)) and not bool(
                    probe.get("has_dubbed_pt_guess")
                )
                want_subs = bool(flags.get("want_subtitles", True)) and not bool(probe.get("has_subtitles"))
                if probe.get("warning") and not subtitle_only:
                    want_audio = bool(flags.get("want_original_audio", True))
                    want_subs = bool(flags.get("want_subtitles", True))
                if not want_audio and not want_dub and not want_subs:
                    _complete_step(
                        plan_id,
                        sid,
                        status="skipped",
                        result={"note": "Já tinha o que você pediu (nada a completar).", "path": path},
                    )
                else:
                    enriched = win.enrich_media(
                        path,
                        query=query,
                        want_original_audio=want_audio,
                        want_dubbed_audio=want_dub,
                        want_subtitles=want_subs,
                        opensubtitles_api_key=os.environ.get("OPENSUBTITLES_API_KEY", ""),
                        opensubtitles_username=os.environ.get("OPENSUBTITLES_USERNAME", ""),
                        opensubtitles_password=os.environ.get("OPENSUBTITLES_PASSWORD", ""),
                    )
                    if not enriched.get("ok"):
                        err = str(enriched.get("error") or "enrich falhou")
                        # Não mata o plano — segue com o arquivo atual
                        _complete_step(
                            plan_id,
                            sid,
                            status="skipped",
                            error=err,
                            result={"note": err, **{k: enriched.get(k) for k in ("notes", "note")}},
                        )
                    else:
                        out = str(enriched.get("output_path") or path)
                        status = "skipped" if enriched.get("skipped") else "done"
                        _complete_step(plan_id, sid, status=status, result=enriched)
                        if out and out != path and not enriched.get("skipped"):
                            windows_path = out
                            _update(plan_id, windows_path=out, enriched_path=out)
                        after = enriched.get("probe_after")
                        if isinstance(after, dict) and after.get("ok"):
                            _update(
                                plan_id,
                                probe={
                                    "audio_count": len(after.get("audio") or []),
                                    "subtitle_count": len(after.get("subtitles") or []),
                                    "has_dubbed_pt_guess": after.get("has_dubbed_pt_guess"),
                                    "has_original_audio_guess": after.get("has_original_audio_guess"),
                                    "has_subtitles": after.get("has_subtitles"),
                                    "audio": after.get("audio"),
                                    "subtitles": after.get("subtitles"),
                                },
                            )

            elif sid == "convert":
                path = (
                    windows_path
                    or str((get_plan(plan_id) or {}).get("enriched_path") or "")
                    or str((get_plan(plan_id) or {}).get("windows_path") or "")
                )
                if not path:
                    _complete_step(plan_id, sid, status="error", error="sem path")
                    summary = "Convert sem arquivo."
                    _update(plan_id, status="error", error=summary, summary=summary)
                    _narrate(plan_id, summary, step_id="__summary__")
                    return
                if path.lower().endswith(".mkv"):
                    converted_path = path
                    probe_now = (get_plan(plan_id) or {}).get("probe") or {}
                    already_muxed = bool(
                        int(probe_now.get("audio_count") or 0) >= 2
                        and int(probe_now.get("subtitle_count") or 0) >= 1
                    )
                    reason = (
                        "Já é MKV com áudio original+dublado e legenda — nada a juntar."
                        if already_muxed
                        else "já é mkv"
                    )
                    _complete_step(
                        plan_id,
                        sid,
                        status="skipped",
                        result={"reason": reason, "path": path},
                    )
                    _update(plan_id, converted_path=converted_path)
                else:
                    conv = win.convert_media(path, container="mkv")
                    if not conv.get("ok"):
                        err = str(conv.get("error") or "convert falhou")
                        _complete_step(plan_id, sid, status="error", error=err, result=conv)
                        summary = _finish_note(plan_id, "error")
                        _update(plan_id, status="error", error=err, summary=summary)
                        _narrate(plan_id, summary, step_id="__summary__")
                        return
                    converted_path = str(conv.get("output_path") or "")
                    _complete_step(plan_id, sid, status="done", result=conv)
                    _update(plan_id, converted_path=converted_path)

            elif sid == "transfer":
                plan_now = get_plan(plan_id) or {}
                path = (
                    converted_path
                    or str(plan_now.get("converted_path") or "")
                    or str(plan_now.get("enriched_path") or "")
                    or windows_path
                    or str(plan_now.get("windows_path") or "")
                )
                xfer = start_windows_video_transfer(windows_path=path, query=query)
                if not xfer.get("ok"):
                    err = str(xfer.get("error") or "transfer falhou")
                    _complete_step(plan_id, sid, status="error", error=err, result=xfer)
                    summary = _finish_note(plan_id, "error")
                    _update(plan_id, status="error", error=err, summary=summary)
                    _narrate(plan_id, summary, step_id="__summary__")
                    return
                tid = str(xfer.get("id") or "")
                _update(plan_id, transfer_id=tid)
                last_st: dict[str, Any] = {}
                while True:
                    if _cancelled(plan_id):
                        summary = _finish_note(plan_id, "cancelled")
                        _update(plan_id, status="cancelled", summary=summary)
                        _narrate(plan_id, summary, step_id="__summary__")
                        return
                    st = get_transfer(tid) or {}
                    last_st = st
                    pct = float(st.get("percent") or 0)
                    _set_step(
                        plan_id,
                        sid,
                        status="running" if st.get("status") not in {"done", "error"} else st.get("status"),
                        percent=pct,
                        result={
                            "transfer_id": tid,
                            "bytes_done": st.get("bytes_done"),
                            "bytes_total": st.get("bytes_total"),
                            "eta_seconds": st.get("eta_seconds"),
                            "dest_path": st.get("dest_path"),
                            "error": st.get("error"),
                        },
                    )
                    _update(plan_id)
                    if st.get("status") == "done":
                        _complete_step(
                            plan_id,
                            sid,
                            status="done",
                            percent=100,
                            result={
                                "transfer_id": tid,
                                "bytes_done": st.get("bytes_done"),
                                "bytes_total": st.get("bytes_total"),
                                "dest_path": st.get("dest_path"),
                            },
                        )
                        break
                    if st.get("status") == "error":
                        err = str(st.get("error") or "transfer error")
                        low = err.lower()
                        if any(x in low for x in ("connect", "timeout", "10061", "refused", "unreachable", "tailscale")):
                            err = (
                                f"{err} — parece queda de rede/Tailscale ou agent Windows offline. "
                                "Quando voltar, posso retomar a transferência."
                            )
                        _complete_step(
                            plan_id,
                            sid,
                            status="error",
                            error=err,
                            result=last_st,
                        )
                        summary = _finish_note(plan_id, "error")
                        _update(plan_id, status="error", error=err, summary=summary)
                        _narrate(plan_id, summary, step_id="__summary__")
                        return
                    if st.get("status") == "paused":
                        _set_step(plan_id, sid, status="paused", percent=pct, result=last_st)
                        # wait until resumed or cancelled
                        time.sleep(1.0)
                        continue
                    time.sleep(1.0)

            elif sid == "delete_debian_old":
                # Lista candidatas e espera confirmação explícita no PlanCard
                current = get_plan(plan_id) or {}
                tid = str(current.get("transfer_id") or "")
                xfer = get_transfer(tid) if tid else None
                keep = Path(str((xfer or {}).get("dest_path") or ""))
                VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
                fold_q = re.sub(r"[^a-z0-9]+", " ", query.lower())
                tokens = [t for t in fold_q.split() if len(t) >= 3]
                candidates: list[str] = []
                for p in VIDEOS_DIR.iterdir():
                    if not p.is_file():
                        continue
                    if keep and keep.exists() and p.resolve() == keep.resolve():
                        continue
                    name_fold = re.sub(r"[^a-z0-9]+", " ", p.name.lower())
                    if tokens and sum(1 for t in tokens if t in name_fold) >= min(2, len(tokens)):
                        candidates.append(str(p))
                if not candidates:
                    _complete_step(
                        plan_id,
                        sid,
                        status="done",
                        result={"deleted": [], "note": "Não havia cópia antiga no Debian para apagar."},
                    )
                elif current.get("delete_confirmed"):
                    deleted: list[str] = []
                    for path_s in candidates:
                        try:
                            Path(path_s).unlink()
                            deleted.append(path_s)
                        except OSError as exc:
                            _complete_step(plan_id, sid, status="error", error=str(exc))
                            summary = _finish_note(plan_id, "error")
                            _update(plan_id, status="error", error=str(exc), summary=summary)
                            _narrate(plan_id, summary, step_id="__summary__")
                            return
                    _complete_step(plan_id, sid, status="done", result={"deleted": deleted})
                else:
                    _update(
                        plan_id,
                        status="awaiting_delete_confirm",
                        delete_candidates=candidates,
                    )
                    _set_step(
                        plan_id,
                        sid,
                        status="awaiting_confirm",
                        result={"candidates": candidates},
                        note=(
                            f"Encontrei {len(candidates)} cópia(s) antiga(s) no Debian. "
                            "Confirme no card do plano para eu apagar."
                        ),
                    )
                    _narrate(
                        plan_id,
                        f"Antes de apagar: {len(candidates)} arquivo(s) antigo(s) no Debian. "
                        "Toque em Confirmar exclusão no plano.",
                        step_id=sid,
                    )
                    # Wait until confirmed or cancelled
                    while True:
                        if _cancelled(plan_id):
                            summary = _finish_note(plan_id, "cancelled")
                            _update(plan_id, status="cancelled", summary=summary)
                            _narrate(plan_id, summary, step_id="__summary__")
                            return
                        cur = get_plan(plan_id) or {}
                        if cur.get("delete_confirmed"):
                            deleted = []
                            for path_s in list(cur.get("delete_candidates") or candidates):
                                try:
                                    Path(str(path_s)).unlink(missing_ok=True)  # type: ignore[call-arg]
                                    deleted.append(str(path_s))
                                except TypeError:
                                    pth = Path(str(path_s))
                                    if pth.is_file():
                                        pth.unlink()
                                        deleted.append(str(path_s))
                                except OSError as exc:
                                    _complete_step(plan_id, sid, status="error", error=str(exc))
                                    summary = _finish_note(plan_id, "error")
                                    _update(plan_id, status="error", error=str(exc), summary=summary)
                                    _narrate(plan_id, summary, step_id="__summary__")
                                    return
                            _complete_step(plan_id, sid, status="done", result={"deleted": deleted})
                            _update(plan_id, status="running")
                            break
                        if cur.get("delete_skipped"):
                            _complete_step(
                                plan_id,
                                sid,
                                status="skipped",
                                result={"deleted": [], "note": "Exclusão pulada a seu pedido."},
                            )
                            _update(plan_id, status="running")
                            break
                        time.sleep(1.0)

        summary = _finish_note(plan_id, "done")
        _update(plan_id, status="done", percent=100.0, error=None, summary=summary)
        _narrate(plan_id, summary, step_id="__summary__")
    except Exception as exc:
        err = f"{type(exc).__name__}: {exc}"
        _update(plan_id, status="error", error=err)
        summary = _finish_note(plan_id, "error")
        _update(plan_id, summary=summary)
        _narrate(plan_id, summary, step_id="__summary__")
