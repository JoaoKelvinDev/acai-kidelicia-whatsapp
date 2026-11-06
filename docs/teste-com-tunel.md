# Sessão de teste com túnel (segura e temporária)

Objetivo: validar com o celular do desenvolvedor que mensagens chegam, são respondidas e têm o
status atualizado. O túnel fica aberto **só durante a sessão** e tudo é desativado no fim.

## Proteções ativas durante a sessão

| Proteção | Como |
|---|---|
| Sem rotas sem login | `APP_ENV=staging` desliga `/dev` e `/docs`. O sistema **recusa** `cloud` com `local` |
| Painel invisível pela internet | `ADMIN_ALLOWED_HOSTS=localhost,127.0.0.1`: pelo túnel, `/admin` responde 404 |
| Só o seu celular recebe | `WHATSAPP_ALLOWED_RECIPIENTS`: qualquer outro número é bloqueado antes de chegar à Meta |
| Só a Meta entra no webhook | Assinatura `X-Hub-Signature-256` conferida com o App Secret antes de ler o conteúdo |
| Segredos fora do código | Só no `.env` (ignorado pelo git) |
| Banco separado | `DATABASE_URL` aponta para `data/teste-meta.db`, descartável |

## Preparação (uma vez)

```bash
winget install --id Cloudflare.cloudflared      # pedir permissão antes
```

`.env` da sessão (preencher os segredos direto no arquivo):

```ini
APP_ENV=staging
DATABASE_URL=sqlite+aiosqlite:///./data/teste-meta.db
SESSION_COOKIE_SECURE=false
ADMIN_ALLOWED_HOSTS=localhost,127.0.0.1
WHATSAPP_GATEWAY=cloud
WHATSAPP_PHONE_NUMBER_ID=...
WHATSAPP_ACCESS_TOKEN=...
WHATSAPP_APP_SECRET=...
WHATSAPP_VERIFY_TOKEN=...
META_GRAPH_API_VERSION=v25.0
WHATSAPP_ALLOWED_RECIPIENTS=55DDDNUMERO
```

```bash
uv run python -m app.cli migrate
uv run python -m app.cli create-operator --username joao --role admin
```

## Sessão

**Antes de começar, pare qualquer servidor do projeto que já esteja rodando** (ex.: um
`uvicorn --reload` iniciado pelo README). Com `--reload`, ele relê o `.env` a cada mudança de
código e passaria a usar a configuração e os segredos da sessão (ocorrido em 06/11/2026).

Terminal 1 — servidor (só escuta no próprio PC):

```bash
uv run uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000
```

Terminal 2 — túnel:

```bash
cloudflared tunnel --url http://127.0.0.1:8000
```

Copiar o endereço `https://….trycloudflare.com` e configurar o webhook na Meta. Conferir as
**duas assinaturas** (campo `messages` e app na conta WhatsApp); ver lições em
([configuracao-meta.md](configuracao-meta.md)). No painel (`http://localhost:8000/admin`),
definir a loja como **aberta** em Configurações.

Roteiro de validação:
1. Do celular, mandar **"Oi"** para o número de teste → receber a saudação.
2. Colar uma **mensagem de pedido do site** → receber a confirmação.
3. Mandar um **áudio** → receber o aviso e ver a conversa em "Aguardando equipe".
4. No painel, ver as mensagens e o status **entregue/lida** das respostas.
5. Clicar **Assumir** e mandar outra mensagem → o assistente **não** responde.

## Desativação (fazer sempre ao terminar)

- [ ] Na Meta, enquanto o token ainda está no `.env`: remover o webhook do app
      (`DELETE /{app-id}/subscriptions?object=whatsapp_business_account`) e a assinatura do app
      na conta (`DELETE /{waba-id}/subscribed_apps`). Conferir que ficaram vazias.
- [ ] `Ctrl+C` no túnel e no servidor. No Windows, conferir que não sobrou processo filho
      (`python`/`uvicorn`) segurando a porta ou o banco; se sobrar, encerrar pelo Gerenciador de
      Tarefas.
- [ ] No `.env`: `WHATSAPP_GATEWAY=fake`, `APP_ENV=local`, e **apagar** os valores de
      `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_APP_SECRET` e `WHATSAPP_VERIFY_TOKEN`.
- [ ] Na Meta (opcional, mais seguro): Configurações do app → Básico → **Redefinir** a chave
      secreta do app, invalidando a que foi usada na sessão.
- [ ] O token temporário expira sozinho em ~24 h; não reutilizar.
- [ ] Apagar o banco descartável: `data/teste-meta.db*`.
- [ ] Desinstalar o túnel, se não for mais usar: `winget uninstall --id Cloudflare.cloudflared`
      (pode exigir terminal **como administrador**; erro 1603 = falta de permissão).

O endereço `trycloudflare.com` deixa de existir quando o túnel é fechado.
