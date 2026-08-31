# Fase E — decisões que ficam à espera do responsável

Escrito com o fecho da Fase E (30/08/2026, `HEAD` `7b3a4b2`, 600 testes verdes).
A Fase E entrega **ficheiros de infraestrutura, não infraestrutura**: nada foi
provisionado, nenhuma sessão foi autenticada em subscrição nenhuma, e nenhum
recurso existe na Azure por causa deste trabalho. O plano mestre pede
explicitamente confirmação do responsável antes de provisionar, e quem detém o
repositório é *Contributor* e não *Owner* — não pode sequer criar atribuições de
papel.

Este ficheiro está em português, e o guia de instalação
([`deployment.md`](deployment.md)) está em inglês, pelo mesmo critério que separa
o `README.md` das notas de `docs/evidence/`: o que se dirige a quem opera o
sistema é escrito em inglês; o registo interno do projecto, dirigido a quem
decide, é escrito em português.

As seis primeiras decisões vêm do plano mestre e estão aqui reverificadas contra
o estado real do código. As restantes apareceram ao escrever a infraestrutura.

---

## As seis do plano mestre

### 1. Que grupo de recursos e que região? Confirmar a subscrição antes de criar

**Por decidir.** Nada nos templates escolhe por si: `location` herda por omissão
a região do grupo de recursos, de propósito, para que a escolha se faça uma vez
— ao criar o grupo — e não fique escrita num repositório público.

O que a decisão precisa de ponderar: os dados são de parcelas em Portugal e as
origens (Copernicus, Climate Data Store, open-data do IPMA) são europeias, o que
aponta para uma região europeia por latência e por residência dos dados. A
escolha em si continua a ser de quem manda no projecto.

### 2. A API é privada ou tem área pública de demonstração? Que dados podem ser públicos?

**Por decidir.** Metade da urgência que esta decisão tinha era a decisão 7, e
essa foi tomada a 31/08/2026: as rotas de escrita já exigem chave. O que resta é
a pergunta que a chave não responde — **que dados podem ser lidos em público**.

Tal como os templates estão, a aplicação nasce com `ingress.external: true`, ou
seja, com um nome em HTTPS acessível a partir da internet. Isso foi escrito assim
porque uma área de demonstração é o objectivo declarado do projecto. Escrever
está fechado desde a decisão 7; ler está aberto, e é isso que falta decidir.

Três respostas possíveis, e cada uma pede trabalho diferente:

- **privada** — pôr `internal: true` e chegar por VPN ou Private Endpoint. É a
  única que não exige alterar código;
- **pública só de leitura** — é o que a aplicação já faz desde a decisão 7:
  ler é aberto, escrever pede chave. Falta decidir se os dados que se leem podem
  ser vistos por qualquer pessoa;
- **pública com autenticação também na leitura** — exige a proposta 3 da decisão
  7, identidade a sério, e não só a chave que lá foi implementada.

Sobre que dados podem ser públicos: as séries de satélite e de meteorologia vêm
de origens abertas. As leituras de campo e as geometrias das parcelas não são
nossas para publicar sem quem as cedeu dizer que sim.

### 3. Quem aprova as AOI e qual é a fonte oficial de cada polígono?

**Parcialmente respondida, com um risco novo por resolver.**

A parte do "quem aprova" está resolvida no schema: a base recusa uma AOI
`approved` sem `approved_by` preenchido, e recusa aprovar uma geometria ainda
marcada como provisória. O nome de quem aprova fica gravado na linha.

O que **não** está resolvido é onde vive a fonte oficial. Os dois polígonos
aprovados (`EUC-TUR-EO1` e `EUC-PTO-EO1`) existem em GeoJSON numa pasta local,
fora deste repositório — o que está certo, porque não devem ser públicos. Mas ao
verificá-la para esta fase encontrou-se o seguinte: **essa pasta não é um
repositório git, não tem remoto, e não tem cópia nenhuma.** Existe num só
computador.

Se esse disco morrer, os polígonos aprovados desaparecem. E não são
reconstrutíveis de memória: as condições de entrada da Fase B registam que a
posição e a rotação de `EUC-PTO-EO1` eram desconhecidas, e a forma como isso foi
resolvido vive apenas nesses ficheiros. Sem eles, qualquer série de satélite
gravada deixa de ser rastreável ao terreno que a originou.

**Decisão pedida:** onde passa a viver a fonte oficial das geometrias — um
repositório privado, um armazenamento com controlo de versões, ou outra coisa —
e quem responde por ela. Não é uma decisão de infraestrutura da Azure; é anterior
a ela.

### 4. Quem cria e guarda as credenciais do Copernicus, e que identidade tem acesso ao Key Vault?

**Metade respondida.** A credencial do Copernicus Data Space foi validada a
28/08/2026 e a do Climate Data Store é usada desde a Fase C, pelo que existem e
funcionam. O que continua por decidir é **quem responde por elas**: hoje vivem no
`.env` de uma máquina, e o `.env` está no `.gitignore` — o que impede o acidente
mas não constitui custódia.

A decisão 7 acrescentou uma quarta credencial a esta pergunta, e é a única que
**nasce connosco em vez de vir de fora**: a chave de escrita (`write-api-key` no
cofre) é gerada por quem faz o deployment, não é emitida por ninguém, e não há
onde a ir buscar outra vez se se perder — perdê-la é gerar outra e distribuí-la
a quem escreve. Quem responde por ela é a mesma pergunta, com a diferença de que
a resposta «ninguém» custa aqui uma rotação e não um pedido de recuperação.

A segunda metade da pergunta é a decisão 8, e não é separável dela: que
identidade tem acesso ao cofre depende de qual das duas variantes se adopta.

### 5. Que ambientes são precisos — dev, staging, produção?

**Por decidir.** Os templates aceitam um `environmentTag` e derivam dele todos os
nomes, pelo que criar um segundo ambiente é correr o mesmo deployment com outra
etiqueta, num grupo de recursos diferente. Nada nos ficheiros pressupõe que haja
só um.

O que a decisão custa: cada ambiente é uma base de dados a mais e um contentor
sempre ligado a mais, e são esses dois que dominam a factura (ver a estimativa
no guia). Um ambiente de desenvolvimento com `minReplicas: 0` custa
substancialmente menos e paga um arranque a frio no primeiro pedido.

### 6. Qual é o primeiro caso real a demonstrar, com fonte, métrica e critério de sucesso?

**Por decidir, e é a decisão que dá sentido a todas as outras.** Sem ela, esta
infraestrutura serve para pôr a API online e para mais nada — não há critério que
diga se o que ela mostra está certo.

O que já existe para lhe servir de base: 697 observações, de três proveniências
(campo, satélite, meteorologia), com a proveniência de cada valor gravada, e a
rota `/timeseries` capaz de as devolver lado a lado para o mesmo sítio e a mesma
métrica. O que não existe é uma afirmação verificável construída sobre isso.

---

## As que apareceram ao escrever a infraestrutura

### 7. ✅ DECIDIDA a 31/08/2026 — chave partilhada nas rotas de escrita

**Escolhida a proposta 2 das três abaixo, e implementada.** As oito rotas que
escrevem exigem um cabeçalho `X-API-Key` conferido contra `WRITE_API_KEY`; as
oito que leem, incluindo `/health`, continuam abertas. O código está em
`src/resoiltwin/api/auth.py` e os testes em `tests/test_api_auth.py`.

**O que fica escrito porque foi aceite, e não esquecido:** isto **não identifica
quem escreveu**. Todos os pedidos válidos são iguais entre si, e `approved_by`
continua a ser um campo de texto que o cliente preenche — uma aprovação continua
a poder dizer que foi feita por qualquer nome. O que muda é que deixa de a poder
fazer quem não tem a chave. O passo seguinte, se e quando fizer sentido, é a
proposta 3 (identidade a sério, Entra ID), e não é este.

Três escolhas dentro da decisão, com o argumento de cada uma:

- **A chave não tem valor por omissão** — como o `DATABASE_URL`, e pela mesma
  razão: um valor por omissão num repositório público é a mesma chave em todas
  as instalações, isto é, uma fechadura pintada.
- **Mas, ao contrário do `DATABASE_URL`, a falta dela não impede o arranque.** O
  `DATABASE_URL` é preciso nas dezasseis rotas e sem ele não há nada para
  servir; a chave é precisa em oito. Recusar arrancar por causa dela partia quem
  só quer ler — e, pior, empurrava quem tem pressa a inventar um valor só para
  arrancar, que é o valor por omissão outra vez, agora por outra via. Sem chave
  configurada, **as rotas de escrita fecham** (503) e as de leitura continuam a
  funcionar. A falha perigosa seria a simétrica — «não há chave, portanto deixa
  passar» — e é essa que a guarda existe para impedir.
- **Sem cabeçalho e com cabeçalho errado dão exactamente a mesma resposta** (401,
  o mesmo corpo, os mesmos cabeçalhos). São coisas diferentes para quem depura,
  e por isso a diferença vai para o registo do servidor, que quem ataca não vê.
  Se fossem duas respostas distintas, um pedido bastava para confirmar que uma
  chave adivinhada tem o formato certo. A comparação é `hmac.compare_digest` e
  nunca `==`, porque um `==` para no primeiro byte diferente e a diferença de
  tempo reconstrói a chave prefixo a prefixo.

O segredo chama-se `write-api-key` no cofre e chega à aplicação como os outros
(`infra/modules/app.bicep`, passo 4 e passo 7 de [`deployment.md`](deployment.md)).
O passo 9 do guia verifica-o das duas maneiras: sem cabeçalho tem de dar 401, e
com a chave tem de passar a guarda.

**O que isto não decide.** A decisão 2 continua aberta: a chave impede que um
desconhecido *escreva*, e não responde à pergunta de que dados podem ser
*lidos* em público. As séries de satélite e de meteorologia vêm de origens
abertas; as leituras de campo e as geometrias das parcelas não são nossas para
publicar.

<details>
<summary>As três propostas como estavam antes da decisão</summary>

Nenhuma das dezasseis rotas da aplicacao exigia credencial. As dependências de
`Depends()` que existiam serviam a sessão da base de dados e os clientes
externos; não havia nenhuma que autenticasse nem autorizasse.

Isso foi aceite enquanto a API só corria em `localhost`. **Publicar em Container
Apps deixava de o ser**: passava a haver um nome em HTTPS, alcançável por
qualquer pessoa, onde um `POST /api/v1/observations` sem credencial escrevia uma
linha na base, e um `POST /api/v1/aois/{code}/approve` aprovava uma AOI em nome
de quem o pedido dissesse que era.

1. **Não publicar até haver decisão.** Pôr `internal: true` no ambiente e chegar
   por rede privada. Custo: zero linhas de código.
2. **Uma chave partilhada nas rotas de escrita.** Uma dependência do FastAPI que
   exija um cabeçalho conferido contra um segredo do cofre, deixando as de
   leitura abertas. Não identifica quem escreveu — só impede quem não tem a
   chave. **← escolhida.**
3. **Identidade a sério.** Microsoft Entra ID à frente do Container App, com os
   pedidos a chegarem já autenticados. Passa a haver um utilizador real por
   detrás de cada `approved_by`. É a resposta certa e é a mais cara.

O que **não** se devia fazer era publicar e adiar: uma linha escrita por um
desconhecido numa base que se apresenta como rastreável é pior do que a base não
existir, porque a proveniência passa a mentir.

</details>

### 8. Aceitar a dívida da identidade gerida, ou pedir a quem tem Owner que corra um ficheiro?

Esta é a decisão que a nota da Fase B já tinha declarado, e continua a precisar
de resposta explícita.

**Em uma frase:** a variante correcta — a aplicação lê os segredos do Key Vault
em execução, através de uma identidade gerida, sem que nenhuma credencial passe
pelo deployment — exige atribuir dois papéis (*Key Vault Secrets User* e
*AcrPull*), e criar atribuições de papel está fora do alcance de um
*Contributor*; a alternativa que um *Contributor* consegue correr até ao fim
guarda os segredos em políticas de acesso e entrega-os à aplicação no momento do
deployment, o que significa uma cópia de cada segredo fora do cofre, uma
credencial administrativa do registo que ninguém roda, e uma rotação que obriga a
refazer o deployment.

A parte privilegiada está isolada em `infra/role-assignments.bicep`, um ficheiro
que corre em dois minutos e não faz mais nada. **A decisão é entre pedir a quem
tem Owner que corra esse ficheiro uma vez, ou assumir a dívida por escrito.**
Pedir custa dois minutos do tempo de uma pessoa; assumir custa uma superfície de
credenciais que fica connosco.

### 9. Com que utilizador da base de dados é que a API corre?

Tal como está, a mesma credencial administrativa serve as migrações e a API.

Para as migrações **não há alternativa**: o PostGIS é uma extensão *untrusted* e
o `CREATE EXTENSION` da migração `0001` exige pertença ao papel
`azure_pg_admin`, que só o login administrativo tem.

Para a API não há nenhuma razão. Ela lê e escreve linhas; não cria extensões nem
altera o schema. Correr com privilégios administrativos significa que um defeito
numa rota tem alcance de administrador — incluindo `DROP TABLE`.

Criar um papel com menos privilégios é um passo de SQL, e um template de
infraestrutura não corre SQL. Fica por decidir se se faz, e quando. **Decisão:**
aceitar que a API corra como administrador nesta fase, ou acrescentar um passo
manual ao guia que crie o papel restrito e um segundo segredo no cofre.

### 10. Nada agenda a ingestão, e um pedido longo é cortado a meio

Duas coisas relacionadas, ambas visíveis assim que o sistema sai do portátil.

**Nada corre as sincronizações num relógio.** A série das estações do IPMA não
tem histórico anterior ao dia em que a sincronização correr pela primeira vez —
o open-data publica as últimas 24 horas e não guarda arquivo. Sem um agendador,
essa série terá buracos permanentes, e cada dia que passa é um dia perdido para
sempre. O código já prevê isto: o comentário no topo de `api/jobs.py` diz que a
fase que agendar a ingestão é a que deve trazer o comando de linha, e que ele
pode chamar a rota que já existe.

**E um pedido de sincronização longo é desligado antes de acabar.** O cliente do
Climate Data Store sonda com um tecto de 900 segundos, e o *ingress* dos
Container Apps desliga um pedido inactivo ao fim de 4 minutos por omissão.
Subir esse limite (até 30 minutos) exige o modo *premium ingress* do ambiente,
que não é o modo por omissão. O trabalho do lado do servidor continua e as
linhas são escritas na mesma; é o cliente HTTP que é largado, e quem só olhar
para a resposta conclui que falhou quando não falhou.

**Decisão:** se as sincronizações passam a ser assíncronas de verdade — a rota
devolve o job e o trabalho corre num Container Apps Job agendado — ou se se sobe
o limite do *ingress* e se vive com pedidos de vários minutos. A primeira é a
resposta certa e resolve as duas metades de uma vez.

### 11. Que retenção de backups, sabendo que parte dos dados não é recuperável?

Os templates ficam com 7 dias, que é o mínimo do serviço, e sem redundância
geográfica.

Isso merece ser decidido e não herdado, porque **nem todos os dados são
reproduzíveis**. Das 697 observações da base actual, 139 são reconstrutíveis por
`scripts/restore_dev_data.py` e a reanálise volta a poder ser transferida. A
série das estações **não**: o feed publica 24 horas e não guarda arquivo, pelo
que as linhas que já foram gravadas são a única cópia que existe no mundo.
Perdê-las é perdê-las.

**Decisão:** 7 dias e sem redundância geográfica chegam, ou a série de estações
justifica retenção maior e uma segunda região? A segunda opção custa dinheiro
todos os meses.

### 12. Quem responde pela factura, e a partir de que valor é que alguém é avisado?

Nada nos templates cria um orçamento nem um alerta de custo, porque não sei a
que subscrição isto se destina nem quem a paga.

A estimativa do guia é de ordem de grandeza — não consultei preços em tempo real
e não invento números — e o que a domina são duas linhas: **o contentor sempre
ligado e a base de dados**. Tudo o resto é arredondamento.

**Decisão:** qual é o tecto mensal aceitável, e quem recebe o alerta quando ele
for atingido. Um alerta de orçamento leva minutos a criar e é a única coisa que
transforma "deve custar umas dezenas de euros" numa afirmação com consequência.

### 13. O Application Insights fica vazio até alguém instrumentar a aplicação

O recurso é criado e a ligação ao workspace está feita, e os logs de `stdout` dos
contentores chegam ao Log Analytics sem alterar uma linha de código — isso
funciona.

O que não funciona sozinho são os traços, as dependências e as métricas de
pedido: para isso a aplicação tem de emitir telemetria, e não há nenhuma
dependência de instrumentação no `pyproject.toml`. O recurso fica criado para
que a ligação exista; enchê-lo é uma alteração deliberada à aplicação.

**Decisão:** aceitar um Application Insights vazio nesta fase, ou acrescentar a
dependência de instrumentação e o passo correspondente.
