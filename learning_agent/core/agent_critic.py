"""Structured critic for Ravenna autonomous repair attempts."""

from __future__ import annotations

import re
from typing import Any


def critique_attempt(
    *,
    original_request: str,
    spec: dict[str, Any],
    applied: dict[str, Any],
    validation: dict[str, Any],
    checklist: dict[str, Any],
) -> dict[str, Any]:
    failures = _collect_failures(applied, validation, checklist)
    categories = sorted({_category(item) for item in failures}) or ["unknown"]
    next_action = _next_action(spec, failures)
    recommended_model_size = _recommended_model_size(spec, categories, failures)
    return {
        "categories": categories,
        "failures": failures,
        "nextAction": next_action,
        "recommendedModelSize": recommended_model_size,
        "repairPrompt": build_surgical_repair_prompt(
            original_request=original_request,
            spec=spec,
            failures=failures,
            next_action=next_action,
        ),
    }


def build_surgical_repair_prompt(
    *,
    original_request: str,
    spec: dict[str, Any],
    failures: list[str],
    next_action: dict[str, Any],
) -> str:
    from learning_agent.core import agent_patterns

    target_files = next_action.get("targetFiles") or spec.get("requiredFiles") or []
    target_text = "\n".join(f"- {item}" for item in target_files) or "- menor conjunto de arquivos necessário"
    locked_files = [item for item in spec.get("lockedFiles") or [] if item not in set(target_files)]
    locked_text = "\n".join(f"- {item}" for item in locked_files)
    locked_section = (
        f"Arquivos protegidos, não reescreva sem necessidade explícita:\n{locked_text}\n\n"
        if locked_files
        else ""
    )
    failure_text = "\n".join(f"- {item}" for item in failures[:12]) or "- validação falhou"
    commands = "\n".join(f"- {item}" for item in spec.get("validationCommands") or [])
    rules = "\n".join(f"- {item}" for item in spec.get("semanticRules") or [])
    patterns = agent_patterns.patterns_for_spec(spec)
    targeted_rules = _targeted_repair_rules(spec, failures, target_files)

    return (
        "Você está corrigindo uma tentativa autônoma que falhou. "
        "Faça uma correção cirúrgica: altere somente os arquivos listados quando possível.\n\n"
        f"Próxima ação: {next_action.get('summary')}\n\n"
        f"Arquivos alvo:\n{target_text}\n\n"
        f"{locked_section}"
        f"Falhas objetivas:\n{failure_text}\n\n"
        f"Comandos que devem passar:\n{commands or '- nenhum comando inferido'}\n\n"
        f"Regras semânticas:\n{rules or '- nenhuma regra inferida'}\n\n"
        f"{patterns + chr(10) + chr(10) if patterns else ''}"
        f"Pedido original resumido:\n{original_request[:1800]}\n\n"
        "Regras obrigatórias:\n"
        "- Retorne blocos ```write caminho``` completos para cada arquivo corrigido.\n"
        "- Se criar testes com node --test, use `import test from 'node:test'` e `assert` de `node:assert/strict`.\n"
        "- Não use `describe`, `it` ou `expect` sem instalar framework.\n"
        "- Em ESM, não use `require`; use imports.\n"
        "- Não reescreva arquivos que não estão nos alvos se não for necessário.\n"
        "- Em tarefas complexas, preserve arquitetura, exports e quantidade mínima de testes; não simplifique o domínio para fazer um erro local passar.\n"
        f"{targeted_rules}"
    )


def _collect_failures(applied: dict[str, Any], validation: dict[str, Any], checklist: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    failures.extend(str(item) for item in validation.get("failures") or [])
    for command in validation.get("commands") or []:
        if command.get("exit_code") not in (0, None):
            output = str(command.get("output") or "")[-1800:]
            if output:
                failures.append(f"Validation output for {command.get('command')}:\n{output}")
    failures.extend(str(item) for item in checklist.get("failures") or [])
    shell = applied.get("shell") or {}
    failures.extend(str(item) for item in shell.get("failures") or [])
    for command in shell.get("ran") or []:
        if not command.get("skipped") and command.get("exit_code") not in (0, None):
            output = str(command.get("output") or "")[-1200:]
            if output:
                failures.append(f"Shell output for {command.get('command')}:\n{output}")
    failures.extend(f"Shell bloqueado: {item.get('command')} ({item.get('reason')})" for item in shell.get("blocked") or [])
    if applied.get("error"):
        failures.append(f"Apply error: {applied['error']}")
    return _dedupe(failures)


def _targeted_repair_rules(spec: dict[str, Any], failures: list[str], target_files: list[str]) -> str:
    lowered = "\n".join(failures).lower()
    lines: list[str] = []
    min_tests = int(spec.get("minTests") or 0)
    if any(path.startswith("test/") for path in target_files):
        lines.extend(
            [
                "- Ao corrigir `node:test`, reescreva o arquivo de teste completo, não apenas um trecho.",
                "- As primeiras linhas do teste devem incluir exatamente imports de `node:test` e `node:assert/strict`.",
                "- Use testes top-level no formato `test('nome', () => { ... })`; não agrupe com `describe` ou `it`.",
            ]
        )
        if min_tests:
            lines.append(f"- Mantenha pelo menos {min_tests} chamadas top-level a `test(` no arquivo final.")
        if "not defined" in lowered or "não importa `node:test`" in lowered:
            lines.append("- Se o erro for `test is not defined`, a correção principal é adicionar/importar `test` no topo do arquivo.")
    fulfillment_exports = (spec.get("requiredExports") or {}).get("src/fulfillment.js") or []
    if "src/fulfillment.js" in target_files and fulfillment_exports:
        lines.append("- Ao corrigir `src/fulfillment.js`, preserve todos estes exports: " + ", ".join(fulfillment_exports) + ".")
        lines.append("- Não remova `replayEvents`, `parseJsonl`, `createStore` ou `applyCommand` para resolver erro local.")
    if not lines:
        return ""
    return "\nRegras específicas desta correção:\n" + "\n".join(lines) + "\n"


def _category(failure: str) -> str:
    text = failure.lower()
    if "apply error" in text or "path" in text or "package.json não encontrado" in text:
        return "infrastructure"
    if "node:test" in text or "jest" in text or "0 tests" in text or "teste" in text:
        return "validation"
    if "arquivo obrigatório" in text or "exporta" in text or "entrega incompleta" in text:
        return "format"
    if any(token in text for token in ("fulfillment", "commandid", "totalcents", "parsejsonl", "event")):
        return "semantic"
    if "shell" in text:
        return "infrastructure"
    return "model_quality"


def _recommended_model_size(spec: dict[str, Any], categories: list[str], failures: list[str]) -> str:
    text = "\n".join(failures).lower()
    semantic_rules = set(spec.get("semanticRules") or [])
    if spec.get("complexity") == "complex":
        return "32b"
    if "semantic" in categories:
        return "32b"
    if any(rule in semantic_rules for rule in ("event-sourcing", "idempotency")):
        return "32b"
    if any(token in text for token in ("event", "fulfillment", "commandid", "idempot", "replayevents", "invariant")):
        return "32b"
    return "0.5b"


def _next_action(spec: dict[str, Any], failures: list[str]) -> dict[str, Any]:
    lowered = "\n".join(failures).lower()
    required_files = spec.get("requiredFiles") or []

    if "pytest" in lowered:
        if any(token in lowered for token in ("keyerror", "assertionerror", "failed: did not raise", "typeerror", "valueerror")):
            source_targets = [path for path in required_files if path.startswith("src/") and path.endswith(".py")]
            return {
                "summary": "corrigir comportamento no código Python que quebrou os testes",
                "targetFiles": source_targets or [path for path in required_files if path.endswith(".py")],
            }
        targets = [path for path in required_files if path.startswith("tests/") or path.startswith("test_") or "/test_" in path]
        return {
            "summary": "corrigir testes Python/pytest no projeto alvo",
            "targetFiles": targets or [path for path in required_files if path.endswith(".py")],
        }
    domain_runtime_failure = "src/fulfillment.js" in lowered and any(
        token in lowered
        for token in (
            "unknown command type",
            "store is not iterable",
            "insufficient inventory",
            "cannot read properties",
            "amountcents",
            "totalcents",
            "unitpricecents",
            "cannot find module",
            "err_module_not_found",
        )
    )
    if domain_runtime_failure:
        targets = [path for path in required_files if path.endswith("fulfillment.js")] or ["src/fulfillment.js"]
        return {
            "summary": "corrigir contrato de domínio usado pelos testes",
            "targetFiles": targets,
        }

    test_file_failure = (
        re.search(r"(^|[\s`])test[/\\]", lowered)
        or "0 tests" in lowered
        or "node:test" in lowered
        or "jest" in lowered
        or "suíte insuficiente" in lowered
        or any(f"referenceerror: {name.lower()} is not defined" in lowered for name in ("createStore", "applyCommand", "replayEvents", "parseJsonl", "test", "assert"))
    )
    if test_file_failure:
        node_test_import_error = "node:test" in lowered and "does not provide an export named" in lowered
        if ("does not provide an export named" in lowered or "não exporta" in lowered) and not node_test_import_error:
            source_targets = [path for path in required_files if path.startswith("src/")]
            return {
                "summary": "corrigir exports do código fonte usados pelos testes",
                "targetFiles": source_targets,
            }
        targets = [path for path in required_files if path.startswith("test/")] or ["test/fulfillment.test.mjs"]
        return {
            "summary": "corrigir/criar testes nativos antes de mexer no domínio",
            "targetFiles": targets,
        }
    if "require" in lowered or "esm" in lowered or "cli" in lowered:
        targets = [path for path in required_files if path.endswith("cli.js")] or ["src/cli.js"]
        return {
            "summary": "corrigir CLI ESM e smoke",
            "targetFiles": targets,
        }
    if any(token in lowered for token in ("commandid", "processedcommandid", "orderreserved", "paymentcaptured", "totalcents", "parsejsonl")):
        targets = [path for path in required_files if path.endswith("fulfillment.js")] or ["src/fulfillment.js"]
        return {
            "summary": "corrigir modelo de domínio/event sourcing",
            "targetFiles": targets,
        }
    if "arquivo obrigatório" in lowered or "entrega incompleta" in lowered:
        missing = _missing_files_from_failures(failures)
        return {
            "summary": "criar arquivos obrigatórios ausentes",
            "targetFiles": missing or required_files,
        }
    return {
        "summary": "corrigir menor conjunto de arquivos necessário para passar validação",
        "targetFiles": required_files,
    }


def _missing_files_from_failures(failures: list[str]) -> list[str]:
    out: list[str] = []
    for failure in failures:
        if "`" not in failure:
            continue
        parts = failure.split("`")
        if len(parts) >= 2:
            candidate = parts[1]
            if "/" in candidate or candidate in {"README.md", "package.json"}:
                out.append(candidate)
    return _dedupe(out)


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out
