# Melhorias IDE — QA Guardian

**ID:** ide-64dd014ece
**Agente:** qa-guardian

## Temas
- testes do ecossistema multi-agente
- smoke tests da IDE
- relatórios de falha acionáveis

## Proposta
### Problema 1: Função Incompleta `prove_distillation_pair_exists`
**Arquivo Alvo:** `learning_agent/core/proofs.py`

A função `prove_distillation_pair_exists` está incompleta. A linha `db.init` parece ser um esquecimento e não faz parte de uma chamada válida ou lógica.

#### Solução:
Complete a função para verificar se o par existe no banco de dados, retornando os resultados corretamente.

```python
def prove_distillation_pair_exists(pair_id: int) -> dict[str, Any]:
    try:
        pair = db.get_pair_by_id(pair_id)
        if pair is not None:
            return _check("distillation_pair_exists", True)
        else:
            return _check("distillation_pair_exists", False, f"Pair ID {pair_id} não encontrado.")
    except Exception as e:
        return _check("distillation_pair_exists", False, str(e))
```

#### Como Testar:
1. Adicione testes unitários para verificar se a função retorna os resultados esperados para pares de IDs existentes e inexistentes.
2. Execute `pytest` na pasta do projeto para garantir que todos os testes passam.

### Problema 2: Falta de Validação de Parâmetros
**Arquivo Alvo:** `learning_agent/core/proofs.py`

A função `_check` não valida se o parâmetro `name` é uma string ou se `passed` é um booleano. Isso pode levar a erros inesperados.

#### Solução:
Adicione verificações de tipo para os parâmetros da função `_check`.

```python
def _check(name: str, passed: bool, detail: str = "") -> dict[str, Any]:
    assert isinstance(name, str), "name deve ser uma string"
    assert isinstance(passed, bool), "passed deve ser um booleano"
    return {"check": name, "passed": passed, "detail": detail}
```

#### Como Testar:
1. Adicione testes unitários para verificar se a função `_check` lida corretamente com tipos de entrada inválidos.
2. Execute `pytest` na pasta do projeto e verifique se os testes passam.

### Problema 3: Falta de Documentação
**Arquivo Alvo

## Arquivos analisados
- learning_agent/core/proofs.py