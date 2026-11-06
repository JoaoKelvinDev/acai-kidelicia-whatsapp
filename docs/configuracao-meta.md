# Configuração da Meta (ambiente de teste)

Guia para ligar o sistema à **WhatsApp Cloud API com o número de teste da Meta**. Nada aqui
envolve o número da loja nem cobrança. As telas da Meta mudam com frequência: se um nome
estiver diferente, procure o equivalente.

## Regras

- **Não cadastrar forma de pagamento.** Se alguma tela pedir cartão, pare.
- **Não cadastrar número real** como remetente. Só o número de teste da Meta.
- **Segredos só no `.env`**: nunca em chat, e-mail, print, commit ou issue.
- App fica **"Não publicado"**. Não publicar, não pedir verificação da empresa nesta etapa.

## O que já foi feito (06/11/2026)

- App **"Acai Kidelicia Teste"** criado no portfólio **"Joao Kelvin Dev"**, caso de uso
  "Conectar-se com os clientes pelo WhatsApp", tipo **Integrar com API**.
- **Etapa 1. Experimente** concluída: número de teste da Meta criado e celular do
  desenvolvedor cadastrado como destinatário.
- **Pendência:** o envio de teste falhou com **erro 131031** (conta restrita). Ver
  "Erro 131031" abaixo. Sem resolver isso, a Meta não entrega mensagens.

## Resultado da sessão de teste (06/11/2026, portfólio do desenvolvedor)

| Verificação | Resultado |
|---|---|
| Verificação do webhook (GET) pela Meta | OK |
| Mensagem real do celular → webhook assinado → gravada e classificada | OK |
| Identificador `user_id` (`BR.…`) recebido e gravado | OK |
| Pausar / Assumir no painel bloqueia resposta automática (mensagens reais) | OK |
| Envio da resposta aceito pela API (ID retornado) | OK, após corrigir o formato do número |
| Status de entrega recebido e exibido no painel | OK (status `failed`) |
| **Entrega da resposta no celular** | **Não**: erro 131031, conta restrita |

Diagnóstico da restrição (consulta `health_status`, só leitura): perfil da empresa incompleto
(131000), empresa não verificada (141010) e problema de forma de pagamento (141006). Decidido
**não** regularizar o portfólio pessoal: a validação final será feita no **portfólio da loja**.

Lições aplicadas no código ou neste guia:
- O `wa_id` de números BR pode chegar **sem o nono dígito**; a lista de destinatários de teste da
  Meta compara o formato exato (erro **131030**). Com lista, o sistema envia no formato da lista.
- São **duas assinaturas**, ambas necessárias para receber mensagens:
  1. campo `messages` do webhook do app (`POST /{app-id}/subscriptions`);
  2. app assinado na conta WhatsApp (`POST /{waba-id}/subscribed_apps`).
  O "Assinar" do painel da Meta não ficou salvo na primeira tentativa; conferir sempre com
  `GET /{app-id}/subscriptions` (campos não podem estar vazios).
- O log de acesso gravava o token de verificação na URL; agora é mascarado.
- Ordem das mensagens no painel usa o relógio do servidor (o horário da Meta é arredondado).

## Valores que vão no `.env`

| Variável | Onde encontrar | Segredo? |
|---|---|---|
| `WHATSAPP_PHONE_NUMBER_ID` | WhatsApp → Etapa 1. Experimente → *Phone Number ID* | Não |
| `WHATSAPP_ACCESS_TOKEN` | Mesma tela → *Token de acesso* (temporário, ~24 h) | **Sim** |
| `WHATSAPP_APP_SECRET` | Configurações do app → Básico → *Chave secreta do app* → Mostrar | **Sim** |
| `WHATSAPP_VERIFY_TOKEN` | Você inventa (comando abaixo) e cadastra o mesmo valor na Meta | **Sim** |
| `META_GRAPH_API_VERSION` | Versão mostrada no exemplo de `curl` da tela (hoje `v25.0`) | Não |
| `WHATSAPP_ALLOWED_RECIPIENTS` | Seu celular, só dígitos com 55 + DDD | Não |

Gerar um token de verificação aleatório:

```bash
uv run python -c "import secrets; print(secrets.token_urlsafe(32))"
```

O token temporário expira em cerca de 24 horas. Para uso contínuo (piloto), será preciso um
token de **usuário do sistema** no portfólio da loja; isso fica para a Etapa 5.

## Configurar o webhook

Só com o servidor e o túnel rodando (ver [teste-com-tunel.md](teste-com-tunel.md)).

1. No app: **WhatsApp → Configuração** (ou *Configuration*) → **Webhook** → **Editar**.
2. **URL de callback:** `https://<endereço-do-túnel>/webhook/whatsapp`
3. **Token de verificação:** o mesmo valor de `WHATSAPP_VERIFY_TOKEN`.
4. **Verificar e salvar.** A Meta faz uma chamada GET; o sistema só responde se o token bater.
5. Em **Campos do webhook**, assinar **somente `messages`**.

## Erro 131031 (conta restrita)

No teste de 06/11/2026 o webhook mostrou `status: failed`, código **131031**. Segundo a
documentação de erros da Cloud API, a conta do WhatsApp Business está **restrita ou desativada
por violação de política**, ou os dados da requisição não conferem com a conta.

Passos (gratuitos):
1. Aguardar alguns minutos e reenviar o modelo de teste uma vez (contas novas levam um tempo
   para registrar o número de teste).
2. Se persistir: em business.facebook.com, abrir o **Gerenciador do WhatsApp** e a
   **Qualidade da conta** e procurar avisos de restrição no portfólio ou no perfil.
3. Não criar contas/portfólios novos para contornar. Se houver restrição, usar o pedido de
   análise oferecido pela própria Meta.

Referência: https://developers.facebook.com/docs/whatsapp/cloud-api/support/error-codes/
