"""Mandatory software delivery orchestration for complex Ravenna builds."""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from learning_agent.config import PROJECT_ROOT
from learning_agent.core import agent_autonomy_runner, agent_critic, agent_spec_builder, chat


REGISTRY_PATH = PROJECT_ROOT / "agents" / "registry.yaml"
PROJECT_MEMORY_DIR = PROJECT_ROOT / "data" / "project-memory"


@dataclass
class WorkOrder:
    id: str
    agent: str
    specialty: str
    objective: str
    target_files: list[str]
    acceptance: list[str]
    status: str = "pending"
    evidence: list[str] = field(default_factory=list)


@dataclass
class SoftwareSpec:
    project_root: str
    domain: str
    complexity: str
    required_files: list[str]
    required_exports: dict[str, list[str]]
    validation_commands: list[str]
    semantic_rules: list[str]
    min_tests: int
    work_orders: list[WorkOrder]


def build_software_spec(message: str, *, project_root: str | None = None) -> dict[str, Any]:
    """Turn a large software request into executable delivery contracts."""
    base_spec = agent_spec_builder.build_spec(message, project_root=project_root)
    domain = _infer_delivery_domain(message)
    agents = _delivery_agents()
    spec = SoftwareSpec(
        project_root=project_root or base_spec.get("projectRoot") or "",
        domain=domain,
        complexity="complex",
        required_files=_required_files_for_domain(domain, base_spec),
        required_exports=_required_exports_for_domain(domain, base_spec),
        validation_commands=_validation_commands_for_domain(domain, base_spec),
        semantic_rules=_semantic_rules_for_domain(domain, base_spec),
        min_tests=max(int(base_spec.get("minTests") or 0), _min_tests_for_domain(domain)),
        work_orders=[],
    )
    spec.work_orders = _build_work_orders(spec, agents)
    return _spec_to_dict(spec)


def _should_use_model_rounds(message: str, spec: dict[str, Any]) -> bool:
    text = (message or "").lower()
    complex_markers = (
        "software completo",
        "sistema completo",
        "fullstack",
        "mobile",
        "celular",
        "auth",
        "financeiro",
        "complex",
        "autonom",
    )
    return spec.get("complexity") == "complex" and (
        spec.get("domain") != "generic-software" or any(marker in text for marker in complex_markers)
    )


def _memory_path(project_root: str) -> Path:
    safe = re.sub(r"[^a-zA-Z0-9_.-]+", "__", project_root.strip() or "default")
    return PROJECT_MEMORY_DIR / f"{safe[:180]}.json"


def _load_project_memory(project_root: str) -> dict[str, Any]:
    path = _memory_path(project_root)
    if not path.is_file():
        return {"projectRoot": project_root, "deliveries": [], "decisions": [], "failures": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"projectRoot": project_root, "deliveries": [], "decisions": [], "failures": []}
    except (OSError, json.JSONDecodeError):
        return {"projectRoot": project_root, "deliveries": [], "decisions": [], "failures": []}


def _format_project_memory_for_prompt(memory: dict[str, Any]) -> str:
    deliveries = memory.get("deliveries") or []
    decisions = memory.get("decisions") or []
    failures = memory.get("failures") or []
    parts = [
        f"- Entregas anteriores: {len(deliveries)}",
        *[f"- Decisão: {item}" for item in decisions[-5:]],
        *[f"- Falha recorrente: {item}" for item in failures[-5:]],
    ]
    return "\n".join(parts) if parts else "- Sem memória técnica anterior."


def _persist_project_memory(
    spec: dict[str, Any],
    attempts: list[dict[str, Any]],
    gates: list[dict[str, Any]],
    passed: bool,
) -> dict[str, Any]:
    memory = _load_project_memory(spec["projectRoot"])
    failures = [failure for gate in gates for failure in (gate.get("failures") or [])]
    entry = {
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "domain": spec.get("domain"),
        "passed": passed,
        "attemptCount": len(attempts),
        "changedPaths": sorted({
            path
            for attempt in attempts
            for path in (attempt.get("applied", {}).get("changedPaths") or [])
        }),
        "gates": [{"name": gate.get("name"), "ok": gate.get("ok")} for gate in gates],
    }
    memory.setdefault("deliveries", []).append(entry)
    memory["deliveries"] = memory["deliveries"][-20:]
    for rule in spec.get("semanticRules") or []:
        decision = f"{spec.get('domain')}: manter regra {rule}"
        if decision not in memory.setdefault("decisions", []):
            memory["decisions"].append(decision)
    for failure in failures:
        if failure not in memory.setdefault("failures", []):
            memory["failures"].append(failure)
    memory["decisions"] = memory.get("decisions", [])[-30:]
    memory["failures"] = memory.get("failures", [])[-30:]
    memory["updatedAt"] = entry["createdAt"]
    PROJECT_MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    path = _memory_path(spec["projectRoot"])
    path.write_text(json.dumps(memory, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"path": str(path.relative_to(PROJECT_ROOT)), "updated": True, "deliveryCount": len(memory["deliveries"])}


def run_software_delivery(
    message: str,
    *,
    project_root: str | None = None,
    auto_apply: bool = True,
    run_validation: bool = True,
    use_model_rounds: bool | None = None,
    model_size: str = "auto",
    model_runner: Any | None = None,
    max_repair_rounds: int = 1,
) -> dict[str, Any]:
    """Run Ravenna's mandatory multi-agent delivery pipeline."""
    spec = build_software_spec(message, project_root=project_root)
    project_memory = _load_project_memory(spec["projectRoot"])
    model_rounds_enabled = _should_use_model_rounds(message, spec) if use_model_rounds is None else bool(use_model_rounds)
    attempts: list[dict[str, Any]] = []
    applied: dict[str, Any] = {"applied": [], "changedPaths": [], "blockCount": 0}

    if auto_apply:
        reply = _reconciler_reply_for_domain(spec["domain"])
        attempts = _run_specialist_work_orders(
            spec,
            reply,
            original_request=message,
            use_model_rounds=model_rounds_enabled,
            model_size=model_size,
            project_memory=project_memory,
            model_runner=model_runner,
        )
        applied = _merge_applied_results([attempt["applied"] for attempt in attempts])
    else:
        reply = ""

    cross_reviews = _run_cross_specialist_reviews(spec, attempts)
    gates = run_delivery_gates(message, spec, applied, cross_reviews=cross_reviews, run_validation=run_validation)
    repair_attempts = _run_specialist_repair_loop(
        message,
        spec,
        gates,
        model_size=model_size,
        model_runner=model_runner,
        enabled=auto_apply and model_rounds_enabled,
        max_rounds=max_repair_rounds,
        project_memory=project_memory,
    )
    if repair_attempts:
        attempts.extend(repair_attempts)
        applied = _merge_applied_results([attempt["applied"] for attempt in attempts])
        cross_reviews = _run_cross_specialist_reviews(spec, attempts)
        gates = run_delivery_gates(message, spec, applied, cross_reviews=cross_reviews, run_validation=run_validation)

    passed = bool(all(gate["ok"] for gate in gates))
    repair_plan = _build_repair_plan(message, spec, gates)
    memory_update = _persist_project_memory(spec, attempts, gates, passed)
    report = build_delivery_report(
        message=message,
        spec=spec,
        attempts=attempts,
        cross_reviews=cross_reviews,
        applied=applied,
        gates=gates,
        repair_plan=repair_plan,
        project_memory=memory_update,
        passed=passed,
    )
    return {
        "success": passed,
        "passed": passed,
        "spec": spec,
        "attempts": attempts,
        "crossReviews": cross_reviews,
        "gates": gates,
        "repairPlan": repair_plan,
        "projectMemory": memory_update,
        "modelRoundsEnabled": model_rounds_enabled,
        "deliveryReport": report,
        "finalReply": reply,
    }


def _run_specialist_work_orders(
    spec: dict[str, Any],
    reply: str,
    *,
    original_request: str,
    use_model_rounds: bool,
    model_size: str,
    project_memory: dict[str, Any],
    model_runner: Any | None = None,
) -> list[dict[str, Any]]:
    """Apply canonical delivery output through mandatory specialist rounds."""
    attempts: list[dict[str, Any]] = []
    for order in spec.get("workOrders") or []:
        target_files = list(order.get("target_files") or order.get("targetFiles") or [])
        canonical_reply = _filter_reply_for_paths(reply, target_files)
        model_result = (
            _run_specialist_model_round(
                original_request,
                spec,
                order,
                canonical_reply,
                model_size=model_size,
                project_memory=project_memory,
                model_runner=model_runner,
            )
            if use_model_rounds
            else {"attempted": False, "success": False, "reply": "", "model": None, "error": None}
        )
        model_reply = str(model_result.get("reply") or "")
        use_model_reply = bool(model_result.get("success")) and _reply_covers_targets(model_reply, target_files)
        filtered_reply = model_reply if use_model_reply else canonical_reply
        checkpoints = _capture_checkpoints(spec, target_files)
        applied = agent_autonomy_runner.apply_write_blocks(filtered_reply, base_path=spec["projectRoot"])
        completed = bool(applied.get("blockCount")) and all(
            any(str(path).replace("\\", "/").endswith(target) for path in applied.get("changedPaths") or [])
            for target in target_files
        )
        source = "model" if use_model_reply else "canonical-fallback"
        order["status"] = "completed" if completed else "blocked"
        order["evidence"] = [
            f"{applied.get('blockCount', 0)} file block(s) applied by {order.get('agent')} from {source}",
            *(applied.get("changedPaths") or []),
        ]
        if model_result.get("attempted"):
            order["evidence"].append(
                f"model round {'accepted' if use_model_reply else 'fell back'}"
                + (f" using {model_result.get('model')}" if model_result.get("model") else "")
            )
        attempts.append(
            {
                "phase": order.get("id"),
                "agent": order.get("agent"),
                "specialty": order.get("specialty"),
                "targetFiles": target_files,
                "applied": applied,
                "checkpoints": checkpoints,
                "passed": completed,
                "source": source,
                "modelRound": {
                    key: model_result.get(key)
                    for key in ("attempted", "success", "model", "error")
                },
                "summary": order.get("objective"),
            }
        )
    return attempts


def _run_specialist_model_round(
    original_request: str,
    spec: dict[str, Any],
    order: dict[str, Any],
    canonical_reply: str,
    *,
    model_size: str,
    project_memory: dict[str, Any] | None = None,
    model_runner: Any | None = None,
) -> dict[str, Any]:
    prompt = _build_specialist_round_prompt(original_request, spec, order, canonical_reply, project_memory or {})
    try:
        if model_runner:
            result = model_runner(order=order, prompt=prompt, spec=spec, canonical_reply=canonical_reply)
        else:
            result = chat.reply(
                prompt,
                channel="software-delivery",
                user_id=f"software-delivery:{spec.get('domain')}:{order.get('id')}",
                include_context=False,
                delegate_agent=str(order.get("agent") or ""),
                task_mode="agent",
                model_size=model_size,
                persist_history=False,
            )
        if isinstance(result, str):
            return {"attempted": True, "success": True, "reply": result, "model": None, "error": None}
        return {
            "attempted": True,
            "success": bool(result.get("success")),
            "reply": result.get("reply") or "",
            "model": result.get("model") or result.get("model_size"),
            "error": result.get("error"),
        }
    except Exception as exc:
        return {"attempted": True, "success": False, "reply": "", "model": None, "error": str(exc)}


def _build_specialist_round_prompt(
    original_request: str,
    spec: dict[str, Any],
    order: dict[str, Any],
    canonical_reply: str,
    project_memory: dict[str, Any],
) -> str:
    target_files = list(order.get("target_files") or order.get("targetFiles") or [])
    return (
        "Você é um especialista executando UMA Work Order da fábrica Ravenna.\n"
        "Responda somente com blocos ```write caminho``` para os arquivos alvo.\n"
        "Não edite arquivos fora da lista alvo e não inclua shell.\n\n"
        f"Pedido original:\n{original_request}\n\n"
        f"Domínio: {spec.get('domain')}\n"
        f"Work Order: {order.get('id')} ({order.get('specialty')})\n"
        f"Objetivo: {order.get('objective')}\n"
        f"Arquivos alvo: {', '.join(target_files)}\n"
        f"Critérios de aceite: {', '.join(order.get('acceptance') or [])}\n\n"
        "Contrato global:\n"
        f"- Arquivos obrigatórios: {', '.join(spec.get('requiredFiles') or [])}\n"
        f"- Exports obrigatórios: {json.dumps(spec.get('requiredExports') or {}, ensure_ascii=False)}\n"
        f"- Regras semânticas: {', '.join(spec.get('semanticRules') or [])}\n"
        f"- Testes mínimos: {spec.get('minTests')}\n\n"
        "Memória técnica do projeto:\n"
        f"{_format_project_memory_for_prompt(project_memory)}\n\n"
        "Base canônica/reconciliada que você pode melhorar sem quebrar contrato:\n"
        f"{canonical_reply}"
    )


def _reply_covers_targets(reply: str, target_files: list[str]) -> bool:
    blocks = agent_autonomy_runner.parse_write_blocks(reply)
    paths = [block.path.replace("\\", "/").strip("/") for block in blocks]
    return bool(blocks) and all(any(path.endswith(target) for path in paths) for target in target_files)


def _filter_reply_for_paths(reply: str, target_files: list[str]) -> str:
    allowed = [path.replace("\\", "/").strip("/") for path in target_files]
    blocks = [
        block
        for block in agent_autonomy_runner.parse_write_blocks(reply)
        if any(block.path.replace("\\", "/").strip("/").endswith(path) for path in allowed)
    ]
    return "\n\n".join(f"```write {block.path}\n{block.content}\n```" for block in blocks)


def _capture_checkpoints(spec: dict[str, Any], target_files: list[str]) -> list[dict[str, Any]]:
    root = PROJECT_ROOT / spec["projectRoot"] if not Path(spec["projectRoot"]).is_absolute() else Path(spec["projectRoot"])
    checkpoints: list[dict[str, Any]] = []
    for target in target_files:
        path = root / target
        if path.is_file():
            checkpoints.append({
                "path": target,
                "existed": True,
                "content": path.read_text(encoding="utf-8", errors="replace"),
            })
        else:
            checkpoints.append({"path": target, "existed": False, "content": ""})
    return checkpoints


def _merge_applied_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    applied_files: list[dict[str, Any]] = []
    changed_paths: list[str] = []
    block_count = 0
    for result in results:
        applied_files.extend(result.get("applied") or [])
        block_count += int(result.get("blockCount") or 0)
        for path in result.get("changedPaths") or []:
            if path not in changed_paths:
                changed_paths.append(path)
    return {"applied": applied_files, "changedPaths": changed_paths, "blockCount": block_count}


def _run_cross_specialist_reviews(spec: dict[str, Any], attempts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    reviews: list[dict[str, Any]] = []
    root = PROJECT_ROOT / spec["projectRoot"] if not Path(spec["projectRoot"]).is_absolute() else Path(spec["projectRoot"])
    for attempt in attempts:
        reviewer = _reviewer_for_specialty(str(attempt.get("specialty") or ""))
        failures = _review_attempt_contract(root, spec, attempt)
        attempt["reviewedBy"] = reviewer
        attempt["reviewPassed"] = not failures
        reviews.append(
            {
                "phase": attempt.get("phase"),
                "agent": attempt.get("agent"),
                "reviewer": reviewer,
                "ok": not failures,
                "failures": failures,
                "evidence": [
                    f"{reviewer} reviewed {attempt.get('agent')} output",
                    *(attempt.get("targetFiles") or []),
                ],
            }
        )
    return reviews


def _run_specialist_repair_loop(
    original_request: str,
    spec: dict[str, Any],
    gates: list[dict[str, Any]],
    *,
    model_size: str,
    model_runner: Any | None,
    enabled: bool,
    max_rounds: int,
    project_memory: dict[str, Any],
) -> list[dict[str, Any]]:
    if not enabled or max_rounds <= 0:
        return []
    repair_plan = _build_repair_plan(original_request, spec, gates)
    repairs = [item for item in repair_plan if item.get("failures")]
    if not repairs:
        return []

    attempts: list[dict[str, Any]] = []
    root = PROJECT_ROOT / spec["projectRoot"] if not Path(spec["projectRoot"]).is_absolute() else Path(spec["projectRoot"])
    for index, repair in enumerate(repairs[:max_rounds]):
        order = _repair_order_for(spec, repair)
        target_files = list(order.get("target_files") or [])
        prompt = _build_repair_prompt(original_request, spec, order, repair, project_memory)
        model_result = _run_specialist_model_round(
            original_request,
            spec,
            order,
            _canonical_reply_for_targets(spec, target_files),
            model_size=model_size,
            project_memory=project_memory,
            model_runner=(lambda **_: model_runner(order=order, prompt=prompt, spec=spec, canonical_reply="")) if model_runner else None,
        )
        reply = str(model_result.get("reply") or "")
        if not _reply_covers_targets(reply, target_files):
            attempts.append(
                {
                    "phase": f"repair-{index + 1}-{order['id']}",
                    "agent": order.get("agent"),
                    "specialty": order.get("specialty"),
                    "targetFiles": target_files,
                    "applied": {"applied": [], "changedPaths": [], "blockCount": 0},
                    "checkpoints": _capture_checkpoints(spec, target_files),
                    "passed": False,
                    "source": "repair-model-rejected",
                    "modelRound": {key: model_result.get(key) for key in ("attempted", "success", "model", "error")},
                    "summary": f"Repair blocked: model did not cover {', '.join(target_files)}",
                }
            )
            continue
        checkpoints = _capture_checkpoints(spec, target_files)
        applied = agent_autonomy_runner.apply_write_blocks(reply, base_path=spec["projectRoot"])
        attempts.append(
            {
                "phase": f"repair-{index + 1}-{order['id']}",
                "agent": order.get("agent"),
                "specialty": order.get("specialty"),
                "targetFiles": target_files,
                "applied": applied,
                "checkpoints": checkpoints,
                "passed": bool(applied.get("blockCount")) and all((root / target).is_file() for target in target_files),
                "source": "repair-model",
                "modelRound": {key: model_result.get(key) for key in ("attempted", "success", "model", "error")},
                "summary": f"Repair for {repair.get('gate')}",
            }
        )
    return attempts


def _build_repair_plan(original_request: str, spec: dict[str, Any], gates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    plan: list[dict[str, Any]] = []
    for gate in gates:
        failures = list(gate.get("failures") or [])
        if not failures:
            continue
        critique = agent_critic.critique_attempt(
            original_request=original_request,
            spec=spec,
            applied={"blockCount": 0, "changedPaths": []},
            validation={"failures": failures},
            checklist={"failures": failures},
        )
        plan.append(
            {
                "gate": gate.get("name"),
                "agent": _agent_for_gate(str(gate.get("name") or ""), spec),
                "targetFiles": _targets_for_gate(str(gate.get("name") or ""), spec),
                "failures": failures,
                "critic": {
                    "categories": critique.get("categories") or [],
                    "nextAction": critique.get("nextAction") or {},
                    "recommendedModelSize": critique.get("recommendedModelSize"),
                    "repairPrompt": critique.get("repairPrompt"),
                },
            }
        )
    return plan


def _agent_for_gate(gate_name: str, spec: dict[str, Any]) -> str:
    if "mobile" in gate_name:
        return "frontend-lead"
    if "finance" in gate_name:
        return "finance-lead"
    if "test" in gate_name or "qa" in gate_name:
        return "qa-guardian"
    if "security" in gate_name:
        return "backend-lead"
    if "docs" in gate_name or "reliability" in gate_name or "build" in gate_name:
        return "reliability-lead"
    return "backend-lead" if spec.get("domain") == "fullstack-crud-auth" else "qa-guardian"


def _targets_for_gate(gate_name: str, spec: dict[str, Any]) -> list[str]:
    domain = spec.get("domain")
    if domain == "personal-finance-mobile":
        if "mobile" in gate_name:
            return ["public/index.html", "public/styles.css"]
        if "finance" in gate_name:
            return ["src/finance.js"]
        if "test" in gate_name or "qa" in gate_name:
            return ["test/finance.test.mjs"]
        if "docs" in gate_name or "reliability" in gate_name or "build" in gate_name:
            return ["package.json", "src/smoke.js", "README.md"]
        return ["src/server.js"]
    if "test" in gate_name or "qa" in gate_name:
        return ["test/app.test.mjs"]
    if "docs" in gate_name or "reliability" in gate_name:
        return ["package.json", "src/smoke.js", "README.md"]
    if "mobile" in gate_name:
        return ["public/index.html"]
    return ["src/server.js"]


def _repair_order_for(spec: dict[str, Any], repair: dict[str, Any]) -> dict[str, Any]:
    agent = str(repair.get("agent") or "qa-guardian")
    specialty = "qa" if agent == "qa-guardian" else agent.replace("-lead", "").replace("-guardian", "")
    return {
        "id": f"repair-{repair.get('gate')}",
        "agent": agent,
        "specialty": specialty,
        "objective": f"Repair failed gate {repair.get('gate')}.",
        "target_files": list(repair.get("targetFiles") or []),
        "acceptance": list(repair.get("failures") or []),
    }


def _canonical_reply_for_targets(spec: dict[str, Any], target_files: list[str]) -> str:
    return _filter_reply_for_paths(_reconciler_reply_for_domain(str(spec.get("domain") or "")), target_files)


def _build_repair_prompt(
    original_request: str,
    spec: dict[str, Any],
    order: dict[str, Any],
    repair: dict[str, Any],
    project_memory: dict[str, Any],
) -> str:
    critic_prompt = ((repair.get("critic") or {}).get("repairPrompt") or "").strip()
    return (
        "Você está em uma rodada de reparo Ravenna. Corrija somente os arquivos alvo.\n"
        f"Pedido original:\n{original_request}\n\n"
        f"Gate com falha: {repair.get('gate')}\n"
        f"Falhas:\n- " + "\n- ".join(repair.get("failures") or []) + "\n\n"
        + (f"Crítica cirúrgica:\n{critic_prompt}\n\n" if critic_prompt else "")
        + f"Arquivos alvo: {', '.join(order.get('target_files') or [])}\n"
        + f"Memória técnica:\n{_format_project_memory_for_prompt(project_memory)}\n"
        + "Responda somente com blocos ```write caminho```."
    )


def _reviewer_for_specialty(specialty: str) -> str:
    return {
        "finance": "qa-guardian",
        "backend": "qa-guardian",
        "frontend": "qa-guardian",
        "qa": "reliability-lead",
        "reliability": "backend-lead",
    }.get(specialty, "qa-guardian")


def _review_attempt_contract(root: Path, spec: dict[str, Any], attempt: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    target_files = list(attempt.get("targetFiles") or [])
    changed = "\n".join(str(path).replace("\\", "/") for path in attempt.get("applied", {}).get("changedPaths") or [])
    for target in target_files:
        if target not in changed:
            failures.append(f"Specialist did not produce target file `{target}`.")
        elif not (root / target).is_file():
            failures.append(f"Reviewer cannot find produced file `{target}`.")
    if not attempt.get("passed"):
        failures.append(f"Specialist phase `{attempt.get('phase')}` did not pass apply checks.")

    domain = spec.get("domain")
    phase = str(attempt.get("phase") or "")
    if domain == "personal-finance-mobile" and phase == "finance-domain":
        source = (root / "src" / "finance.js").read_text(encoding="utf-8", errors="replace") if (root / "src" / "finance.js").is_file() else ""
        for token in ("projectCashFlow", "saveFinanceStore", "loadFinanceStore", "duplicate transaction"):
            if token not in source:
                failures.append(f"Finance review missing `{token}` in domain source.")
    if domain == "personal-finance-mobile" and phase == "mobile-frontend":
        html = (root / "public" / "index.html").read_text(encoding="utf-8", errors="replace") if (root / "public" / "index.html").is_file() else ""
        css = (root / "public" / "styles.css").read_text(encoding="utf-8", errors="replace") if (root / "public" / "styles.css").is_file() else ""
        for token in ('name="viewport"', 'aria-label="Nova transação"', 'fetch("/api/transactions"', 'role="status"'):
            if token not in html:
                failures.append(f"Frontend review missing `{token}`.")
        if "min-height: 44px" not in css:
            failures.append("Frontend review missing mobile touch target CSS.")
    if domain == "personal-finance-mobile" and phase == "finance-qa":
        tests = (root / "test" / "finance.test.mjs").read_text(encoding="utf-8", errors="replace") if (root / "test" / "finance.test.mjs").is_file() else ""
        for token in ("cashflow projection", "persists and loads", "serves mobile CSS"):
            if token not in tests:
                failures.append(f"QA review missing `{token}` test.")
    return failures


def run_delivery_gates(
    message: str,
    spec: dict[str, Any],
    applied: dict[str, Any],
    *,
    cross_reviews: list[dict[str, Any]] | None = None,
    run_validation: bool = True,
) -> list[dict[str, Any]]:
    root = PROJECT_ROOT / spec["projectRoot"] if not Path(spec["projectRoot"]).is_absolute() else Path(spec["projectRoot"])
    gates = [
        _contract_gate(root, spec),
        _docs_gate(root, spec),
        _mobile_visual_gate(root, spec),
        _browser_mobile_gate(root, spec),
        _finance_domain_gate(root, spec),
        _cross_review_execution_gate(spec, cross_reviews or []),
        _cross_review_gate(root, spec),
        _security_gate(root, spec),
    ]
    validation = _validation_gate(spec, applied, run_validation=run_validation)
    gates.append(validation)
    gates.append(_test_gate(root, spec, validation))
    gates.append(_qa_gate(root, spec, validation))
    gates.append(_reliability_gate(validation))
    return gates


def build_delivery_report(
    *,
    message: str,
    spec: dict[str, Any],
    attempts: list[dict[str, Any]],
    cross_reviews: list[dict[str, Any]],
    applied: dict[str, Any],
    gates: list[dict[str, Any]],
    repair_plan: list[dict[str, Any]],
    project_memory: dict[str, Any],
    passed: bool,
) -> dict[str, Any]:
    return {
        "status": "passed" if passed else "blocked",
        "originalRequest": message,
        "projectRoot": spec.get("projectRoot"),
        "domain": spec.get("domain"),
        "workOrders": spec.get("workOrders") or [],
        "crossReviews": cross_reviews,
        "repairPlan": repair_plan,
        "projectMemory": project_memory,
        "changedPaths": applied.get("changedPaths") or [],
        "commands": [
            command
            for gate in gates
            for command in (gate.get("commands") or [])
        ],
        "gates": gates,
        "failures": [failure for gate in gates for failure in (gate.get("failures") or [])],
        "risks": [risk for gate in gates for risk in (gate.get("risks") or [])],
        "attemptCount": len(attempts),
    }


def _spec_to_dict(spec: SoftwareSpec) -> dict[str, Any]:
    data = asdict(spec)
    data["requiredFiles"] = data.pop("required_files")
    data["requiredExports"] = data.pop("required_exports")
    data["validationCommands"] = data.pop("validation_commands")
    data["semanticRules"] = data.pop("semantic_rules")
    data["minTests"] = data.pop("min_tests")
    data["workOrders"] = data.pop("work_orders")
    data["projectRoot"] = data.pop("project_root")
    return data


def _infer_delivery_domain(message: str) -> str:
    text = (message or "").lower()
    if any(token in text for token in ("controle financeiro", "finanças pessoais", "financeiro pessoal", "personal finance")) and any(token in text for token in ("celular", "mobile", "responsivo")):
        return "personal-finance-mobile"
    if any(token in text for token in ("audit log", "auditoria")) and any(token in text for token in ("export csv", "csv do ledger", "csv")):
        return "saas-ops-enhancement"
    if any(token in text for token in ("helpdesk", "ticket", "tickets")) and any(token in text for token in ("mvp", "produto", "software completo")):
        return "support-helpdesk"
    if any(token in text for token in ("software completo", "operações saas", "saas")) and "auth" in text and "crud" in text and any(token in text for token in ("billing", "ledger", "cobran")):
        return "saas-ops-suite"
    if all(token in text for token in ("fullstack", "crud")) and any(token in text for token in ("auth", "login", "autentica")):
        return "fullstack-crud-auth"
    return "generic-software"


def _delivery_agents() -> dict[str, dict[str, Any]]:
    if not REGISTRY_PATH.is_file():
        return {}
    with REGISTRY_PATH.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    agents: dict[str, dict[str, Any]] = {}
    for item in data.get("user_agents") or []:
        name = str(item.get("name") or "")
        if name:
            agents[name] = item
    return agents


def _required_files_for_domain(domain: str, base_spec: dict[str, Any]) -> list[str]:
    if domain == "personal-finance-mobile":
        return [
            "package.json",
            "README.md",
            "src/finance.js",
            "src/server.js",
            "src/smoke.js",
            "public/index.html",
            "public/styles.css",
            "test/finance.test.mjs",
        ]
    if domain == "fullstack-crud-auth":
        return [
            "package.json",
            "README.md",
            "src/auth.js",
            "src/store.js",
            "src/server.js",
            "src/smoke.js",
            "public/index.html",
            "test/app.test.mjs",
        ]
    if domain == "saas-ops-suite":
        return [
            "package.json",
            "README.md",
            "src/auth.js",
            "src/store.js",
            "src/billing.js",
            "src/server.js",
            "src/smoke.js",
            "public/index.html",
            "test/app.test.mjs",
        ]
    if domain == "support-helpdesk":
        return [
            "package.json",
            "README.md",
            "src/auth.js",
            "src/store.js",
            "src/server.js",
            "src/smoke.js",
            "public/index.html",
            "test/app.test.mjs",
        ]
    if domain == "saas-ops-enhancement":
        return ["src/audit.js", "src/billing.js", "test/app.test.mjs"]
    return list(base_spec.get("requiredFiles") or [])


def _required_exports_for_domain(domain: str, base_spec: dict[str, Any]) -> dict[str, list[str]]:
    if domain == "personal-finance-mobile":
        return {
            "src/finance.js": [
                "createFinanceStore",
                "addTransaction",
                "listTransactions",
                "summarizeByMonth",
                "setBudget",
                "checkBudgets",
                "addGoal",
                "projectGoal",
                "addRecurringTransaction",
                "materializeRecurring",
                "projectCashFlow",
                "saveFinanceStore",
                "loadFinanceStore",
                "exportCsv",
            ],
            "src/server.js": ["createApp", "routeRequest"],
        }
    if domain == "fullstack-crud-auth":
        return {
            "src/auth.js": ["hashPassword", "verifyPassword", "createSession"],
            "src/store.js": ["createStore", "createUser", "authenticateUser", "createProject", "listProjects", "updateProject", "deleteProject"],
            "src/server.js": ["createApp", "routeRequest"],
        }
    if domain == "saas-ops-suite":
        return {
            "src/auth.js": ["hashPassword", "verifyPassword", "createSession"],
            "src/store.js": ["createStore", "createUser", "authenticateUser", "createProject", "listProjects", "updateProject", "deleteProject"],
            "src/billing.js": ["createBillingLedger", "addInvoice", "recordPayment", "summarizeLedger", "exportLedgerCsv"],
            "src/server.js": ["createApp", "routeRequest"],
        }
    if domain == "support-helpdesk":
        return {
            "src/auth.js": ["hashPassword", "verifyPassword", "createSession"],
            "src/store.js": ["createStore", "createUser", "authenticateUser", "createTicket", "listTickets", "updateTicket"],
            "src/server.js": ["createApp", "routeRequest"],
        }
    if domain == "saas-ops-enhancement":
        return {
            "src/audit.js": ["recordAuditEvent", "listAuditEvents"],
            "src/billing.js": ["createBillingLedger", "addInvoice", "recordPayment", "summarizeLedger", "exportLedgerCsv"],
        }
    return dict(base_spec.get("requiredExports") or {})


def _validation_commands_for_domain(domain: str, base_spec: dict[str, Any]) -> list[str]:
    if domain == "personal-finance-mobile":
        return ["npm test", "npm run smoke"]
    if domain == "fullstack-crud-auth":
        return ["npm test", "npm run smoke"]
    if domain == "saas-ops-suite":
        return ["npm test", "npm run smoke"]
    if domain == "support-helpdesk":
        return ["npm test", "npm run smoke"]
    if domain == "saas-ops-enhancement":
        return ["npm test"]
    return list(base_spec.get("validationCommands") or [])


def _semantic_rules_for_domain(domain: str, base_spec: dict[str, Any]) -> list[str]:
    rules = list(base_spec.get("semanticRules") or [])
    if domain == "personal-finance-mobile":
        for rule in ("node-test-native", "esm-no-require", "personal-finance", "integer-cents", "mobile-responsive", "delivery-gates"):
            if rule not in rules:
                rules.append(rule)
    if domain == "fullstack-crud-auth":
        for rule in ("node-test-native", "esm-no-require", "auth-rbac", "fullstack-crud", "delivery-gates"):
            if rule not in rules:
                rules.append(rule)
    if domain == "saas-ops-suite":
        for rule in ("node-test-native", "esm-no-require", "auth-rbac", "fullstack-crud", "integer-cents", "ledger-audit", "delivery-gates"):
            if rule not in rules:
                rules.append(rule)
    if domain == "support-helpdesk":
        for rule in ("node-test-native", "esm-no-require", "auth-rbac", "ticket-workflow", "accessible-html", "delivery-gates"):
            if rule not in rules:
                rules.append(rule)
    if domain == "saas-ops-enhancement":
        for rule in ("node-test-native", "esm-no-require", "incremental-change", "ledger-audit", "csv-export", "delivery-gates"):
            if rule not in rules:
                rules.append(rule)
    return rules


def _min_tests_for_domain(domain: str) -> int:
    if domain == "personal-finance-mobile":
        return 12
    if domain == "saas-ops-suite":
        return 10
    if domain == "support-helpdesk":
        return 8
    if domain == "saas-ops-enhancement":
        return 6
    return 7 if domain == "fullstack-crud-auth" else 0


def _build_work_orders(spec: SoftwareSpec, agents: dict[str, dict[str, Any]]) -> list[WorkOrder]:
    def agent(name: str) -> str:
        return name if name in agents else "ravenna"

    if spec.domain == "personal-finance-mobile":
        return [
            WorkOrder(
                id="finance-domain",
                agent=agent("finance-lead"),
                specialty="finance",
                objective="Implement personal finance domain with integer cents, budgets, recurring entries and goals.",
                target_files=["src/finance.js"],
                acceptance=["Uses cents integers", "Covers income and expenses", "Includes budgets, goals and recurring transactions"],
            ),
            WorkOrder(
                id="finance-api",
                agent=agent("backend-lead"),
                specialty="backend",
                objective="Expose routeable API functions for the finance system.",
                target_files=["src/server.js"],
                acceptance=["Exports createApp and routeRequest", "Routes transactions, summary, budgets and goals", "No external dependencies"],
            ),
            WorkOrder(
                id="mobile-frontend",
                agent=agent("frontend-lead"),
                specialty="frontend",
                objective="Implement mobile-first personal finance UI.",
                target_files=["public/index.html", "public/styles.css"],
                acceptance=["Responsive viewport", "Mobile-first cards", "Accessible forms and labels"],
            ),
            WorkOrder(
                id="finance-qa",
                agent=agent("qa-guardian"),
                specialty="qa",
                objective="Provide tests for finance invariants and edge cases.",
                target_files=["test/finance.test.mjs"],
                acceptance=[f"At least {spec.min_tests} tests", "Covers budget overspend", "Covers CSV and recurring transactions"],
            ),
            WorkOrder(
                id="finance-reliability",
                agent=agent("reliability-lead"),
                specialty="reliability",
                objective="Provide smoke command and delivery evidence.",
                target_files=["package.json", "src/smoke.js", "README.md"],
                acceptance=["npm test passes", "npm run smoke passes", "README explains mobile usage"],
            ),
        ]

    if spec.domain == "saas-ops-suite":
        return [
            WorkOrder(
                id="backend-domain",
                agent=agent("backend-lead"),
                specialty="backend",
                objective="Implement auth, persistence and tenant-scoped CRUD domain functions.",
                target_files=["src/auth.js", "src/store.js", "src/server.js"],
                acceptance=["Exports required backend functions", "No external dependencies", "Auth rejects invalid credentials"],
            ),
            WorkOrder(
                id="billing-ledger",
                agent=agent("finance-lead"),
                specialty="finance",
                objective="Implement integer-cents billing and append-only ledger operations.",
                target_files=["src/billing.js"],
                acceptance=["Uses integer cents", "Records invoices and payments", "Summarizes ledger balances"],
            ),
            WorkOrder(
                id="frontend-shell",
                agent=agent("frontend-lead"),
                specialty="frontend",
                objective="Implement a usable SaaS operations shell for auth, projects and billing overview.",
                target_files=["public/index.html"],
                acceptance=["Contains login form", "Contains project CRUD UI", "Contains billing dashboard", "Uses accessible labels"],
            ),
            WorkOrder(
                id="qa-contract",
                agent=agent("qa-guardian"),
                specialty="qa",
                objective="Provide meaningful tests for auth, CRUD, billing and API routing.",
                target_files=["test/app.test.mjs"],
                acceptance=[f"At least {spec.min_tests} tests", "Uses node:test", "Covers billing and rejection paths"],
            ),
            WorkOrder(
                id="reliability-smoke",
                agent=agent("reliability-lead"),
                specialty="reliability",
                objective="Provide smoke command and delivery evidence.",
                target_files=["package.json", "src/smoke.js", "README.md"],
                acceptance=["npm test passes", "npm run smoke passes", "README explains local usage"],
            ),
        ]

    if spec.domain == "support-helpdesk":
        return [
            WorkOrder(
                id="helpdesk-backend",
                agent=agent("backend-lead"),
                specialty="backend",
                objective="Implement auth and ticket workflow domain functions.",
                target_files=["src/auth.js", "src/store.js", "src/server.js"],
                acceptance=["Exports auth and ticket functions", "Routes login and tickets", "No external dependencies"],
            ),
            WorkOrder(
                id="helpdesk-frontend",
                agent=agent("frontend-lead"),
                specialty="frontend",
                objective="Implement accessible helpdesk dashboard for tickets and priorities.",
                target_files=["public/index.html"],
                acceptance=["Contains ticket form", "Shows priorities", "Uses accessible labels"],
            ),
            WorkOrder(
                id="helpdesk-qa",
                agent=agent("qa-guardian"),
                specialty="qa",
                objective="Provide tests for auth, ticket creation, listing and priority updates.",
                target_files=["test/app.test.mjs"],
                acceptance=[f"At least {spec.min_tests} tests", "Uses node:test", "Covers invalid login and ticket update"],
            ),
            WorkOrder(
                id="helpdesk-reliability",
                agent=agent("reliability-lead"),
                specialty="reliability",
                objective="Provide smoke command and delivery evidence.",
                target_files=["package.json", "src/smoke.js", "README.md"],
                acceptance=["npm test passes", "npm run smoke passes", "README explains local usage"],
            ),
        ]

    if spec.domain == "saas-ops-enhancement":
        return [
            WorkOrder(
                id="audit-enhancement",
                agent=agent("backend-lead"),
                specialty="backend",
                objective="Add audit log helpers for incremental project and invoice events.",
                target_files=["src/audit.js"],
                acceptance=["Exports recordAuditEvent and listAuditEvents", "Does not require external dependencies"],
            ),
            WorkOrder(
                id="ledger-csv-enhancement",
                agent=agent("finance-lead"),
                specialty="finance",
                objective="Add CSV export to billing ledger while preserving integer-cents accounting.",
                target_files=["src/billing.js"],
                acceptance=["Exports exportLedgerCsv", "Preserves summarizeLedger", "Uses integer cents"],
            ),
            WorkOrder(
                id="enhancement-qa",
                agent=agent("qa-guardian"),
                specialty="qa",
                objective="Provide regression tests for audit log and ledger CSV export.",
                target_files=["test/app.test.mjs"],
                acceptance=[f"At least {spec.min_tests} tests", "Covers audit", "Covers CSV"],
            ),
        ]

    return [
        WorkOrder(
            id="backend-domain",
            agent=agent("backend-lead"),
            specialty="backend",
            objective="Implement auth, persistence and CRUD domain functions.",
            target_files=["src/auth.js", "src/store.js", "src/server.js"],
            acceptance=["Exports required backend functions", "No external dependencies", "Auth rejects invalid credentials"],
        ),
        WorkOrder(
            id="frontend-shell",
            agent=agent("frontend-lead"),
            specialty="frontend",
            objective="Implement a usable frontend shell for login and project CRUD.",
            target_files=["public/index.html"],
            acceptance=["Contains login form", "Contains project CRUD UI", "Uses accessible labels"],
        ),
        WorkOrder(
            id="qa-contract",
            agent=agent("qa-guardian"),
            specialty="qa",
            objective="Provide meaningful tests for auth, CRUD and API routing.",
            target_files=["test/app.test.mjs"],
            acceptance=[f"At least {spec.min_tests} tests", "Uses node:test", "Covers rejection paths"],
        ),
        WorkOrder(
            id="reliability-smoke",
            agent=agent("reliability-lead"),
            specialty="reliability",
            objective="Provide smoke command and delivery evidence.",
            target_files=["package.json", "src/smoke.js", "README.md"],
            acceptance=["npm test passes", "npm run smoke passes", "README explains local usage"],
        ),
    ]


def _mark_work_orders_done(spec: dict[str, Any], applied: dict[str, Any]) -> None:
    changed = "\n".join(applied.get("changedPaths") or [])
    for order in spec.get("workOrders") or []:
        if all(path in changed for path in order.get("targetFiles") or []):
            order["status"] = "completed"
            order["evidence"] = ["canonical files applied"]


def _contract_gate(root: Path, spec: dict[str, Any]) -> dict[str, Any]:
    failures = [f"Missing required file: {path}" for path in spec.get("requiredFiles") or [] if not (root / path).is_file()]
    for file_path, exports in (spec.get("requiredExports") or {}).items():
        source = (root / file_path).read_text(encoding="utf-8", errors="replace") if (root / file_path).is_file() else ""
        for name in exports:
            if f"export function {name}" not in source and f"export const {name}" not in source:
                failures.append(f"`{file_path}` does not export `{name}`.")
    return {"name": "contract_gate", "ok": not failures, "failures": failures, "risks": []}


def _validation_gate(spec: dict[str, Any], applied: dict[str, Any], *, run_validation: bool) -> dict[str, Any]:
    if not run_validation:
        return {"name": "build_gate", "ok": True, "failures": [], "risks": ["Validation skipped."], "commands": []}
    shell_text = "\n".join(f"```shell\n{command}\n```" for command in spec.get("validationCommands") or [])
    result = agent_autonomy_runner.run_safe_shell_blocks(
        shell_text,
        changed_paths=applied.get("changedPaths") or [],
        project_root=spec.get("projectRoot"),
        timeout_seconds=120,
    )
    return {
        "name": "build_gate",
        "ok": bool(result.get("ok")) and not result.get("blocked"),
        "failures": list(result.get("failures") or []) + [item.get("reason", "blocked") for item in result.get("blocked") or []],
        "risks": [],
        "commands": result.get("ran") or [],
    }


def _test_gate(root: Path, spec: dict[str, Any], validation: dict[str, Any]) -> dict[str, Any]:
    output = "\n".join(str(command.get("output") or "") for command in validation.get("commands") or [])
    count = _node_test_count(output)
    if count == 0:
        count = _source_test_count(root)
    min_tests = int(spec.get("minTests") or 0)
    failures = []
    if min_tests and count < min_tests:
        failures.append(f"Insufficient tests: {count} found; expected >= {min_tests}.")
    if validation.get("failures"):
        failures.append("Validation commands failed before test gate could pass.")
    return {"name": "test_gate", "ok": not failures, "failures": failures, "risks": [], "testCount": count, "minTests": min_tests}


def _source_test_count(root: Path) -> int:
    count = 0
    for path in (root / "test").glob("*.mjs"):
        count += path.read_text(encoding="utf-8", errors="replace").count("test(")
    for path in (root / "tests").glob("test_*.py"):
        count += path.read_text(encoding="utf-8", errors="replace").count("def test_")
    return count


def _qa_gate(root: Path, spec: dict[str, Any], validation: dict[str, Any]) -> dict[str, Any]:
    output = "\n".join(str(command.get("output") or "") for command in validation.get("commands") or [])
    source = output
    if not source.strip():
        test_dir = root / "test"
        source = "\n".join(
            path.read_text(encoding="utf-8", errors="replace")
            for path in test_dir.glob("*.mjs")
        )
    if spec.get("domain") == "personal-finance-mobile":
        required_terms = ["budget", "transaction", "goal"]
    elif spec.get("domain") == "saas-ops-suite":
        required_terms = ["auth", "project", "billing", "ledger"]
    elif spec.get("domain") == "support-helpdesk":
        required_terms = ["auth", "ticket", "priority"]
    elif spec.get("domain") == "saas-ops-enhancement":
        required_terms = ["audit", "csv", "ledger"]
    else:
        required_terms = ["auth", "project", "delete"]
    missing = [term for term in required_terms if term not in source.lower()]
    failures = [f"QA coverage missing visible assertion area: {term}" for term in missing]
    return {"name": "qa_gate", "ok": not failures, "failures": failures, "risks": []}


def _mobile_visual_gate(root: Path, spec: dict[str, Any]) -> dict[str, Any]:
    if spec.get("domain") != "personal-finance-mobile":
        return {"name": "mobile_visual_gate", "ok": True, "failures": [], "risks": ["Not a mobile UI domain."]}
    html_path = root / "public" / "index.html"
    css_path = root / "public" / "styles.css"
    html = html_path.read_text(encoding="utf-8", errors="replace") if html_path.is_file() else ""
    css = css_path.read_text(encoding="utf-8", errors="replace") if css_path.is_file() else ""
    checks = {
        "viewport width=device-width": 'name="viewport"' in html and "width=device-width" in html,
        "accessible transaction form": 'aria-label="Nova transação"' in html and "<label" in html,
        "mobile numeric input": 'inputmode="numeric"' in html,
        "submit flow posts transaction": 'addEventListener("submit"' in html and 'fetch("/api/transactions"' in html,
        "accessible submit feedback": 'role="status"' in html and 'aria-live="polite"' in html,
        "mobile-first single column": "grid-template-columns: 1fr" in css,
        "390px-friendly touch targets": "min-height: 44px" in css,
        "responsive breakpoint": "@media" in css and "min-width: 720px" in css,
    }
    failures = [f"Mobile visual check failed: {name}" for name, ok in checks.items() if not ok]
    return {
        "name": "mobile_visual_gate",
        "ok": not failures,
        "failures": failures,
        "risks": ["Static mobile gate; add real browser screenshot diff for full visual parity."],
        "viewport": {"width": 390, "height": 844},
    }


def _browser_mobile_gate(root: Path, spec: dict[str, Any]) -> dict[str, Any]:
    html_path = root / "public" / "index.html"
    css_path = root / "public" / "styles.css"
    server_path = root / "src" / "server.js"
    html = html_path.read_text(encoding="utf-8", errors="replace") if html_path.is_file() else ""
    css = css_path.read_text(encoding="utf-8", errors="replace") if css_path.is_file() else ""
    server = server_path.read_text(encoding="utf-8", errors="replace") if server_path.is_file() else ""
    if spec.get("domain") != "personal-finance-mobile" and not html:
        return {"name": "browser_mobile_gate", "ok": True, "failures": [], "risks": ["No web UI detected."], "evidence": {"webUiDetected": False}}
    if spec.get("domain") != "personal-finance-mobile":
        return {
            "name": "browser_mobile_gate",
            "ok": True,
            "failures": [],
            "risks": ["Generic web evidence collected; mobile finance flow checks are not required for this domain."],
            "evidence": {
                "webUiDetected": True,
                "viewport": {"width": 390, "height": 844},
                "checks": {
                    "html exists": bool(html),
                    "viewport present": 'name="viewport"' in html and "width=device-width" in html,
                    "server route file present": server_path.is_file(),
                },
                "runner": {"configured": bool(os.environ.get("RAVENNA_BROWSER_GATE_CMD", "").strip())},
            },
        }
    checks = {
        "viewport 390px contract": 'name="viewport"' in html and "width=device-width" in html,
        "form can submit in browser": 'addEventListener("submit"' in html and 'fetch("/api/transactions"' in html,
        "submit route exists": 'path === "/api/transactions"' in server,
        "css route exists": 'path === "/styles.css"' in server and "readFileSync(\"public/styles.css\"" in server,
        "accessible feedback": 'role="status"' in html and 'aria-live="polite"' in html,
        "touch targets": "min-height: 44px" in css,
        "no horizontal desktop breakpoint at 390": "@media (min-width: 720px)" in css,
    }
    failures = [f"Browser mobile check failed: {name}" for name, ok in checks.items() if not ok]
    evidence = {
        "viewport": {"width": 390, "height": 844},
        "scenario": "fill description/category/amount/date, submit transaction, expect status text",
        "selectorContracts": ["form[aria-label='Nova transação']", ".form-status", "input[name='amountCents']"],
        "checks": checks,
    }
    runner = os.environ.get("RAVENNA_BROWSER_GATE_CMD", "").strip()
    if runner:
        try:
            proc = subprocess.run(
                runner,
                cwd=root,
                shell=True,
                capture_output=True,
                text=True,
                timeout=90,
                env={
                    **os.environ,
                    "RAVENNA_BROWSER_WIDTH": "390",
                    "RAVENNA_BROWSER_HEIGHT": "844",
                    "RAVENNA_BROWSER_SCENARIO": "finance-mobile-submit",
                },
            )
            evidence["runner"] = {
                "command": runner,
                "exitCode": proc.returncode,
                "output": (proc.stdout + proc.stderr)[-4000:],
            }
            if proc.returncode != 0:
                failures.append(f"Browser runner failed with exit {proc.returncode}.")
        except (OSError, subprocess.TimeoutExpired) as exc:
            evidence["runner"] = {"command": runner, "error": str(exc)}
            failures.append(f"Browser runner failed: {exc}")
    else:
        evidence["runner"] = {"configured": False}
    return {
        "name": "browser_mobile_gate",
        "ok": not failures,
        "failures": failures,
        "risks": [] if runner else ["No browser runner configured; deterministic DOM/server contract was used."],
        "evidence": evidence,
    }


def _finance_domain_gate(root: Path, spec: dict[str, Any]) -> dict[str, Any]:
    if spec.get("domain") != "personal-finance-mobile":
        return {"name": "finance_domain_gate", "ok": True, "failures": [], "risks": ["Not a finance domain."]}
    source_path = root / "src" / "finance.js"
    source = source_path.read_text(encoding="utf-8", errors="replace") if source_path.is_file() else ""
    required_tokens = {
        "integer cents": "assertCents",
        "cash-flow projection": "projectCashFlow",
        "local JSON persistence": "saveFinanceStore",
        "duplicate transaction detection": "duplicate transaction",
        "budget overspend": "overspent",
        "recurring materialization": "materializeRecurring",
        "goal deadline projection": "targetDate",
        "CSV export": "exportCsv",
    }
    failures = [f"Finance invariant missing: {name}" for name, token in required_tokens.items() if token not in source]
    if re.search(r"amount(?:\s*[+\-*/]|\s*=)\s*\d+\.\d+", source):
        failures.append("Finance source appears to use decimal money arithmetic.")
    return {"name": "finance_domain_gate", "ok": not failures, "failures": failures, "risks": []}


def _cross_review_execution_gate(spec: dict[str, Any], reviews: list[dict[str, Any]]) -> dict[str, Any]:
    work_orders = spec.get("workOrders") or []
    failures: list[str] = []
    if len(reviews) < len(work_orders):
        failures.append(f"Cross-review incomplete: {len(reviews)} reviewed; expected {len(work_orders)}.")
    for review in reviews:
        if not review.get("ok"):
            failures.extend(review.get("failures") or [f"Cross-review failed for `{review.get('phase')}`."])
    return {
        "name": "cross_review_execution_gate",
        "ok": not failures,
        "failures": failures,
        "risks": [],
        "reviewCount": len(reviews),
        "expectedReviews": len(work_orders),
    }


def _cross_review_gate(root: Path, spec: dict[str, Any]) -> dict[str, Any]:
    failures: list[str] = []
    if spec.get("domain") == "personal-finance-mobile":
        html = (root / "public" / "index.html").read_text(encoding="utf-8", errors="replace") if (root / "public" / "index.html").is_file() else ""
        server = (root / "src" / "server.js").read_text(encoding="utf-8", errors="replace") if (root / "src" / "server.js").is_file() else ""
        tests = (root / "test" / "finance.test.mjs").read_text(encoding="utf-8", errors="replace") if (root / "test" / "finance.test.mjs").is_file() else ""
        for route in re.findall(r'fetch\("([^"]+)"', html):
            if f'path === "{route}"' not in server:
                failures.append(f"Frontend submits to `{route}`, but server route is missing.")
        for token in ("projectCashFlow", "saveFinanceStore", "loadFinanceStore"):
            if token not in server:
                failures.append(f"Backend does not wire finance export `{token}`.")
        for coverage in ("cashflow projection", "persists and loads", "serves mobile CSS"):
            if coverage not in tests:
                failures.append(f"QA suite missing cross-review coverage: {coverage}.")
    elif spec.get("domain") in {"fullstack-crud-auth", "saas-ops-suite", "support-helpdesk"}:
        html = (root / "public" / "index.html").read_text(encoding="utf-8", errors="replace") if (root / "public" / "index.html").is_file() else ""
        server = (root / "src" / "server.js").read_text(encoding="utf-8", errors="replace") if (root / "src" / "server.js").is_file() else ""
        tests = (root / "test" / "app.test.mjs").read_text(encoding="utf-8", errors="replace") if (root / "test" / "app.test.mjs").is_file() else ""
        if "Login" in html and 'path === "/api/login"' not in server:
            failures.append("Frontend exposes login but backend login route is missing.")
        if spec.get("domain") != "support-helpdesk" and "delete" not in tests.lower():
            failures.append("QA suite missing delete-path coverage.")
        if spec.get("domain") == "saas-ops-suite":
            billing = (root / "src" / "billing.js").read_text(encoding="utf-8", errors="replace") if (root / "src" / "billing.js").is_file() else ""
            if "summarizeLedger" not in billing:
                failures.append("Billing ledger summary is missing.")
            if "billing" not in tests.lower() or "ledger" not in tests.lower():
                failures.append("QA suite missing billing/ledger coverage.")
        if spec.get("domain") == "support-helpdesk":
            if 'path === "/api/tickets"' not in server:
                failures.append("Helpdesk backend ticket route is missing.")
            if "ticket" not in tests.lower() or "priority" not in tests.lower():
                failures.append("QA suite missing ticket/priority coverage.")
    elif spec.get("domain") == "saas-ops-enhancement":
        audit = (root / "src" / "audit.js").read_text(encoding="utf-8", errors="replace") if (root / "src" / "audit.js").is_file() else ""
        billing = (root / "src" / "billing.js").read_text(encoding="utf-8", errors="replace") if (root / "src" / "billing.js").is_file() else ""
        tests = (root / "test" / "app.test.mjs").read_text(encoding="utf-8", errors="replace") if (root / "test" / "app.test.mjs").is_file() else ""
        if "recordAuditEvent" not in audit:
            failures.append("Audit enhancement helper is missing.")
        if "exportLedgerCsv" not in billing:
            failures.append("Ledger CSV export is missing.")
        if "audit" not in tests.lower() or "csv" not in tests.lower():
            failures.append("QA suite missing audit/CSV coverage.")
    return {"name": "cross_review_gate", "ok": not failures, "failures": failures, "risks": []}


def _security_gate(root: Path, spec: dict[str, Any]) -> dict[str, Any]:
    failures = []
    risks = []
    scan_files = ["src/auth.js", "src/store.js", "src/server.js"]
    if spec.get("domain") == "personal-finance-mobile":
        scan_files.extend(["src/finance.js", "public/index.html"])
    if spec.get("domain") == "saas-ops-suite":
        scan_files.extend(["src/billing.js", "public/index.html"])
    if spec.get("domain") == "support-helpdesk":
        scan_files.extend(["public/index.html"])
    if spec.get("domain") == "saas-ops-enhancement":
        scan_files.extend(["src/audit.js", "src/billing.js"])
    for rel in scan_files:
        path = root / rel
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if "password ===" in text:
            failures.append(f"{rel} compares raw passwords.")
        if re.search(r"(api[_-]?key|secret)\s*=", text, re.IGNORECASE):
            failures.append(f"{rel} appears to hardcode a secret.")
        if re.search(r"\beval\s*\(|new Function\s*\(", text):
            failures.append(f"{rel} uses dynamic code execution.")
        if rel.endswith(".html") and "innerHTML" in text:
            failures.append(f"{rel} may inject unsafe HTML.")
    if not failures and spec.get("domain") == "personal-finance-mobile":
        risks.append("No user auth/encryption yet; acceptable for local MVP, not production finance.")
    elif not failures:
        risks.append("Security gate is static; production auth still needs threat-model review.")
    return {"name": "security_gate", "ok": not failures, "failures": failures, "risks": risks}


def _docs_gate(root: Path, spec: dict[str, Any]) -> dict[str, Any]:
    readme = root / "README.md"
    failures = []
    if "README.md" in (spec.get("requiredFiles") or []) and not readme.is_file():
        failures.append("README.md missing.")
    elif readme.is_file():
        text = readme.read_text(encoding="utf-8", errors="replace").lower()
        for token in ("npm test", "npm run smoke"):
            if token not in text:
                failures.append(f"README.md does not document `{token}`.")
    return {"name": "docs_gate", "ok": not failures, "failures": failures, "risks": []}


def _reliability_gate(validation: dict[str, Any]) -> dict[str, Any]:
    failures = []
    for command in validation.get("commands") or []:
        if command.get("exit_code") not in (0, None):
            failures.append(f"{command.get('command')} failed with exit {command.get('exit_code')}.")
    return {"name": "reliability_gate", "ok": not failures, "failures": failures, "risks": []}


def _node_test_count(output: str) -> int:
    match = re.search(r"tests\s+(\d+)", output)
    return int(match.group(1)) if match else 0


def _reconciler_reply_for_domain(domain: str) -> str:
    if domain == "personal-finance-mobile":
        blocks = {
            "package.json": _finance_package_json(),
            "README.md": _finance_readme(),
            "src/finance.js": _finance_js(),
            "src/server.js": _finance_server_js(),
            "src/smoke.js": _finance_smoke_js(),
            "public/index.html": _finance_index_html(),
            "public/styles.css": _finance_styles_css(),
            "test/finance.test.mjs": _finance_tests(),
        }
        return "\n\n".join(f"```write {path}\n{content}\n```" for path, content in blocks.items())
    if domain == "saas-ops-suite":
        blocks = {
            "package.json": _fullstack_package_json(),
            "README.md": _ops_readme(),
            "src/auth.js": _fullstack_auth_js(),
            "src/store.js": _fullstack_store_js(),
            "src/billing.js": _ops_billing_js(),
            "src/server.js": _ops_server_js(),
            "src/smoke.js": _ops_smoke_js(),
            "public/index.html": _ops_index_html(),
            "test/app.test.mjs": _ops_tests(),
        }
        return "\n\n".join(f"```write {path}\n{content}\n```" for path, content in blocks.items())
    if domain == "support-helpdesk":
        blocks = {
            "package.json": _fullstack_package_json(),
            "README.md": _helpdesk_readme(),
            "src/auth.js": _fullstack_auth_js(),
            "src/store.js": _helpdesk_store_js(),
            "src/server.js": _helpdesk_server_js(),
            "src/smoke.js": _helpdesk_smoke_js(),
            "public/index.html": _helpdesk_index_html(),
            "test/app.test.mjs": _helpdesk_tests(),
        }
        return "\n\n".join(f"```write {path}\n{content}\n```" for path, content in blocks.items())
    if domain == "saas-ops-enhancement":
        blocks = {
            "src/audit.js": _audit_js(),
            "src/billing.js": _ops_billing_js(),
            "test/app.test.mjs": _ops_enhancement_tests(),
        }
        return "\n\n".join(f"```write {path}\n{content}\n```" for path, content in blocks.items())
    if domain != "fullstack-crud-auth":
        return ""
    blocks = {
        "package.json": _fullstack_package_json(),
        "README.md": _fullstack_readme(),
        "src/auth.js": _fullstack_auth_js(),
        "src/store.js": _fullstack_store_js(),
        "src/server.js": _fullstack_server_js(),
        "src/smoke.js": _fullstack_smoke_js(),
        "public/index.html": _fullstack_index_html(),
        "test/app.test.mjs": _fullstack_tests(),
    }
    return "\n\n".join(f"```write {path}\n{content}\n```" for path, content in blocks.items())


def _finance_package_json() -> str:
    return json.dumps(
        {
            "type": "module",
            "scripts": {
                "test": "node --test test/finance.test.mjs",
                "smoke": "node src/smoke.js",
                "start": "node src/server.js",
            },
        },
        ensure_ascii=False,
        indent=2,
    )


def _finance_readme() -> str:
    return """# Personal Finance Mobile

Mobile-first personal finance control system without external dependencies.

## Features

- Income and expense tracking using integer cents.
- Categories, monthly summaries and cash-flow balance.
- Budgets with overspend detection.
- Financial goals with projection.
- Recurring transactions materialized by month.
- CSV export for offline analysis.
- Responsive mobile UI in `public/index.html` and `public/styles.css`.

## Commands

- Run tests with `npm test`.
- Run smoke validation with `npm run smoke`.
- Start the local server with `npm start`.
"""


def _finance_js() -> str:
    return """import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";

export function createFinanceStore(snapshot = {}) {
  const store = {
    transactions: new Map(),
    budgets: new Map(),
    goals: new Map(),
    recurring: new Map(),
    nextId: snapshot.nextId || 1,
  };
  for (const item of snapshot.transactions || []) store.transactions.set(item.id, item);
  for (const item of snapshot.budgets || []) store.budgets.set(item.id, item);
  for (const item of snapshot.goals || []) store.goals.set(item.id, item);
  for (const item of snapshot.recurring || []) store.recurring.set(item.id, item);
  return store;
}

function snapshotStore(store) {
  return {
    transactions: [...store.transactions.values()].map((item) => ({ ...item })),
    budgets: [...store.budgets.values()].map((item) => ({ ...item })),
    goals: [...store.goals.values()].map((item) => ({ ...item })),
    recurring: [...store.recurring.values()].map((item) => ({ ...item })),
    nextId: store.nextId,
  };
}

export function saveFinanceStore(store, filePath = "data/finance-store.json") {
  mkdirSync(dirname(filePath), { recursive: true });
  writeFileSync(filePath, JSON.stringify(snapshotStore(store), null, 2), "utf-8");
  return { saved: true, filePath };
}

export function loadFinanceStore(filePath = "data/finance-store.json") {
  return createFinanceStore(JSON.parse(readFileSync(filePath, "utf-8")));
}

function assertCents(value, name) {
  if (!Number.isInteger(value) || value < 0) throw new Error(`${name} must be a non-negative integer in cents`);
}

function monthOf(date) {
  return String(date || "").slice(0, 7);
}

function nextId(store, prefix) {
  const id = `${prefix}-${store.nextId}`;
  store.nextId += 1;
  return id;
}

export function addTransaction(store, input) {
  const type = input?.type;
  if (!["income", "expense"].includes(type)) throw new Error("type must be income or expense");
  assertCents(input.amountCents, "amountCents");
  if (!input.category) throw new Error("category is required");
  if (!input.date || !/^\\d{4}-\\d{2}-\\d{2}$/.test(input.date)) throw new Error("date must be YYYY-MM-DD");
  const description = input.description || "";
  const duplicate = [...store.transactions.values()].some((transaction) =>
    transaction.type === type &&
    transaction.amountCents === input.amountCents &&
    transaction.category === input.category &&
    transaction.date === input.date &&
    transaction.description === description
  );
  if (!input.id && duplicate) throw new Error("duplicate transaction detected");
  const transaction = {
    id: input.id || nextId(store, "tx"),
    type,
    amountCents: input.amountCents,
    category: input.category,
    date: input.date,
    description,
  };
  store.transactions.set(transaction.id, transaction);
  return { ...transaction };
}

export function listTransactions(store, filters = {}) {
  return [...store.transactions.values()]
    .filter((transaction) => !filters.month || monthOf(transaction.date) === filters.month)
    .filter((transaction) => !filters.type || transaction.type === filters.type)
    .sort((a, b) => a.date.localeCompare(b.date))
    .map((transaction) => ({ ...transaction }));
}

export function summarizeByMonth(store, month) {
  const transactions = listTransactions(store, { month });
  const summary = { month, incomeCents: 0, expenseCents: 0, balanceCents: 0, byCategory: {} };
  for (const transaction of transactions) {
    if (transaction.type === "income") summary.incomeCents += transaction.amountCents;
    if (transaction.type === "expense") {
      summary.expenseCents += transaction.amountCents;
      summary.byCategory[transaction.category] = (summary.byCategory[transaction.category] || 0) + transaction.amountCents;
    }
  }
  summary.balanceCents = summary.incomeCents - summary.expenseCents;
  return summary;
}

export function setBudget(store, input) {
  if (!input?.month || !/^\\d{4}-\\d{2}$/.test(input.month)) throw new Error("month must be YYYY-MM");
  if (!input.category) throw new Error("category is required");
  assertCents(input.limitCents, "limitCents");
  const key = `${input.month}:${input.category}`;
  const budget = { id: key, month: input.month, category: input.category, limitCents: input.limitCents };
  store.budgets.set(key, budget);
  return { ...budget };
}

export function checkBudgets(store, month) {
  const summary = summarizeByMonth(store, month);
  return [...store.budgets.values()]
    .filter((budget) => budget.month === month)
    .map((budget) => {
      const spentCents = summary.byCategory[budget.category] || 0;
      return {
        ...budget,
        spentCents,
        remainingCents: budget.limitCents - spentCents,
        overspent: spentCents > budget.limitCents,
      };
    });
}

export function addGoal(store, input) {
  assertCents(input?.targetCents, "targetCents");
  assertCents(input?.savedCents || 0, "savedCents");
  const goal = {
    id: input.id || nextId(store, "goal"),
    name: input.name || "Goal",
    targetCents: input.targetCents,
    savedCents: input.savedCents || 0,
    monthlyContributionCents: input.monthlyContributionCents || 0,
    targetDate: input.targetDate || null,
  };
  assertCents(goal.monthlyContributionCents, "monthlyContributionCents");
  store.goals.set(goal.id, goal);
  return { ...goal };
}

export function projectGoal(store, goalId) {
  const goal = store.goals.get(goalId);
  if (!goal) throw new Error("goal not found");
  const remainingCents = Math.max(0, goal.targetCents - goal.savedCents);
  const monthsToTarget = goal.monthlyContributionCents > 0 ? Math.ceil(remainingCents / goal.monthlyContributionCents) : null;
  const onTrack = goal.targetDate && monthsToTarget !== null
    ? monthsToTarget <= monthsBetween(new Date().toISOString().slice(0, 10), goal.targetDate)
    : null;
  return { ...goal, remainingCents, monthsToTarget, onTrack };
}

export function addRecurringTransaction(store, input) {
  const template = {
    id: input.id || nextId(store, "rec"),
    type: input.type,
    amountCents: input.amountCents,
    category: input.category,
    description: input.description || "",
    dayOfMonth: input.dayOfMonth || 1,
  };
  if (!["income", "expense"].includes(template.type)) throw new Error("type must be income or expense");
  assertCents(template.amountCents, "amountCents");
  store.recurring.set(template.id, template);
  return { ...template };
}

export function materializeRecurring(store, month) {
  if (!/^\\d{4}-\\d{2}$/.test(month)) throw new Error("month must be YYYY-MM");
  const created = [];
  for (const template of store.recurring.values()) {
    const date = `${month}-${String(template.dayOfMonth).padStart(2, "0")}`;
    const id = `${template.id}:${month}`;
    if (!store.transactions.has(id)) {
      created.push(addTransaction(store, { ...template, id, date }));
    }
  }
  return created;
}

function addMonths(month, offset) {
  const [year, rawMonth] = month.split("-").map(Number);
  const date = new Date(Date.UTC(year, rawMonth - 1 + offset, 1));
  return date.toISOString().slice(0, 7);
}

function monthsBetween(startDate, endDate) {
  const [startYear, startMonth] = startDate.slice(0, 7).split("-").map(Number);
  const [endYear, endMonth] = endDate.slice(0, 7).split("-").map(Number);
  return Math.max(0, (endYear - startYear) * 12 + (endMonth - startMonth));
}

export function projectCashFlow(store, startMonth, months = 3) {
  if (!/^\\d{4}-\\d{2}$/.test(startMonth)) throw new Error("startMonth must be YYYY-MM");
  const projections = [];
  for (let index = 0; index < months; index += 1) {
    const month = addMonths(startMonth, index);
    const summary = summarizeByMonth(store, month);
    for (const template of store.recurring.values()) {
      if (template.type === "income") summary.incomeCents += template.amountCents;
      if (template.type === "expense") summary.expenseCents += template.amountCents;
    }
    summary.balanceCents = summary.incomeCents - summary.expenseCents;
    projections.push(summary);
  }
  return projections;
}

export function exportCsv(store) {
  const rows = ["id,date,type,category,amountCents,description"];
  for (const transaction of listTransactions(store)) {
    rows.push([transaction.id, transaction.date, transaction.type, transaction.category, transaction.amountCents, transaction.description.replaceAll(",", " ")].join(","));
  }
  return `${rows.join("\\n")}\\n`;
}
"""


def _finance_server_js() -> str:
    return """import { createServer } from "node:http";
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";
import {
  createFinanceStore,
  addTransaction,
  listTransactions,
  summarizeByMonth,
  setBudget,
  checkBudgets,
  addGoal,
  projectGoal,
  addRecurringTransaction,
  materializeRecurring,
  projectCashFlow,
  saveFinanceStore,
  loadFinanceStore,
  exportCsv,
} from "./finance.js";

export function createApp(store = createFinanceStore()) {
  return { store };
}

function json(status, body) {
  return { status, headers: { "content-type": "application/json" }, body: JSON.stringify(body) };
}

export function routeRequest(app, request) {
  const { method, path, body = {}, query = {} } = request;
  try {
    if (method === "GET" && path === "/") return { status: 200, headers: { "content-type": "text/html" }, body: readFileSync("public/index.html", "utf-8") };
    if (method === "GET" && path === "/styles.css") return { status: 200, headers: { "content-type": "text/css" }, body: readFileSync("public/styles.css", "utf-8") };
    if (method === "POST" && path === "/api/transactions") return json(201, addTransaction(app.store, body));
    if (method === "GET" && path === "/api/transactions") return json(200, listTransactions(app.store, query));
    if (method === "GET" && path === "/api/summary") return json(200, summarizeByMonth(app.store, query.month));
    if (method === "POST" && path === "/api/budgets") return json(201, setBudget(app.store, body));
    if (method === "GET" && path === "/api/budgets") return json(200, checkBudgets(app.store, query.month));
    if (method === "POST" && path === "/api/goals") return json(201, addGoal(app.store, body));
    if (method === "GET" && path.startsWith("/api/goals/")) return json(200, projectGoal(app.store, path.split("/").pop()));
    if (method === "POST" && path === "/api/recurring") return json(201, addRecurringTransaction(app.store, body));
    if (method === "POST" && path === "/api/recurring/materialize") return json(201, materializeRecurring(app.store, body.month));
    if (method === "GET" && path === "/api/cashflow") return json(200, projectCashFlow(app.store, query.startMonth, Number(query.months || 3)));
    if (method === "POST" && path === "/api/persistence/save") return json(200, saveFinanceStore(app.store, body.filePath));
    if (method === "POST" && path === "/api/persistence/load") {
      app.store = loadFinanceStore(body.filePath);
      return json(200, { loaded: true });
    }
    if (method === "GET" && path === "/api/export.csv") return { status: 200, headers: { "content-type": "text/csv" }, body: exportCsv(app.store) };
    return json(404, { error: "not found" });
  } catch (error) {
    return json(400, { error: error.message });
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const app = createApp();
  const server = createServer((req, res) => {
    const chunks = [];
    req.on("data", (chunk) => chunks.push(chunk));
    req.on("end", () => {
      const url = new URL(req.url, "http://localhost");
      const body = chunks.length ? JSON.parse(Buffer.concat(chunks).toString("utf-8")) : {};
      const query = Object.fromEntries(url.searchParams.entries());
      const result = routeRequest(app, { method: req.method, path: url.pathname, query, body });
      res.writeHead(result.status, result.headers);
      res.end(result.body);
    });
  });
  server.listen(3000, () => console.log("finance app listening on http://localhost:3000"));
}
"""


def _finance_smoke_js() -> str:
    return """import { rmSync } from "node:fs";
import { createFinanceStore, addTransaction, summarizeByMonth, setBudget, checkBudgets, addRecurringTransaction, projectCashFlow, saveFinanceStore, loadFinanceStore } from "./finance.js";

const store = createFinanceStore();
addTransaction(store, { type: "income", amountCents: 500000, category: "salary", date: "2026-06-01" });
addTransaction(store, { type: "expense", amountCents: 120000, category: "housing", date: "2026-06-02" });
addRecurringTransaction(store, { type: "expense", amountCents: 9000, category: "internet", dayOfMonth: 5 });
setBudget(store, { month: "2026-06", category: "housing", limitCents: 150000 });
saveFinanceStore(store, "data/smoke-finance-store.json");
const restored = loadFinanceStore("data/smoke-finance-store.json");
rmSync("data/smoke-finance-store.json", { force: true });
console.log(JSON.stringify({ ok: true, summary: summarizeByMonth(restored, "2026-06"), budgets: checkBudgets(restored, "2026-06"), cashflow: projectCashFlow(restored, "2026-06", 2) }));
"""


def _finance_index_html() -> str:
    return """<!doctype html>
<html lang="pt-BR">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Controle Financeiro Pessoal</title>
    <link rel="stylesheet" href="./styles.css" />
  </head>
  <body>
    <main class="app-shell">
      <section class="hero-card" aria-label="Resumo financeiro">
        <p class="eyebrow">Junho 2026</p>
        <h1>Controle financeiro pessoal</h1>
        <div class="summary-grid">
          <article><span>Receitas</span><strong>R$ 5.000,00</strong></article>
          <article><span>Despesas</span><strong>R$ 1.200,00</strong></article>
          <article><span>Saldo</span><strong>R$ 3.800,00</strong></article>
        </div>
      </section>

      <form class="card-form" aria-label="Nova transação">
        <label>Descrição <input name="description" placeholder="Mercado" /></label>
        <label>Categoria <input name="category" placeholder="Alimentação" /></label>
        <label>Valor em centavos <input name="amountCents" inputmode="numeric" /></label>
        <label>Data <input name="date" type="date" value="2026-06-15" /></label>
        <label>Tipo
          <select name="type">
            <option value="expense">Despesa</option>
            <option value="income">Receita</option>
          </select>
        </label>
        <button type="submit">Adicionar transação</button>
        <p class="form-status" role="status" aria-live="polite"></p>
      </form>

      <section class="card-list" aria-label="Orçamentos e metas">
        <article><h2>Orçamento</h2><p>Moradia: R$ 1.200,00 de R$ 1.500,00</p></article>
        <article><h2>Meta</h2><p>Reserva de emergência: 8 meses restantes</p></article>
        <article><h2>Recorrentes</h2><p>Salário, aluguel, internet e assinaturas.</p></article>
      </section>
    </main>
    <script>
      const form = document.querySelector("form[aria-label='Nova transação']");
      const status = document.querySelector(".form-status");
      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const data = new FormData(form);
        const body = {
          description: data.get("description"),
          category: data.get("category"),
          amountCents: Number(data.get("amountCents")),
          date: data.get("date"),
          type: data.get("type"),
        };
        const response = await fetch("/api/transactions", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify(body),
        });
        const payload = await response.json();
        status.textContent = response.ok ? `Transação ${payload.id} adicionada.` : payload.error;
      });
    </script>
  </body>
</html>
"""


def _finance_styles_css() -> str:
    return """:root {
  color-scheme: light dark;
  font-family: Inter, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  background: #0f172a;
  color: #e5eefb;
}

* {
  box-sizing: border-box;
}

body {
  margin: 0;
}

.app-shell {
  width: min(100%, 880px);
  margin: 0 auto;
  padding: 16px;
  display: grid;
  gap: 16px;
}

.hero-card,
.card-form,
.card-list article {
  border: 1px solid rgba(148, 163, 184, 0.25);
  border-radius: 24px;
  background: rgba(15, 23, 42, 0.9);
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.24);
  padding: 20px;
}

.eyebrow {
  color: #93c5fd;
  text-transform: uppercase;
  letter-spacing: 0.12em;
  font-size: 0.75rem;
}

.summary-grid,
.card-list {
  display: grid;
  grid-template-columns: 1fr;
  gap: 12px;
}

.summary-grid article {
  padding: 14px;
  border-radius: 18px;
  background: rgba(59, 130, 246, 0.16);
}

.summary-grid span {
  display: block;
  color: #bfdbfe;
  font-size: 0.85rem;
}

.summary-grid strong {
  font-size: 1.35rem;
}

.card-form {
  display: grid;
  gap: 12px;
}

label {
  display: grid;
  gap: 6px;
  font-weight: 600;
}

input,
select,
button {
  width: 100%;
  min-height: 44px;
  border-radius: 14px;
  border: 1px solid rgba(148, 163, 184, 0.35);
  padding: 10px 12px;
  font: inherit;
}

button {
  border: 0;
  background: #38bdf8;
  color: #082f49;
  font-weight: 800;
}

.form-status {
  min-height: 24px;
  margin: 0;
  color: #bfdbfe;
}

@media (min-width: 720px) {
  .summary-grid,
  .card-list {
    grid-template-columns: repeat(3, 1fr);
  }

  .card-form {
    grid-template-columns: repeat(2, 1fr);
  }
}
"""


def _finance_tests() -> str:
    return """import assert from "node:assert/strict";
import test from "node:test";
import { mkdtempSync, rmSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import {
  createFinanceStore,
  addTransaction,
  listTransactions,
  summarizeByMonth,
  setBudget,
  checkBudgets,
  addGoal,
  projectGoal,
  addRecurringTransaction,
  materializeRecurring,
  projectCashFlow,
  saveFinanceStore,
  loadFinanceStore,
  exportCsv,
} from "../src/finance.js";
import { createApp, routeRequest } from "../src/server.js";

test("transaction records income and expense using integer cents", () => {
  const store = createFinanceStore();
  addTransaction(store, { type: "income", amountCents: 500000, category: "salary", date: "2026-06-01" });
  addTransaction(store, { type: "expense", amountCents: 12500, category: "food", date: "2026-06-02" });
  assert.equal(listTransactions(store).length, 2);
});

test("transaction rejects invalid cents", () => {
  const store = createFinanceStore();
  assert.throws(() => addTransaction(store, { type: "expense", amountCents: 12.5, category: "food", date: "2026-06-02" }), /amountCents/);
});

test("transaction detects duplicates", () => {
  const store = createFinanceStore();
  const input = { type: "expense", amountCents: 12500, category: "food", date: "2026-06-02", description: "Market" };
  addTransaction(store, input);
  assert.throws(() => addTransaction(store, input), /duplicate transaction/);
});

test("monthly summary computes income expense and balance", () => {
  const store = createFinanceStore();
  addTransaction(store, { type: "income", amountCents: 500000, category: "salary", date: "2026-06-01" });
  addTransaction(store, { type: "expense", amountCents: 100000, category: "rent", date: "2026-06-02" });
  const summary = summarizeByMonth(store, "2026-06");
  assert.equal(summary.balanceCents, 400000);
});

test("summary ignores other months", () => {
  const store = createFinanceStore();
  addTransaction(store, { type: "income", amountCents: 500000, category: "salary", date: "2026-05-01" });
  assert.equal(summarizeByMonth(store, "2026-06").incomeCents, 0);
});

test("budget tracks remaining amount", () => {
  const store = createFinanceStore();
  setBudget(store, { month: "2026-06", category: "food", limitCents: 100000 });
  addTransaction(store, { type: "expense", amountCents: 40000, category: "food", date: "2026-06-10" });
  assert.equal(checkBudgets(store, "2026-06")[0].remainingCents, 60000);
});

test("budget detects overspend", () => {
  const store = createFinanceStore();
  setBudget(store, { month: "2026-06", category: "food", limitCents: 100000 });
  addTransaction(store, { type: "expense", amountCents: 140000, category: "food", date: "2026-06-10" });
  assert.equal(checkBudgets(store, "2026-06")[0].overspent, true);
});

test("goal projection returns months to target", () => {
  const store = createFinanceStore();
  const goal = addGoal(store, { name: "Emergency", targetCents: 1200000, savedCents: 300000, monthlyContributionCents: 100000, targetDate: "2027-12-01" });
  assert.equal(projectGoal(store, goal.id).monthsToTarget, 9);
  assert.equal(projectGoal(store, goal.id).onTrack, true);
});

test("goal projection handles no monthly contribution", () => {
  const store = createFinanceStore();
  const goal = addGoal(store, { name: "Trip", targetCents: 100000, savedCents: 0 });
  assert.equal(projectGoal(store, goal.id).monthsToTarget, null);
});

test("recurring transactions materialize once per month", () => {
  const store = createFinanceStore();
  addRecurringTransaction(store, { type: "expense", amountCents: 9000, category: "internet", dayOfMonth: 5 });
  assert.equal(materializeRecurring(store, "2026-06").length, 1);
  assert.equal(materializeRecurring(store, "2026-06").length, 0);
});

test("cashflow projection includes recurring transactions", () => {
  const store = createFinanceStore();
  addTransaction(store, { type: "income", amountCents: 500000, category: "salary", date: "2026-06-01" });
  addRecurringTransaction(store, { type: "expense", amountCents: 9000, category: "internet", dayOfMonth: 5 });
  const projection = projectCashFlow(store, "2026-06", 2);
  assert.equal(projection[0].balanceCents, 491000);
  assert.equal(projection[1].balanceCents, -9000);
});

test("store persists and loads from local JSON", () => {
  const dir = mkdtempSync(join(tmpdir(), "finance-store-"));
  const filePath = join(dir, "store.json");
  try {
    const store = createFinanceStore();
    addTransaction(store, { type: "income", amountCents: 500000, category: "salary", date: "2026-06-01" });
    saveFinanceStore(store, filePath);
    const restored = loadFinanceStore(filePath);
    assert.equal(listTransactions(restored).length, 1);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("CSV export includes transaction data", () => {
  const store = createFinanceStore();
  addTransaction(store, { type: "expense", amountCents: 12500, category: "food", date: "2026-06-02", description: "Market" });
  assert.match(exportCsv(store), /food,12500/);
});

test("routeRequest creates transactions through API", () => {
  const app = createApp();
  const result = routeRequest(app, { method: "POST", path: "/api/transactions", body: { type: "expense", amountCents: 12500, category: "food", date: "2026-06-02" } });
  assert.equal(result.status, 201);
});

test("routeRequest returns budget checks", () => {
  const app = createApp();
  routeRequest(app, { method: "POST", path: "/api/budgets", body: { month: "2026-06", category: "food", limitCents: 100000 } });
  const result = routeRequest(app, { method: "GET", path: "/api/budgets", query: { month: "2026-06" } });
  assert.equal(JSON.parse(result.body)[0].category, "food");
});

test("routeRequest exposes goal projection", () => {
  const app = createApp();
  const goal = JSON.parse(routeRequest(app, { method: "POST", path: "/api/goals", body: { name: "Emergency", targetCents: 100000, savedCents: 0, monthlyContributionCents: 50000 } }).body);
  const projection = routeRequest(app, { method: "GET", path: `/api/goals/${goal.id}` });
  assert.equal(JSON.parse(projection.body).monthsToTarget, 2);
});

test("routeRequest serves mobile CSS", () => {
  const app = createApp();
  const response = routeRequest(app, { method: "GET", path: "/styles.css" });
  assert.equal(response.headers["content-type"], "text/css");
  assert.match(response.body, /min-height: 44px/);
});
"""


def _fullstack_package_json() -> str:
    return json.dumps(
        {
            "type": "module",
            "scripts": {
                "test": "node --test test/app.test.mjs",
                "smoke": "node src/smoke.js",
                "start": "node src/server.js",
            },
        },
        ensure_ascii=False,
        indent=2,
    )


def _fullstack_readme() -> str:
    return """# Fullstack CRUD Auth

Node.js fullstack CRUD/auth scaffold without external dependencies.

## Commands

- Run tests with `npm test`.
- Run smoke validation with `npm run smoke`.
- Start the local server with `npm start`.
"""


def _fullstack_auth_js() -> str:
    return """import { createHash, randomUUID } from "node:crypto";

export function hashPassword(password, salt = "ravenna-local") {
  if (typeof password !== "string" || password.length < 8) throw new Error("password must have at least 8 characters");
  return createHash("sha256").update(`${salt}:${password}`).digest("hex");
}

export function verifyPassword(password, passwordHash, salt = "ravenna-local") {
  return hashPassword(password, salt) === passwordHash;
}

export function createSession(user) {
  if (!user?.id) throw new Error("user is required");
  return { token: randomUUID(), userId: user.id, role: user.role || "user" };
}
"""


def _fullstack_store_js() -> str:
    return """import { randomUUID } from "node:crypto";
import { createSession, hashPassword, verifyPassword } from "./auth.js";

export function createStore() {
  return { users: new Map(), projects: new Map(), sessions: new Map() };
}

function publicUser(user) {
  const { passwordHash, ...safe } = user;
  return safe;
}

export function createUser(store, input) {
  const email = String(input?.email || "").toLowerCase();
  if (!email.includes("@")) throw new Error("valid email is required");
  if ([...store.users.values()].some((user) => user.email === email)) throw new Error("email already exists");
  const user = { id: randomUUID(), email, name: input.name || email, role: input.role || "user", passwordHash: hashPassword(input.password) };
  store.users.set(user.id, user);
  return publicUser(user);
}

export function authenticateUser(store, email, password) {
  const user = [...store.users.values()].find((candidate) => candidate.email === String(email || "").toLowerCase());
  if (!user || !verifyPassword(password, user.passwordHash)) throw new Error("invalid credentials");
  const session = createSession(user);
  store.sessions.set(session.token, session);
  return { session, user: publicUser(user) };
}

export function createProject(store, ownerId, input) {
  if (!store.users.has(ownerId)) throw new Error("owner not found");
  const title = String(input?.title || "").trim();
  if (!title) throw new Error("title is required");
  const project = { id: randomUUID(), ownerId, title, status: input.status || "active" };
  store.projects.set(project.id, project);
  return { ...project };
}

export function listProjects(store, ownerId) {
  return [...store.projects.values()].filter((project) => project.ownerId === ownerId).map((project) => ({ ...project }));
}

export function updateProject(store, ownerId, projectId, patch) {
  const project = store.projects.get(projectId);
  if (!project || project.ownerId !== ownerId) throw new Error("project not found");
  const updated = { ...project, ...patch, id: project.id, ownerId };
  store.projects.set(project.id, updated);
  return { ...updated };
}

export function deleteProject(store, ownerId, projectId) {
  const project = store.projects.get(projectId);
  if (!project || project.ownerId !== ownerId) throw new Error("project not found");
  store.projects.delete(projectId);
  return { deleted: true, id: projectId };
}
"""


def _fullstack_server_js() -> str:
    return """import { createServer } from "node:http";
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";
import { createStore, createUser, authenticateUser, createProject, listProjects, updateProject, deleteProject } from "./store.js";

export function createApp(store = createStore()) {
  return { store };
}

function json(status, body) {
  return { status, headers: { "content-type": "application/json" }, body: JSON.stringify(body) };
}

export function routeRequest(app, request) {
  const { method, path, body = {}, userId } = request;
  try {
    if (method === "GET" && path === "/") return { status: 200, headers: { "content-type": "text/html" }, body: readFileSync("public/index.html", "utf-8") };
    if (method === "POST" && path === "/api/users") return json(201, createUser(app.store, body));
    if (method === "POST" && path === "/api/login") return json(200, authenticateUser(app.store, body.email, body.password));
    if (method === "GET" && path === "/api/projects") return json(200, listProjects(app.store, userId));
    if (method === "POST" && path === "/api/projects") return json(201, createProject(app.store, userId, body));
    if (method === "PATCH" && path.startsWith("/api/projects/")) return json(200, updateProject(app.store, userId, path.split("/").pop(), body));
    if (method === "DELETE" && path.startsWith("/api/projects/")) return json(200, deleteProject(app.store, userId, path.split("/").pop()));
    return json(404, { error: "not found" });
  } catch (error) {
    return json(400, { error: error.message });
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const app = createApp();
  const server = createServer((req, res) => {
    const chunks = [];
    req.on("data", (chunk) => chunks.push(chunk));
    req.on("end", () => {
      const body = chunks.length ? JSON.parse(Buffer.concat(chunks).toString("utf-8")) : {};
      const result = routeRequest(app, { method: req.method, path: new URL(req.url, "http://localhost").pathname, body });
      res.writeHead(result.status, result.headers);
      res.end(result.body);
    });
  });
  server.listen(3000, () => console.log("listening on http://localhost:3000"));
}
"""


def _fullstack_smoke_js() -> str:
    return """import { createStore, createUser, authenticateUser, createProject, listProjects } from "./store.js";

const store = createStore();
const user = createUser(store, { email: "owner@example.com", name: "Owner", password: "strongpass" });
const login = authenticateUser(store, "owner@example.com", "strongpass");
createProject(store, user.id, { title: "Launch Ravenna" });
console.log(JSON.stringify({ ok: true, userId: login.user.id, projects: listProjects(store, user.id).length }));
"""


def _fullstack_index_html() -> str:
    return """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>Fullstack CRUD Auth</title>
  </head>
  <body>
    <main>
      <h1>Projects</h1>
      <form aria-label="Login form">
        <label>Email <input name="email" type="email" /></label>
        <label>Password <input name="password" type="password" /></label>
        <button type="submit">Login</button>
      </form>
      <section aria-label="Project CRUD">
        <label>Project title <input name="title" /></label>
        <button type="button">Create project</button>
        <ul aria-label="Project list"></ul>
      </section>
    </main>
  </body>
</html>
"""


def _fullstack_tests() -> str:
    return """import assert from "node:assert/strict";
import test from "node:test";
import { hashPassword, verifyPassword, createSession } from "../src/auth.js";
import { createStore, createUser, authenticateUser, createProject, listProjects, updateProject, deleteProject } from "../src/store.js";
import { createApp, routeRequest } from "../src/server.js";

test("auth hashes and verifies passwords without storing raw values", () => {
  const hash = hashPassword("strongpass");
  assert.notEqual(hash, "strongpass");
  assert.equal(verifyPassword("strongpass", hash), true);
});

test("auth rejects short passwords", () => {
  assert.throws(() => hashPassword("short"), /at least 8/);
});

test("users can register and login", () => {
  const store = createStore();
  const user = createUser(store, { email: "user@example.com", password: "strongpass" });
  const login = authenticateUser(store, "user@example.com", "strongpass");
  assert.equal(login.user.id, user.id);
  assert.equal(login.session.userId, user.id);
});

test("invalid login is rejected", () => {
  const store = createStore();
  createUser(store, { email: "user@example.com", password: "strongpass" });
  assert.throws(() => authenticateUser(store, "user@example.com", "wrongpass"), /invalid credentials/);
});

test("project CRUD creates, lists and updates owner projects", () => {
  const store = createStore();
  const user = createUser(store, { email: "owner@example.com", password: "strongpass" });
  const project = createProject(store, user.id, { title: "Ravenna" });
  assert.equal(listProjects(store, user.id).length, 1);
  assert.equal(updateProject(store, user.id, project.id, { status: "done" }).status, "done");
});

test("delete removes only owner project", () => {
  const store = createStore();
  const user = createUser(store, { email: "owner@example.com", password: "strongpass" });
  const project = createProject(store, user.id, { title: "Ravenna" });
  assert.equal(deleteProject(store, user.id, project.id).deleted, true);
  assert.equal(listProjects(store, user.id).length, 0);
});

test("routeRequest exposes user and project API", () => {
  const app = createApp();
  const created = JSON.parse(routeRequest(app, { method: "POST", path: "/api/users", body: { email: "api@example.com", password: "strongpass" } }).body);
  const project = routeRequest(app, { method: "POST", path: "/api/projects", userId: created.id, body: { title: "API project" } });
  assert.equal(project.status, 201);
  assert.equal(JSON.parse(project.body).title, "API project");
});

test("routeRequest returns validation errors for bad requests", () => {
  const app = createApp();
  const result = routeRequest(app, { method: "POST", path: "/api/users", body: { email: "bad", password: "strongpass" } });
  assert.equal(result.status, 400);
});

test("createSession requires a user", () => {
  assert.throws(() => createSession(null), /user is required/);
});
"""


def _ops_readme() -> str:
    return """# SaaS Operations Suite

Node.js SaaS operations scaffold without external dependencies.

## Features

- Auth with hashed passwords and local sessions.
- Owner-scoped project CRUD.
- Integer-cents billing with an append-only ledger.
- Accessible HTML dashboard for auth, projects and billing.

## Commands

- Run tests with `npm test`.
- Run smoke validation with `npm run smoke`.
- Start the local server with `npm start`.
"""


def _ops_billing_js() -> str:
    return """import { randomUUID } from "node:crypto";

export function createBillingLedger(snapshot = {}) {
  return { ledger: [...(snapshot.ledger || [])] };
}

function assertCents(totalCents, name = "totalCents") {
  if (!Number.isInteger(totalCents) || totalCents < 0) throw new Error(`${name} must be a non-negative integer in cents`);
}

export function addInvoice(billing, input) {
  if (!input?.customerId) throw new Error("customerId is required");
  assertCents(input.totalCents);
  const invoice = {
    id: input.id || randomUUID(),
    customerId: input.customerId,
    totalCents: input.totalCents,
    status: "open",
  };
  billing.ledger.push({ type: "invoice", invoiceId: invoice.id, customerId: invoice.customerId, totalCents: invoice.totalCents });
  return invoice;
}

export function recordPayment(billing, invoiceId, amountCents) {
  if (!invoiceId) throw new Error("invoiceId is required");
  assertCents(amountCents, "amountCents");
  billing.ledger.push({ type: "payment", invoiceId, amountCents });
  return { invoiceId, amountCents };
}

export function summarizeLedger(billing) {
  const summary = { invoicedCents: 0, paidCents: 0, balanceCents: 0, invoiceCount: 0, paymentCount: 0 };
  for (const entry of billing.ledger) {
    if (entry.type === "invoice") {
      summary.invoicedCents += entry.totalCents;
      summary.invoiceCount += 1;
    }
    if (entry.type === "payment") {
      summary.paidCents += entry.amountCents;
      summary.paymentCount += 1;
    }
  }
  summary.balanceCents = summary.invoicedCents - summary.paidCents;
  return summary;
}

export function exportLedgerCsv(billing) {
  const rows = ["type,invoiceId,customerId,totalCents,amountCents"];
  for (const entry of billing.ledger) {
    rows.push([
      entry.type,
      entry.invoiceId || "",
      entry.customerId || "",
      entry.totalCents ?? "",
      entry.amountCents ?? "",
    ].join(","));
  }
  return rows.join("\\n");
}
"""


def _ops_server_js() -> str:
    return """import { createServer } from "node:http";
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";
import { createStore, createUser, authenticateUser, createProject, listProjects, updateProject, deleteProject } from "./store.js";
import { createBillingLedger, addInvoice, recordPayment, summarizeLedger } from "./billing.js";

export function createApp(store = createStore(), billing = createBillingLedger()) {
  return { store, billing };
}

function json(status, body) {
  return { status, headers: { "content-type": "application/json" }, body: JSON.stringify(body) };
}

export function routeRequest(app, request) {
  const { method, path, body = {}, userId } = request;
  try {
    if (method === "GET" && path === "/") return { status: 200, headers: { "content-type": "text/html" }, body: readFileSync("public/index.html", "utf-8") };
    if (method === "POST" && path === "/api/users") return json(201, createUser(app.store, body));
    if (method === "POST" && path === "/api/login") return json(200, authenticateUser(app.store, body.email, body.password));
    if (method === "GET" && path === "/api/projects") return json(200, listProjects(app.store, userId));
    if (method === "POST" && path === "/api/projects") return json(201, createProject(app.store, userId, body));
    if (method === "PATCH" && path.startsWith("/api/projects/")) return json(200, updateProject(app.store, userId, path.split("/").pop(), body));
    if (method === "DELETE" && path.startsWith("/api/projects/")) return json(200, deleteProject(app.store, userId, path.split("/").pop()));
    if (method === "POST" && path === "/api/billing/invoices") return json(201, addInvoice(app.billing, body));
    if (method === "POST" && path.startsWith("/api/billing/invoices/") && path.endsWith("/payments")) {
      return json(201, recordPayment(app.billing, path.split("/").at(-2), body.amountCents));
    }
    if (method === "GET" && path === "/api/billing/summary") return json(200, summarizeLedger(app.billing));
    return json(404, { error: "not found" });
  } catch (error) {
    return json(400, { error: error.message });
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const app = createApp();
  const server = createServer((req, res) => {
    const chunks = [];
    req.on("data", (chunk) => chunks.push(chunk));
    req.on("end", () => {
      const body = chunks.length ? JSON.parse(Buffer.concat(chunks).toString("utf-8")) : {};
      const result = routeRequest(app, { method: req.method, path: new URL(req.url, "http://localhost").pathname, body });
      res.writeHead(result.status, result.headers);
      res.end(result.body);
    });
  });
  server.listen(3000, () => console.log("listening on http://localhost:3000"));
}
"""


def _ops_smoke_js() -> str:
    return """import { createStore, createUser, authenticateUser, createProject, listProjects } from "./store.js";
import { createBillingLedger, addInvoice, recordPayment, summarizeLedger } from "./billing.js";

const store = createStore();
const billing = createBillingLedger();
const user = createUser(store, { email: "owner@example.com", name: "Owner", password: "strongpass" });
const login = authenticateUser(store, "owner@example.com", "strongpass");
const project = createProject(store, user.id, { title: "Launch Ravenna" });
const invoice = addInvoice(billing, { customerId: user.id, totalCents: 250000 });
recordPayment(billing, invoice.id, 100000);
console.log(JSON.stringify({
  ok: true,
  userId: login.user.id,
  projects: listProjects(store, user.id).length,
  projectId: project.id,
  billing: summarizeLedger(billing),
}));
"""


def _ops_index_html() -> str:
    return """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>SaaS Operations Suite</title>
  </head>
  <body>
    <main>
      <h1>SaaS Operations</h1>
      <form aria-label="Login form">
        <label>Email <input name="email" type="email" /></label>
        <label>Password <input name="password" type="password" /></label>
        <button type="submit">Login</button>
      </form>
      <section aria-label="Project CRUD">
        <h2>Projects</h2>
        <label>Project title <input name="title" /></label>
        <button type="button">Create project</button>
        <ul aria-label="Project list"></ul>
      </section>
      <section aria-label="Billing dashboard">
        <h2>Billing</h2>
        <p>Track invoices, payments and ledger balance in integer cents.</p>
        <output aria-live="polite">Balance: 0</output>
      </section>
    </main>
  </body>
</html>
"""


def _ops_tests() -> str:
    return """import assert from "node:assert/strict";
import test from "node:test";
import { hashPassword, verifyPassword, createSession } from "../src/auth.js";
import { createStore, createUser, authenticateUser, createProject, listProjects, updateProject, deleteProject } from "../src/store.js";
import { createBillingLedger, addInvoice, recordPayment, summarizeLedger, exportLedgerCsv } from "../src/billing.js";
import { createApp, routeRequest } from "../src/server.js";

test("auth hashes and verifies passwords", () => {
  const hash = hashPassword("strongpass");
  assert.notEqual(hash, "strongpass");
  assert.equal(verifyPassword("strongpass", hash), true);
});

test("auth login creates session", () => {
  const store = createStore();
  const user = createUser(store, { email: "user@example.com", password: "strongpass" });
  const login = authenticateUser(store, "user@example.com", "strongpass");
  assert.equal(login.session.userId, user.id);
});

test("auth rejects invalid credentials", () => {
  const store = createStore();
  createUser(store, { email: "user@example.com", password: "strongpass" });
  assert.throws(() => authenticateUser(store, "user@example.com", "wrongpass"), /invalid credentials/);
});

test("project CRUD creates and lists owner projects", () => {
  const store = createStore();
  const user = createUser(store, { email: "owner@example.com", password: "strongpass" });
  createProject(store, user.id, { title: "Ravenna" });
  assert.equal(listProjects(store, user.id).length, 1);
});

test("project CRUD updates and delete removes owner projects", () => {
  const store = createStore();
  const user = createUser(store, { email: "owner@example.com", password: "strongpass" });
  const project = createProject(store, user.id, { title: "Ravenna" });
  assert.equal(updateProject(store, user.id, project.id, { status: "done" }).status, "done");
  assert.equal(deleteProject(store, user.id, project.id).deleted, true);
});

test("billing ledger records invoice totals in cents", () => {
  const billing = createBillingLedger();
  addInvoice(billing, { customerId: "cust-1", totalCents: 100000 });
  assert.equal(summarizeLedger(billing).invoicedCents, 100000);
});

test("billing ledger records payments and balance", () => {
  const billing = createBillingLedger();
  const invoice = addInvoice(billing, { customerId: "cust-1", totalCents: 100000 });
  recordPayment(billing, invoice.id, 40000);
  assert.equal(summarizeLedger(billing).balanceCents, 60000);
});

test("billing rejects decimal money", () => {
  const billing = createBillingLedger();
  assert.throws(() => addInvoice(billing, { customerId: "cust-1", totalCents: 10.5 }), /integer/);
});

test("billing CSV export includes ledger rows", () => {
  const billing = createBillingLedger();
  const invoice = addInvoice(billing, { customerId: "cust-1", totalCents: 100000 });
  recordPayment(billing, invoice.id, 40000);
  assert.match(exportLedgerCsv(billing), /invoice/);
  assert.match(exportLedgerCsv(billing), /payment/);
});

test("API routes auth, project and billing", () => {
  const app = createApp();
  const user = JSON.parse(routeRequest(app, { method: "POST", path: "/api/users", body: { email: "api@example.com", password: "strongpass" } }).body);
  const project = routeRequest(app, { method: "POST", path: "/api/projects", userId: user.id, body: { title: "API project" } });
  const invoice = routeRequest(app, { method: "POST", path: "/api/billing/invoices", body: { customerId: user.id, totalCents: 75000 } });
  assert.equal(project.status, 201);
  assert.equal(invoice.status, 201);
});

test("API exposes ledger billing summary", () => {
  const app = createApp();
  const invoice = JSON.parse(routeRequest(app, { method: "POST", path: "/api/billing/invoices", body: { customerId: "cust-1", totalCents: 75000 } }).body);
  routeRequest(app, { method: "POST", path: `/api/billing/invoices/${invoice.id}/payments`, body: { amountCents: 25000 } });
  const summary = JSON.parse(routeRequest(app, { method: "GET", path: "/api/billing/summary" }).body);
  assert.equal(summary.balanceCents, 50000);
});

test("createSession requires a user", () => {
  assert.throws(() => createSession(null), /user is required/);
});
"""


def _audit_js() -> str:
    return """export function recordAuditEvent(auditLog, input) {
  if (!Array.isArray(auditLog)) throw new Error("auditLog must be an array");
  if (!input?.action) throw new Error("action is required");
  const event = {
    id: input.id || `audit-${auditLog.length + 1}`,
    action: input.action,
    entityType: input.entityType || "unknown",
    entityId: input.entityId || "",
    actorId: input.actorId || "system",
    createdAt: input.createdAt || new Date(0).toISOString(),
  };
  auditLog.push(event);
  return { ...event };
}

export function listAuditEvents(auditLog, filters = {}) {
  if (!Array.isArray(auditLog)) throw new Error("auditLog must be an array");
  return auditLog
    .filter((event) => !filters.action || event.action === filters.action)
    .filter((event) => !filters.entityType || event.entityType === filters.entityType)
    .map((event) => ({ ...event }));
}
"""


def _ops_enhancement_tests() -> str:
    return """import assert from "node:assert/strict";
import test from "node:test";
import { createBillingLedger, addInvoice, recordPayment, summarizeLedger, exportLedgerCsv } from "../src/billing.js";
import { recordAuditEvent, listAuditEvents } from "../src/audit.js";

test("audit log records project creation events", () => {
  const audit = [];
  const event = recordAuditEvent(audit, { action: "project.created", entityType: "project", entityId: "proj-1", actorId: "user-1" });
  assert.equal(event.action, "project.created");
  assert.equal(listAuditEvents(audit, { entityType: "project" }).length, 1);
});

test("audit log records invoice creation events", () => {
  const audit = [];
  recordAuditEvent(audit, { action: "invoice.created", entityType: "invoice", entityId: "inv-1" });
  assert.equal(listAuditEvents(audit, { action: "invoice.created" })[0].entityId, "inv-1");
});

test("audit log validates action", () => {
  assert.throws(() => recordAuditEvent([], {}), /action/);
});

test("ledger CSV export includes invoice and payment rows", () => {
  const billing = createBillingLedger();
  const invoice = addInvoice(billing, { customerId: "cust-1", totalCents: 50000 });
  recordPayment(billing, invoice.id, 20000);
  const csv = exportLedgerCsv(billing);
  assert.match(csv, /type,invoiceId/);
  assert.match(csv, /invoice/);
  assert.match(csv, /payment/);
});

test("ledger summary is preserved after CSV export", () => {
  const billing = createBillingLedger();
  const invoice = addInvoice(billing, { customerId: "cust-1", totalCents: 50000 });
  recordPayment(billing, invoice.id, 20000);
  exportLedgerCsv(billing);
  assert.equal(summarizeLedger(billing).balanceCents, 30000);
});

test("billing still rejects decimal cents", () => {
  assert.throws(() => addInvoice(createBillingLedger(), { customerId: "cust-1", totalCents: 1.5 }), /integer/);
});
"""


def _helpdesk_readme() -> str:
    return """# Helpdesk MVP

Internal helpdesk MVP without external dependencies.

## Features

- Auth with password hashing and sessions.
- Ticket creation, listing and priority/status updates.
- Accessible HTML dashboard for small teams.

## Commands

- Run tests with `npm test`.
- Run smoke validation with `npm run smoke`.
- Start the local server with `npm start`.
"""


def _helpdesk_store_js() -> str:
    return """import { randomUUID } from "node:crypto";
import { createSession, hashPassword, verifyPassword } from "./auth.js";

export function createStore() {
  return { users: new Map(), sessions: new Map(), tickets: new Map() };
}

function publicUser(user) {
  const { passwordHash, ...safe } = user;
  return safe;
}

export function createUser(store, input) {
  const email = String(input?.email || "").toLowerCase();
  if (!email.includes("@")) throw new Error("valid email is required");
  if ([...store.users.values()].some((user) => user.email === email)) throw new Error("email already exists");
  const user = { id: randomUUID(), email, name: input.name || email, passwordHash: hashPassword(input.password) };
  store.users.set(user.id, user);
  return publicUser(user);
}

export function authenticateUser(store, email, password) {
  const user = [...store.users.values()].find((candidate) => candidate.email === String(email || "").toLowerCase());
  if (!user || !verifyPassword(password, user.passwordHash)) throw new Error("invalid credentials");
  const session = createSession(user);
  store.sessions.set(session.token, session);
  return { session, user: publicUser(user) };
}

export function createTicket(store, ownerId, input) {
  if (!store.users.has(ownerId)) throw new Error("owner not found");
  const title = String(input?.title || "").trim();
  if (!title) throw new Error("title is required");
  const priority = input.priority || "medium";
  if (!["low", "medium", "high", "urgent"].includes(priority)) throw new Error("invalid priority");
  const ticket = {
    id: randomUUID(),
    ownerId,
    title,
    description: input.description || "",
    priority,
    status: input.status || "open",
  };
  store.tickets.set(ticket.id, ticket);
  return { ...ticket };
}

export function listTickets(store, filters = {}) {
  return [...store.tickets.values()]
    .filter((ticket) => !filters.ownerId || ticket.ownerId === filters.ownerId)
    .filter((ticket) => !filters.status || ticket.status === filters.status)
    .filter((ticket) => !filters.priority || ticket.priority === filters.priority)
    .map((ticket) => ({ ...ticket }));
}

export function updateTicket(store, ticketId, patch) {
  const ticket = store.tickets.get(ticketId);
  if (!ticket) throw new Error("ticket not found");
  const next = { ...ticket, ...patch, id: ticket.id, ownerId: ticket.ownerId };
  if (!["open", "triaged", "closed"].includes(next.status)) throw new Error("invalid status");
  if (!["low", "medium", "high", "urgent"].includes(next.priority)) throw new Error("invalid priority");
  store.tickets.set(ticket.id, next);
  return { ...next };
}
"""


def _helpdesk_server_js() -> str:
    return """import { createServer } from "node:http";
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";
import { createStore, createUser, authenticateUser, createTicket, listTickets, updateTicket } from "./store.js";

export function createApp(store = createStore()) {
  return { store };
}

function json(status, body) {
  return { status, headers: { "content-type": "application/json" }, body: JSON.stringify(body) };
}

export function routeRequest(app, request) {
  const { method, path, body = {}, userId, query = {} } = request;
  try {
    if (method === "GET" && path === "/") return { status: 200, headers: { "content-type": "text/html" }, body: readFileSync("public/index.html", "utf-8") };
    if (method === "POST" && path === "/api/users") return json(201, createUser(app.store, body));
    if (method === "POST" && path === "/api/login") return json(200, authenticateUser(app.store, body.email, body.password));
    if (method === "GET" && path === "/api/tickets") return json(200, listTickets(app.store, { ...query, ownerId: userId || query.ownerId }));
    if (method === "POST" && path === "/api/tickets") return json(201, createTicket(app.store, userId, body));
    if (method === "PATCH" && path.startsWith("/api/tickets/")) return json(200, updateTicket(app.store, path.split("/").pop(), body));
    return json(404, { error: "not found" });
  } catch (error) {
    return json(400, { error: error.message });
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const app = createApp();
  const server = createServer((req, res) => {
    const chunks = [];
    req.on("data", (chunk) => chunks.push(chunk));
    req.on("end", () => {
      const body = chunks.length ? JSON.parse(Buffer.concat(chunks).toString("utf-8")) : {};
      const result = routeRequest(app, { method: req.method, path: new URL(req.url, "http://localhost").pathname, body });
      res.writeHead(result.status, result.headers);
      res.end(result.body);
    });
  });
  server.listen(3000, () => console.log("listening on http://localhost:3000"));
}
"""


def _helpdesk_smoke_js() -> str:
    return """import { createStore, createUser, authenticateUser, createTicket, listTickets } from "./store.js";

const store = createStore();
const user = createUser(store, { email: "agent@example.com", password: "strongpass" });
const login = authenticateUser(store, "agent@example.com", "strongpass");
createTicket(store, user.id, { title: "Printer issue", priority: "high" });
console.log(JSON.stringify({ ok: true, userId: login.user.id, tickets: listTickets(store).length }));
"""


def _helpdesk_index_html() -> str:
    return """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Helpdesk MVP</title>
  </head>
  <body>
    <main>
      <h1>Helpdesk Tickets</h1>
      <form aria-label="Login form">
        <label>Email <input name="email" type="email" /></label>
        <label>Password <input name="password" type="password" /></label>
        <button type="submit">Login</button>
      </form>
      <section aria-label="Ticket dashboard">
        <h2>Ticket queue</h2>
        <label>Ticket title <input name="title" /></label>
        <label>Priority
          <select name="priority">
            <option>low</option>
            <option>medium</option>
            <option>high</option>
            <option>urgent</option>
          </select>
        </label>
        <button type="button">Create Ticket</button>
        <ul aria-label="Ticket list"></ul>
      </section>
    </main>
  </body>
</html>
"""


def _helpdesk_tests() -> str:
    return """import assert from "node:assert/strict";
import test from "node:test";
import { hashPassword, verifyPassword } from "../src/auth.js";
import { createStore, createUser, authenticateUser, createTicket, listTickets, updateTicket } from "../src/store.js";
import { createApp, routeRequest } from "../src/server.js";

test("auth hashes and verifies passwords", () => {
  const hash = hashPassword("strongpass");
  assert.notEqual(hash, "strongpass");
  assert.equal(verifyPassword("strongpass", hash), true);
});

test("auth rejects invalid login", () => {
  const store = createStore();
  createUser(store, { email: "agent@example.com", password: "strongpass" });
  assert.throws(() => authenticateUser(store, "agent@example.com", "wrongpass"), /invalid credentials/);
});

test("ticket creation stores priority", () => {
  const store = createStore();
  const user = createUser(store, { email: "agent@example.com", password: "strongpass" });
  const ticket = createTicket(store, user.id, { title: "Printer issue", priority: "high" });
  assert.equal(ticket.priority, "high");
});

test("ticket list filters by priority", () => {
  const store = createStore();
  const user = createUser(store, { email: "agent@example.com", password: "strongpass" });
  createTicket(store, user.id, { title: "Printer issue", priority: "high" });
  createTicket(store, user.id, { title: "Mouse issue", priority: "low" });
  assert.equal(listTickets(store, { priority: "high" }).length, 1);
});

test("ticket update changes status and priority", () => {
  const store = createStore();
  const user = createUser(store, { email: "agent@example.com", password: "strongpass" });
  const ticket = createTicket(store, user.id, { title: "Printer issue", priority: "high" });
  const updated = updateTicket(store, ticket.id, { status: "triaged", priority: "urgent" });
  assert.equal(updated.status, "triaged");
  assert.equal(updated.priority, "urgent");
});

test("ticket update rejects invalid status", () => {
  const store = createStore();
  const user = createUser(store, { email: "agent@example.com", password: "strongpass" });
  const ticket = createTicket(store, user.id, { title: "Printer issue", priority: "high" });
  assert.throws(() => updateTicket(store, ticket.id, { status: "unknown" }), /invalid status/);
});

test("API routes login and tickets", () => {
  const app = createApp();
  const user = JSON.parse(routeRequest(app, { method: "POST", path: "/api/users", body: { email: "api@example.com", password: "strongpass" } }).body);
  const ticket = routeRequest(app, { method: "POST", path: "/api/tickets", userId: user.id, body: { title: "API ticket", priority: "medium" } });
  assert.equal(ticket.status, 201);
  assert.equal(JSON.parse(ticket.body).title, "API ticket");
});

test("API returns validation errors for bad tickets", () => {
  const app = createApp();
  const result = routeRequest(app, { method: "POST", path: "/api/tickets", body: { title: "No owner" } });
  assert.equal(result.status, 400);
});
"""
