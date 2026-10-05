"""Relatório performance paper + graduação live — CLI."""

from __future__ import annotations

import json
import sys

from learning_agent.core.cli_encoding import ensure_utf8_stdio
from learning_agent.core.finance_paper_performance import (
    compute_paper_performance,
    format_performance_telegram,
    graduation_eligibility,
)


def main() -> None:
    ensure_utf8_stdio()
    perf = compute_paper_performance()
    grad = graduation_eligibility(perf=perf)
    print(format_performance_telegram(perf))
    print()
    print(json.dumps(grad, ensure_ascii=False, indent=2))
    raise SystemExit(0 if grad.get("eligible") else 0)


if __name__ == "__main__":
    main()
