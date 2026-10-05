"""Testes — estudo inteligente de workspace."""

from __future__ import annotations

from learning_agent.core.workspace_study import (
    build_deep_analysis,
    collect_study_paths,
    verify_study_reply,
)


def test_collect_remoteapp_paths_includes_core():
    paths = collect_study_paths(["luis-132-255-110-213"], max_files=36)
    joined = " ".join(paths)
    assert "models.py" in joined
    assert "routes.py" in joined
    assert "docker-compose.yml" in joined


def test_deep_analysis_extracts_routes_and_models():
    cache = {
        "luis-132-255-110-213/remote_app/routes.py": (
            '@bp.route("/acionamentos")\n@bp.route("/api/ai/chat")\n'
        ),
        "luis-132-255-110-213/remote_app/models.py": (
            "class User(db.Model):\nclass Atividade(db.Model):\n"
        ),
        "luis-132-255-110-213/remote_app/hub.py": (
            "{'id': 'acionamentos', 'title': 'Gerenciador'}\n"
        ),
        "luis-132-255-110-213/requirements.txt": "Flask\nFlask-SQLAlchemy\ngunicorn\n",
    }
    deep = build_deep_analysis("luis-132-255-110-213", cache)
    assert deep["route_total"] == 2
    assert "Atividade" in deep["model_classes"]
    assert "acionamentos" in deep["hub_modules"]
    assert "Flask" in deep["stack_hints"]


def test_verify_study_reply_scores_coverage():
    deep = [
        {
            "stack_hints": ["Flask", "PostgreSQL"],
            "model_classes": ["Atividade", "User"],
            "hub_modules": ["acionamentos", "copilot", "preventivas"],
            "route_total": 40,
            "pipeline_statuses": ["Aguardando", "Em Andamento"],
        }
    ]
    good = (
        "REMOTE_APP usa Flask e PostgreSQL. Entidade Atividade no pipeline. "
        "Hub com acionamentos e copilot. Rotas /acionamentos e API."
    )
    result = verify_study_reply(good, deep)
    assert result["score"] >= 70
    assert result["passed"] >= 4
