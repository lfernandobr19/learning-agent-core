#!/usr/bin/env python3
"""
Supervisão QA — agentes direcionam a Ravenna enquanto rodam todos os testes da IDE.

Uso:
  py -m learning_agent.scripts.run_ide_test_supervision
  py -m learning_agent.cli supervise-ide-tests
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "ravenna-ide" / "frontend"
DOC = ROOT / "docs" / "frontend" / "ide-testing-mastery.md"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from learning_agent.core import chat, knowledge, theater  # noqa: E402
from learning_agent.core.supervision_agents import SupervisionContext, broadcast_supervision_round  # noqa: E402

PY = sys.executable
NPM = "npm.cmd" if sys.platform == "win32" else "npm"
NPX = "npx.cmd" if sys.platform == "win32" else "npx"


def _npm_run(script: str) -> list[str]:
    return [NPM, "run", script]


@dataclass
class SuiteResult:
    suite_id: str
    name: str
    phase: str
    passed: bool
    skipped: bool = False
    detail: str = ""
    stdout: str = ""
    stderr: str = ""


@dataclass
class TestSuite:
    id: str
    name: str
    phase: str
    command: list[str]
    cwd: Path
    timeout: int = 180
    skip_reason: str = ""
    staff_brief: str = ""
    mentor_directive: str = ""
    reviewer_focus: str = ""


def _api_has_ide_endpoints() -> bool:
    try:
        with urllib.request.urlopen("http://127.0.0.1:8000/api/mcp/status", timeout=2) as resp:
            return resp.status == 200
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def _run_command(cmd: list[str], cwd: Path, timeout: int) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            shell=False,
        )
        return proc.returncode, proc.stdout or "", proc.stderr or ""
    except subprocess.TimeoutExpired as exc:
        out = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
        err = (exc.stderr or "") if isinstance(exc.stderr, str) else ""
        return 124, out, (err + f"\n[timeout após {timeout}s]").strip()
    except OSError as exc:
        return 127, "", str(exc)


def _tail(text: str, limit: int = 1200) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return "…\n" + text[-limit:]


def _build_suites() -> list[TestSuite]:
    suites: list[TestSuite] = [
        TestSuite(
            id="pytest-workspace",
            name="Explorer + Editor",
            phase="Fase 1–2",
            command=[PY, "-m", "pytest", "tests/test_workspace_api.py", "-q", "--tb=short"],
            cwd=ROOT,
            staff_brief=(
                "**Staff QA — Workspace**\n"
                "Valida jail path, listagem, leitura e gravação UTF-8. "
                "Prova que a Ravenna não expõe arquivos fora do workspace."
            ),
            mentor_directive="Ravenna: confirme que `resolve_path` bloqueia `..` antes de celebrar verde.",
            reviewer_focus="Falhas aqui indicam regressão no explorer ou no contrato PUT /api/files/content.",
        ),
        TestSuite(
            id="pytest-attachments",
            name="Anexos + RAG",
            phase="Fase 4",
            command=[PY, "-m", "pytest", "tests/test_attachments.py", "-q", "--tb=short"],
            cwd=ROOT,
            staff_brief=(
                "**Staff QA — Anexos**\n"
                "Upload multipart, whitelist MIME, indexação automática. "
                "Sem executar binários uploadados."
            ),
            mentor_directive="Ravenna: verifique se nota `[Anexo]` aparece no knowledge após upload real.",
            reviewer_focus="415 em extensão proibida é comportamento esperado — não é bug.",
        ),
        TestSuite(
            id="pytest-terminal",
            name="Terminal PTY/pipe",
            phase="Fase 3",
            command=[PY, "-m", "pytest", "tests/test_terminal_backend.py", "-q", "--tb=short"],
            cwd=ROOT,
            staff_brief=(
                "**Staff QA — Terminal**\n"
                "Backend deve expor modo `pty` ou `pipe`. WS testado indiretamente via factory."
            ),
            mentor_directive="Ravenna: no painel, confirme rodapé `backend: pty` no Windows com pywinpty.",
            reviewer_focus="Pipe-only em CI Linux é aceitável; pty é obrigatório em dev Windows.",
        ),
        TestSuite(
            id="pytest-mcp",
            name="Painel MCP",
            phase="Fase 5",
            command=[PY, "-m", "pytest", "tests/test_mcp_api.py", "-q", "--tb=short"],
            cwd=ROOT,
            staff_brief=(
                "**Staff QA — MCP bridge**\n"
                "Lista tools do FastMCP embutido; invoke seguro; bloqueio de theater/sync na UI."
            ),
            mentor_directive="Ravenna: tools bloqueadas devem continuar acessíveis via REST dedicado.",
            reviewer_focus="403 em `start_teaching_theater` pela IDE é contrato, não falha.",
        ),
        TestSuite(
            id="pytest-git",
            name="Git integrado",
            phase="Fase 6",
            command=[PY, "-m", "pytest", "tests/test_git_api.py", "-q", "--tb=short"],
            cwd=ROOT,
            staff_brief=(
                "**Staff QA — Git**\n"
                "status/diff/commit via subprocess com subcomandos fixos — sem flags arbitrários."
            ),
            mentor_directive="Ravenna: painel Git deve refletir o mesmo branch que `git status` no workspace.",
            reviewer_focus="Sandbox tmp em pytest — não commita no repo real do desenvolvedor.",
        ),
        TestSuite(
            id="vitest-frontend",
            name="Componentes React",
            phase="Frontend unit",
            command=_npm_run("test"),
            cwd=FRONTEND,
            timeout=120,
            staff_brief=(
                "**Staff QA — Vitest**\n"
                "Unit em componentes RemoteApp (`NeuralReasoningDetails`, estrutura details/summary)."
            ),
            mentor_directive="Ravenna: cada painel flutuante merece pelo menos um teste de render mínimo.",
            reviewer_focus="jsdom não cobre Three.js — teste comportamento DOM, não WebGL.",
        ),
    ]

    if _api_has_ide_endpoints():
        suites.append(
            TestSuite(
                id="playwright-e2e",
                name="Playwright smoke (UI + API)",
                phase="E2E",
                command=_npm_run("test:e2e"),
                cwd=FRONTEND,
                timeout=300,
                staff_brief=(
                    "**Staff QA — Playwright**\n"
                    "Shell mente infinita, FABs Explorer/MCP/Git, health/MCP/Git via API :8000."
                ),
                mentor_directive="Ravenna: e2e prova o que o usuário vê — complementa pytest, não substitui.",
                reviewer_focus="Reinicie API após deploy de rotas novas; proxy Vite depende de :8000 atualizado.",
            )
        )
    else:
        suites.append(
            TestSuite(
                id="playwright-ui",
                name="Playwright UI (API desatualizada)",
                phase="E2E parcial",
                command=[
                    NPX,
                    "playwright",
                    "test",
                    "--grep",
                    "carrega shell|abre painéis",
                ],
                cwd=FRONTEND,
                timeout=180,
                skip_reason="API :8000 sem /api/mcp/status — reinicie `py -m learning_agent.api` para e2e completo.",
                staff_brief=(
                    "**Staff QA — Playwright (modo parcial)**\n"
                    "Rodando só testes de UI; API em :8000 está desatualizada ou offline."
                ),
                mentor_directive="Ravenna: reinicie a API e rode `npm run test:e2e` para cobertura API.",
                reviewer_focus="Falso verde se ignorar API stale — documentar no relatório.",
            )
        )

    suites.append(
        TestSuite(
            id="run-proofs",
            name="Provas reais (DB + RAG)",
            phase="Provas",
            command=[PY, "-m", "learning_agent.cli", "run-proofs"],
            cwd=ROOT,
            timeout=240,
            staff_brief=(
                "**Staff QA — Provas**\n"
                "Confirma persistência: SQLite, Chroma, execução Python, sync opcional."
            ),
            mentor_directive="Ravenna: aprendizado só conta se provas passarem após os testes.",
            reviewer_focus="Falha em Chroma/embeddings pode ser ambiente — investigar antes de merge.",
        )
    )
    return suites


async def _broadcast(role: str, agent: str, content: str, *, level: str = "") -> None:
    await theater.post_agent_message(role, agent, content, level=level)
    await asyncio.sleep(0.35)


async def _ravenna_reflect(suite: TestSuite, result: SuiteResult) -> None:
    status = "PASSOU" if result.passed else ("PULADO" if result.skipped else "FALHOU")
    prompt = (
        f"[Supervisão QA — máx. 3 frases, feminino] "
        f"Suíte {suite.name} ({suite.phase}): {status}. "
        f"O que aprendi sobre testes nesta camada e o que faço se falhar de novo?"
    )
    loop = asyncio.get_event_loop()
    try:
        out = await asyncio.wait_for(
            loop.run_in_executor(
                None,
                lambda: chat.reply(
                    prompt,
                    channel="test-supervision",
                    user_id="qa-supervisor",
                    include_context=True,
                ),
            ),
            timeout=50.0,
        )
        if out.get("success"):
            reply = (out.get("reply") or "")[:450]
            reasoning = f"model={out.get('model', '?')}"
        else:
            reply = f"Registrei o resultado ({status}). Retomo quando o LLM responder."
            reasoning = str(out.get("error", ""))[:120]
    except asyncio.TimeoutError:
        reply = f"Teste {suite.name}: {status}. Lição salva no knowledge base."
        reasoning = "LLM timeout"

    await theater.post_agent_message("ravenna", "Ravenna", reply, level=suite.phase, reasoning=reasoning)


async def _run_suite(suite: TestSuite) -> SuiteResult:
    await _broadcast("system", "Supervisão QA", f"— {suite.phase}: {suite.name} —", level=suite.phase)
    await broadcast_supervision_round(
        SupervisionContext(
            level=suite.phase,
            topic=suite.name,
            process="qa",
            phase=suite.phase,
            staff_brief=suite.staff_brief,
            mentor_directive=suite.mentor_directive,
            reviewer_focus=suite.reviewer_focus,
            track_id=suite.id,
        ),
        broadcast=_broadcast,
        pause_seconds=0.35,
    )

    if suite.skip_reason and not suite.command:
        result = SuiteResult(suite.id, suite.name, suite.phase, passed=False, skipped=True, detail=suite.skip_reason)
        await _broadcast("system", "Supervisão QA", f"⏭ {suite.name}: {suite.skip_reason}", level=suite.phase)
        await _ravenna_reflect(suite, result)
        return result

    code, stdout, stderr = _run_command(suite.command, suite.cwd, suite.timeout)
    passed = code == 0
    detail = _tail(stdout + ("\n" + stderr if stderr else ""))
    result = SuiteResult(
        suite.id,
        suite.name,
        suite.phase,
        passed=passed,
        detail=detail,
        stdout=stdout,
        stderr=stderr,
    )

    icon = "✅" if passed else "❌"
    extra = f"\n\n{suite.skip_reason}" if suite.skip_reason and passed else ""
    await _broadcast(
        "reviewer",
        "Revisor QA",
        f"{icon} **{suite.name}** — exit={code}{extra}\n```\n{detail}\n```",
        level=suite.phase,
    )
    await _ravenna_reflect(suite, result)
    return result


async def _teach_testing_pyramid() -> None:
    await broadcast_supervision_round(
        SupervisionContext(
            level="IDE Testing Mastery",
            topic="Pirâmide de testes completa",
            process="session",
            staff_brief=(
                "Ordem: pytest por fase → Vitest → Playwright → run_proofs.\n"
                "Unit isola lógica; integração valida HTTP; e2e valida UX RemoteApp."
            ),
            mentor_directive=(
                "Ravenna: execute mentalmente cada assert, registre lições e priorize fix mínimo se falhar."
            ),
            reviewer_focus="Nunca confundir verde em pytest com IDE funcionando no browser.",
        ),
        broadcast=_broadcast,
        pause_seconds=0.35,
    )


def _save_knowledge_note(results: list[SuiteResult]) -> dict[str, Any]:
    doc_body = DOC.read_text(encoding="utf-8") if DOC.exists() else ""
    passed = sum(1 for r in results if r.passed)
    failed = [r for r in results if not r.passed and not r.skipped]
    skipped = [r for r in results if r.skipped]

    report = [
        "# Relatório supervisão QA",
        "",
        f"- Total: {len(results)} suítes",
        f"- Verdes: {passed}",
        f"- Falhas: {len(failed)}",
        f"- Puladas: {len(skipped)}",
        "",
        "## Por suíte",
    ]
    for r in results:
        st = "PASS" if r.passed else ("SKIP" if r.skipped else "FAIL")
        report.append(f"- [{st}] {r.phase} — {r.name} (`{r.suite_id}`)")
        if r.detail and st != "PASS":
            report.append(f"  - {r.detail[:200].replace(chr(10), ' ')}")

    body = doc_body + "\n\n---\n\n" + "\n".join(report)
    return knowledge.add_note(
        "[IDE Testing Mastery] Supervisão QA — bateria completa",
        body,
        tags=["testing", "pytest", "vitest", "playwright", "e2e", "qa", "ravenna-ide", "supervision"],
    )


async def main() -> int:
    os.chdir(ROOT)
    suites = _build_suites()
    results: list[SuiteResult] = []

    await _teach_testing_pyramid()

    for suite in suites:
        results.append(await _run_suite(suite))

    note = _save_knowledge_note(results)
    all_pass = all(r.passed for r in results)
    failed = [r.name for r in results if not r.passed and not r.skipped]

    summary = (
        f"**Relatório final supervisão QA**\n"
        f"Verdes: {sum(1 for r in results if r.passed)}/{len(results)}.\n"
        f"Nota KB: #{note.get('note_id') or note.get('id')}.\n"
    )
    if failed:
        summary += f"Falhas: {', '.join(failed)}.\n"
        summary += "Ravenna: priorize fix mínimo na camada que falhou antes de novas features."
    else:
        summary += "Todas as camadas verdes — IDE pronta para teste manual do usuário."

    await broadcast_supervision_round(
        SupervisionContext(
            level="IDE Testing Mastery",
            topic="Relatório final QA",
            process="qa",
            mentor_directive=summary,
            reviewer_focus=(
                f"Falhas: {', '.join(failed)}." if failed else "Todas as camadas verdes — validar manualmente no browser."
            ),
        ),
        broadcast=_broadcast,
        pause_seconds=0.3,
    )

    try:
        reflect = chat.reply(
            "[Supervisão QA final — feminino, 4 frases] Resuma o que aprendi sobre testes na IDE RemoteApp hoje.",
            channel="test-supervision",
            user_id="qa-supervisor",
            include_context=True,
        )
        if reflect.get("success"):
            await theater.post_agent_message(
                "ravenna",
                "Ravenna",
                (reflect.get("reply") or "")[:500],
                level="IDE Testing Mastery",
                reasoning="Síntese final da sessão QA",
            )
    except Exception:
        pass

    print(f"supervision_done passed={sum(1 for r in results if r.passed)} total={len(results)} note={note.get('note_id') or note.get('id')}")
    for r in results:
        st = "PASS" if r.passed else ("SKIP" if r.skipped else "FAIL")
        print(f"  [{st}] {r.phase}: {r.name}")

    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
