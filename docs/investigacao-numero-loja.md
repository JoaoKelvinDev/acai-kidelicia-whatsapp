# Investigação: como o número da loja pode ir para a API (antes da Etapa 5)

Nada aqui deve ser executado agora. É o checklist para decidir, com o proprietário, como
conectar o número real **sem perder o atendimento pelo celular**.

## Perguntas ao proprietário

- [ ] O número hoje usa **WhatsApp Business App** ou WhatsApp comum?
- [ ] A equipe precisa continuar respondendo **pelo celular**?
- [ ] Quantas pessoas atendem e em quais aparelhos?
- [ ] Existe portfólio empresarial da loja na Meta? Quem é o administrador?
- [ ] Há documentos para a verificação da empresa (CNPJ etc.)?

## Coexistência (Business App + API no mesmo número)

Informações de integradores (não confirmadas na documentação da Meta; reconferir antes):
- Exige versão recente do Business App, país suportado, empresa verificada no portfólio e
  webhooks ativos com a Cloud API.
- Fluxo: o número existente é informado, a Meta envia um código, a conexão é confirmada no app;
  compartilhar histórico e contatos é opcional; há uma janela de ~24 h para sincronizar.
- Limitações relatadas: grupos, listas de transmissão, status, chamadas e mensagens
  temporárias não passam pela API. Desconectar é feito pelo app.
- Mensagens enviadas pelo app chegariam como `smb_message_echoes`. O sistema já trata esse
  evento pausando a automação da conversa — **comportamento a validar com evento real**.

Checklist de verificação (documentação oficial vigente):
- [ ] Coexistência disponível para conta/região/número da loja?
- [ ] Integração direta suporta o fluxo ou exige provedor oficial (BSP)?
- [ ] Quais eventos chegam para mensagens manuais e com que atraso?
- [ ] Dispositivos suportados (celular principal, aparelhos vinculados, WhatsApp Web)?
- [ ] Custos por conversa/mensagem vigentes no Brasil.
- [ ] Ativos (portfólio, WABA, número) ficam **no nome da loja**.

## Se a coexistência não estiver disponível

Opções para decisão do proprietário (nunca remover o número do app como primeiro passo):
1. **Número separado** para o atendimento automático; o número atual segue no app.
2. **Caixa de entrada conectada à API** (o painel pode evoluir para isso): a equipe deixa de
   responder pelo app.

## Fontes consultadas (06/11/2026)

- https://developers.facebook.com/docs/whatsapp/embedded-signup/custom-flows/onboarding-business-app-users/
- https://docs.360dialog.com/docs/waba-management/embedded-signup/whatsapp-coexistence/coexistence-webhooks
- https://docs.jelou.ai/pt/connect/pre-requisitos/coexistencia.md
