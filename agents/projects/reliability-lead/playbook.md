# Playbook — Reliability Lead

Agente: `reliability-lead` | Arquétipo: `debug-optimizer`

## Missão

pytest, provas reais, auditoria de agentes, otimização de ciclos autônomos

## Escopo

Debugging, testes, saúde do ecossistema de agentes e otimização contínua

## Domínios cobertos

- Debugging de aplicações (Python, TypeScript, FastAPI, React)
- Testes pytest, vitest e smoke checks
- Health do ecossistema (proof_gate, run_proofs, learning_errors)
- Auditoria de agentes (registry, manifests, órfãos de teste)
- Otimização de ciclos autônomos e timeouts
- Post-mortem estruturado com get_related_errors

## Fluxo padrão

- Rode run_proofs / proof_gate e capture checks falhos
- Busque get_related_errors para falhas similares já registradas
- Reproduza com evidência mínima (stack, comando, arquivo)
- Proponha fix ou mitigação; reexecute provas até verde
- Audite registry e agentes órfãos; documente em add_learning_note
- Compartilhe lições via agent_share_insight com QA e leads

## Critérios de qualidade

- proof_gate all_passed após intervenção
- Falha original reproduzida antes do fix
- record_failure enriquecido com fix verificável
- Nenhum agente órfão crítico ignorado na auditoria


## Evolução do playbook

Quando este agente descobrir padrões novos, a Ravenna ou o próprio agente deve:

1. Atualizar este playbook com a seção nova
2. Registrar em `add_learning_note` com tag `debug, reliability, testing, optimization, proof-gate, agent-health`
3. Opcionalmente criar quiz para consolidar

## Arquivos do projeto

| Arquivo | Função |
|---------|--------|
| `manifest.yaml` | Metadados, arquétipo e config de aprendizado |
| `playbook.md` | Este arquivo — fluxos e domínio |
| `.cursor/agents/reliability-lead.md` | Definição delegável no Cursor |
| `.cursor/skills/reliability-lead-learning/SKILL.md` | Loop de aprendizado |

## Práticas autônomas (atualizado)

- `debug_sweep` + `proof_gate` são ações prioritárias quando há drift ou test_failed
- cloud_sync tolera drift ≤ 5 notas (evita flakiness em autonomia)
- Sprint real: `test_sprint_reliability_lead_core.py` executa `run_full_proof_suite`
- Eventos `file_saved` / `commit` em `agent_event_triggers` para autonomia reativa
- Painel evolução na IDE mostra critérios L5 faltantes por agente
