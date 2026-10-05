"""Reliability scoring for Ravenna autonomy benchmark runs."""

from __future__ import annotations

from typing import Any


DEFAULT_GATES = {
    "simple": 0.90,
    "medium": 0.75,
    "complex": 0.50,
}


def summarize_runs(runs: list[dict[str, Any]]) -> dict[str, Any]:
    by_complexity: dict[str, list[dict[str, Any]]] = {}
    false_successes = 0
    for run in runs:
        complexity = run.get("complexity") or "medium"
        by_complexity.setdefault(complexity, []).append(run)
        if run.get("passed") and run.get("hasFailures"):
            false_successes += 1

    groups: dict[str, dict[str, Any]] = {}
    for complexity, items in by_complexity.items():
        passed = sum(1 for item in items if item.get("passed"))
        rate = passed / len(items) if items else 0.0
        gate = DEFAULT_GATES.get(complexity, 0.75)
        groups[complexity] = {
            "runs": len(items),
            "passed": passed,
            "successRate": round(rate, 4),
            "gate": gate,
            "meetsGate": rate >= gate,
        }

    return {
        "runs": len(runs),
        "falseSuccesses": false_successes,
        "zeroFalseSuccessGate": false_successes == 0,
        "groups": groups,
        "reliable": false_successes == 0 and all(group["meetsGate"] for group in groups.values()),
    }


def classify_run_failure(autonomy: dict[str, Any]) -> list[str]:
    if autonomy.get("passed"):
        return []
    categories: set[str] = set()
    for attempt in autonomy.get("attempts") or []:
        critique = attempt.get("critique") or {}
        categories.update(critique.get("categories") or [])
    return sorted(categories) or ["unknown"]
