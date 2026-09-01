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

## Ponto de situação a 31/08/2026

**Cinco decisões foram tomadas por Talys Cordeiro a 31/08/2026** e estão
registadas abaixo, cada uma na sua secção, com o argumento e com o que fica por
pagar: a **1** (região), a **2** (público/privado), a **5** (ambientes), a **7**
(autenticação) e a **8** (identidade gerida). O raciocínio que estava escrito
antes de cada uma não foi apagado — está lá, e é o que sustenta a escolha.

**Continuam por decidir**, e não se inventam aqui: a **3** (fonte oficial das
geometrias), a **4** (custódia das credenciais), a **6** (primeiro caso real a
demonstrar), a **9** (utilizador da base de dados), a **10** (agendamento da
ingestão), a **11** (retenção dos backups), a **12** (orçamento e alerta) e a
**13** (instrumentação do Application Insights).

**Nada foi provisionado por causa destas cinco decisões.** Continuam a não
existir recursos na Azure, e nenhuma sessão foi autenticada em subscrição
nenhuma para as tomar ou para as escrever.

**Adenda de 01/09/2026.** A decisão **2** ganhou uma entrada nova — a consola
passa a pedir senha —, com o argumento e com a alternativa que foi rejeitada
(tornar o ambiente interno) escritos na secção dela. Continua a não existir
recurso nenhum na Azure por causa disto, e nenhuma sessão foi autenticada em
subscrição nenhuma para o escrever.

---

## As seis do plano mestre

### 1. Que grupo de recursos e que região? Confirmar a subscrição antes de criar

**✅ DECIDIDA a 31/08/2026 por Talys Cordeiro — West Europe.**

Escolhida por ser a região europeia onde **tudo o que os templates pedem existe
de certeza**. A alternativa considerada foi Spain Central (Madrid), que é mais
próxima de Portugal e melhor por latência; foi posta de lado por ser recente e
por haver risco real de um dos recursos que estes ficheiros criam — a versão do
PostgreSQL Flexible Server, o ambiente de Container Apps, o Log Analytics — não
poder ser criado lá. Um deployment que rebenta a meio por indisponibilidade
regional custa mais do que os milissegundos que a proximidade poupa, e custa-os
a alguém que está a correr isto pela primeira vez.

O raciocínio que já estava aqui continua a valer, e é o que sustenta a escolha:
os dados são de parcelas em Portugal e as origens (Copernicus, Climate Data
Store, open-data do IPMA) são europeias, o que aponta para uma região europeia
por latência e por residência dos dados. West Europe satisfaz as duas.

⚠️ **Nada muda nos ficheiros de infraestrutura, e é de propósito.** O
`infra/main.bicep` tem `param location string = resourceGroup().location`: a
região é **herdada do grupo de recursos** e não está escrita em template nenhum.
A decisão aplica-se uma vez, ao criar o grupo:

```bash
az group create --name <grupo> --location westeurope
```

Fixar `westeurope` no template seria escrever a escolha num repositório público
e tirar ao segundo ambiente a liberdade de nascer noutro sítio — sem nada em
troca, porque o grupo de recursos já a determina.

### 2. A API é privada ou tem área pública de demonstração? Que dados podem ser públicos?

**✅ DECIDIDA a 31/08/2026 por Talys Cordeiro — nada público.** A chave passou a
ser exigida em **todas as rotas da aplicação**, e não só nas oito que escrevem.
A única excepção é `GET /api/v1/health`. Ver a decisão 7 para o que a chave faz
e, sobretudo, para o que não faz.

**A razão, e ela merece ficar escrita:** as geometrias das parcelas e as leituras
de campo **não são públicas**, e isso já tinha sido decidido duas vezes noutro
sítio. Os polígonos aprovados foram postos num repositório **privado**
(`EuroUnionConsult/resoiltwin-internal`) precisamente por isso, e as notas de
evidência publicadas seguem a mesma regra desde que existem: publicam distâncias
e o tamanho da célula, **nunca os polígonos**. Uma API que devolvia essas mesmas
geometrias e essas mesmas leituras a quem as pedisse contradizia as duas
decisões. Não há aqui nada de novo sobre o que é público; há o código a passar a
dizer o que o resto do projecto já dizia.

**O que esta decisão não é.** Não é `internal: true`. O `ingress.external`
continua `true` e a aplicação continua a nascer com um nome em HTTPS alcançável
a partir da internet — o que muda é que nesse nome não responde nada sem
credencial, menos o `/health`. Uma área de demonstração continua possível: passa
a precisar de uma chave entregue a quem a vê.

**Uma afirmação desta secção estava errada, e fica corrigida em vez de apagada.**
Estava escrito que a resposta «pública com autenticação também na leitura» exigia
a proposta 3 da decisão 7, identidade a sério. **Não exigia.** A chave partilhada
da proposta 2 chegou para alargar o âmbito, e o alargamento custou mudar *onde* a
guarda é aplicada, não trocá-la. O que continua verdade é que a chave **não
identifica ninguém** — isso, sim, precisa da proposta 3.

Sobre que dados poderiam ser públicos, a resposta por agora é **nenhuns**. As
séries de satélite e de meteorologia vêm de origens abertas e poderiam sê-lo, mas
são servidas pelas mesmas rotas que tudo o resto, e separar a fronteira por linha
em vez de por rota é um trabalho maior do que este. As leituras de campo e as
geometrias das parcelas não são nossas para publicar sem quem as cedeu dizer que
sim, e ninguém disse.

#### Adenda de 01/09/2026 — a consola passa a pedir senha

**A lacuna que isto fecha.** A decisão de 31/08 fechou a leitura da API. A
consola, escrita nesse mesmo dia, tem uma camada de servidor que guarda a chave
da API e a apresenta por conta do navegador — e **tem** de ser assim, porque um
frontend não pode ter credencial nenhuma: qualquer coisa no código, na
configuração ou numa resposta dele é visível a quem abra as ferramentas de
programador. O efeito colateral é que a consola lê os mesmos dados **sem
apresentar credencial**. Publicá-la aberta reabria, por outra porta, a leitura
que a decisão de 31/08 tinha acabado de fechar — e reabria-a a quem apenas
alcançasse o endereço.

**O que ficou decidido.** Uma senha à porta da consola: autenticação HTTP básica
sobre todas as rotas sob `/console` (`src/resoiltwin/api/console_auth.py`),
aplicada aos **dois** routers em `main.py` — o das páginas e o apanha-tudo — e
não rota a rota, para que uma rota nova nasça guardada. Sem `CONSOLE_PASSWORD`
configurada a consola responde 503 em tudo e não serve uma linha; a API não é
tocada e continua a decidir pela sua chave.

**Porquê básica, e não um cabeçalho como o da API.** Um navegador não põe
cabeçalhos numa barra de endereços — foi precisamente esse o custo assumido na
decisão 7 quando o `/docs` deixou de abrir escrevendo o URL. A autenticação
básica é o único esquema a que o navegador responde sozinho, e a consola só
serve navegadores.

**O que esta senha não faz, e fica escrito porque foi aceite e não esquecido.**
Não identifica ninguém: é um par igual para toda a gente, dois visitantes
válidos são indistinguíveis um do outro, e tirar o acesso a um obriga a
mudá-la para todos — exactamente as limitações da chave da API, pelas mesmas
razões. A resposta certa continua a ser a **proposta 3 da decisão 7** (Entra ID
à frente do Container App). O que muda com esta porta é que o endereço deixa de
servir dados a quem apenas o conheça, que era a razão pela qual a consola não
podia ser publicada.

**A alternativa rejeitada, e porquê: `internal: true` no ambiente.** É a
proposta 1 da decisão 7 aplicada à consola — não publicar. Foi posta de lado por
duas razões concretas, e nenhuma delas é preferência:

- **tornava a API privada também.** A consola partilha o ambiente e o contentor
  com a API por decisão de desenho: é um router na mesma imagem, e não um
  segundo serviço a construir, publicar, actualizar e proteger. Não há maneira
  de tornar privada metade de um contentor. O que se ganhava em fechar três
  vistas perdia-se em fechar a API inteira a toda a gente — **incluindo a quem
  instala**: o passo 9 do guia deixava de poder ser corrido de fora, e a área de
  demonstração deixava de existir;
- **obrigava a recriar o ambiente.** `vnetConfiguration.internal` não se altera
  num ambiente de Container Apps já criado; muda-se criando outro, e com ele a
  aplicação e o job de migração. É uma mudança que derruba tudo o que existe
  para fechar a parte menos crítica do sistema.

**O que isto custa.** Duas variáveis de ambiente e um segredo no cofre, e uma
linha a mais no `.env` de quem desenvolve. Não fecha nada a ninguém que já tenha
acesso. O par vai **inteiro** pelo cofre — o utilizador também, embora não seja
segredo no mesmo sentido: a guarda confere o par numa só comparação para que
nada diga qual das metades estava errada, e guardar metade em claro na
configuração da revisão respondia essa pergunta a quem tivesse *Reader* no
grupo. O argumento está escrito em `infra/modules/app.bicep`, ao lado dos
segredos.

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
a **toda a gente que use a API**, e não só a quem escreve, desde que a decisão 2
alargou o âmbito. Quem responde por ela é a mesma pergunta, com a diferença de
que a resposta «ninguém» custa aqui uma rotação e não um pedido de recuperação.

A segunda metade da pergunta é a decisão 8, e não é separável dela: que
identidade tem acesso ao cofre depende de qual das duas variantes se adopta.

### 5. Que ambientes são precisos — dev, staging, produção?

**✅ DECIDIDA a 31/08/2026 por Talys Cordeiro — só desenvolvimento, por agora.**

Os templates aceitam um `environmentTag` e derivam dele todos os nomes, pelo que
criar um segundo ambiente é **correr o mesmo deployment com outra etiqueta, num
grupo de recursos diferente**. Nada nos ficheiros pressupõe que haja só um, e
nada terá de mudar no dia em que houver um segundo — o que torna esta decisão
barata de rever, que é metade da razão para a tomar já.

O que a decisão poupa, e que continua a valer: cada ambiente é uma base de dados
a mais e um contentor sempre ligado a mais, e são esses dois que dominam a
factura (ver a estimativa no guia). Um ambiente de desenvolvimento com
`minReplicas: 0` custa substancialmente menos e paga um arranque a frio no
primeiro pedido.

⚠️ **Nada muda em `infra/main.bicepparam`.** Já lá está
`param environmentTag = 'dev'`. O que mudou não é o valor, é o estatuto: era um
valor por omissão à espera de decisão, e passa a ser a decisão.

⚠️ **E o ambiente é de desenvolvimento, não de produção** — o que importa para
três das decisões que ficam abertas. Os 7 dias de retenção de backup sem
redundância geográfica (decisão 11), o Application Insights vazio (decisão 13) e
a API a correr como administrador da base (decisão 9) são aceitáveis num ambiente
de desenvolvimento e **não** o seriam num de produção. No dia em que houver um
segundo ambiente com esse nome, estas três voltam à mesa antes dele.

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

### 7. ✅ DECIDIDA a 31/08/2026 por Talys Cordeiro — chave partilhada em todas as rotas

**Escolhida a proposta 2 das três abaixo, e implementada** — primeiro nas oito
rotas que escrevem, e **no mesmo dia alargada a todas as rotas**, por força da
decisão 2. Hoje, toda a API exige um cabeçalho `X-API-Key` conferido contra
`WRITE_API_KEY`. A única excepção é `GET /api/v1/health`, que a sonda de saúde da
plataforma chama sem credencial nenhuma: uma guarda ali não aperta o sistema,
desliga-o — a revisão nunca fica saudável e o deployment não arranca. O que essa
rota devolve foi conferido antes de ficar aberta (estado, nome da aplicação,
etiqueta do ambiente; não toca na base, não diz a versão, não diz para onde
aponta a `DATABASE_URL`) e as chaves da resposta estão presas por teste.

As quatro rotas de documentação (`/openapi.json`, `/docs`,
`/docs/oauth2-redirect`, `/redoc`) ficaram fechadas como as outras. O esquema não
contém dados, mas contém o mapa — os nomes das rotas, a forma de cada corpo, que
`approved_by` é texto livre — e nada de automático precisa dele, que foi o
critério que manteve o `/health` aberto. O custo é assumido e não disfarçado: um
navegador não põe cabeçalhos numa barra de endereços, portanto o `/docs` deixa de
abrir escrevendo o URL, e o esquema pede-se com a chave
(`curl -H "X-API-Key: ..." "$URL/openapi.json"`).

O código está em `src/resoiltwin/api/auth.py` e `src/resoiltwin/api/docs.py`, a
aplicação da guarda em `src/resoiltwin/main.py`, e os testes em
`tests/test_api_auth.py`.

**⚠️ O que esta decisão NÃO faz, e fica escrito porque foi aceite e não
esquecido:**

- **não identifica quem escreveu.** Todos os pedidos válidos são iguais entre si,
  e `approved_by` continua a ser um campo de texto que o cliente preenche — uma
  aprovação continua a poder dizer que foi feita por qualquer nome. O que muda é
  que deixa de a poder fazer quem não tem a chave;
- **não tem revogação por pessoa.** Há uma chave e é a mesma para toda a gente.
  Tirar o acesso a alguém é gerar outra chave e **redistribuí-la a todos os
  outros** — e quem tenha guardado a antiga não a devolve;
- **não deixa rasto de quem fez o quê.** O registo do servidor distingue «sem
  cabeçalho» de «cabeçalho errado» e mais nada: dois pedidos válidos vindos de
  pessoas diferentes são indistinguíveis um do outro.

**O passo seguinte seria identidade a sério** — a proposta 3, Microsoft Entra ID
à frente do Container App, com um utilizador real por detrás de cada
`approved_by`. É a resposta certa às três alíneas acima, é a mais cara, e não é
este passo.

⚠️ **Uma dívida de nome, para não passar por descuido.** A variável continua a
chamar-se `WRITE_API_KEY` e o segredo do cofre `write-api-key`, e o nome já diz
menos do que a chave faz. Ficou assim por ser o contrato com o deployment — é a
variável que o `infra/modules/app.bicep` leva para dentro do contentor —, e
renomeá-la é uma alteração com uma reposição atrás, não um alargamento de âmbito.

Três escolhas dentro da decisão, com o argumento de cada uma:

- **A chave não tem valor por omissão** — como o `DATABASE_URL`, e pela mesma
  razão: um valor por omissão num repositório público é a mesma chave em todas
  as instalações, isto é, uma fechadura pintada.
- **Mas, ao contrário do `DATABASE_URL`, a falta dela continua a não impedir o
  arranque — e agora por outra razão.** Enquanto o âmbito eram as oito rotas de
  escrita, o argumento era que sem chave ainda se podia ler; a decisão 2 acabou
  com isso. O que resta, e chega, é poder **diagnosticar**: uma aplicação que
  arranca responde no `/health`, escreve no registo qual é a variável que falta,
  e devolve 503 em todas as outras rotas — que é exactamente o que o passo 9 do
  guia manda distinguir de um 401. Uma que se recusasse a arrancar não diria nada
  a ninguém, e empurrava quem tem pressa a inventar um valor só para arrancar,
  que é o valor por omissão outra vez, agora por outra via. A falha perigosa
  seria a simétrica — «não há chave, portanto deixa passar» — e é essa que a
  guarda existe para impedir.
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

**O que isto não decide.** Nada sobre *quem* é cada pessoa que escreve — ver as
três alíneas acima. A pergunta que a decisão 2 fazia («que dados podem ser lidos
em público») ficou respondida no mesmo dia, e a resposta foi *nenhuns*: a chave
deixou de separar escrita de leitura e passou a separar quem a tem de quem não a
tem.

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

### 8. ✅ DECIDIDA a 31/08/2026 por Talys Cordeiro — variante `deployTime`

**Escolhida a variante que um *Contributor* corre até ao fim.** Esta é a decisão
que a nota da Fase B já tinha declarado, e tinha uma resposta explícita por
dar.

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
que corre em dois minutos e não faz mais nada. A decisão era entre pedir a quem
tem Owner que corra esse ficheiro uma vez, ou assumir a dívida por escrito — e
**a dívida foi assumida**, para que a instalação não fique à espera de uma pessoa
que ainda não existe no projecto.

**⚠️ Isto é dívida técnica assumida, não a solução certa.** O que ela custa, dito
sem rodeios:

- **uma cópia de cada segredo fica fora do cofre**, na configuração do Container
  App. O cofre continua a ser o registo oficial, mas deixa de ser o único sítio
  onde os segredos estão;
- **a conta administrativa do registo fica ligada** — um utilizador e uma
  palavra-passe de vida longa que nada roda;
- **os segredos passam por um deployment**, portanto quem o corre vê-os;
- **rodar um segredo obriga a refazer o deployment**, o que faz da rotação uma
  operação que ninguém faz por hábito.

**O que muda exactamente no dia em que houver um Owner** (ou um User Access
Administrator). Nada tem de ser renomeado nem recriado: a identidade gerida é
criada nas duas variantes e em `deployTime` fica apenas por usar.

1. **Entre a primeira e a segunda passagem, correr `infra/role-assignments.bicep`
   uma vez** (passo 6 do guia), com `managedIdentityPrincipalId`, `registryName`
   e `keyVaultName` saídos dos *outputs* da primeira passagem. São dois papéis:
   *AcrPull* no registo e *Key Vault Secrets User* no cofre. O ficheiro é
   idempotente — o nome de cada atribuição é um GUID determinista do triplo
   (âmbito, principal, papel) —, portanto corrê-lo duas vezes não cria uma
   segunda atribuição nem falha.
2. **Na segunda passagem, passar `secretsMode=rbac` em vez de `deployTime`**, e
   passar os parâmetros `*SecretUri` em vez dos `*Value`. O passo 7 do guia já
   tem as duas formas escritas lado a lado (Variant A e Variant B); é trocar de
   bloco.
3. **A conta administrativa do registo desliga-se sozinha.** O
   `infra/main.bicep` tem `adminUserEnabled: !usaRbac`, e a imagem passa a ser
   puxada pela identidade gerida.
4. **A partir daí, rodar um segredo é escrever a versão nova no cofre.** A
   aplicação lê-o em execução e não é preciso refazer o deployment. As cópias
   fora do cofre desaparecem com a revisão que as trazia.

⚠️ **Uma coisa continua por verificar, e não se inventa aqui.** As referências ao
Key Vault do Container Apps estão documentadas como autorizando **apenas** pelo
papel RBAC *Key Vault Secrets User* — é essa limitação que impede a variante
`deployTime` de simplesmente manter a referência ao cofre e trocar o modelo de
autorização, e por isso ela entrega os valores no deployment. Isso foi lido na
documentação do serviço e não confirmado num deployment real, porque não houve
nenhum.

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
