# Meu Jarvis

Meu Jarvis e um assistente/agente pessoal local para PC, baseado em um fork legal do projeto Mark-XXXIX / MARK XXXIX, evoluido para uso pessoal com foco em memoria persistente, acoes controladas, percepcao local, automacao assistida e evolucao incremental.

## Overview
Este repositorio e local-first: foi pensado para rodar no seu proprio computador, com foco em controle, auditabilidade e limites claros de seguranca. O objetivo e evoluir por etapas, com testes e contratos antes de mudar o runtime.

## Origin and Attribution
- Origem: fork legal de Mark-XXXIX / MARK XXXIX.
- Este repositorio preserva a atribuicao ao projeto original e segue a licenca/atribuicao correspondente.

## Current Status
- Status geral: em progresso (uso pessoal/local).
- Entry point: `main.py`.
- UI: `ui.py`.
- Memoria:
  - Memoria legada ainda existe (JSON em `memory/` via `save_memory`).
  - Novo Memory Engine (SQLite + JSONL) existe em `memory_engine/`.
  - Integracao read-only do Memory Engine no runtime existe e e OFF por padrao (toggle por ambiente).
- Testes: `python -m unittest discover tests` (local).

## What Meu Jarvis Is
- Um assistente local, com voz/UI, capaz de executar acoes via ferramentas (apps, navegador, desktop, arquivos, etc.).
- Um projeto com memoria estruturada local (SQLite) e trilha de auditoria (JSONL).
- Um sistema com evolucao incremental (contratos + testes + auditorias antes de integrar).

## What Meu Jarvis Is Not
- Nao e um produto comercial.
- Nao e "production ready".
- Nao e AGI.
- Nao e infraestrutura de servidor.
- Nao e um mecanismo de "salvar tudo" automaticamente.

## Core Capabilities (Local)
As capacidades abaixo existem como modulos no repositorio. Algumas sao experimentais e dependem do ambiente local (Windows/permissoes/instalacoes):
- Voz em tempo real (entrada/saida) e UI local.
- Tool/function calling para acionar acoes.
- Controle de apps, navegador e desktop.
- Manipulacao e processamento de arquivos.
- Processamento de tela.
- Web search e YouTube (acoes dedicadas).
- Reminders, weather, messaging.
- Game updater (voltado a jogos).
- Memoria legada (JSON) e Memory Engine novo (SQLite).

## Current Local Architecture
- `main.py`: runtime atual, sessao e roteamento de tool calls.
- `ui.py`: interface local.
- `actions/`: implementacoes de ferramentas (abrir app, browser control, etc.).
- `agent/`: fila/planejamento/executor de tarefas.
- `brain/`: Brain Foundation deterministico (v0) - roteamento/validacao, ainda standalone.
- `memory/`: memoria legada JSON (inclui `save_memory`).
- `memory_engine/`: memoria estruturada SQLite + auditoria JSONL + read-only adapter/wrapper.

## Memory Engine (Resumo)
O Memory Engine (em `memory_engine/`) fornece:
- SQLite local: `data/jarvis_memory.db` (runtime local, ignorado pelo Git).
- JSONL append-only: `data/raw_events.jsonl` (runtime local, ignorado pelo Git).
- Politicas de escopo:
  - `GLOBAL_RULE` deve ser `scope=global`.
  - `PROJECT_CONTEXT` e `TECHNICAL_STATE` nao podem ser `scope=global`.
- Privacy guard: bloqueia secrets (API keys, tokens, passwords, private keys, etc.).
- Runtime read-only:
  - `runtime_adapter.py`: leitura estritamente read-only (`mode=ro`) e contexto bounded.
  - `runtime_context.py`: wrapper toggle-gated que retorna bloco de contexto ou vazio.

## Brain Foundation (Resumo)
A Brain Foundation (em `brain/`) e deterministica/rule-based (v0):
- Detecta contexto e risco por palavras-chave.
- Roteia para modos (Debugger, Sysadmin, Security Reviewer, etc.).
- Nao executa shell e nao chama LLM.

## Safety Model (Resumo)
- Sem "autonomous learning" e sem "save everything".
- Escrita de memoria deve ser explicita (CLI/manual) e validada.
- Integracao runtime do SQLite e read-only primeiro e OFF por padrao.
- Segredos nao devem ser versionados no Git (chaves ficam locais).

## Local Setup (Exemplo)
```bash
git clone https://github.com/livefgs-ux/Meu-Jarvi.git
cd Meu-Jarvi
python -m venv .venv
.venv\\Scripts\\activate
pip install -r requirements.txt
playwright install
python main.py
```

## Environment Variables (Read-Only Memory)
O contexto read-only do Memory Engine e controlado por variaveis de ambiente (OFF por padrao):
- `JARVIS_READONLY_MEMORY=0|1` (default 0)
- `JARVIS_MEMORY_PROJECT=Meu-Jarvi` (obrigatorio quando enabled)
- `JARVIS_MEMORY_MAX_CHARS=2500` (opcional)
- `JARVIS_MEMORY_LIMIT=8` (opcional)
- `JARVIS_MEMORY_DB=data/jarvis_memory.db` (opcional)

Observacao: este projeto nao carrega `.env` automaticamente. Essas variaveis devem ser definidas no shell/sistema.

## Documentation Map
- `docs/PROJECT_CONTEXT.md`
- `docs/ARCHITECTURE.md`
- `docs/MEMORY_ENGINE.md`
- `docs/ACTIONS_AND_TOOLS.md`
- `docs/SECURITY_MODEL.md`
- `docs/CODEX_WORKFLOW.md`
- `ROADMAP.md`
- `CHANGELOG.md`

## License and Attribution
Este repositorio e um fork legal de Mark-XXXIX / MARK XXXIX e preserva a atribuicao e licenca aplicavel.

## Project Philosophy
- Local-first, humano-no-loop.
- Auditar antes de integrar.
- Preferir regras explicitas, logs e limites claros a automatizacao sem controle.
