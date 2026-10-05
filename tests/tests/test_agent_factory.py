"""Testes — criação e validação de agentes."""

from __future__ import annotations

import shutil

import pytest
import yaml
from fastapi.testclient import TestClient

from learning_agent.api import app
from learning_agent.config import PROJECT_ROOT
from learning_agent.core import agent_factory

TEST_AGENT = "test-scaffold-agent"
TEST_SKILL = "test-scaffold-skill"


def _cleanup_agent(slug: str) -> None:
    paths = [
        PROJECT_ROOT / ".cursor" / "agents" / f"{slug}.md",
        PROJECT_ROOT / "agents" / "projects" / slug,
        PROJECT_ROOT / ".cursor" / "skills" / f"{slug}-learning",
        PROJECT_ROOT / ".cursor" / "skills" / slug,
    ]
    for path in paths:
        if path.is_file():
            path.unlink()
        elif path.is_dir():
            shutil.rmtree(path, ignore_errors=True)

    registry_path = PROJECT_ROOT / "agents" / "registry.yaml"
    if registry_path.is_file():
        with registry_path.open(encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        agents = [a for a in data.get("user_agents", []) if a.get("name") != slug]
        data["user_agents"] = agents
        with registry_path.open("w", encoding="utf-8") as fh:
            yaml.dump(data, fh, allow_unicode=True, sort_keys=False)


@pytest.fixture(autouse=True)
def cleanup_scaffolds():
    yield
    _cleanup_agent(TEST_AGENT)
    _cleanup_agent(TEST_SKILL)


def test_list_archetypes_has_core_types():
    result = agent_factory.list_archetypes()
    assert result["success"] is True
    ids = {a["id"] for a in result["archetypes"]}
    assert {"backend", "frontend", "qa-inspector", "data", "debug-optimizer", "custom"} <= ids


def test_list_agents_includes_quiz_master():
    result = agent_factory.list_agents()
    assert result["success"] is True
    names = {a["name"] for a in result["agents"]}
    assert "quiz-master" in names
    assert len(result["archetypes"]) >= 5


def test_validate_quiz_master():
    result = agent_factory.validate_agent_definition(".cursor/agents/quiz-master.md")
    assert result["success"] is True
    assert result["valid"] is True
    assert result["name"] == "quiz-master"


def test_scaffold_agent_project_backend():
    result = agent_factory.scaffold_agent_project(
        TEST_AGENT,
        "backend",
        "Agente backend de teste.",
        focus="APIs de teste",
        overwrite=True,
    )
    assert result["success"] is True
    assert result["archetype"] == "backend"
    assert result["learning_enabled"] is True

    agent_path = PROJECT_ROOT / result["files"]["agent"]
    manifest_path = PROJECT_ROOT / result["files"]["manifest"]
    playbook_path = PROJECT_ROOT / result["files"]["playbook"]
    skill_path = PROJECT_ROOT / result["files"]["learning_skill"]

    assert agent_path.is_file()
    assert manifest_path.is_file()
    assert playbook_path.is_file()
    assert skill_path.is_file()

    agent_text = agent_path.read_text(encoding="utf-8")
    assert "Aprendizado contínuo" in agent_text
    assert "FastAPI" in agent_text or "API" in agent_text

    with manifest_path.open(encoding="utf-8") as fh:
        manifest = yaml.safe_load(fh)
    assert manifest["learning"]["enabled"] is True
    assert "backend" in manifest["learning"]["tags"]


def test_scaffold_cursor_agent_uses_archetype():
    result = agent_factory.scaffold_cursor_agent(
        TEST_AGENT,
        "Agente QA de teste.",
        "vistorias",
        archetype="qa-inspector",
        overwrite=True,
    )
    assert result["success"] is True
    assert result["archetype"] == "qa-inspector"
    text = (PROJECT_ROOT / result["files"]["agent"]).read_text(encoding="utf-8")
    assert "vistoria" in text.lower() or "qualidade" in text.lower()


def test_scaffold_skill():
    result = agent_factory.scaffold_skill(
        TEST_SKILL,
        "Skill de teste para validar scaffold.",
        "workflows de teste",
        overwrite=True,
    )
    assert result["success"] is True
    path = PROJECT_ROOT / result["file_path"]
    assert path.is_file()
    assert "add_learning_note" in path.read_text(encoding="utf-8")


def test_api_agents_endpoints():
    with TestClient(app) as client:
        archetypes = client.get("/api/agents/archetypes")
        assert archetypes.status_code == 200
        assert len(archetypes.json()["archetypes"]) >= 5

        listing = client.get("/api/agents")
        assert listing.status_code == 200
        assert listing.json()["success"] is True

        scaffold = client.post(
            "/api/agents/projects/scaffold",
            json={
                "name": TEST_AGENT,
                "archetype": "data",
                "description": "Via API REST.",
                "overwrite": True,
            },
        )
        assert scaffold.status_code == 200
        assert scaffold.json()["success"] is True
        assert scaffold.json()["archetype"] == "data"

        validate = client.get(
            "/api/agents/validate",
            params={"path": f".cursor/agents/{TEST_AGENT}.md"},
        )
        assert validate.status_code == 200
        assert validate.json()["valid"] is True
        assert validate.json()["project"] is not None
