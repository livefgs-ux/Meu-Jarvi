# Meu Jarvis - Memory Migration Plan

## 1. Purpose
Planejar uma migracao segura e gradual da escrita de memoria legada (JSON) para o novo Memory Engine (SQLite + JSONL), sem quebrar o comportamento atual do Jarvis e sem executar migracao real nesta fase.

## 2. Current State
Estado confirmado no codigo local:
- Leitura runtime pode usar o novo Memory Engine como contexto **read-only**, via:
  - `main.py` -> `build_readonly_memory_context_from_env()`
  - `memory_engine/runtime_context.py` -> `memory_engine/runtime_adapter.py`
- Essa leitura e:
  - read-only
  - toggle-gated por env vars
  - OFF por padrao
- O tool `save_memory` ainda escreve na memoria legada:
  - `main.py::_execute_tool()` -> `memory.memory_manager.update_memory()` -> `memory/long_term.json`
- O writer SQLite existe (`memory_engine/writer.py`), mas **nao e chamado pelo fluxo runtime `save_memory` atual**.
- O runtime ainda injeta a memoria legada no prompt e, se habilitado, injeta o contexto read-only do SQLite:
  1. time context
  2. legacy memory string (se existir)
  3. read-only memory context (se env permitir)
  4. system prompt (core/prompt.txt) como ultima parte/autoridade final

## 3. Migration Goals
- Nao perder memorias antigas.
- Nao duplicar fatos e preferencias.
- Bloquear secrets/credenciais durante a migracao.
- Manter compatibilidade com o comportamento atual do Jarvis.
- Preservar testes existentes e adicionar testes novos antes de qualquer integracao de escrita.
- Manter rollback simples e confiavel.
- Migrar de forma gradual e auditavel (com relatorios e logs).

## 4. Non-Goals
Este plano NAO faz (e nao deve fazer automaticamente):
- Remover ou apagar `memory/long_term.json`.
- Trocar `save_memory` diretamente para SQLite sem testes e feature flag.
- Apagar dados legados.
- Migrar secrets (API keys, tokens, passwords, private keys, `.env`-like).
- Alterar o comportamento do prompt sem controle e sem limites.
- Ligar read-only memory por padrao sem decisao explicita.

## 5. Source Systems
- Legacy memory file: `memory/long_term.json`
- Legacy manager: `memory/memory_manager.py`
- New memory DB (runtime local): `data/jarvis_memory.db`
- New audit/event log (runtime local): `data/raw_events.jsonl`
- New validated writer: `memory_engine/writer.py`
- New read-only runtime path: `memory_engine/runtime_context.py` + `memory_engine/runtime_adapter.py`

## 6. Memory Authority Model
Proposta de autoridade por fases (para reduzir risco):

### Phase A - Current (baseline)
- Escrita runtime: JSON legado (`save_memory` -> `memory/long_term.json`)
- Leitura runtime: opcional (SQLite read-only) via env toggle

### Phase B - Offline migration + validation
- Criar uma ferramenta offline que le JSON e escreve no SQLite de forma controlada.
- SQLite pode ser inspecionado/validado (status lifecycle).
- JSON legado permanece intacto como backup/verdade historica.

### Phase C - Feature-flagged runtime write
- `save_memory` passa a escrever no SQLite **apenas com feature flag**.
- Opcional: dual-write temporario (com regras anti-duplicacao) OU backup do JSON somente.
- JSON legado permanece como fallback/backup.

### Phase D - SQLite primary + legacy frozen
- SQLite vira a fonte principal para escrita.
- JSON legado fica congelado/arquivado (sem novas escritas).
- Remocao completa do JSON legado apenas em uma fase futura separada (se/quando aprovado).

## 7. Mapping Strategy
O JSON legado contem categorias provaveis:
- `identity`
- `preferences`
- `projects`
- `relationships`
- `wishes`
- `notes`

### Mapping sugerido (primeira proposta)
Observacao: este mapping deve ser conservador. Em duvida, preferir status `candidate` e exigir revisao.

- `identity`
  - Preferir `PREFERENCE` (scope global) para informacoes pessoais gerais do usuario (nome/cidade/idioma) SE isso for desejado pelo usuario.
  - Se for informacao tecnica de projeto (raro), mapear para `PROJECT_CONTEXT` com scope `project:<name>`.
  - Em caso de incerteza: `candidate`.

- `preferences` -> `PREFERENCE` (scope global)

- `projects` -> `PROJECT_CONTEXT` (scope `project:<project>`)

- `relationships`
  - Pode ser PII. Mapear apenas se o usuario quiser manter. Caso mantenha:
    - Preferir `PREFERENCE` ou `PROJECT_CONTEXT` dependendo do conteudo.
    - Em duvida: `candidate`.

- `wishes`
  - `IDEA` ou `TASK` dependendo se e desejo/ideia ou algo com acao planejada.
  - Scope normalmente global (a menos que explicitamente ligado a projeto).

- `notes`
  - Pode virar `PROJECT_CONTEXT`, `TECHNICAL_STATE`, `WARNING` ou `IDEA` dependendo do conteudo.
  - Regras:
    - Conteudo tecnico do projeto: `TECHNICAL_STATE` ou `PROJECT_CONTEXT` com scope `project:<name>`.
    - Alertas/riscos: `WARNING` com scope `project:<name>` (ou global se realmente global).
    - Ideias soltas: `IDEA`.

### Escopo (scope) - regras
- Preferir `scope="global"` apenas para regras globais e preferencias gerais.
- Para conteudo tecnico do projeto, usar `scope="project:<nome>"`.
- Respeitar a policy do Memory Engine:
  - `GLOBAL_RULE` deve ser global.
  - `PROJECT_CONTEXT` e `TECHNICAL_STATE` nao podem ser global.
- Sempre passar por `validate_memory_scope_policy()` (via MemoryRecord.validated()).

## 8. Safety Rules
- Nunca migrar secrets/credenciais:
  - aplicar `privacy_guard` antes de qualquer tentativa de `create_memory`.
- Nunca sobrescrever/alterar `data/jarvis_memory.db` sem backup.
- Nunca apagar JSON legado automaticamente.
- Registrar eventos de migracao (via JSONL do Memory Engine) para auditoria.
- Evitar duplicatas:
  - definir estrategia de dedupe por (type, scope, project, normalized content).
- Entradas duvidosas:
  - marcar como `candidate` por padrao.
- Conflitos:
  - deixar o conflict detection atuar; nao forcar status `validated`.
- Bounded prompt:
  - nao injetar contexto ilimitado; respeitar `max_chars` e `limit`.

## 9. Backup Strategy
- Antes de qualquer migracao (mesmo offline):
  - Fazer backup manual de `memory/long_term.json` com timestamp.
  - Fazer backup do SQLite `data/jarvis_memory.db` com timestamp.
- Nunca commitar backups.
- Backups devem ficar fora do repo OU em local gitignored.

## 10. Offline Migration Tool Plan (future)
Planejar (sem implementar agora) uma ferramenta offline, sugerida:
- `tools/migrate_legacy_memory.py`

### Safe mode default
- `--dry-run` por padrao:
  - le o JSON legado
  - calcula mapping
  - detecta secrets
  - detecta duplicatas
  - detecta conflitos potenciais
  - gera relatorio (sem escrever em DB)

### Flags sugeridas
- `--dry-run` (default)
- `--apply` (escrever no SQLite apenas com confirmacao explicita)
- `--project Meu-Jarvi` (nome do projeto para scopes project)
- `--backup` (criar backups com timestamp)
- `--report <path>` (salvar relatorio de migracao; nao commitar)

### Saida esperada (relatorio)
- total lido (itens no JSON)
- total migravel
- total bloqueado por privacy_guard
- total duplicado (skip)
- total em conflito (marcar candidate/conflicted)
- total escrito (apenas em --apply)
- paths de backup/relatorio

## 11. Runtime save_memory Migration Plan (future)
Planejar mudanca futura no runtime (sem implementar agora):

### Options
1. Option 1 - legacy-only (atual): manter JSON apenas.
2. Option 2 - dual-write temporario: JSON + SQLite (com dedupe e feature flag).
3. Option 3 - sqlite-primary + legacy backup: escreve SQLite, e opcionalmente salva snapshot/backup do JSON.
4. Option 4 - sqlite-only final: apenas SQLite (fase tardia).

### Recomendacao
- Comecar com migracao offline (Phase B), validar e revisar.
- Depois introduzir runtime write com feature flag, com testes e rollback claro.
- Evitar trocar diretamente sem fase offline + validacao.

### Feature flags sugeridas (design)
- `JARVIS_MEMORY_WRITE_BACKEND=legacy|sqlite|dual`
- `JARVIS_MEMORY_WRITE_SQLITE=false|true`
- `JARVIS_MEMORY_LEGACY_BACKUP=true|false`

## 12. Required Tests Before Implementation
Testes novos necessarios antes de qualquer runtime write:
- Test parse do JSON legado (read-only) e estabilidade de schema.
- Test mapping por categoria (identity/preferences/projects/notes).
- Test `privacy_guard` bloqueia secrets.
- Test dedupe/duplicate prevention.
- Test conflict handling (candidate/conflicted).
- Test `--dry-run` nao escreve em SQLite nem JSONL.
- Test `--apply` escreve o numero esperado de rows no SQLite (em DB temporario).
- Test `save_memory` legado preservado quando backend=legacy.
- Test `save_memory` com feature flag sqlite/dual (em DB temporario; sem tocar `data/` real).
- Test bounded context (max_chars/limit) para evitar "prompt explosion".
- Test rollback scenario (restaurar backup, desabilitar flags).

## 13. Rollback Plan
- Se SQLite write falhar: voltar para legacy-only (feature flag).
- Se migracao offline gerar resultado ruim:
  - restaurar backup do SQLite DB
  - manter JSON legado intacto
- Se prompt piorar/ficar grande:
  - desligar `JARVIS_READONLY_MEMORY`
  - reduzir `JARVIS_MEMORY_MAX_CHARS` / `JARVIS_MEMORY_LIMIT`
- Se dual-write duplicar dados:
  - congelar escrita SQLite e voltar para legacy-only ate resolver dedupe.

## 14. Step-by-Step Implementation Roadmap (future)
1. Criar testes da ferramenta de migracao (DB temporario).
2. Criar parser read-only do JSON legado.
3. Implementar dry-run migrator.
4. Implementar relatorio de mapeamento.
5. Implementar backup automatico (opt-in).
6. Implementar apply mode (opt-in).
7. Validar SQLite com `retriever` (consultas deterministicas).
8. Ativar read-only memory manualmente para teste (env).
9. Criar feature flag para runtime write backend (sem default ON).
10. Testar dual-write (se escolhido).
11. Escolher cutover (sqlite-primary).
12. Congelar legacy JSON.
13. Documentar migracao concluida + manter rollback disponivel.

## 15. Acceptance Criteria
Considerar a migracao segura somente quando:
- Nenhum teste atual quebra.
- Novos testes passam (dry-run/apply/flags).
- Backups existem e sao verificaveis.
- Secrets sao bloqueados (nao migram).
- Duplicatas sao evitadas de forma previsivel.
- SQLite recupera contexto corretamente via `retriever` e via read-only adapter.
- Runtime funciona com read-only OFF.
- Runtime funciona com read-only ON (bounded).
- `save_memory` tem comportamento previsivel por feature flag.
- Rollback e possivel e documentado.

## 16. Open Questions
- O usuario quer preservar todas as memorias legadas (inclui PII/relationships) ou filtrar?
- Qual escopo padrao para dados pessoais (global vs session vs temporary)?
- Qual escopo padrao para dados tecnicos do projeto?
- Dual-write deve existir ou evitar para reduzir duplicacao?
- Quando congelar/desativar JSON legado?
- Deve haver uma UI/manual review para promover `candidate` -> `validated` antes de confiar?

