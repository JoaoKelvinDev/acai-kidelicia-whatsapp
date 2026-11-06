# Açaí Ki-Delícia PL — atendimento automático no WhatsApp

Backend de atendimento para o WhatsApp da loja. Requisitos completos em [`CLAUDE.md`](CLAUDE.md).

**Situação: Etapa 3 implementada — integração com a WhatsApp Cloud API em ambiente de teste.**
Validação real com o número de teste da Meta pendente (conta com erro 131031; ver
[docs/configuracao-meta.md](docs/configuracao-meta.md)). Sem IA (Etapa 4) e sem o número real da
loja (Etapa 5).

## Como rodar

Requisitos: Python 3.12+ e [uv](https://docs.astral.sh/uv/).

```bash
uv sync                                   # dependências
cp .env.example .env                      # APP_ENV=local habilita /dev e /docs
uv run python -m app.cli migrate          # cria/atualiza o banco (data/acai.db)
uv run python -m app.cli create-operator --username joao --role admin
uv run uvicorn app.main:create_app --factory --reload
```

- Painel da equipe: `http://localhost:8000/admin`
- Documentação interativa (só local): `http://localhost:8000/docs`

Testes e qualidade:

```bash
uv run pytest
uv run ruff check . && uv run ruff format --check .
```

## WhatsApp Cloud API

- `GET /webhook/whatsapp`: verificação da Meta (token em `WHATSAPP_VERIFY_TOKEN`).
- `POST /webhook/whatsapp`: eventos assinados. A assinatura `X-Hub-Signature-256` é conferida
  sobre o corpo bruto **antes** de ler o conteúdo. Todos os itens de cada notificação são lidos.
  - **Mensagens** seguem o fluxo de atendimento; **status** (enviada, entregue, lida, falhou)
    atualizam a resposta, deduplicados e sem regredir; **eco do app do celular**
    (`smb_message_echoes`, coexistência) pausa a automação da conversa.
  - Eventos de outro número e mensagens do próprio número são ignorados (sem loop).
- Envio: `WHATSAPP_GATEWAY=cloud`. Falhas classificadas em retentável (limite, 5xx, conexão),
  incerta (timeout após envio; nunca reenviada) e definitiva (ex.: fora da janela de 24 h).
- Travas: `cloud` é recusado com `APP_ENV=local`; fora de produção exige
  `WHATSAPP_ALLOWED_RECIPIENTS` e bloqueia qualquer outro destinatário antes de chamar a Meta.
- Guias: [configuração da Meta](docs/configuracao-meta.md) ·
  [sessão de teste com túnel e desativação](docs/teste-com-tunel.md) ·
  [investigação do número da loja](docs/investigacao-numero-loja.md).

## Comandos de operação

| Comando | Uso |
|---|---|
| `python -m app.cli migrate` | Aplica as migrações. A aplicação se recusa a iniciar com banco desatualizado |
| `python -m app.cli create-operator --username X --role admin\|atendente` | Cria operador (senha pedida no terminal, mínimo 10 caracteres) |
| `python -m app.cli set-password --username X` | Troca a senha e encerra as sessões abertas |
| `python -m app.cli deactivate-operator --username X` | Desativa e encerra as sessões |
| `python -m app.cli purge [--dry-run]` | Aplica a retenção. Agendar 1×/dia (cron ou Agendador de Tarefas) |

Todos com `uv run` na frente. Para scripts, `--password-stdin` lê a senha da entrada padrão.

## Painel da equipe (`/admin`)

Páginas HTML simples, pensadas para o celular, sem JavaScript.

- **Conversas**: abas *Aguardando equipe* (a mais antiga primeiro), *Em atendimento*,
  *Automático* e *Encerradas*. A lista se atualiza sozinha a cada 20 s.
- **Conversa**: pedido organizado (itens, cremes, sorvetes, adicionais, entrega, pagamento e
  troco), avisos para conferir, trechos não reconhecidos, histórico de mensagens e botões
  Assumir / Pausar / Devolver ao automático / Encerrar.
- **Configurações** (só admin): status da loja (manual ou pelos horários), horários por dia,
  link do site e pausa global da automação.

| Função | Pode |
|---|---|
| `atendente` | Ver conversas e assumir, pausar, devolver ao automático, encerrar |
| `admin` | Tudo acima, mais configurações da loja e pausa global |

Segurança: senha com Argon2; sessão em cookie `HttpOnly`/`SameSite=Lax` (token guardado só como
hash); CSRF em todo formulário; bloqueio de 5 min após 5 senhas erradas; cabeçalhos CSP,
`X-Frame-Options` e `no-store`; ações registradas na auditoria com o nome do operador.

## Retenção de dados (14 dias)

Decisão do proprietário. `purge` aplica:

- Conversa **sem atividade há mais de 14 dias** e fora de atendimento humano: apagada por
  completo (mensagens, pedidos e respostas).
- Conversa **ainda ativa**: registros com mais de 14 dias têm texto, nome, telefone e endereço
  removidos. Itens, modalidade e forma de pagamento ficam, para estatística.
- Conversas **Aguardando equipe / Em atendimento** nunca são limpas automaticamente.
- **Auditoria** (sem dados pessoais) fica 365 dias, sem o número do cliente depois da limpeza.
- Sessões expiradas são apagadas.

Prazos configuráveis em `RETENTION_DAYS` e `AUDIT_RETENTION_DAYS`.

## Simulação local (`/dev`, somente `APP_ENV=local`/`test`)

```bash
curl -X POST localhost:8000/dev/simulate/inbound \
  -H "Content-Type: application/json" \
  -d '{"from": "5511974123058", "text": "Oi"}'
```

| Rota | Uso |
|---|---|
| `POST /dev/simulate/inbound` | Mensagem recebida (`from`, `text`, `type`, `message_id` opcional) |
| `GET /dev/conversations/{id}` | Estado, mensagens, rascunhos, respostas e auditoria |
| `POST /dev/conversations/{id}/{take_over\|pause\|resume\|close}` | Controle humano sem login |
| `POST /dev/automation-pause` | Pausa global |
| `GET/PUT /dev/store-settings` | Configuração completa da loja |
| `POST /dev/retention/purge?dry_run=true` | Retenção |
| `GET /dev/sent` | Mensagens "enviadas" pelo gateway falso |

A loja começa com status **não configurado**: pedidos completos vão para conferência humana,
sem confirmação, até o admin definir status ou horários no painel.

## Arquitetura

```
mensagem ─► ConversationService ─────── uma transação ───────┐
            dedupe por ID · estado · intenção · parser ·      │
            validação · rascunho · respostas na outbox        ▼
                                                     SQLite (Alembic)
OutboxWorker (a cada 1 s) ─► Dispatcher ─► revalida pausa, handoff e janela de 24 h ─► gateway
Painel /admin ─► HandoffService / configuração ─► mesma base, com auditoria
```

```
app/
  main.py                  create_app(): lifespan (checa migração, inicia worker), cabeçalhos
  cli.py                   migrate, operadores, purge
  core/                    config, relógio, logs mascarados, container
  db/                      engine (SQLite WAL + BEGIN IMMEDIATE), esquema, tipo UTC
  domain/                  enums, modelos, loja, telefone, validação, operadores
  parsers/                 normalização, dinheiro, valores, pedido do site, respostas
  services/                conversa, transições, despacho, handoff, autenticação, retenção
  workers/outbox.py        fila de envio em segundo plano
  web/                     painel: rotas, textos, templates, CSS
  integrations/whatsapp/   contrato, gateway falso, gateway Cloud API, leitura do webhook
  repositories/            contrato (Database/Tx) + implementação SQL
  api/                     health, webhook da Meta e simulação
migrations/                Alembic
tests/                     312 testes sobre SQLite real; fixtures sintéticas
```

### Garantias

- **Transação única** por mensagem recebida: se algo falhar, nada é gravado e o reenvio do
  mesmo evento é processado normalmente.
- **Deduplicação** por ID do provedor (chave única) e **idempotência** das respostas por chave.
- **Versão otimista** da conversa e **reivindicação atômica** de cada resposta da fila: dois
  processos não enviam a mesma resposta.
- **Novas tentativas** só para falhas transitórias, com espera de 5 s, 10 s, 20 s, 40 s… (até
  5 tentativas). Resultado incerto (`unknown`) nunca é reenviado automaticamente; envio
  interrompido por queda vira `unknown` após 120 s.
- Antes de **cada tentativa**: pausa global, handoff (época da conversa) e janela de 24 h.

## Limitações conhecidas

- **Risco residual de envio**: resposta já em `sending` não pode ser cancelada; se a equipe
  assumir nesse instante, a mensagem em trânsito ainda chega ao cliente.
- O bloqueio de login por tentativas fica na memória do processo (zera ao reiniciar; com vários
  processos, cada um conta separadamente).
- A equipe ainda responde ao cliente pelo WhatsApp, não pelo painel. O painel mostra, organiza e
  controla a automação. Notificação de conversa nova (som/push) não existe ainda.
- Horários: uma janela por dia no painel (o modelo aceita mais, via `/dev/store-settings`).
- SQLite atende um único servidor. Para produção, propor PostgreSQL (mesmo esquema e
  migrações; falta só o driver `asyncpg` e testes nele).
- Parser baseado na mensagem de referência do `CLAUDE.md`; o código do site não foi inspecionado.
- Eco do app do celular (coexistência) implementado, mas só validável com o número real.
- Token temporário da Meta expira em ~24 h; token permanente (usuário do sistema) fica para a
  Etapa 5, no portfólio da loja.
- Processamento do webhook é síncrono (rápido, sem IA). Com IA (Etapa 4), passa para fila.
- Sem FAQ e sem IA (Etapa 4).
