"""Transferência Windows → Debian (ravenna) com progresso 0–100% e ETA."""

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

TRANSFERS_DIR = DATA_DIR / "transfers"
VIDEOS_DIR = DATA_DIR / "videos"

_jobs_lock = threading.Lock()
_jobs: dict[str, dict[str, Any]] = {}
_pause: set[str] = set()
_cancel_xfer: set[str] = set()


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _job_path(job_id: str) -> Path:
    TRANSFERS_DIR.mkdir(parents=True, exist_ok=True)
    return TRANSFERS_DIR / f"{job_id}.json"


def _persist(job: dict[str, Any]) -> None:
    path = _job_path(str(job["id"]))
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def get_transfer(job_id: str) -> dict[str, Any] | None:
    jid = (job_id or "").strip()
    if not jid:
        return None
    with _jobs_lock:
        if jid in _jobs:
            return dict(_jobs[jid])
    path = _job_path(jid)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if isinstance(data, dict):
        with _jobs_lock:
            _jobs[jid] = data
        return dict(data)
    return None


def _update(job_id: str, **fields: Any) -> dict[str, Any]:
    with _jobs_lock:
        job = dict(_jobs.get(job_id) or {})
        if not job:
            loaded = None
            path = _job_path(job_id)
            if path.is_file():
                try:
                    loaded = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    loaded = None
            if isinstance(loaded, dict):
                job = loaded
        job.update(fields)
        job["updated_at"] = _utcnow()
        done = int(job.get("bytes_done") or 0)
        total = int(job.get("bytes_total") or 0)
        started = float(job.get("started_monotonic") or 0)
        if done > 0 and total > 0 and started > 0:
            elapsed = max(0.001, time.monotonic() - started)
            speed = done / elapsed
            job["bytes_per_sec"] = round(speed, 1)
            remain = max(0, total - done)
            job["eta_seconds"] = int(remain / speed) if speed > 1 else None
            job["percent"] = min(100.0, round(100.0 * done / total, 1))
        elif total > 0 and done >= total:
            job["percent"] = 100.0
            job["eta_seconds"] = 0
        _jobs[job_id] = job
        _persist(job)
        return dict(job)


def extract_video_queries(message: str) -> list[str]:
    """Extrai um ou mais nomes de filme/vídeo (todas as aspas; senão fallback singular)."""
    text = (message or "").strip()
    if not text:
        return []
    quoted = re.findall(r"[\"“”']([^\"“”']{2,120})[\"“”']", text)
    out: list[str] = []
    seen: set[str] = set()
    for raw in quoted:
        q = (raw or "").strip()
        if len(q) < 2:
            continue
        key = q.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(q)
    if out:
        return out
    single = _extract_video_query_unquoted(text)
    return [single] if single else []


def extract_video_query(message: str) -> str | None:
    """Extrai o primeiro nome de filme/vídeo do pedido em PT/EN."""
    queries = extract_video_queries(message)
    return queries[0] if queries else None


def _extract_video_query_unquoted(text: str) -> str | None:
    """Fallback quando não há títulos entre aspas."""
    # "vídeo/filme NAME para ... debian"
    m = re.search(
        r"\b(?:o\s+|a\s+)?(?:v[ií]deo|filme|movie)\s+(.+?)\s+"
        r"(?:para|pro|pra|ao|à|a)\s+(?:o\s+|a\s+)?(?:debian|linux|ravenna|servidor|host|m[aá]quina)\b",
        text,
        re.IGNORECASE,
    )
    if m:
        return m.group(1).strip(" .,")
    m = re.search(
        r"\b(?:envia|enviar|manda|mandar|transfere|transferir|copia|copiar)\s+"
        r"(?:o\s+|a\s+)?(?:v[ií]deo|filme)?\s*(.+?)\s+(?:para|pro|pra)\s+"
        r"(?:o\s+|a\s+)?(?:debian|linux|ravenna|servidor|host|m[aá]quina)\b",
        text,
        re.IGNORECASE,
    )
    if m:
        q = m.group(1).strip(" .,")
        q = re.sub(r"^(o|a|um|uma|v[ií]deo|filme)\s+", "", q, flags=re.IGNORECASE).strip()
        if len(q) >= 2:
            return q
    # "encontrar/achar/find o vídeo/filme X" (opcionalmente "no Windows/PC")
    m = re.search(
        r"\b(?:encontrar|encontre|acha|achar|achou|buscar|busca|localizar|localiza|find)\s+"
        r"(?:o\s+|a\s+|um\s+|uma\s+)?(?:v[ií]deo|filme|movie|arquivo)?\s*(.+?)(?:\s+"
        r"(?:no|na|em|on)\s+(?:windows|pc|computador|downloads|v[ií]deos?))?\s*[?.!]*$",
        text,
        re.IGNORECASE,
    )
    if m:
        q = m.group(1).strip(" .,?!")
        q = re.sub(
            r"^(o|a|um|uma|v[ií]deo|filme|movie|arquivo)\s+",
            "",
            q,
            flags=re.IGNORECASE,
        ).strip()
        q = re.sub(r"\s+(?:no|na|em|on)\s+(?:windows|pc|computador).*$", "", q, flags=re.IGNORECASE).strip()
        if len(q) >= 2:
            return q
    # "tem o filme X" / "o vídeo X no Windows"
    m = re.search(
        r"\b(?:tem|existe|cad[eê])\s+(?:o\s+|a\s+)?(?:v[ií]deo|filme|movie)\s+(.+?)(?:\s+"
        r"(?:no|na|em)\s+(?:windows|pc))?\s*[?.!]*$",
        text,
        re.IGNORECASE,
    )
    if m:
        return m.group(1).strip(" .,?!")
    return None


def is_windows_find_video_request(message: str) -> bool:
    """Pedido de localizar vídeo/filme no Windows (sem necessariamente transferir)."""
    low = (message or "").lower()
    find_verb = bool(
        re.search(
            r"\b(encontrar|encontre|acha|achar|achou|buscar|busca|localizar|localiza|find|"
            r"caminho|path|onde\s+est[aá]|tem\s+o\s+(v[ií]deo|filme))\b",
            low,
        )
    )
    if not find_verb:
        return False
    # Evitar confundir com gravação de tela
    if re.search(r"\b(grava|gravar|filmagem|captura\s+de\s+tela)\b", low):
        return False
    media_cue = bool(re.search(r"\b(v[ií]deo|filme|movie|mkv|mp4|avi|arquivo)\b", low))
    win_cue = bool(re.search(r"\b(windows|pc|computador|downloads|v[ií]deos?)\b", low))
    if media_cue or win_cue or extract_video_query(message):
        return True
    return False


def is_windows_to_debian_transfer_request(message: str) -> bool:
    low = (message or "").lower()
    if not re.search(r"\b(debian|linux|ravenna|servidor|m[aá]quina)\b", low):
        return False
    if not re.search(
        r"\b(envia|enviar|manda|mandar|transfere|transferir|copia|copiar|upload|sobe|subir)\b",
        low,
    ):
        return False
    return bool(
        re.search(r"\b(v[ií]deo|filme|movie|mkv|mp4|avi)\b", low) or extract_video_query(message)
    )


def is_subtitle_only_request(message: str) -> bool:
    """Pedido focado em baixar/juntar legenda — não é pipeline completo."""
    low = (message or "").lower()
    if not re.search(r"\b(legenda|legendas|subtitle|subtitles)\b", low):
        return False
    # Mux de dois/três arquivos (filme+dublado+legenda) NÃO é “só legenda”
    if is_media_mux_request(message):
        return False
    asks = bool(
        re.search(
            r"\b(baix\w*|download\w*|pega\w*|busca\w*|acha\w*|junt\w*|anexa\w*|coloca\w*|completa\w*)\b.{0,40}\b"
            r"(legenda|legendas|subtitle)",
            low,
        )
        or re.search(
            r"\b(legenda|legendas|subtitle).{0,40}\b(baix\w*|download\w*|pega\w*|junt\w*)",
            low,
        )
        or re.search(r"\b(s[oó]\s+(a\s+)?legenda|apenas\s+(a\s+)?legenda)\b", low)
    )
    if not asks:
        return False
    # Mux dual / juntar dois vídeos+áudio NÃO é “só legenda”
    if re.search(
        r"\b(junt\w*|mescla\w*|combin\w*).{0,60}\b(dois|2|tr[eê]s|3|v[ií]deos|videos|arquivos|dublad|original|faixas)\b",
        low,
    ):
        return False
    if re.search(
        r"\b((áudio|audio)\s+original).{0,100}\b(dublad)|(dublad).{0,100}\b((áudio|audio)\s+original)\b",
        low,
    ):
        return False
    # Bloqueia se também pediu envio/conversão/apagar explicitamente
    if re.search(
        r"\b(envia\w*|manda\w*\s+(pro|para)\s+(o\s+)?debian|transfere\w*|apaga\w*\s+(a\s+)?c[oó]pia|"
        r"conver\w*\s+(pra|para|em)|pipeline|plano\s+completo)\b",
        low,
    ):
        return False
    return True


def is_media_mux_request(message: str) -> bool:
    """Junta vídeos/áudios/legendas num MKV (dual + srt) — plano de mídia, não papo genérico."""
    low = (message or "").lower()
    if not re.search(r"\b(junt\w*|mescl\w*|combin\w*|mux(?:ar)?)\b", low):
        return False
    return bool(
        re.search(
            r"\b(mkv|v[ií]deos?|arquivos?|faixas?|áudios?|audios?|legendas?|dublad|original|"
            r"dois|2|tr[eê]s|3|ambos)\b",
            low,
        )
    )


def is_media_pipeline_request(message: str) -> bool:
    """Pedido multi-etapa real: achar+checar+converter+enviar+apagar — não contexto casual."""
    if is_media_mux_request(message):
        return True
    if is_subtitle_only_request(message):
        return False
    low = (message or "").lower()
    steps = 0
    if is_windows_find_video_request(message) or (
        extract_video_query(message)
        and re.search(r"\b(acha\w*|localiz\w*|procura\w*|encontra\w*)\b", low)
    ):
        steps += 1
    # Áudio/legenda só conta se for ação de checar/completar — não menção de contexto
    if re.search(
        r"\b((checa|verificar|completa|completa\w*|junt\w*|tem)\b.{0,30}\b(áudio|audio|dublad|original|legenda|subtitle|faixa)|"
        r"(áudio|audio|dublad|original|legenda|subtitle).{0,30}\b(checa|verificar|completa|junt))\b",
        low,
    ):
        steps += 1
    # "mkv" sozinho (ex.: "preparando um mkv") NÃO conta — precisa verbo de conversão
    if re.search(r"\b(conver\w*|transcod\w*|handbrake|ffmpeg)\b", low):
        steps += 1
    if is_windows_to_debian_transfer_request(message) or re.search(
        r"\b(envia|enviar|manda|mandar|transfere).{0,40}\b(debian|linux)\b", low
    ):
        steps += 1
    if re.search(r"\b(apaga|apagar|deleta|deletar|remove|remover|exclui)\b.{0,40}\b(antiga|antigo|debian|c[oó]pia)\b", low):
        steps += 1
    return steps >= 2


def _format_bytes(n: int) -> str:
    x = float(max(0, n))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if x < 1024 or unit == "TB":
            return f"{x:.0f} {unit}" if unit == "B" else f"{x:.1f} {unit}"
        x /= 1024
    return f"{n} B"


def start_windows_video_transfer(*, query: str = "", windows_path: str = "") -> dict[str, Any]:
    """Localiza (se preciso) e inicia transferência em background."""
    from learning_agent.core import windows_agent_client as win

    q = (query or "").strip()
    path = (windows_path or "").strip()
    size = 0
    filename = ""
    matches: list[dict[str, Any]] = []

    if not path:
        if not q:
            return {"ok": False, "error": "informe o nome do vídeo"}
        found = win.find_files(q, kind="video")
        if not found.get("ok") and not found.get("matches"):
            return {
                "ok": False,
                "error": found.get("error") or "busca falhou no Windows",
                "matches": [],
            }
        matches = list(found.get("matches") or [])
        if not matches:
            return {
                "ok": False,
                "error": f'Não achei vídeo com “{q}” em Downloads/Vídeos/Desktop.',
                "matches": [],
            }
        best = matches[0]
        path = str(best.get("path") or "")
        size = int(best.get("size") or 0)
        filename = str(best.get("name") or Path(path).name)
    else:
        filename = Path(path.replace("\\", "/")).name

    if not path:
        return {"ok": False, "error": "caminho vazio"}

    VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r"[^\w.\- ()\[\]]+", "_", filename, flags=re.UNICODE)[:160] or "video.bin"
    dest = VIDEOS_DIR / safe_name
    # Retoma parcial incompleto do mesmo nome; só gera novo se já estiver completo.
    if dest.exists() and size > 0 and dest.stat().st_size >= size:
        dest = VIDEOS_DIR / f"{dest.stem}-{uuid.uuid4().hex[:6]}{dest.suffix}"
    elif dest.exists() and size > 0 and 0 < dest.stat().st_size < size:
        pass  # resume into existing partial
    elif dest.exists() and size <= 0:
        dest = VIDEOS_DIR / f"{dest.stem}-{uuid.uuid4().hex[:6]}{dest.suffix}"

    job_id = f"xfer-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
    job = {
        "id": job_id,
        "ok": True,
        "status": "starting",
        "query": q,
        "windows_path": path,
        "filename": safe_name,
        "dest_path": str(dest),
        "host_hint": str(VIDEOS_DIR),
        "bytes_done": 0,
        "bytes_total": size,
        "percent": 0.0,
        "eta_seconds": None,
        "bytes_per_sec": 0.0,
        "size_label": _format_bytes(size) if size else "?",
        "error": None,
        "matches_count": len(matches),
        "created_at": _utcnow(),
        "updated_at": _utcnow(),
        "started_monotonic": time.monotonic(),
    }
    with _jobs_lock:
        _jobs[job_id] = job
        _persist(job)

    threading.Thread(
        target=_run_transfer,
        args=(job_id, path, dest, size),
        name=f"xfer-{job_id}",
        daemon=True,
    ).start()
    return dict(job)


def _run_transfer(job_id: str, windows_path: str, dest: Path, known_size: int) -> None:
    from learning_agent.core import windows_agent_client as win

    _update(job_id, status="running", started_monotonic=time.monotonic())
    try:
        done = 0
        total = known_size
        if dest.exists():
            done = dest.stat().st_size
            if known_size and done >= known_size:
                _update(
                    job_id,
                    status="done",
                    bytes_done=done,
                    bytes_total=known_size,
                    percent=100.0,
                    eta_seconds=0,
                )
                return
            _update(job_id, bytes_done=done, bytes_total=total or known_size)

        headers = dict(win._headers())  # noqa: SLF001
        if done > 0:
            headers["Range"] = f"bytes={done}-"

        timeout = __import__("httpx").Timeout(60.0, connect=30.0, read=180.0)
        httpx = __import__("httpx")
        with httpx.stream(
            "GET",
            f"{win._base_url()}/file",  # noqa: SLF001
            params={"path": windows_path},
            headers=headers,
            timeout=timeout,
        ) as resp:
            if resp.status_code == 416:
                # Already complete according to server
                size = dest.stat().st_size if dest.exists() else done
                _update(job_id, status="done", bytes_done=size, bytes_total=size or total, percent=100.0, eta_seconds=0)
                return
            if resp.status_code not in {200, 206}:
                body = (resp.read() or b"")[:300].decode("utf-8", "replace")
                _update(job_id, status="error", error=f"HTTP {resp.status_code}: {body}")
                return
            cl = resp.headers.get("content-length")
            cr = resp.headers.get("content-range") or ""
            if cr.startswith("bytes ") and "/" in cr:
                try:
                    total = int(cr.rsplit("/", 1)[-1])
                except ValueError:
                    pass
            elif cl and str(cl).isdigit() and resp.status_code == 200:
                total = int(cl)
                done = 0  # full replace
            elif cl and str(cl).isdigit() and resp.status_code == 206:
                total = max(total, done + int(cl))
            if total:
                _update(job_id, bytes_total=total, size_label=_format_bytes(total))

            dest.parent.mkdir(parents=True, exist_ok=True)
            mode = "ab" if resp.status_code == 206 and done > 0 else "wb"
            if mode == "wb":
                done = 0
            last_persist = 0.0
            with dest.open(mode) as fh:
                for chunk in resp.iter_bytes(1024 * 1024):
                    if job_id in _cancel_xfer:
                        _cancel_xfer.discard(job_id)
                        _pause.discard(job_id)
                        fh.flush()
                        _update(
                            job_id,
                            status="cancelled",
                            bytes_done=done,
                            bytes_total=total or known_size or done,
                            error="cancelado",
                        )
                        return
                    while job_id in _pause:
                        _update(
                            job_id,
                            status="paused",
                            bytes_done=done,
                            bytes_total=total or known_size or done,
                        )
                        if job_id in _cancel_xfer:
                            break
                        time.sleep(0.5)
                    if job_id in _cancel_xfer:
                        _cancel_xfer.discard(job_id)
                        _pause.discard(job_id)
                        fh.flush()
                        _update(
                            job_id,
                            status="cancelled",
                            bytes_done=done,
                            bytes_total=total or known_size or done,
                            error="cancelado",
                        )
                        return
                    if not chunk:
                        continue
                    fh.write(chunk)
                    done += len(chunk)
                    now = time.monotonic()
                    if now - last_persist >= 0.5:
                        fh.flush()
                        _update(job_id, status="running", bytes_done=done, bytes_total=total or known_size or done)
                        last_persist = now
            _update(job_id, bytes_done=done, bytes_total=total or done)

        final_total = total or done
        if final_total and done < final_total:
            _update(
                job_id,
                status="error",
                error=f"transferência incompleta ({done}/{final_total})",
                bytes_done=done,
                bytes_total=final_total,
            )
            return
        _update(
            job_id,
            status="done",
            bytes_done=done,
            bytes_total=final_total or done,
            percent=100.0,
            eta_seconds=0,
            error=None,
            size_label=_format_bytes(final_total or done),
        )
    except Exception as exc:
        msg = f"{type(exc).__name__}: {exc}"
        low = msg.lower()
        if any(x in low for x in ("connect", "timeout", "refused", "unreachable", "10061", "network")):
            msg += (
                " — possível queda Tailscale/rede ou agent Windows offline. "
                "Use retomar quando voltar."
            )
        _update(job_id, status="error", error=msg)


def pause_transfer(job_id: str) -> dict[str, Any]:
    jid = (job_id or "").strip()
    if not jid:
        return {"ok": False, "error": "id obrigatório"}
    job = get_transfer(jid)
    if not job:
        return {"ok": False, "error": "transfer not found"}
    if job.get("status") not in {"running", "starting", "paused"}:
        return {"ok": False, "error": f"não dá para pausar em status={job.get('status')}"}
    _pause.add(jid)
    return {"ok": True, **(_update(jid, status="paused") or job)}


def resume_transfer(job_id: str) -> dict[str, Any]:
    """Retoma job pausado ou reinicia transferência incompleta/com erro de rede."""
    jid = (job_id or "").strip()
    if not jid:
        return {"ok": False, "error": "id obrigatório"}
    job = get_transfer(jid)
    if not job:
        return {"ok": False, "error": "transfer not found"}
    status = str(job.get("status") or "")
    if status == "paused":
        _pause.discard(jid)
        return {"ok": True, **(_update(jid, status="running", error=None) or job)}
    if status in {"error", "cancelled"}:
        path = str(job.get("windows_path") or "")
        dest = Path(str(job.get("dest_path") or ""))
        size = int(job.get("bytes_total") or 0)
        if not path or not dest:
            return {"ok": False, "error": "job sem path/dest para retomar"}
        _pause.discard(jid)
        _cancel_xfer.discard(jid)
        _update(jid, status="starting", error=None)
        threading.Thread(
            target=_run_transfer,
            args=(jid, path, dest, size),
            name=f"xfer-resume-{jid}",
            daemon=True,
        ).start()
        return {"ok": True, **(get_transfer(jid) or job)}
    return {"ok": False, "error": f"status={status} não retomável"}


def cancel_transfer(job_id: str) -> dict[str, Any]:
    jid = (job_id or "").strip()
    if not jid:
        return {"ok": False, "error": "id obrigatório"}
    job = get_transfer(jid)
    if not job:
        return {"ok": False, "error": "transfer not found"}
    _cancel_xfer.add(jid)
    _pause.discard(jid)
    return {"ok": True, **(_update(jid, status="cancelling") or job)}
