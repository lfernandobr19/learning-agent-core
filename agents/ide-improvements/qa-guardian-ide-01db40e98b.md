# Melhorias IDE — QA Guardian

**ID:** ide-01db40e98b
**Agente:** qa-guardian

## Temas
- testes do ecossistema multi-agente
- smoke tests da IDE
- relatórios de falha acionáveis

## Proposta
### Problema: Sem documentação para a função _cleanup() e sem testes de smoke.
#### Solução: Adicionar uma docstring à função _cleanup para explicar seu propósito, além de adicionar um novo arquivo tests/test_agent_ide_smoke.py com o seguinte conteúdo. Esse caminho permite que testadores rapidamente verifiquem se a estrutura básica do IDE está funcionando antes de conduzir outros testes mais detalhados:
```python
from tests.test_agent_ide import _cleanup  # Importa a função para o novo arquivo
import pytest
from learning_agent.config import PROJECT_ROOT, TESTS_DIR

@pytest.mark.smoke
def test_cleanup():
    """Teste smoke do processamento de limpeza."""
    
    # Cria agentes e projetos para obter o caminho dos arquivos que precisam ser removidos pelo _cleanup()
    peer = "test-agent"  # Nome fictício, não deve existir em nosso sistema real.
    agent_factory(peer)
    
    project = TESTS_DIR / f"{peer}-project"
    skill = PROJECT_ROOT / ".cursor/skills" / (f"{peer}-learning")  # Skill learning é um teste realista.
    agent_collaboration(peer)
    
    assert project.exists(), f"Project file {project} not found."
    assert skill.is_dir(), f"Skill directory for peer-agent does not exist: {skill}"
    
    # Executa limpeza e verifica se os arquivos foram removidos corretamente.
    _cleanup(f"{peer}")  # Invocação da função de limpeza com o nome do agente fictício como parâmetro.
    assert not (project.exists() and skill.is_dir()), "Files were not removed."
```
Com isso, testadores podem rapidamente verificar se a estrutura básica do IDE está funcionando antes de

## Arquivos analisados
- tests/agent_sprints/__init__.py
- tests/test_agent_autonomy.py
- tests/test_agent_capability.py
- tests/test_agent_collaboration.py