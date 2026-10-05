"""HTTP client for Ravenna Windows Agent (PC_DO_LUIS via Tailscale)."""

from __future__ import annotations

import base64
import json
import os
import re
from typing import Any, Iterator

import httpx

DEFAULT_URL = "http://<PC_TAILSCALE_IP>:8780"
DEFAULT_TOKEN = "ravenna-win-agent-2026"


def _base_url() -> str:
    return (os.environ.get("WINDOWS_AGENT_URL") or DEFAULT_URL).rstrip("/")


def _token() -> str:
    return (
        os.environ.get("WINDOWS_AGENT_TOKEN")
        or os.environ.get("RAVENNA_WINDOWS_AGENT_TOKEN")
        or DEFAULT_TOKEN
    )


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_token()}"}


def _post(path: str, payload: dict[str, Any], *, timeout: float = 90.0) -> dict[str, Any]:
    try:
        with httpx.Client(timeout=timeout) as client:
            r = client.post(f"{_base_url()}{path}", json=payload, headers=_headers())
        if r.status_code >= 400:
            return {"ok": False, "error": r.text[:500], "status_code": r.status_code}
        data = r.json()
        if isinstance(data, dict):
            data.setdefault("ok", True)
            data["target"] = "windows"
        return data
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "target": "windows"}


def _tool_media_payload(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": True,
        "media_id": record.get("id"),
        "media_url": record.get("url"),
        "media_type": record.get("type"),
        "filename": record.get("filename"),
        "mime": record.get("mime"),
        "size": record.get("size"),
        "source": record.get("source"),
    }


def pull_file_to_media(windows_path: str) -> dict[str, Any]:
    from learning_agent.core.chat_media import save_media_stream

    path = (windows_path or "").strip()
    if not path:
        return {"ok": False, "error": "path obrigatório", "target": "windows"}
    fname = path.replace("\\", "/").split("/")[-1] or "arquivo.bin"
    try:
        timeout = httpx.Timeout(30.0, read=None)
        with httpx.stream(
            "GET",
            f"{_base_url()}/file",
            params={"path": path},
            headers=_headers(),
            timeout=timeout,
        ) as r:
            if r.status_code >= 400:
                return {"ok": False, "error": r.text[:500], "status_code": r.status_code, "target": "windows"}

            def _iter() -> Iterator[bytes]:
                for chunk in r.iter_bytes(1024 * 1024):
                    yield chunk

            record = save_media_stream(_iter(), fname, source="windows")
            out = _tool_media_payload(record)
            out["windows_path"] = path
            out["target"] = "windows"
            return out
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "target": "windows"}


def find_files(query: str, *, kind: str = "video", max_results: int = 12) -> dict[str, Any]:
    data = _post(
        "/find-files",
        {"query": query, "kind": kind, "max_results": max_results},
        timeout=120.0,
    )
    if not isinstance(data, dict):
        return {"ok": False, "error": "resposta inválida", "matches": []}
    data.setdefault("matches", [])
    data.setdefault("ok", True)
    data["target"] = "windows"
    return data


def probe_media(windows_path: str) -> dict[str, Any]:
    data = _post("/probe-media", {"path": windows_path}, timeout=120.0)
    if not isinstance(data, dict):
        return {"ok": False, "error": "resposta inválida"}
    data["target"] = "windows"
    return data


def convert_media(windows_path: str, *, output_path: str = "", container: str = "mkv") -> dict[str, Any]:
    data = _post(
        "/convert-media",
        {"path": windows_path, "output_path": output_path, "container": container},
        timeout=3600.0,
    )
    if not isinstance(data, dict):
        return {"ok": False, "error": "resposta inválida"}
    data["target"] = "windows"
    return data


def enrich_media(
    windows_path: str,
    *,
    query: str = "",
    want_original_audio: bool = True,
    want_dubbed_audio: bool = False,
    want_subtitles: bool = True,
    subtitle_languages: str = "pt-BR,en",
    opensubtitles_api_key: str = "",
    opensubtitles_username: str = "",
    opensubtitles_password: str = "",
) -> dict[str, Any]:
    data = _post(
        "/enrich-media",
        {
            "path": windows_path,
            "query": query,
            "want_original_audio": want_original_audio,
            "want_dubbed_audio": want_dubbed_audio,
            "want_subtitles": want_subtitles,
            "subtitle_languages": subtitle_languages,
            "opensubtitles_api_key": opensubtitles_api_key,
            "opensubtitles_username": opensubtitles_username,
            "opensubtitles_password": opensubtitles_password,
        },
        timeout=3600.0,
    )
    if not isinstance(data, dict):
        return {"ok": False, "error": "resposta inválida"}
    data["target"] = "windows"
    return data


def delete_file(windows_path: str) -> dict[str, Any]:
    data = _post("/delete-file", {"path": windows_path}, timeout=60.0)
    if not isinstance(data, dict):
        return {"ok": False, "error": "resposta inválida"}
    data["target"] = "windows"
    return data


def open_stream_file(windows_path: str):
    """Context manager helper: retorna (response, headers) — caller itera bytes."""
    path = (windows_path or "").strip()
    timeout = httpx.Timeout(60.0, read=None)
    return httpx.stream(
        "GET",
        f"{_base_url()}/file",
        params={"path": path},
        headers=_headers(),
        timeout=timeout,
    )


def status() -> dict[str, Any]:
    try:
        with httpx.Client(timeout=15.0) as client:
            r = client.get(f"{_base_url()}/status", headers=_headers())
        if r.status_code >= 400:
            return {"ok": False, "error": r.text[:300]}
        return r.json()
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def health() -> dict[str, Any]:
    try:
        with httpx.Client(timeout=10.0) as client:
            r = client.get(f"{_base_url()}/health")
        return r.json() if r.status_code < 400 else {"ok": False}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def open_app(name: str) -> dict[str, Any]:
    """Abre app no Windows; Opera GX resolve path real (Start-Process 'opera' falha)."""
    key = (name or "").strip().lower()
    if key in {"opera", "opera gx"}:
        # Paths comuns + fallback Start-Process pelo atalho do menu
        script = (
            "$cands = @("
            "[IO.Path]::Combine($env:LOCALAPPDATA, \"Programs\", \"Opera GX\", \"opera.exe\"), "
            "[IO.Path]::Combine($env:LOCALAPPDATA, \"Programs\", \"Opera\", \"opera.exe\"), "
            "[IO.Path]::Combine($env:ProgramFiles, \"Opera\", \"opera.exe\"), "
            "[IO.Path]::Combine([Environment]::GetEnvironmentVariable(\"ProgramFiles(x86)\"), \"Opera\", \"opera.exe\")"
            "); "
            "$exe = $cands | Where-Object { Test-Path $_ } | Select-Object -First 1; "
            "if ($exe) { Start-Process -FilePath $exe; \"OPENED \" + $exe } "
            "else { "
            "$cmd = Get-Command opera -ErrorAction SilentlyContinue; "
            "if ($cmd) { Start-Process -FilePath $cmd.Source; \"OPENED \" + $cmd.Source } "
            "else { throw \"opera.exe nao encontrado\" } "
            "}"
        )
        assert "'" not in script
        data = exec_command(script, timeout=45)
        out = str(data.get("output") or "")
        data["ok"] = bool(data.get("exit_code") == 0 and "OPENED" in out.upper())
        if not data["ok"]:
            data["error"] = out[:240] or "falha ao abrir Opera"
        data["target"] = "windows"
        return data
    return _post("/open-app", {"name": name})


_CLOSE_IMAGE = {
    "chrome": "chrome.exe",
    "google chrome": "chrome.exe",
    "edge": "msedge.exe",
    "firefox": "firefox.exe",
    "opera": "opera.exe",
    "opera gx": "opera.exe",
    "brave": "brave.exe",
    "cursor": "Cursor.exe",
    "discord": "Discord.exe",
    "notepad": "notepad.exe",
    "bloco de notas": "notepad.exe",
    "calculadora": "CalculatorApp.exe",
    "calc": "CalculatorApp.exe",
    "spotify": "Spotify.exe",
    "explorer": "explorer.exe",
}


def close_app(name: str) -> dict[str, Any]:
    result = _post("/close-app", {"name": name})
    if result.get("status_code") == 404:
        key = (name or "").strip().lower()
        image = _CLOSE_IMAGE.get(key, name.strip())
        if not image.lower().endswith(".exe"):
            image = f"{image}.exe"
        image = image.replace("'", "")
        fallback = exec_command(f"taskkill /IM {image} /F", timeout=30)
        fallback["via"] = "exec-fallback"
        if fallback.get("exit_code") == 0 or "SUCCESS" in str(fallback.get("output") or "").upper():
            fallback["ok"] = True
        return fallback
    return result


_PS_CLOSE_SCOPED = r"""
param([string]$FilterProc = "opera", [string]$OnlyState = "min")
Add-Type @"
using System;
using System.Text;
using System.Collections.Generic;
using System.Runtime.InteropServices;
public class RavenWinClose {
  public delegate bool EnumProc(IntPtr h, IntPtr l);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc lp, IntPtr l);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr h);
  [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern int GetWindowTextLength(IntPtr h);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr h, uint Msg, IntPtr w, IntPtr l);
  const uint WM_CLOSE = 0x0010;
  public static List<string> ListCands() {
    var rows = new List<string>();
    EnumWindows((h, l) => {
      uint pid; GetWindowThreadProcessId(h, out pid);
      bool vis = IsWindowVisible(h);
      bool mini = IsIconic(h);
      if (!vis && !mini) return true;
      string state = mini ? "min" : "vis";
      int len = GetWindowTextLength(h);
      if (len <= 0 && !mini) return true;
      var sb = new StringBuilder(Math.Max(len, 1) + 1);
      GetWindowText(h, sb, sb.Capacity);
      string title = sb.ToString();
      if (string.IsNullOrWhiteSpace(title) && !mini) return true;
      if (string.IsNullOrWhiteSpace(title)) title = "(sem titulo)";
      rows.Add(pid.ToString() + "\t" + ((long)h).ToString() + "\t" + state + "\t" + title);
      return true;
    }, IntPtr.Zero);
    return rows;
  }
  public static bool CloseHwnd(long hwnd) {
    return PostMessage((IntPtr)hwnd, WM_CLOSE, IntPtr.Zero, IntPtr.Zero);
  }
}
"@
$filter = ($FilterProc + "").Trim().ToLower()
$only = ($OnlyState + "").Trim().ToLower()
$cands = [RavenWinClose]::ListCands()
$out = New-Object System.Collections.Generic.List[string]
$n = 0
foreach ($row in $cands) {
  $parts = $row.Split([char]9)
  if ($parts.Length -lt 4) { continue }
  $procId = [int]$parts[0]
  try { $pn = (Get-Process -Id $procId -ErrorAction Stop).ProcessName } catch { continue }
  $pnLower = $pn.ToLower()
  if (-not ($pnLower -eq $filter -or $pnLower.StartsWith($filter))) { continue }
  $state = $parts[2]
  if ($only -eq "min" -and $state -ne "min") { continue }
  if ($only -eq "vis" -and $state -ne "vis") { continue }
  $hwnd = [int64]$parts[1]
  $ok = [RavenWinClose]::CloseHwnd($hwnd)
  if ($ok) {
    $n++
    $out.Add(("CLOSED`t" + $state + "`t" + $parts[3]))
  }
}
if ($n -eq 0) { "NONE" } else { ("COUNT " + $n.ToString()); ($out -join [char]10) }
"""


def close_windows(name: str, *, only_state: str = "all") -> dict[str, Any]:
    """Fecha janelas por escopo (min/vis/all). min/vis usam WM_CLOSE; all mata o processo."""
    import base64

    proc = (name or "").strip().lower()
    if proc.startswith("opera"):
        proc = "opera"
    elif proc in {"google chrome", "chrome"}:
        proc = "chrome"
    elif proc in {"edge", "msedge"}:
        proc = "msedge"
    proc = re.sub(r"[^a-z0-9_-]", "", proc)[:40]
    state = (only_state or "all").strip().lower()
    if state not in {"min", "vis", "all"}:
        state = "all"
    if state == "all":
        return close_app(name)

    b64 = base64.b64encode(_PS_CLOSE_SCOPED.encode("utf-8")).decode("ascii")
    outer = (
        f"$b={json.dumps(b64)}; "
        "$bytes=[Convert]::FromBase64String($b); "
        "$script=[Text.Encoding]::UTF8.GetString($bytes); "
        f"& ([scriptblock]::Create($script)) -FilterProc {json.dumps(proc)} -OnlyState {json.dumps(state)}"
    )
    data = exec_command(outer, timeout=60)
    out = str(data.get("output") or "").strip()
    closed: list[dict[str, str]] = []
    count = 0
    for line in out.splitlines():
        if line.startswith("COUNT "):
            try:
                count = int(line.split(" ", 1)[1])
            except ValueError:
                pass
        elif line.startswith("CLOSED\t"):
            parts = line.split("\t")
            if len(parts) >= 3:
                closed.append({"state": parts[1], "title": parts[2]})
    data["closed"] = closed
    data["count"] = count or len(closed)
    data["filter"] = proc
    data["only_state"] = state
    data["ok"] = bool(data.get("exit_code") == 0 and data["count"] > 0 and "caractere:" not in out.lower())
    if not data["ok"] and "NONE" in out.upper():
        data["error"] = f"Nenhuma janela {state} de {proc} para fechar"
    return data


def open_url(url: str) -> dict[str, Any]:
    return _post("/open-url", {"url": url})


def search_youtube(query: str) -> dict[str, Any]:
    result = _post("/search-youtube", {"query": query})
    if result.get("status_code") == 404:
        from urllib.parse import quote

        q = quote((query or "").strip())
        return open_url(f"https://www.youtube.com/results?search_query={q}")
    return result


def search_google(query: str) -> dict[str, Any]:
    result = _post("/search-google", {"query": query})
    if result.get("status_code") == 404:
        from urllib.parse import quote

        q = quote((query or "").strip())
        return open_url(f"https://www.google.com/search?q={q}")
    return result


def download_url(url: str) -> dict[str, Any]:
    from urllib.parse import unquote, urlparse

    raw = (url or "").strip()
    if not raw.startswith(("http://", "https://")):
        return {"ok": False, "error": "url deve ser http(s)"}
    name = unquote(urlparse(raw).path.rstrip("/").split("/")[-1] or "download.bin")
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name)[:80] or "download.bin"
    escaped = raw.replace("'", "''")
    fname = name.replace("'", "")
    script = (
        f"$out = Join-Path $home 'Downloads\\{fname}'; "
        f"curl.exe -L --fail -o $out '{escaped}'; "
        "if (Test-Path $out) { 'SAVED ' + $out } else { throw 'download failed' }"
    )
    data = exec_command(script, timeout=120)
    data["filename"] = fname
    out = str(data.get("output") or "")
    saved_path = ""
    if "SAVED " in out:
        saved_path = out.split("SAVED ", 1)[-1].strip().splitlines()[0].strip()
        data["saved_path"] = saved_path
    data["ok"] = bool(data.get("exit_code") == 0 and saved_path)
    return data


def exec_command(command: str, *, timeout: int = 120) -> dict[str, Any]:
    return _post("/exec", {"command": command, "timeout": timeout}, timeout=float(timeout + 10))


def list_dir(path: str) -> dict[str, Any]:
    data = _post("/list-dir", {"path": path}, timeout=60.0)
    data["ok"] = bool(data.get("ok") or data.get("exit_code") == 0)
    return data


# EnumWindows + UI Automation (abas). Enviado via base64 para o /exec não corromper aspas.
_PS_LIST_WINDOWS = r"""
param([string]$FilterProc = "", [switch]$IncludeTabs)
Add-Type @"
using System;
using System.Text;
using System.Collections.Generic;
using System.Runtime.InteropServices;
public class RavenWinEnum {
  public delegate bool EnumProc(IntPtr h, IntPtr l);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc lp, IntPtr l);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern int GetWindowTextLength(IntPtr h);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr h);
  public static List<string> ListAll() {
    var rows = new List<string>();
    EnumWindows((h, l) => {
      uint pid; GetWindowThreadProcessId(h, out pid);
      bool vis = IsWindowVisible(h);
      bool mini = IsIconic(h);
      if (!vis && !mini) return true;
      int len = GetWindowTextLength(h);
      var sb = new StringBuilder(Math.Max(len, 1) + 1);
      GetWindowText(h, sb, sb.Capacity);
      string title = sb.ToString();
      if (string.IsNullOrWhiteSpace(title)) {
        if (!mini) return true;
        title = "(sem titulo)";
      }
      string state = mini ? "min" : "vis";
      rows.Add(pid.ToString() + "\t" + ((long)h).ToString() + "\t" + state + "\t" + title);
      return true;
    }, IntPtr.Zero);
    return rows;
  }
}
"@
$filter = ($FilterProc + "").Trim().ToLower()
$all = [RavenWinEnum]::ListAll()
$wins = New-Object System.Collections.Generic.List[string]
foreach ($row in $all) {
  $parts = $row.Split([char]9, 4)
  if ($parts.Length -lt 4) { continue }
  $procId = [int]$parts[0]
  try { $pn = (Get-Process -Id $procId -ErrorAction Stop).ProcessName } catch { continue }
  $pnLower = $pn.ToLower()
  if ($filter) {
    if (-not ($pnLower -eq $filter -or $pnLower.StartsWith($filter))) { continue }
  } else {
    # ruído de sistema
    if ($pnLower -in @("dwm","textinputhost","shellexperiencehost","searchhost","applicationframehost")) { continue }
  }
  $wins.Add(("WIN`t" + $procId.ToString() + "`t" + $pn + "`t" + $parts[1] + "`t" + $parts[2] + "`t" + $parts[3]))
}
if ($wins.Count -eq 0) { "NONE" } else { $wins -join [char]10 }

if ($IncludeTabs) {
  "---TABS---"
  try {
    Add-Type -AssemblyName UIAutomationClient
    Add-Type -AssemblyName UIAutomationTypes
    $root = [System.Windows.Automation.AutomationElement]::RootElement
    $cond = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ControlTypeProperty, [System.Windows.Automation.ControlType]::Window)
    $uwins = $root.FindAll([System.Windows.Automation.TreeScope]::Children, $cond)
    $tabsOut = New-Object System.Collections.Generic.List[string]
    foreach ($w in $uwins) {
      $wname = [string]$w.Current.Name
      $procId = [int]$w.Current.ProcessId
      try { $pn = (Get-Process -Id $procId -ErrorAction Stop).ProcessName } catch { continue }
      $pnLower = $pn.ToLower()
      if ($filter) {
        if (-not ($pnLower -eq $filter -or $pnLower.StartsWith($filter))) { continue }
      } else {
        if ($pnLower -notmatch "^(opera|chrome|msedge|firefox|brave)") { continue }
      }
      $tabCond = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ControlTypeProperty, [System.Windows.Automation.ControlType]::TabItem)
      $tabs = $w.FindAll([System.Windows.Automation.TreeScope]::Descendants, $tabCond)
      foreach ($t in $tabs) {
        $tn = [string]$t.Current.Name
        if (-not [string]::IsNullOrWhiteSpace($tn)) {
          $tabsOut.Add(("TAB`t" + $procId.ToString() + "`t" + $pn + "`t" + $wname + "`t" + $tn))
        }
      }
    }
    if ($tabsOut.Count -eq 0) { "TABS_NONE" } else { $tabsOut -join [char]10 }
  } catch {
    "TABS_ERR"
  }
}
"""


def list_windows(name: str = "", *, include_tabs: bool = True) -> dict[str, Any]:
    """Lista janelas top-level (visíveis + minimizadas) e, se pedido, abas de browser via UIA."""
    import base64

    proc = (name or "").strip().lower()
    if proc.startswith("opera"):
        proc = "opera"
    elif proc in {"google chrome", "chrome"}:
        proc = "chrome"
    elif proc in {"edge", "msedge"}:
        proc = "msedge"
    proc = re.sub(r"[^a-z0-9_-]", "", proc)[:40]

    # Monta chamada sem aspas simples no comando enviado ao /exec.
    b64 = base64.b64encode(_PS_LIST_WINDOWS.encode("utf-8")).decode("ascii")
    tabs_flag = "$true" if include_tabs else "$false"
    filter_json = json.dumps(proc)
    outer = (
        f"$b={json.dumps(b64)}; "
        "$bytes=[Convert]::FromBase64String($b); "
        "$script=[Text.Encoding]::UTF8.GetString($bytes); "
        f"& ([scriptblock]::Create($script)) -FilterProc {filter_json} -IncludeTabs:{tabs_flag}"
    )
    data = exec_command(outer, timeout=90)
    out = str(data.get("output") or "").strip()
    windows: list[dict[str, Any]] = []
    tabs: list[dict[str, str]] = []
    section = "wins"
    if out and out.upper() != "NONE" and "caractere:" not in out.lower():
        for line in out.splitlines():
            line = line.strip()
            if not line:
                continue
            if line == "---TABS---":
                section = "tabs"
                continue
            if line in {"TABS_NONE", "TABS_ERR", "NONE"}:
                continue
            if section == "wins" and line.startswith("WIN\t"):
                parts = line.split("\t")
                if len(parts) >= 6:
                    windows.append(
                        {
                            "id": parts[1],
                            "process": parts[2],
                            "hwnd": parts[3],
                            "state": parts[4],  # vis | min
                            "title": parts[5],
                        }
                    )
            elif section == "tabs" and line.startswith("TAB\t"):
                parts = line.split("\t")
                if len(parts) >= 5:
                    tabs.append(
                        {
                            "id": parts[1],
                            "process": parts[2],
                            "window_title": parts[3],
                            "tab": parts[4],
                        }
                    )
    # Anexa abas à janela correspondente (por pid + título da janela).
    for w in windows:
        w_tabs = [
            t["tab"]
            for t in tabs
            if t.get("id") == w.get("id")
            and (
                not t.get("window_title")
                or t.get("window_title") == w.get("title")
                or (w.get("title") or "") in (t.get("window_title") or "")
                or (t.get("window_title") or "") in (w.get("title") or "")
            )
        ]
        # fallback: todas as abas do mesmo pid se match de título falhar
        if not w_tabs:
            w_tabs = [t["tab"] for t in tabs if t.get("id") == w.get("id")]
        # dedupe preservando ordem
        seen: set[str] = set()
        uniq: list[str] = []
        for t in w_tabs:
            if t not in seen:
                seen.add(t)
                uniq.append(t)
        w["tabs"] = uniq

    data["windows"] = windows
    data["tabs"] = tabs
    data["count"] = len(windows)
    data["tab_count"] = len(tabs)
    data["filter"] = proc
    data["ok"] = bool(data.get("exit_code") == 0) and "caractere:" not in out.lower()
    data["include_tabs"] = include_tabs
    return data


def read_file(path: str, *, max_bytes: int = 512_000) -> dict[str, Any]:
    data = _post("/read-file", {"path": path, "max_bytes": max_bytes}, timeout=90.0)
    if data.get("ok") and data.get("binary") and data.get("encoding") == "base64":
        ext = path.replace("\\", "/").split("/")[-1].lower()
        if ext.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")):
            pulled = pull_file_to_media(path)
            if pulled.get("ok"):
                return pulled
    return data


def screenshot(*, window_title: str = "", monitor: int = 0) -> dict[str, Any]:
    data = _post(
        "/screenshot",
        {"window_title": window_title, "monitor": monitor},
        timeout=120.0,
    )
    if not data.get("ok"):
        return data
    win_path = str(data.get("path") or "")
    if not win_path:
        return {"ok": False, "error": "screenshot sem path", "target": "windows"}
    pulled = pull_file_to_media(win_path)
    pulled["window_title"] = window_title
    pulled["monitor"] = monitor
    return pulled


def record_screen(*, seconds: int = 10, window_title: str = "") -> dict[str, Any]:
    data = _post(
        "/record-screen",
        {"seconds": seconds, "window_title": window_title},
        timeout=float(max(120, seconds + 90)),
    )
    if not data.get("ok"):
        return data
    win_path = str(data.get("path") or "")
    if not win_path:
        return {"ok": False, "error": "gravação sem path", "target": "windows"}
    pulled = pull_file_to_media(win_path)
    pulled["seconds"] = seconds
    return pulled


def send_media_to_downloads(media_id: str) -> dict[str, Any]:
    """Copia mídia hospedada na ravenna para Downloads do Windows."""
    from learning_agent.core.chat_media import resolve_media_path

    try:
        src = resolve_media_path(media_id)
    except Exception as exc:
        return {"ok": False, "error": str(exc), "target": "windows"}
    try:
        size = src.stat().st_size
    except OSError as exc:
        return {"ok": False, "error": str(exc), "target": "windows"}
    fname = src.name.split("-", 2)[-1] if src.name.count("-") >= 2 else src.name
    fname = re.sub(r"[^\w.\-]", "_", fname)[:80] or "arquivo.bin"

    home_base = (os.environ.get("RAVENNA_HOME_PUBLIC_URL") or "http://<RAVENNA_TAILSCALE_IP>:8100").rstrip("/")
    home_token = (
        os.environ.get("RAVENNA_HOME_TOKEN")
        or os.environ.get("HOME_API_TOKEN")
        or ""
    ).strip()
    media_url = f"{home_base}/api/chat/media/{media_id}"
    auth_hdr = f'-H `"Authorization: Bearer {home_token}`"' if home_token else ""

    script = (
        f'$out = Join-Path $home "Downloads\\{fname}"; '
        f'curl.exe -L --fail {auth_hdr} -o $out "{media_url}"; '
        'if (Test-Path $out) { Write-Output ("SAVED " + $out) } else { throw "curl failed" }'
    )
    data = exec_command(script, timeout=max(180, size // 500_000 + 120))

    out = str(data.get("output") or "")
    saved = ""
    if "SAVED " in out:
        saved = out.split("SAVED ", 1)[-1].strip().splitlines()[0].strip()
    elif out and not data.get("error"):
        data["error"] = out[:500]
    data["saved_path"] = saved
    data["ok"] = bool(data.get("exit_code") == 0 and saved)
    data["filename"] = fname
    return data
