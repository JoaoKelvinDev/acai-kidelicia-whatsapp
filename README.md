# Açaí Ki-Delícia PL — atendimento automático no WhatsApp

Backend de atendimento para o WhatsApp da loja. Requisitos completos em [`CLAUDE.md`](CLAUDE.md).

**Situação: Etapa 1 — núcleo local com simulação.** Sem credenciais, sem rede, sem banco remoto,
sem LLM e sem alteração no site. Nada aqui conversa com a Meta ainda.

## Como rodar

Requisitos: Python 3.12+ e [uv](https://docs.astral.sh/uv/).

```bash
uv sync                      # instala dependências
cp .env.example .env         # APP_ENV=local habilita as rotas /dev
uv run pytest                # testes
uv run ruff check . && uv run ruff format --check .
uv run uvicorn app.main:create_app --factory --reload
```

Com `APP_ENV=local`, a documentação interativa fica em `http://localhost:8000/docs`.

### Simular uma mensagem

```bash
curl -X POST localhost:8000/dev/simulate/inbound \
  -H "Content-Type: application/json" \
  -d '{"from": "5511974123058", "text": "Oi"}'
```

Rotas de simulação (somente `APP_ENV=local`/`test`; inexistentes em qualquer outro ambiente):

| Rota | Uso |
|---|---|
| `POST /dev/simulate/inbound` | Mensagem recebida (`from`, `text`, `type`, `message_id` opcional) |
| `GET /dev/conversations/{id}` | Estado, mensagens, rascunhos, respostas e auditoria |
| `POST /dev/conversations/{id}/{take_over\|pause\|resume\|close}` | Controle humano (`{"actor": "..."}`) |
| `POST /dev/automation-pause` | Pausa global (`{"paused": true, "actor": "..."}`) |
| `GET/PUT /dev/store-settings` | Configuração da loja (status, horários, textos, limites) |
| `GET /dev/sent` | Mensagens "enviadas" pelo gateway falso |

A loja começa com status **desconhecido**: pedidos completos vão para conferência humana, sem
confirmação, até que `status_override` ou `opening_hours` sejam configurados.

## Arquitetura

```
mensagem → ConversationService (lock por conversa, dedupe por ID do provedor)
         → estado da conversa / pausa global → intenção (determinística)
         → parser + validação → rascunho → intenções de resposta (OutboundIntent)
         → Dispatcher: revalida pausa, época de handoff e janela de 24 h → gateway
```

```
app/
  main.py                  create_app(); rotas /dev só em local/test
  core/                    config, relógio injetável, logs mascarados, container
  domain/                  enums, modelos, configuração da loja, telefone, validação
  parsers/                 normalização, dinheiro, valores, pedido do site, respostas a pendências
  services/                intenções, respostas, orquestração, transições, despacho, handoff
  integrations/whatsapp/   contrato do gateway + gateway falso
  repositories/            contrato + implementação em memória
  api/                     health e simulação
tests/                     202 testes; fixtures sintéticas em tests/fixtures/orders
```

### Regras principais

- **Pedido do site** reconhecido por estrutura (rótulos), tolerante a emojis, asteriscos, `�`,
  CRLF e taxa com ponto ou vírgula. Rótulos desconhecidos e linhas soltas não são descartados:
  levam o pedido à conferência humana.
- **Validação** separa: campos de cadastro ausentes/inválidos (perguntados ao cliente), problemas
  de itens/estrutura (equipe) e notas não verificáveis (taxa sempre "não verificada", telefone
  diferente do remetente).
- **Confirmação** só com dados completos e loja **aberta**, uma vez por mensagem, sem preço e sem
  dizer que o açaí está sendo montado. Em seguida a conversa vai para `HUMAN_PENDING`.
- **Respostas a pendências** atualizam o mesmo rascunho. Após 2 tentativas sem progresso
  (configurável), handoff. Alterar itens exige humano.
- **Handoff imediato**: pedido de atendente, cancelamento/alteração, reclamação, pergunta de
  status, dúvida sem resposta, mídia (padrão).
- `HUMAN_PENDING`, `HUMAN_ACTIVE`, `CLOSED` e pausa global: nenhuma resposta automática; as
  mensagens continuam registradas. Conversa encerrada não é reaberta pelo bot.
- **Época de respostas**: todo handoff/retomada/encerramento avança a época da conversa e cancela
  respostas pendentes; o Dispatcher confere a época de novo no momento do envio.

## Limitações conhecidas da Etapa 1

- **Memória em processo**: reinício perde tudo. Persistência durável, migrações e outbox com
  retries entram na Etapa 2.
- Se o processamento falhar depois de gravar a mensagem, um reenvio do mesmo evento é tratado
  como duplicado. Na Etapa 2 a gravação e o processamento ficam na mesma transação.
- **Risco residual de envio**: uma resposta já marcada `sending` não pode ser cancelada; se a
  equipe assumir nesse instante, a mensagem em trânsito ainda chega ao cliente.
- Falhas de envio ficam registradas (`failed`/`unknown`) sem retry automático; `unknown` nunca é
  reenviado às cegas.
- Controles humanos ainda **sem autenticação** — por isso só existem nas rotas `/dev`.
- Parser baseado na mensagem de referência do `CLAUDE.md`; o código do site não foi inspecionado.
- Sem webhook real, sem verificação de assinatura, sem FAQ e sem IA (Etapas 3 e 4).
