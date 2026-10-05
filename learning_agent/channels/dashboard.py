"""Dashboard web simples — status e capacidades da Ravenna."""

from __future__ import annotations

from typing import Any

from learning_agent.core import active_learning, distillation, graph, progress
from learning_agent import sync
from learning_agent.identity import AGENT_NAME, AGENT_ROLE, IDENTITY_BRIEF


def get_dashboard() -> dict[str, Any]:
    prog = progress.get_progress()
    return {
        "agent": AGENT_NAME,
        "role": AGENT_ROLE,
        "identity": IDENTITY_BRIEF,
        "progress": prog.get("summary", {}),
        "weak_areas": prog.get("weak_areas", []),
        "distillation": distillation.get_status(),
        "graph": graph.graph_stats(),
        "suggestions": active_learning.suggest_learning(5),
        "cloud_sync": sync.is_configured(),
        "capabilities": [
            "RAG + ChromaDB",
            "Knowledge Distillation",
            "Codebase indexing",
            "Session memory",
            "Error-driven learning",
            "Knowledge graph",
            "Active learning",
            "Ollama fine-tune export",
            "GitHub + RSS sources",
            "Telegram bot",
            "CI learning",
            "Provas reais",
            "Supabase sync",
        ],
    }


DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8"/>
  <title>Ravenna Dashboard</title>
  <style>
    body { font-family: system-ui; background: #0f1117; color: #e6e6e6; margin: 2rem; }
    h1 { color: #c9a0ff; }
    .card { background: #1a1d27; border-radius: 8px; padding: 1rem; margin: 1rem 0; }
    .tag { display: inline-block; background: #2d3148; padding: 0.2rem 0.6rem; border-radius: 4px; margin: 0.2rem; font-size: 0.85rem; }
  </style>
</head>
<body>
  <h1>Ravenna — Dashboard</h1>
  <p>API: <a href="/dashboard" style="color:#9cf">/dashboard</a> | <a href="/health" style="color:#9cf">/health</a></p>
  <div class="card"><pre id="data">Carregando...</pre></div>
  <script>
    fetch('/dashboard').then(r => r.json()).then(d => {
      document.getElementById('data').textContent = JSON.stringify(d, null, 2);
    });
  </script>
</body>
</html>"""
