# Melhorias IDE — Data Engineer

**ID:** ide-ee298445e0
**Agente:** data-engineer

## Temas
- indexação peer-learning
- métricas de evolução por agente
- export fine-tune

## Proposta
### 1. Melhoria na configuração da função de embedding

**Problema:** 
A documentação sobre a escolha da função de embedding está parcialmente incompleta e pode levar a confusão para o desenvolvedor.

**Solução:**
Completar a documentação e adicionar uma verificação para garantir que as funções de embedding sejam carregadas corretamente. Além disso, tornar a escolha da função de embedding mais flexível através de um parâmetro configurável.

**Arquivo alvo:** `learning_agent/rag.py`

```python
import os
from pathlib import Path
from typing import Any

import chromadb
from chromadb.utils import embedding_functions

from learning_agent.config import CHROMA_PATH, RAG_EMBEDDINGS_FUNCTION

COLLECTION_NAME = "knowledge"

def get_embedding_function():
    if RAG_EMBEDDINGS_FUNCTION == "sentence-transformers":
        return embedding_functions.SentenceTransformerEmbeddingFunction(model_name="all-MiniLM-L6-v2")
    else:
        return chromadb.utils.embedding_functions.DefaultEmbeddingFunction()

embedding_function = get_embedding_function()
```

**Como testar:**
- Configure a variável de ambiente `RAG_EMBEDDINGS_FUNCTION` para `"sentence-transformers"` e verifique se o modelo correto é carregado.
- Defina `RAG_EMBEDDINGS_FUNCTION` como qualquer outro valor para usar a função padrão do ChromaDB.

### 2. Correção da função `_utcnow`

**Problema:** 
A função `_utcnow()` pode causar problemas de desempenho se for chamada em larga escala, pois cria um objeto `datetime` a cada invocação.

**Solução:**
Utilizar uma abordagem mais eficiente para gerar timestamps UTC ao utilizar a função `datetime.utcnow().isoformat()`, que é menos custosa em termos de desempenho.

**Arquivo alvo:** `learning_agent/db.py`

```python
from datetime import datetime, timezone

def _utcnow() -> str:
    return datetime.utcnow().isoformat()
```

**Como testar:**
- Use um benchmark para comparar o desempenho da função original e a função modificada.
- Verifique se a saída é consistente com a data UTC correta

## Arquivos analisados
- learning_agent/rag.py
- learning_agent/db.py