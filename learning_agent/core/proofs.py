"""Provas reais — verifica que cada ação de aprendizado funcionou de verdade."""

import json
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from learning_agent import db
from learning_agent.config import AUTO_PROOFS, PROJECT_ROOT, SUPABASE_KEY, SUPABASE_URL
from learning_agent import rag
from learning_agent import sync


def _check(name: str, passed: bool, detail: str = "") -> dict[str, Any]:
    return {"check": name, "passed": passed, "detail": detail}


def prove_distillation_pair_exists(pair_id: int) -> dict[str, Any]:
    db.init_db()
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT id, topic, similarity_score FROM distillation_pairs WHERE id = ?",
            (pair_id,),
        ).fetchone()
    if not row:
        return _check("distillation_pair", False, f"Pair {pair_id} não encontrado")
    return _check(
        "distillation_pair",
        True,
        f"Pair #{pair_id}: {row['topic'][:50]} (similarity={row['similarity_score']})",
    )


def prove_quiz_attempt_exists(quiz_item_id: int) -> dict[str, Any]:
    db.init_db()
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT id, correct, attempted_at FROM quiz_attempts WHERE quiz_item_id = ? ORDER BY id DESC LIMIT 1",
            (quiz_item_id,),
        ).fetchone()
    if not row:
        return _check("quiz_attempt_in_sqlite", False, f"Nenhuma tentativa para quiz #{quiz_item_id}")
    return _check(
        "quiz_attempt_in_sqlite",
        True,
        f"Tentativa #{row['id']} (correct={row['correct']}) em {row['attempted_at']}",
    )


def prove_note_exists(note_id: int) -> dict[str, Any]:
    db.init_db()
    with db.get_connection() as conn:
        row = conn.execute("SELECT id, title, content FROM learning_notes WHERE id = ?", (note_id,)).fetchone()
    if not row:
        return _check("note_in_sqlite", False, f"Nota {note_id} não encontrada")
    return _check("note_in_sqlite", True, f"Nota #{note_id}: {row['title'][:60]}")


def prove_file_exists(relative_path: str) -> dict[str, Any]:
    path = PROJECT_ROOT / relative_path.replace("/", "\\") if "\\" not in relative_path else PROJECT_ROOT / relative_path
    if not path.exists():
        path = PROJECT_ROOT / relative_path
    if not path.exists():
        return _check("file_on_disk", False, f"Arquivo não existe: {relative_path}")
    size = path.stat().st_size
    return _check("file_on_disk", True, f"{relative_path} ({size} bytes)")


def prove_rag_finds(title: str, min_results: int = 1) -> dict[str, Any]:
    # Busca por palavras-chave do título
    words = [w for w in re.split(r"\W+", title) if len(w) >= 4][:3]
    query = " ".join(words) if words else title[:40]
    results = rag.search_knowledge(query, limit=5)
    passed = len(results) >= min_results
    return _check(
        "rag_search",
        passed,
        f"Query '{query}' -> {len(results)} resultado(s)"
        + (f" | top: {results[0].get('id', '')}" if results else ""),
    )


def prove_local_drive_backup(max_age_hours: int = 72) -> dict[str, Any]:
    """Backup recente em pasta Google Drive / OneDrive (LOCAL_BACKUP_DIR)."""
    from learning_agent.scripts import backup_local

    root = backup_local.resolve_backup_root()
    if not root.parent.exists():
        return _check(
            "cloud_sync",
            True,
            "Backup Drive não configurado — modo local-only",
        )

    dirs = sorted(
        (p for p in root.iterdir() if p.is_dir() and p.name[:4].isdigit()),
        key=lambda p: p.name,
        reverse=True,
    )
    if not dirs:
        return _check("cloud_sync", False, f"Nenhum backup em {root}")

    latest = dirs[0]
    manifest_path = latest / backup_local.BACKUP_MANIFEST
    if not manifest_path.is_file():
        return _check("cloud_sync", False, f"Manifest ausente: {latest.name}")

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return _check("cloud_sync", False, f"Manifest inválido: {exc}")

    created = manifest.get("created_at", "")
    age_h = 9999.0
    if created:
        try:
            ts = datetime.fromisoformat(created.replace("Z", "+00:00"))
            age_h = (datetime.now(timezone.utc) - ts).total_seconds() / 3600
        except ValueError:
            pass

    sqlite_mb = round(manifest.get("sqlite_bytes", 0) / 1024 / 1024, 2)
    passed = age_h <= max_age_hours
    detail = (
        f"Drive: {latest.name} · {sqlite_mb} MB SQLite · "
        f"{len(manifest.get('state_files', []))} state file(s) · "
        f"idade {age_h:.0f}h (limite {max_age_hours}h)"
    )
    return _check("cloud_sync", passed, detail)


def prove_cloud_snapshot() -> dict[str, Any]:
    if not sync.is_configured():
        return prove_local_drive_backup()

    try:
        with httpx.Client(timeout=20.0) as client:
            response = client.get(
                f"{SUPABASE_URL.rstrip('/')}/rest/v1/learning_snapshots?id=eq.default&select=data",
                headers={
                    "apikey": SUPABASE_KEY,
                    "Authorization": f"Bearer {SUPABASE_KEY}",
                },
            )
        if response.status_code >= 400:
            return _check("cloud_sync", False, f"HTTP {response.status_code}")

        rows = response.json()
        if not rows:
            return _check("cloud_sync", False, "Snapshot 'default' não existe na nuvem")

        cloud_notes = len(rows[0]["data"].get("notes", []))
        db.init_db()
        with db.get_connection() as conn:
            local_notes = conn.execute("SELECT COUNT(*) FROM learning_notes").fetchone()[0]

        drift = abs(cloud_notes - local_notes)
        passed = cloud_notes >= local_notes or drift <= 5
        return _check(
            "cloud_sync",
            passed,
            f"Nuvem: {cloud_notes} notas | Local: {local_notes} notas (drift={drift})",
        )
    except Exception as exc:
        return _check("cloud_sync", False, str(exc))


def prove_python_runs(code: str, expected_in_output: str = "") -> dict[str, Any]:
    """Executa código Python real e verifica saída (prova prática)."""
    if not code.strip():
        return _check("python_exec", False, "Código vazio")

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as tmp:
        tmp.write(code)
        tmp_path = tmp.name

    try:
        result = subprocess.run(
            [sys.executable, tmp_path],
            capture_output=True,
            text=True,
            timeout=15,
            cwd=str(PROJECT_ROOT),
        )
        passed = result.returncode == 0
        detail = f"exit={result.returncode}"
        if result.stdout.strip():
            detail += f" | stdout: {result.stdout.strip()[:200]}"
        if result.stderr.strip():
            detail += f" | stderr: {result.stderr.strip()[:200]}"
        if expected_in_output and expected_in_output not in result.stdout:
            passed = False
            detail += f" | esperado '{expected_in_output}' não encontrado"
        return _check("python_exec", passed, detail)
    except subprocess.TimeoutExpired:
        return _check("python_exec", False, "Timeout (>15s)")
    except Exception as exc:
        return _check("python_exec", False, str(exc))
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def prove_learning_result(result: dict[str, Any]) -> dict[str, Any]:
    """Roda provas reais sobre o resultado de fetch_and_learn / add_note / etc."""
    checks: list[dict[str, Any]] = []

    if note_id := result.get("note_id"):
        checks.append(prove_note_exists(note_id))

    if doc_path := result.get("doc_path"):
        checks.append(prove_file_exists(doc_path))

    if title := result.get("title"):
        checks.append(prove_rag_finds(title))

    if session_id := result.get("session_id"):
        db.init_db()
        with db.get_connection() as conn:
            row = conn.execute(
                "SELECT id FROM agent_sessions WHERE id = ?", (session_id,)
            ).fetchone()
        checks.append(_check("session_in_sqlite", bool(row), f"Sessão #{session_id}"))

    if error_id := result.get("error_id"):
        db.init_db()
        with db.get_connection() as conn:
            row = conn.execute(
                "SELECT id FROM learning_errors WHERE id = ?", (error_id,)
            ).fetchone()
        checks.append(_check("error_in_sqlite", bool(row), f"Erro #{error_id}"))

    if pair_id := result.get("pair_id"):
        checks.append(prove_distillation_pair_exists(pair_id))

    if quiz_item_id := result.get("quiz_item_id"):
        checks.append(prove_quiz_attempt_exists(quiz_item_id))

    if result.get("cloud_sync", {}).get("success") and not result.get("cloud_sync", {}).get("skipped"):
        checks.append(prove_cloud_snapshot())

    passed = all(c["passed"] for c in checks) if checks else False
    return {
        "all_passed": passed,
        "total": len(checks),
        "passed_count": sum(1 for c in checks if c["passed"]),
        "checks": checks,
    }


def prove_search_and_learn_result(result: dict[str, Any]) -> dict[str, Any]:
    all_checks: list[dict[str, Any]] = []
    for item in result.get("learned", []):
        proof = prove_learning_result(item)
        all_checks.append({"item": item.get("title", ""), **proof})

    overall = all(p.get("all_passed", False) for p in all_checks) if all_checks else False
    return {
        "all_passed": overall,
        "items_proved": len(all_checks),
        "items": all_checks,
    }


def run_full_proof_suite() -> dict[str, Any]:
    """Suite completa — como um 'health check' com provas reais."""
    checks: list[dict[str, Any]] = []

    # 1. SQLite
    db.init_db()
    try:
        with db.get_connection() as conn:
            count = conn.execute("SELECT COUNT(*) FROM learning_notes").fetchone()[0]
        checks.append(_check("sqlite", True, f"{count} notas"))
    except Exception as exc:
        checks.append(_check("sqlite", False, str(exc)))

    # 2. RAG (Windows: RAG_DISABLE_CHROMA=true no stack overnight/API — skip, como cloud)
    if rag.chroma_disabled():
        checks.append(
            _check("chromadb", True, "Chroma desabilitado (RAG_DISABLE_CHROMA) — ignorado"),
        )
    else:
        try:
            results = rag.search_knowledge("python", limit=1)
            checks.append(_check("chromadb", len(results) > 0, f"{len(results)} hit(s) para 'python'"))
        except Exception as exc:
            checks.append(_check("chromadb", False, str(exc)))

    # 3. Backup (Supabase se ativo; senão Google Drive / OneDrive)
    checks.append(prove_cloud_snapshot())

    # 4. Python exec smoke test
    checks.append(prove_python_runs('print("proof_ok")', expected_in_output="proof_ok"))

    passed = all(c["passed"] for c in checks)
    return {
        "all_passed": passed,
        "total": len(checks),
        "passed_count": sum(1 for c in checks if c["passed"]),
        "checks": checks,
    }


def attach_proofs(result: dict[str, Any]) -> dict[str, Any]:
    """Anexa provas reais ao resultado de uma operação de aprendizado."""
    if not AUTO_PROOFS:
        return result

    if "learned" in result:
        result["proofs"] = prove_search_and_learn_result(result)
    else:
        result["proofs"] = prove_learning_result(result)

    result["verified"] = result["proofs"].get("all_passed", False)

    if result.get("verified") is False:
        try:
            from learning_agent.core import errors as errors_core

            failure = errors_core.maybe_record_from_result(result)
            if failure:
                result["failure_recorded"] = failure.get("error_id")
        except Exception:
            pass

    return result
