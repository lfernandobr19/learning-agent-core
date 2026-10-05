from learning_agent.core.llm_engines import resolve_ide_chat_endpoint


def test_fast_uses_local_not_cloud():
    # Raven local (groq engine + 0.5b) segue local — não vira cloud.
    assert resolve_ide_chat_endpoint(
        engine="groq",
        task_mode="chat",
        resolved_size="0.5b",
        model_size_requested="0.5b",
    ) is None


def test_deepseek_pro_not_swallowed_by_light_message(monkeypatch):
    # Regra Luis: DeepSeek Pro selecionado NUNCA é engolido pelo atalho 0.5b/fast.
    monkeypatch.setattr(
        "learning_agent.core.llm_engines.DEEPSEEK_API_KEY",
        "sk-test",
    )
    monkeypatch.setattr(
        "learning_agent.core.llm_engines.DEEPSEEK_API_BASE",
        "https://api.deepseek.com/v1",
    )
    monkeypatch.setattr(
        "learning_agent.core.llm_engines.DEEPSEEK_MODEL",
        "deepseek-v4-pro",
    )
    ep = resolve_ide_chat_endpoint(
        engine="deepseek_pro",
        task_mode="fast",  # mensagem leve costumava rebaixar p/ fast
        resolved_size="0.5b",
        model_size_requested="0.5b",
    )
    assert ep is not None
    assert ep["model"] == "deepseek-v4-pro"


def test_deepseek_cloud_when_configured(monkeypatch):
    monkeypatch.setattr(
        "learning_agent.core.llm_engines.DEEPSEEK_API_KEY",
        "sk-test",
    )
    monkeypatch.setattr(
        "learning_agent.core.llm_engines.DEEPSEEK_API_BASE",
        "https://api.deepseek.com/v1",
    )
    monkeypatch.setattr(
        "learning_agent.core.llm_engines.DEEPSEEK_MODEL",
        "deepseek-v4-pro",
    )
    ep = resolve_ide_chat_endpoint(
        engine="deepseek_pro",
        task_mode="chat",
        resolved_size="32b",
        model_size_requested="auto",
    )
    assert ep is not None
    assert ep["model"] == "deepseek-v4-pro"
    assert "deepseek" in ep["base_url"]


def test_deepseek_agent_mode(monkeypatch):
    monkeypatch.setattr(
        "learning_agent.core.llm_engines.DEEPSEEK_API_KEY",
        "sk-test",
    )
    monkeypatch.setattr(
        "learning_agent.core.llm_engines.DEEPSEEK_API_BASE",
        "https://api.deepseek.com/v1",
    )
    monkeypatch.setattr(
        "learning_agent.core.llm_engines.DEEPSEEK_MODEL",
        "deepseek-v4-pro",
    )
    ep = resolve_ide_chat_endpoint(
        engine="deepseek_pro",
        task_mode="agent",
        resolved_size="32b",
        model_size_requested="auto",
    )
    assert ep is not None
    assert ep["model"] == "deepseek-v4-pro"


def test_deepseek_flash_chat_and_agent(monkeypatch):
    monkeypatch.setattr(
        "learning_agent.core.llm_engines.DEEPSEEK_API_KEY",
        "sk-test",
    )
    monkeypatch.setattr(
        "learning_agent.core.llm_engines.DEEPSEEK_API_BASE",
        "https://api.deepseek.com/v1",
    )
    monkeypatch.setattr(
        "learning_agent.core.llm_engines.DEEPSEEK_MODEL_FAST",
        "deepseek-v4-flash",
    )
    for mode in ("chat", "agent"):
        ep = resolve_ide_chat_endpoint(
            engine="deepseek_flash",
            task_mode=mode,
            resolved_size="32b",
            model_size_requested="flash",
        )
        assert ep is not None
        assert ep["model"] == "deepseek-v4-flash"
        assert ep["base_url"] == "https://api.deepseek.com/v1"


def test_groq_agent_stays_local():
    assert resolve_ide_chat_endpoint(
        engine="groq",
        task_mode="agent",
        resolved_size="32b",
        model_size_requested="auto",
    ) is None
