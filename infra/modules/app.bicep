/*
  Ambiente Container Apps, a aplicacao, e o job que corre as migracoes.

  Porque e que as migracoes sao um JOB e nao um passo no arranque do contentor.
  O requisito e que `alembic upgrade head` corra antes de a aplicacao servir
  pedidos. Poe-lo no entrypoint da imagem cumpre a letra e falha a intencao: em
  qualquer momento em que haja mais do que uma replica -- e ha, sempre que uma
  revisao nova substitui a antiga -- ficam dois processos a correr
  `alembic upgrade head` ao mesmo tempo contra a mesma base. O Alembic nao toma
  nenhum bloqueio que impeca isso. Um job separado corre uma vez, tem um
  resultado que se le, e falha de forma visivel quando falha.

  ⚠️ E `upgrade`, nunca `downgrade`. Um `alembic downgrade` ja apagou a base de
  desenvolvimento deste projecto duas vezes. Nao ha nesta infraestrutura nenhum
  caminho que corra downgrade, e nao deve passar a haver: reverter uma migracao
  em producao e uma operacao a decidir por uma pessoa, com backup a mao, e nao
  algo que um pipeline faca sozinho.
*/

param location string
param environmentName string
param containerAppName string
param migrationJobName string

param appsSubnetId string
param logAnalyticsCustomerId string

@secure()
param logAnalyticsSharedKey string

param containerImage string
param registryLoginServer string

@description('"rbac" = identidade gerida le os segredos do Key Vault em execucao. "deployTime" = os segredos entram como parametros seguros no deployment.')
@allowed([
  'rbac'
  'deployTime'
])
param secretsMode string

@description('Resource ID da identidade atribuida pelo utilizador. So usado em modo rbac.')
param userAssignedIdentityId string = ''

@description('URIs dos segredos no Key Vault. So usados em modo rbac.')
param databaseUrlSecretUri string = ''
param writeApiKeySecretUri string = ''
param consoleUserSecretUri string = ''
param consolePasswordSecretUri string = ''
param cdseClientIdSecretUri string = ''
param cdseClientSecretSecretUri string = ''
param cdsApiKeySecretUri string = ''

@secure()
@description('Valores dos segredos. So usados em modo deployTime.')
param databaseUrlValue string = ''
@secure()
param writeApiKeyValue string = ''
@secure()
param consoleUserValue string = ''
@secure()
param consolePasswordValue string = ''
@secure()
param cdseClientIdValue string = ''
@secure()
param cdseClientSecretValue string = ''
@secure()
param cdsApiKeyValue string = ''

@description('Utilizador administrativo do registo. So usado em modo deployTime.')
param registryUsername string = ''
@secure()
param registryPassword string = ''

param cdsApiUrl string
param environmentTag string

param minReplicas int
param maxReplicas int
param cpu string
param memory string

var usaRbac = secretsMode == 'rbac'

// Os segredos alem da DATABASE_URL sao opcionais no codigo, e a aplicacao
// arranca sem qualquer deles. Os das credenciais externas comandam um conector
// cada (a rota de reanalise responde 503 a nomear as variaveis que faltam); a
// chave de escrita comanda TODAS as rotas da API menos o `/health` desde a
// decisao 2 de 31/08, e nao so as oito que escrevem (respondem 503 sem ela); a
// senha da consola comanda as rotas sob `/console`, e mais nada.
// Nenhum deles abre nada por faltar. So entram na configuracao quando ha valor,
// para nao criar um secret vazio que pareca configurado e nao esteja -- o que
// no caso da chave de escrita seria pior do que parece, porque uma chave vazia
// e uma chave que nao existe e a guarda trata-a como tal.
var segredosRbac = concat(
  [
    {
      name: 'database-url'
      keyVaultUrl: databaseUrlSecretUri
      identity: userAssignedIdentityId
    }
  ],
  empty(writeApiKeySecretUri) ? [] : [
    {
      name: 'write-api-key'
      keyVaultUrl: writeApiKeySecretUri
      identity: userAssignedIdentityId
    }
  ],
  // ⚠️ O UTILIZADOR DA CONSOLA TAMBEM VAI PELO COFRE, e nao como valor simples
  // na revisao. Ele nao e segredo no mesmo sentido da senha -- o navegador
  // mostra-o na caixa que pede as credenciais, viaja em claro no mesmo
  // cabecalho, e `config.py` da-lhe um valor por omissao que esta escrito num
  // repositorio publico. Vem pelo cofre na mesma, por tres razoes:
  //   1. o par e UMA credencial. A guarda confere-o numa unica comparacao,
  //      justamente para que nada diga qual das metades estava errada. Guardar
  //      metade em claro entrega essa metade a quem tenha Reader no grupo --
  //      que e a pergunta que a guarda se recusa a responder;
  //   2. um valor de parametro sem @secure() fica no historico de deployments e
  //      na configuracao da revisao, legivel para sempre e ainda depois de a
  //      senha ser rodada. O cofre e tambem o sitio de onde se roda o par
  //      inteiro de uma vez, em vez de dois sitios para uma rotacao;
  //   3. custa dois parametros e um segredo, num caminho que ja existe e que a
  //      chave de escrita ja percorre.
  // Isto NAO promete confidencialidade em transito, e nao e disso que se trata:
  // e nao publicar mais largo do que e preciso.
  //
  // ⚠️ As duas metades sao conferidas SEPARADAMENTE, e nao em bloco como o par
  // do CDSE aqui em baixo. Um `CONSOLE_USER` vazio nao cai no valor por omissao
  // do codigo -- sobrepoe-se a ele, e a consola fecha com 503 a culpar a senha.
  // Criar o segredo do utilizador so porque a senha existe fabricava
  // exactamente essa avaria.
  empty(consoleUserSecretUri) ? [] : [
    {
      name: 'console-user'
      keyVaultUrl: consoleUserSecretUri
      identity: userAssignedIdentityId
    }
  ],
  empty(consolePasswordSecretUri) ? [] : [
    {
      name: 'console-password'
      keyVaultUrl: consolePasswordSecretUri
      identity: userAssignedIdentityId
    }
  ],
  empty(cdseClientIdSecretUri) ? [] : [
    {
      name: 'cdse-client-id'
      keyVaultUrl: cdseClientIdSecretUri
      identity: userAssignedIdentityId
    }
    {
      name: 'cdse-client-secret'
      keyVaultUrl: cdseClientSecretSecretUri
      identity: userAssignedIdentityId
    }
  ],
  empty(cdsApiKeySecretUri) ? [] : [
    {
      name: 'cds-api-key'
      keyVaultUrl: cdsApiKeySecretUri
      identity: userAssignedIdentityId
    }
  ]
)

var segredosDeployTime = concat(
  [
    {
      name: 'database-url'
      value: databaseUrlValue
    }
    {
      name: 'registry-password'
      value: registryPassword
    }
  ],
  empty(writeApiKeyValue) ? [] : [
    {
      name: 'write-api-key'
      value: writeApiKeyValue
    }
  ],
  // O par da consola. Ver o argumento em `segredosRbac`, incluindo o de o
  // utilizador ser conferido a parte da senha.
  empty(consoleUserValue) ? [] : [
    {
      name: 'console-user'
      value: consoleUserValue
    }
  ],
  empty(consolePasswordValue) ? [] : [
    {
      name: 'console-password'
      value: consolePasswordValue
    }
  ],
  empty(cdseClientIdValue) ? [] : [
    {
      name: 'cdse-client-id'
      value: cdseClientIdValue
    }
    {
      name: 'cdse-client-secret'
      value: cdseClientSecretValue
    }
  ],
  empty(cdsApiKeyValue) ? [] : [
    {
      name: 'cds-api-key'
      value: cdsApiKeyValue
    }
  ]
)

var segredos = usaRbac ? segredosRbac : segredosDeployTime

var registos = usaRbac ? [
  {
    server: registryLoginServer
    identity: userAssignedIdentityId
  }
] : [
  {
    server: registryLoginServer
    username: registryUsername
    passwordSecretRef: 'registry-password'
  }
]

var identidade = usaRbac ? {
  type: 'UserAssigned'
  userAssignedIdentities: {
    '${userAssignedIdentityId}': {}
  }
} : {
  type: 'None'
}

var temChaveDeEscrita = usaRbac ? !empty(writeApiKeySecretUri) : !empty(writeApiKeyValue)
var temSenhaDaConsola = usaRbac ? !empty(consolePasswordSecretUri) : !empty(consolePasswordValue)
var temUtilizadorDaConsola = usaRbac ? !empty(consoleUserSecretUri) : !empty(consoleUserValue)
var temCdse = usaRbac ? !empty(cdseClientIdSecretUri) : !empty(cdseClientIdValue)
var temCds = usaRbac ? !empty(cdsApiKeySecretUri) : !empty(cdsApiKeyValue)

// DATABASE_URL entra por secretRef e nao tem valor por omissao em lado nenhum.
// Se este segredo faltar, o contentor arranca, `Settings` levanta
// MissingDatabaseUrlError e a replica morre a vista -- que e exactamente o
// comportamento que config.py foi escrito para ter. A infraestrutura respeita
// isso; nao ha aqui nenhum valor de recurso a servir de rede de seguranca.
var variaveisBase = [
  {
    name: 'DATABASE_URL'
    secretRef: 'database-url'
  }
  {
    name: 'ENVIRONMENT'
    value: environmentTag
  }
]

// WRITE_API_KEY nao impede o arranque -- ao contrario da DATABASE_URL -- mas
// sem ela as oito rotas que escrevem respondem 503. Se este segredo faltar, a
// aplicacao sobe e serve as leituras, e nao aceita escrita nenhuma. Ver
// src/resoiltwin/config.py e docs/fase-e-decisoes-pendentes.md, decisao 7.
// Entra por secretRef, nunca como valor literal na revisao.
var variaveisDeEscrita = temChaveDeEscrita ? [
  {
    name: 'WRITE_API_KEY'
    secretRef: 'write-api-key'
  }
] : []

// CONSOLE_PASSWORD nao impede o arranque nem toca na API: sem ela, todas as
// rotas sob `/console` respondem 503 e nenhuma serve uma linha de dados, e a
// API continua a decidir pela WRITE_API_KEY. Se este segredo faltar, a
// aplicacao sobe, a API serve quem tem a chave, e a consola nao serve ninguem.
// Ver src/resoiltwin/api/console_auth.py e a decisao 2 de
// docs/fase-e-decisoes-pendentes.md. Entra por secretRef, nunca como valor
// literal na revisao.
var variaveisDaConsola = temSenhaDaConsola ? [
  {
    name: 'CONSOLE_PASSWORD'
    secretRef: 'console-password'
  }
] : []

// ⚠️ Separado do de cima de proposito, e a variavel so aparece quando ha valor.
// `CONSOLE_USER` vazia NAO cai no valor por omissao do codigo -- sobrepoe-se a
// ele, e a consola fecha com 503 como se faltasse a senha. Nao passar nada
// deixa a variavel de fora e a aplicacao usa o seu valor por omissao, que e o
// comportamento pretendido.
var variaveisDoUtilizadorDaConsola = temUtilizadorDaConsola ? [
  {
    name: 'CONSOLE_USER'
    secretRef: 'console-user'
  }
] : []

var variaveisCdse = temCdse ? [
  {
    name: 'CDSE_CLIENT_ID'
    secretRef: 'cdse-client-id'
  }
  {
    name: 'CDSE_CLIENT_SECRET'
    secretRef: 'cdse-client-secret'
  }
] : []

var variaveisCds = temCds ? [
  {
    name: 'CDS_API_URL'
    value: cdsApiUrl
  }
  {
    name: 'CDS_API_KEY'
    secretRef: 'cds-api-key'
  }
] : []

var variaveisDeAmbiente = concat(
  variaveisBase,
  variaveisDeEscrita,
  variaveisDaConsola,
  variaveisDoUtilizadorDaConsola,
  variaveisCdse,
  variaveisCds
)

resource ambiente 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: environmentName
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalyticsCustomerId
        sharedKey: logAnalyticsSharedKey
      }
    }
    vnetConfiguration: {
      infrastructureSubnetId: appsSubnetId
      // internal: false da a aplicacao um nome publico em HTTPS. E o que
      // permite a demonstracao. Desde 31/08/2026 TODAS as rotas da API exigem a
      // chave partilhada -- leitura incluida --, menos `GET /api/v1/health`
      // (decisoes 2 e 7 de docs/fase-e-decisoes-pendentes.md), e desde
      // 01/09/2026 as rotas sob `/console` exigem a senha da consola.
      //
      // ⚠️ `internal: true` NAO e a alternativa que parece: a consola partilha
      // este ambiente e este contentor com a API, portanto torna-lo interno
      // tornava a API privada tambem, e para toda a gente -- incluindo quem
      // instala. Alem disso `vnetConfiguration.internal` nao se muda num
      // ambiente existente: obriga a recriar o ambiente, a aplicacao e o job.
      // Ver a decisao 2, entrada de 01/09/2026, onde isto ficou rejeitado com
      // esse argumento.
      internal: false
    }
    workloadProfiles: [
      {
        name: 'Consumption'
        workloadProfileType: 'Consumption'
      }
    ]
    zoneRedundant: false
  }
}

resource aplicacao 'Microsoft.App/containerApps@2024-03-01' = {
  name: containerAppName
  location: location
  identity: identidade
  properties: {
    managedEnvironmentId: ambiente.id
    workloadProfileName: 'Consumption'
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true
        targetPort: 8000
        transport: 'auto'
        // A plataforma termina TLS e serve o nome em HTTPS. allowInsecure a
        // false faz o HTTP simples ser redireccionado em vez de servido.
        allowInsecure: false
        traffic: [
          {
            latestRevision: true
            weight: 100
          }
        ]
      }
      registries: registos
      secrets: segredos
    }
    template: {
      containers: [
        {
          name: 'api'
          image: containerImage
          resources: {
            cpu: json(cpu)
            memory: memory
          }
          env: variaveisDeAmbiente
          probes: [
            {
              // ⚠️ /api/v1/health NAO toca na base de dados: devolve o nome do
              // servico e o ambiente, e mais nada. Verificado a 30/08/2026 num
              // contentor com DATABASE_URL a apontar para um servidor
              // inexistente -- a rota respondeu 200 na mesma.
              //
              // Ou seja: estas sondas provam que o processo esta vivo e que o
              // FastAPI responde. NAO provam que a base esta alcancavel. Uma
              // replica com a base em baixo continua a receber trafego e a
              // devolver 500 nas rotas que leem dados. Fechar isso exige uma
              // rota de prontidao que faca um SELECT 1, e isso e uma alteracao
              // ao codigo da aplicacao, nao a esta infraestrutura.
              type: 'Liveness'
              httpGet: {
                path: '/api/v1/health'
                port: 8000
              }
              initialDelaySeconds: 10
              periodSeconds: 30
              failureThreshold: 3
            }
            {
              type: 'Readiness'
              httpGet: {
                path: '/api/v1/health'
                port: 8000
              }
              initialDelaySeconds: 5
              periodSeconds: 10
              failureThreshold: 3
            }
            {
              type: 'Startup'
              httpGet: {
                path: '/api/v1/health'
                port: 8000
              }
              initialDelaySeconds: 3
              periodSeconds: 5
              failureThreshold: 20
            }
          ]
        }
      ]
      scale: {
        // minReplicas: 1 e deliberado. A zero, cada pedido depois de um periodo
        // parado paga um arranque a frio, e o pool de ligacoes do SQLAlchemy e
        // reconstruido de cada vez. Custa mais; ver a estimativa no relatorio.
        minReplicas: minReplicas
        maxReplicas: maxReplicas
      }
    }
  }
}

resource jobDeMigracao 'Microsoft.App/jobs@2024-03-01' = {
  name: migrationJobName
  location: location
  identity: identidade
  properties: {
    environmentId: ambiente.id
    workloadProfileName: 'Consumption'
    configuration: {
      triggerType: 'Manual'
      // As migracoes deste projecto sao rapidas, mas o tecto e generoso: uma
      // migracao interrompida a meio e pior do que uma migracao lenta.
      replicaTimeout: 1800
      // Zero retentativas, de proposito. Repetir automaticamente uma migracao
      // que falhou a meio corre-a outra vez sobre um estado parcial. Quem le o
      // erro decide.
      replicaRetryLimit: 0
      manualTriggerConfig: {
        parallelism: 1
        replicaCompletionCount: 1
      }
      registries: registos
      secrets: segredos
    }
    template: {
      containers: [
        {
          name: 'migrate'
          image: containerImage
          command: [
            'alembic'
          ]
          args: [
            'upgrade'
            'head'
          ]
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          env: [
            {
              // O job corre com a MESMA imagem da API -- alembic.ini e
              // migrations/ vao la dentro. Duas imagens diferentes podiam
              // divergir, e o schema deixaria de corresponder ao codigo.
              name: 'DATABASE_URL'
              secretRef: 'database-url'
            }
            {
              name: 'ENVIRONMENT'
              value: environmentTag
            }
          ]
        }
      ]
    }
  }
}

output containerAppFqdn string = aplicacao.properties.configuration.ingress.fqdn
output containerAppName string = aplicacao.name
output migrationJobName string = jobDeMigracao.name
output environmentId string = ambiente.id
