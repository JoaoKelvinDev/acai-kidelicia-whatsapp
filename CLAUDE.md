# Açaí Ki-Delícia PL — Atendimento automático no WhatsApp

Documento de contexto e instruções para Claude Code ou outro agente de desenvolvimento.
Data de referência: 06/11/2026. Idioma do produto: português do Brasil.

## 1. Missão e forma de trabalhar

Desenvolver um assistente de atendimento para o WhatsApp do Açaí Ki-Delícia PL, aproveitando o site de pedidos existente. Trabalhar de forma incremental, com revisão do desenvolvedor João Kelvin.

Na primeira interação, antes de implementar:
1. Ler integralmente este arquivo e as instruções existentes no repositório.
2. Inspecionar o código disponível e identificar stack, estrutura, testes e geração da mensagem do WhatsApp. Se o repositório do site não estiver disponível, declarar essa limitação e planejar o backend independente.
3. Apresentar diagnóstico, arquitetura mínima, arquivos propostos, dependências, critérios de validação e dúvidas realmente bloqueantes.
4. Propor apenas a primeira etapa e aguardar aprovação do desenvolvedor para escrever código.

Depois da aprovação, implementar somente a etapa aprovada, verificar seu comportamento e apresentar resultado e próximo passo. Não criar uma plataforma genérica, múltiplos agentes ou uma arquitetura distribuída sem necessidade demonstrada. Não modificar produção nem conectar o número da loja durante o desenvolvimento inicial.

Este documento define requisitos; não afirma que o repositório, a conta Meta ou a elegibilidade do número já foram inspecionados.

## 2. Contexto confirmado

- Existe um E-commerce Web App do estabelecimento: https://acaikideliciapl.com.br.
- O cliente monta um ou mais açaís: recipiente/tamanho, base, cremes, sorvetes e adicionais.
- O produto é vendido por peso. O tamanho em ml não define peso nem preço final.
- O responsável monta, pesa e informa manualmente o valor final pelo WhatsApp.
- Há retirada e delivery. Retirada exige nome e telefone; delivery também exige endereço e ponto de referência.
- Pagamentos: Pix, cartão e dinheiro. Cartão na entrega utiliza maquininha. Não presumir como o Pix é operacionalizado; cadastrar a orientação fornecida pela loja.
- No delivery em dinheiro, coletar necessidade de troco e, se necessário, para qual valor.
- O site abre o WhatsApp com uma mensagem preenchida. O cliente precisa efetivamente enviá-la.
- A automação atende tanto pedidos do site quanto contatos diretos, como “Oi”.

Não presumir preço por kg, horário, limites de ingredientes, taxa geral de entrega, bairros atendidos, prazo de preparo, chave Pix ou disponibilidade de estoque. R$ 3,00 é a taxa do exemplo, não uma regra universal.

## 3. Escopo do MVP

### Incluído

- Receber mensagens individuais pela integração oficial do WhatsApp Business Platform.
- Reconhecer e extrair pedidos no formato atual do site.
- Validar estrutura e campos, pedir correções e manter contexto das respostas.
- Confirmar recebimento quando as condições configuradas permitirem.
- Explicar que o valor final será enviado pela equipe após montagem e pesagem.
- Atender saudações e dúvidas com base nas informações cadastradas.
- Direcionar novos pedidos ao site; montagem conversacional completa não faz parte do MVP.
- Encaminhar exceções para atendimento humano e pausar respostas automáticas.
- Oferecer um controle autenticado mínimo para assumir, pausar, retomar e encerrar conversas.
- Registrar estado e eventos suficientes para evitar reprocessamentos após reinício.

### Fora do MVP

- Calcular preço final, estimar peso ou integrar balança.
- Cobrar, confirmar Pix, interpretar comprovantes como pagamento ou integrar gateway.
- Prometer disponibilidade, entrega ou preparo sem informação registrada.
- Alterar ou cancelar pedidos automaticamente.
- Enviar campanhas ou prospecção.
- Criar um painel completo de cozinha, estoque, entregadores ou gestão financeira.
- Registrar pedidos no site antes do WhatsApp como pré-requisito: isso pode ser evolução posterior.

## 4. Mensagem real de referência

Os emojis abaixo foram normalizados para legibilidade; o parser não pode depender deles.

```text
Novo pedido - Açaí Ki-Delícia PL
Nome: Teste
Telefone: 00000000000
Modalidade: Delivery
Endereço: Teste
Ponto de referência: Teste
Taxa de Entrega: R$ 3.00
------------------------------
Pedido
• Quantidade: 1x
• Tamanho: Copo 500ml
• Base: Açaí Zero
• Cremes: Creme de Maracujá, Creme de Cupuaçu, Creme de Nutela, Creme de Ninho
• Sorvetes: Abacaxi, Prestígio, Babalu, Terremoto, Bombom Ferrero, Tapioca
• Adicionais: Leite Condensado, Côco Ralado, Amendoim
Pagamento: Pix
Obrigado!
```

O original pode conter asteriscos de formatação, emojis e caracteres de substituição “�”. Aceitar diferenças de espaços, quebras de linha e pontuação sem destruir nomes ou observações.

O exemplo é uma fixture inválida para atendimento real: telefone zerado e endereço “Teste”. Criar também fixtures sintéticas plausíveis. Não usar dados reais de clientes em testes.

## 5. Fluxos de atendimento

### A. Pedido vindo do site

1. Receber evento autêntico de mensagem e persistir com chave única.
2. Verificar estado da conversa antes de gerar qualquer resposta.
3. Reconhecer o pedido pela estrutura, não apenas por uma palavra ou emoji.
4. Extrair campos com parser determinístico e construir modelo validado.
5. Se faltar informação, registrar pendências e perguntar especificamente por elas.
6. Aplicar respostas subsequentes ao mesmo rascunho sem perder itens. Mudanças ambíguas ou de ingredientes exigem humano.
7. Verificar configuração de atendimento: aberto/fechado/pausado/desconhecido.
8. Com dados completos e atendimento habilitado, confirmar recebimento uma única vez.
9. Encaminhar à equipe e colocar a conversa em HUMAN_PENDING, suspendendo respostas automáticas posteriores até decisão explícita do responsável.
10. O responsável monta, pesa e informa o valor manualmente.

Texto de referência para confirmação, configurável:
“Recebemos seu pedido! A equipe dará sequência ao atendimento. O valor final será informado por aqui após a montagem e a pesagem. Se houver alguma indisponibilidade, entraremos em contato.”

Somente afirmar “entrou na fila de montagem” se houver regra operacional explícita autorizando essa afirmação. Nunca afirmar “está sendo montado” apenas porque a mensagem chegou.

Se fechado ou pausado, informar a condição e não confirmar montagem. Se horário ou disponibilidade de atendimento não estiverem configurados, encaminhar para conferência humana, sem inventar funcionamento.

### B. Cliente chega diretamente

1. “Oi” ou saudação: identificar o assistente virtual da loja, oferecer cardápio/link do site e ajuda.
2. Intenção de comprar: direcionar ao site, sem exigir nome ou endereço antes de haver necessidade.
3. Dúvida conhecida: responder exclusivamente com a base cadastrada.
4. Dúvida sem resposta: informar que a equipe verificará e encaminhar.
5. Pedido espontâneo em texto livre: direcionar ao site ou encaminhar ao humano; não aceitar silenciosamente uma montagem incompleta.
6. Quando chegar pedido estruturado durante a conversa, mudar para o fluxo A.

### C. Exceções e atendimento humano

- “Quero falar com alguém”, reclamação, cancelamento, alteração ou falta de entendimento: handoff imediato.
- Pergunta sobre andamento sem status confiável: encaminhar; não inferir a partir do tempo decorrido.
- Após duas tentativas sem resolver os dados pendentes, encaminhar para humano; limite configurável.
- Áudio, imagem, localização e documento: não fingir leitura; encaminhar ou solicitar texto conforme configuração. Não implementar transcrição no MVP.
- HUMAN_PENDING e HUMAN_ACTIVE bloqueiam novas respostas automáticas; mensagens continuam registradas e visíveis à equipe.
- Encerramento não apaga o histórico nem autoriza reabertura automática pelo bot; definir retomada explícita ou política aprovada.

## 6. Validação de pedidos

Separar campos ausentes, campos inválidos e condições que não podem ser verificadas.

| Campo | Regra |
|---|---|
| Nome | Não vazio; rejeitar placeholders óbvios sem inventar restrições de nomes |
| Telefone | Normalização BR configurável, formato plausível, rejeição de sequências fictícias; não afirmar titularidade |
| Modalidade | Enum retirada/delivery com aliases conhecidos |
| Endereço | Delivery: informações suficientes; aceitar “sem número”; dúvidas de localização vão ao humano |
| Referência | Exigida no delivery conforme regra atual; permitir configurar mudança futura |
| Itens | Pelo menos um, quantidade inteira positiva e tamanho reconhecido quando catálogo disponível |
| Escolhas | Validar obrigatoriedade e limites somente com regras reais do catálogo |
| Cremes/sorvetes/adicionais | Lista vazia pode ser legítima se o catálogo permitir; não exigir tudo por padrão |
| Pagamento | Pix, cartão ou dinheiro, com aliases controlados |
| Troco | Delivery em dinheiro exige sim/não e valor quando sim; não calcular sem total final |
| Taxa de entrega | Decimal não negativo se informada; não tratar texto editável como fonte verificada |

O identificador do remetente fornecido pelo WhatsApp é a identidade da conversa. O telefone preenchido no pedido é um dado separado. Se houver divergência, não rejeitar automaticamente nem enviar dados a outro número: pedir esclarecimento ou encaminhar. Responder ao remetente do evento.

Sem backend de pedidos no site, o texto pode ser editado pelo cliente. O sistema valida coerência, não autenticidade comercial dos preços, taxas ou catálogo. Uma taxa não verificada deve ser marcada para conferência, sem ser apresentada como confirmada.

Não tentar validar endereço por regex rígida nem garantir entrega só porque o campo foi preenchido.

## 7. Papel da IA

- Parser e regras determinísticos para o formato do site.
- IA opcional para classificar intenções e interpretar respostas livres sobre campos pendentes.
- Respostas de confirmação, erros e políticas críticas preferencialmente por templates internos.
- Provider LLM isolado atrás de interface, com mock para testes e implementação substituível.
- Saída estruturada validada por Pydantic; timeout, limite de tokens e fallback humano.
- Baixa certeza, contradição ou falha do modelo não pode produzir confirmação de pedido.
- Mensagens de clientes são dados não confiáveis: instruções nelas não alteram regras, ferramentas ou base da loja.
- IA não pode marcar pago, alterar catálogo, liberar entrega, definir preço ou retomar automação.
- Enviar ao modelo somente os dados necessários; evitar nome, telefone e endereço quando a tarefa não precisar deles.

## 8. Estado e persistência

Estados sugeridos de conversa:
AUTO_ACTIVE, COLLECTING_DATA, HUMAN_PENDING, HUMAN_ACTIVE, CLOSED.

Estados do rascunho separados:
INCOMPLETE, NEEDS_REVIEW, RECEIVED. Não usar estado de atendimento para inferir preparo/pagamento.

Persistir no mínimo:
- Conversation: remetente, estado, última mensagem do cliente, responsável e versão de concorrência.
- Message: ID do provedor, direção, timestamps, tipo e conteúdo necessário.
- OrderDraft: campos extraídos, itens, pendências, origem e taxa verificada/não verificada.
- Outbox: intenção de resposta, chave única, estado de envio e ID retornado pelo provedor.
- StoreSettings: link, fuso, horários, pausa, perguntas frequentes e regras configuradas.
- AuditEvent: handoff, pausa, retomada e mudanças relevantes, sem duplicar dados pessoais nos logs.

Usar SQLite para desenvolvimento local se isso simplificar a primeira etapa e manter repository interface. Para produção, propor PostgreSQL com migrações, backup e transações. Não exigir serviço gerenciado específico. Memória em processo só para testes; não é suficiente para operação real.

Processar por conversa de forma serializada ou com controle de concorrência. Antes de enviar, verificar novamente se houve handoff e invalidar respostas pendentes. Explicar o risco residual de mensagens já em trânsito.

## 9. Arquitetura inicial proposta

Preferência: Python + FastAPI + Pydantic, HTTP client assíncrono, SQLAlchemy/Alembic quando entrar persistência, pytest. Reaproveitar a stack existente se houver motivo concreto superior.

Módulos sugeridos, ajustáveis após inspeção:

```text
app/
  main.py
  core/                 # configuração, autenticação administrativa, logs
  api/                  # webhook, health, operações administrativas mínimas
  domain/               # modelos, estados, regras de validação
  services/             # orquestração, handoff, base da loja
  parsers/              # mensagem atual e respostas a pendências
  integrations/
    whatsapp/           # adapter oficial e adapter fake
    llm/                # interface, mock e provider opcional
  repositories/         # persistência e transações
  workers/              # processamento durável e outbox quando necessário
tests/
docs/
.env.example
README.md
```

Começar com um serviço e persistência simples; não adicionar Redis/Celery por hábito. A fila/outbox persistida pode ser suficiente no volume inicial; justificar qualquer tecnologia adicional.

## 10. Integração oficial com WhatsApp

### Produtos diferentes

WhatsApp Business App é o aplicativo utilizado no celular. WhatsApp Business Platform/Cloud API é a interface oficial para integrar o backend. O aplicativo sozinho não fornece toda a integração necessária para este projeto.

Caminho lógico: cliente envia mensagem → Meta envia webhook HTTPS → backend autentica e registra → processamento verifica regras/estado → backend envia resposta pela API → eventos de status atualizam registros.

### Preservar o número e o atendimento manual

Antes de cadastrar ou migrar o número atual, verificar na documentação vigente e no onboarding:
- Possibilidade de Coexistence para usar o Business App e a API no mesmo número.
- Elegibilidade da conta, região e fluxo de onboarding.
- Se integração direta suporta o fluxo necessário ou se exige um provedor oficial com suporte à coexistência.
- Eventos disponíveis para observar mensagens manuais, limitações de sincronização e dispositivos suportados.
- Custos e propriedade dos ativos Meta pela loja.

Não prometer coexistência automática, não remover o número do aplicativo e não orientar exclusão da conta como primeiro passo. Se coexistência não estiver disponível, apresentar opções: número de teste/separado ou atendimento humano em inbox conectado à API, com decisão do proprietário antes de mudar a operação.

### Handoff é requisito de produção

Sempre implementar um controle explícito autenticado “Assumir/Pausar/Retomar”. Se a modalidade de integração fornecer eventos de mensagens enviadas pelo dono, usá-los como sinal adicional de pausa e verificar seu comportamento em testes reais. Não pressupor que toda mensagem manual será observável.

Sem evento confiável, o dono deve pausar antes de responder pelo aplicativo; se isso for inviável na operação, usar uma inbox que centralize a conversa. A limitação deve ser documentada e resolvida no piloto.

### Configuração e requisitos técnicos

1. Criar ambiente Meta de desenvolvimento e utilizar número de teste antes do número real.
2. Identificar Business Portfolio, WABA e phone_number_id apropriados, mantendo a loja proprietária dos ativos de produção.
3. Configurar credenciais e permissões mínimas, distinguindo teste temporário de credencial adequada à operação.
4. Publicar endpoint HTTPS e configurar verificação GET do webhook.
5. Autenticar POST com assinatura conforme documentação vigente; no fluxo direto Meta, verificar X-Hub-Signature-256 sobre o corpo bruto usando App Secret. Verify token do GET não substitui assinatura do POST.
6. Assinar eventos necessários e testar mensagens recebidas, envio e status de falha/entrega.
7. Separar eventos de mensagem, status e ecos para não responder aos próprios envios.
8. Processar todos os elementos dos arrays de eventos, não somente o primeiro.
9. Responder ao webhook rapidamente após persistência durável; não esperar o LLM. Se persistência falhar, permitir retry do provedor.
10. Deduplicar por ID de mensagem com restrição única. Eventos de status exigem sua própria chave de idempotência; não descartá-los só porque o ID da mensagem já existe.
11. Usar outbox e retries com backoff para falhas transitórias; tratar rate limits. Timeout de envio pode ser resultado desconhecido: não prometer exactly-once nem reenviar cegamente.
12. Revalidar janela de atendimento e estado de pausa antes de enviar respostas pendentes.

Respeitar a janela de atendimento de 24 horas após a última mensagem do cliente; fora dela, não enviar texto livre pela API. Templates aprovados só quando configurados e aplicáveis. Não incluir campanhas no projeto. Verificar preços vigentes; não assumir gratuidade universal.

Variáveis sugeridas, sem valores reais no repositório:
APP_ENV, DATABASE_URL, WHATSAPP_ACCESS_TOKEN, WHATSAPP_PHONE_NUMBER_ID,
WHATSAPP_APP_SECRET, WHATSAPP_VERIFY_TOKEN, META_GRAPH_API_VERSION,
LLM_API_KEY, LLM_MODEL, STORE_TIMEZONE, STORE_WEBSITE_URL.

Versão da API deve ser definida com base na documentação vigente e ser configurável. Se um provedor oficial for escolhido, adaptar assinatura, credenciais e contratos ao provedor sem fingir que são idênticos aos da integração direta.

Não usar automação de WhatsApp Web ou bibliotecas que simulam sessão como base deste projeto.

## 11. Dados e segurança operacional

- Nenhuma credencial, telefone real ou endereço de cliente em commits e fixtures.
- .env ignorado; .env.example só com placeholders.
- Logs com IDs e dados pessoais minimizados/mascarados.
- Controles administrativos autenticados, com autorização e auditoria.
- Definir retenção e acesso antes do piloto, sem armazenamento indefinido por padrão.
- Pausa global da automação disponível para falhas e manutenção.
- CORS não substitui autenticação; configuração de loja e handoff não podem ser endpoints públicos desprotegidos.

## 12. Etapas e entregáveis

### Etapa 0 — Diagnóstico e plano
Inspecionar repositório, listar lacunas, propor primeira entrega e aguardar aprovação. Identificar se o dono precisa continuar no aplicativo e tratar coexistência como investigação pendente, sem bloquear código local.

### Etapa 1 — Núcleo local com simulação
FastAPI base, modelos, parser do formato atual, validação, estado de conversa, provider fake e testes. Sem credenciais externas, LLM real, banco remoto ou alteração do site de produção. Não expor endpoint de simulação em produção.

### Etapa 2 — Estado durável e controle humano
Persistência local, migrações, idempotência, outbox, controles autenticados mínimos e testes de concorrência/retomada. Não construir dashboard extenso; interface mínima responsiva se necessária à operação.

### Etapa 3 — API oficial em ambiente de teste
Webhook verificado e autenticado, envio real para destinatários de teste autorizados, status e falhas, documentação de configuração. Validar rota do número de produção em paralelo, sem migrá-lo automaticamente.

### Etapa 4 — Atendimento geral e IA limitada
FAQ configurada, saudações, direcionamento ao site, interpretação de respostas livres e fallback. IA não é requisito para parser nem confirmação. Medir chamadas, latência, custo e erros antes de ampliar escopo.

### Etapa 5 — Piloto controlado
Conectar número de produção somente após validação do onboarding e decisão do proprietário. Confirmar configuração da loja, handoff real, privacidade, monitoramento, backup e pausa global. Começar em modo observação ou aprovação manual de respostas e liberar automação gradualmente.

## 13. Critérios de aceitação essenciais

- Pedido delivery válido e loja habilitada: uma confirmação de recebimento, sem preço final ou promessa de preparo iniciado.
- Exemplo “Teste/00000000000”: pedir correção, não confirmar montagem.
- Retirada válida: não pedir endereço.
- Delivery em dinheiro sem troco: perguntar necessidade de troco; sem total, não calcular.
- Pix: não pedir troco nem afirmar pagamento recebido.
- Mensagem sem emojis, com asteriscos, “�”, CRLF ou taxa com ponto/vírgula: parser tolerante sem corromper os itens.
- Dois itens: manter escolhas e quantidades separadas; ambiguidade provoca revisão humana.
- Resposta a campo pendente: atualizar o rascunho existente, sem criar pedido novo.
- “Oi”: oferecer ajuda e link configurado sem inventar informações da loja.
- Loja fechada/pausada/desconhecida: não confirmar fila de montagem.
- Pedido de status sem registro operacional: encaminhar ao humano.
- Evento repetido e processamento concorrente: não gerar duas intenções de confirmação para a mesma mensagem.
- Duas mensagens iguais com IDs distintos podem ser dois pedidos; não descartar automaticamente por igualdade de texto. Sinalizar possível duplicação para conferência quando apropriado.
- HUMAN_PENDING/HUMAN_ACTIVE ou pausa global: nenhuma nova resposta automática; manter recebimento dos eventos.
- Handoff durante resposta pendente: cancelar envio ainda não iniciado.
- Eventos de status/eco: não criar loops.
- Assinatura inválida: rejeitar antes de processar conteúdo.
- Reinício: preservar pendências, pausa e IDs processados.
- Timeout/saída inválida do LLM: fallback sem confirmação indevida.
- Após 24 horas: bloquear texto livre pela API; não simular envio bem-sucedido.

## 14. Ajustes opcionais no site

Propor em entrega separada: número de pedido, numeração de itens, aviso de cobrança por peso, formatação monetária BR e campos de troco. Identificador no texto facilita referência, mas não autentica conteúdo nem substitui idempotência por ID do WhatsApp.

Evolução posterior: registrar pedido no backend antes de abrir WhatsApp e usar identificador consultável. Essa evolução melhora integridade de itens e taxas, mas não é exigência para iniciar o MVP atual.

## 15. Questões a confirmar antes do piloto

- Conta/número atual e necessidade de continuar atendendo no aplicativo.
- Rota de coexistência e provedor, se necessário.
- Horários, fuso, atendimento pausado, regiões e taxas de entrega.
- Preço por kg e cobranças separadas, para informação correta ao cliente; não para cálculo automático do MVP.
- Limites e obrigatoriedade das escolhas do catálogo.
- Regra comercial de autorização da montagem antes do valor final.
- Como a equipe será avisada e assumirá conversas no dia a dia.
- Orçamento operacional: hospedagem, banco, mensagens/provedor e IA.

Não bloquear diagnóstico, parser e testes por informações que podem permanecer configuráveis. Não inventar respostas.

## 16. Referências para verificação na implementação

- Central oficial: https://whatsappbusiness.com/pt-br/developers/developer-hub/
- Cloud API: https://developers.facebook.com/docs/whatsapp/cloud-api/overview/
- Onboarding de usuários do Business App: https://developers.facebook.com/docs/whatsapp/embedded-signup/custom-flows/onboarding-business-app-users/
- Política: https://business.whatsapp.com/policy
- Preços: https://business.whatsapp.com/products/platform-pricing

Documentação e fluxos da Meta mudam. Reconsultar antes de onboarding, escolha da versão e produção. Se a página estiver indisponível, informar o limite da verificação e não concluir elegibilidade sem evidência.

## 17. Primeira resposta esperada do Claude

Entregar diagnóstico do repositório, arquitetura da primeira etapa, lista de arquivos com responsabilidades, dependências, plano de testes e dúvidas bloqueantes. Não implementar tudo de uma vez. Aguardar aprovação da Etapa 1.
