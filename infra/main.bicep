/*
  ReSoilTwin -- infraestrutura Azure.

  ⛔ Este ficheiro nunca foi corrido. Nenhum recurso foi criado, e nenhuma
  sessao foi autenticada em subscricao nenhuma para o escrever. Foi validado
  por leitura do codigo da aplicacao e da documentacao do servico. Quem tiver
  autoridade para o correr comeca por compilar (`az bicep build`) e por um
  `--what-if`, como o guia descreve.

  ALCANCE: grupo de recursos. O grupo de recursos e a regiao sao decisao de
  quem manda no projecto, nao deste ficheiro -- ver
  docs/fase-e-decisoes-pendentes.md, decisao 1. `location` herda por omissao a
  regiao do grupo, para que a escolha se faca uma vez, ao criar o grupo, e nao
  fique escrita num repositorio publico.

  DUAS PASSAGENS. O deployment corre duas vezes, e nao e um contorno:
    - passagem 1 (deployApp = false) cria a plataforma -- rede, base de dados,
      cofre, registo, observabilidade, identidade. Ainda nao ha imagem
      nenhuma para correr.
    - entre as duas: escrevem-se os segredos no cofre, publica-se a imagem no
      registo, e -- na variante rbac -- atribuem-se os papeis com
      infra/role-assignments.bicep.
    - passagem 2 (deployApp = true) cria o ambiente Container Apps, a
      aplicacao e o job de migracao.
  Uma so passagem obrigaria a aplicacao a nascer a apontar para uma imagem que
  ainda nao existe, e -- na variante rbac -- sem a atribuicao de papel que lhe
  permite puxa-la.
*/

targetScope = 'resourceGroup'

// ---------------------------------------------------------------- identidade

@minLength(3)
@maxLength(12)
@description('Prefixo dos nomes. Minusculas e digitos.')
param projectName string = 'resoiltwin'

@minLength(2)
@maxLength(6)
@description('Etiqueta do ambiente. Vai nos nomes dos recursos E na variavel ENVIRONMENT que a aplicacao devolve em /health.')
param environmentTag string = 'dev'

@description('Regiao. Por omissao a do grupo de recursos -- de proposito: assim a escolha nao fica escrita neste ficheiro.')
param location string = resourceGroup().location

// -------------------------------------------------------------- faseamento

@description('false na primeira passagem (plataforma), true na segunda (aplicacao).')
param deployApp bool = false

@description('Imagem completa, com registo e etiqueta. Etiqueta imutavel, nunca "latest": com "latest" nao ha forma de saber que revisao esta a correr nem de voltar atras.')
param containerImage string = ''

// ------------------------------------------------------------- modo de segredos

@description('"rbac" precisa de Owner ou User Access Administrator. "deployTime" basta Contributor. O compromisso esta explicado em docs/deployment.md.')
@allowed([
  'rbac'
  'deployTime'
])
param secretsMode string = 'deployTime'

@description('Object ID de quem faz o deployment, para lhe dar acesso de escrita aos segredos do cofre no modo deployTime. Obtem-se com: az ad signed-in-user show --query id -o tsv')
param deployerObjectId string = ''

// -------------------------------------------------------------- base de dados

@description('Login administrativo do PostgreSQL.')
param postgresAdministratorLogin string

@secure()
@description('Palavra-passe administrativa. Passar por --parameters no momento do deployment; nunca escrever em ficheiro.')
param postgresAdministratorPassword string

param postgresSkuName string = 'Standard_B1ms'

@allowed([
  'Burstable'
  'GeneralPurpose'
  'MemoryOptimized'
])
param postgresSkuTier string = 'Burstable'

param postgresStorageSizeGb int = 32

@minValue(7)
@maxValue(35)
param postgresBackupRetentionDays int = 7

param postgresGeoRedundantBackup bool = false

param databaseName string = 'resoiltwin'

// ------------------------------------------------------------------ rede

param vnetAddressPrefix string = '10.60.0.0/22'
param appsSubnetPrefix string = '10.60.0.0/23'
param dbSubnetPrefix string = '10.60.2.0/28'

// ----------------------------------------------------------------- cofre

@minValue(7)
@maxValue(90)
param keyVaultSoftDeleteRetentionInDays int = 7

param keyVaultEnablePurgeProtection bool = false

// ---------------------------------------------------------------- registo

@allowed([
  'Basic'
  'Standard'
  'Premium'
])
param containerRegistrySku string = 'Basic'

// --------------------------------------------------------- observabilidade

@minValue(30)
@maxValue(730)
param logRetentionInDays int = 30

@description('Tecto diario de ingestao em GB. Sem tecto, uma origem de logs a fugir e uma fatura a fugir.')
param logDailyQuotaGb int = 1

// ------------------------------------------------------------- aplicacao

param minReplicas int = 1
param maxReplicas int = 2
param containerCpu string = '0.5'
param containerMemory string = '1Gi'

@description('Endpoint do Climate Data Store. Nao e segredo -- o segredo e a chave.')
param cdsApiUrl string = 'https://cds.climate.copernicus.eu/api'

// As credenciais administrativas do registo entram como parametros e NAO sao
// lidas com listCredentials() dentro do template. A razao e concreta: um
// ternario em Bicep nao garante que o ARM deixe o ramo morto por avaliar, e no
// modo rbac a conta administrativa do registo esta desligada -- uma
// listCredentials() avaliada nesse ramo faria o deployment inteiro falhar.
// Obtem-se com: az acr credential show --name <registo>
@description('Utilizador administrativo do registo. So no modo deployTime.')
param registryUsername string = ''

@secure()
@description('Palavra-passe administrativa do registo. So no modo deployTime.')
param registryPassword string = ''

// URIs dos segredos no cofre (modo rbac). Preenchidos na segunda passagem,
// depois de os segredos existirem. Usar a forma SEM versao, para que uma
// rotacao da chave nao obrigue a refazer o deployment.
param databaseUrlSecretUri string = ''
param writeApiKeySecretUri string = ''
param cdseClientIdSecretUri string = ''
param cdseClientSecretSecretUri string = ''
param cdsApiKeySecretUri string = ''

// Valores dos segredos (modo deployTime).
@secure()
param databaseUrlValue string = ''
@secure()
param writeApiKeyValue string = ''
@secure()
param cdseClientIdValue string = ''
@secure()
param cdseClientSecretValue string = ''
@secure()
param cdsApiKeyValue string = ''

// ------------------------------------------------------------------ nomes

var sufixo = uniqueString(resourceGroup().id)
var base = toLower('${projectName}-${environmentTag}')

var nomeVnet = 'vnet-${base}'
var nomeSubRedeApps = 'snet-${base}-apps'
var nomeSubRedeDb = 'snet-${base}-db'
var nomeZonaDns = '${base}.private.postgres.database.azure.com'

var nomeServidorPostgres = toLower('psql-${base}-${take(sufixo, 8)}')
// O nome do ACR nao aceita hifens e tem de ser globalmente unico.
var nomeRegisto = toLower('acr${replace(base, '-', '')}${take(sufixo, 10)}')
// O nome do cofre tem um tecto de 24 caracteres e tambem e global.
var nomeCofre = take(toLower('kv-${projectName}-${sufixo}'), 24)
var nomeLogAnalytics = 'log-${base}'
var nomeApplicationInsights = 'appi-${base}'
var nomeIdentidade = 'id-${base}'
var nomeAmbienteContainer = 'cae-${base}'
var nomeAplicacao = 'ca-${base}-api'
var nomeJobMigracao = 'caj-${base}-migrate'

var usaRbac = secretsMode == 'rbac'

// ------------------------------------------------------------- plataforma

module rede 'modules/network.bicep' = {
  name: 'rede'
  params: {
    location: location
    vnetName: nomeVnet
    appsSubnetName: nomeSubRedeApps
    dbSubnetName: nomeSubRedeDb
    vnetAddressPrefix: vnetAddressPrefix
    appsSubnetPrefix: appsSubnetPrefix
    dbSubnetPrefix: dbSubnetPrefix
    privateDnsZoneName: nomeZonaDns
  }
}

module baseDeDados 'modules/postgres.bicep' = {
  name: 'base-de-dados'
  params: {
    location: location
    serverName: nomeServidorPostgres
    databaseName: databaseName
    dbSubnetId: rede.outputs.dbSubnetId
    privateDnsZoneId: rede.outputs.privateDnsZoneId
    administratorLogin: postgresAdministratorLogin
    administratorPassword: postgresAdministratorPassword
    skuName: postgresSkuName
    skuTier: postgresSkuTier
    storageSizeGb: postgresStorageSizeGb
    backupRetentionDays: postgresBackupRetentionDays
    geoRedundantBackup: postgresGeoRedundantBackup
  }
}

module cofre 'modules/keyvault.bicep' = {
  name: 'cofre'
  params: {
    location: location
    keyVaultName: nomeCofre
    useRbac: usaRbac
    deployerObjectId: deployerObjectId
    softDeleteRetentionInDays: keyVaultSoftDeleteRetentionInDays
    enablePurgeProtection: keyVaultEnablePurgeProtection
  }
}

module registo 'modules/registry.bicep' = {
  name: 'registo'
  params: {
    location: location
    registryName: nomeRegisto
    skuName: containerRegistrySku
    // A conta administrativa so existe na variante que nao pode atribuir AcrPull.
    adminUserEnabled: !usaRbac
  }
}

module observabilidade 'modules/observability.bicep' = {
  name: 'observabilidade'
  params: {
    location: location
    logAnalyticsName: nomeLogAnalytics
    applicationInsightsName: nomeApplicationInsights
    retentionInDays: logRetentionInDays
    dailyQuotaGb: logDailyQuotaGb
  }
}

// A identidade e criada nas duas variantes -- criar uma identidade gerida e
// uma escrita de recurso normal, ao alcance de um Contributor. O que um
// Contributor nao pode e ATRIBUIR-LHE papeis. Na variante deployTime ela fica
// criada e por usar, para que passar a variante rbac mais tarde nao obrigue a
// mexer em nomes.
resource identidade 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: nomeIdentidade
  location: location
}

// Sem dependsOn: um recurso `existing` e uma referencia, nao um deployment, e
// o Bicep recusa dependsOn nele. A ordem esta garantida por outra via -- o
// modulo `aplicacao` consome observabilidade.outputs.workspaceCustomerId, o
// que lhe cria dependencia implicita, e os parametros de um modulo condicional
// so sao avaliados quando a condicao e verdadeira.
resource workspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' existing = {
  name: nomeLogAnalytics
}

// ------------------------------------------------------------- aplicacao

module aplicacao 'modules/app.bicep' = if (deployApp) {
  name: 'aplicacao'
  params: {
    location: location
    environmentName: nomeAmbienteContainer
    containerAppName: nomeAplicacao
    migrationJobName: nomeJobMigracao
    appsSubnetId: rede.outputs.appsSubnetId
    logAnalyticsCustomerId: observabilidade.outputs.workspaceCustomerId
    logAnalyticsSharedKey: workspace.listKeys().primarySharedKey
    containerImage: containerImage
    registryLoginServer: registo.outputs.loginServer
    secretsMode: secretsMode
    userAssignedIdentityId: identidade.id
    databaseUrlSecretUri: databaseUrlSecretUri
    writeApiKeySecretUri: writeApiKeySecretUri
    cdseClientIdSecretUri: cdseClientIdSecretUri
    cdseClientSecretSecretUri: cdseClientSecretSecretUri
    cdsApiKeySecretUri: cdsApiKeySecretUri
    databaseUrlValue: databaseUrlValue
    writeApiKeyValue: writeApiKeyValue
    cdseClientIdValue: cdseClientIdValue
    cdseClientSecretValue: cdseClientSecretValue
    cdsApiKeyValue: cdsApiKeyValue
    registryUsername: registryUsername
    registryPassword: registryPassword
    cdsApiUrl: cdsApiUrl
    environmentTag: environmentTag
    minReplicas: minReplicas
    maxReplicas: maxReplicas
    cpu: containerCpu
    memory: containerMemory
  }
}

// --------------------------------------------------------------- resultados
//
// Nenhum destes outputs e um segredo. A URL de ligacao NAO e composta nem
// devolvida aqui de proposito: compo-la no template poria a palavra-passe no
// historico de deployments, e escondia a decisao de com que utilizador da base
// e que a API corre. O guia compoe-na a mao, num passo consciente.

output postgresServerFqdn string = baseDeDados.outputs.serverFqdn
output postgresServerName string = baseDeDados.outputs.serverName
output postgresDatabaseName string = baseDeDados.outputs.databaseName
output keyVaultName string = cofre.outputs.keyVaultName
output keyVaultUri string = cofre.outputs.keyVaultUri
output registryLoginServer string = registo.outputs.loginServer
output registryName string = registo.outputs.registryName
output managedIdentityPrincipalId string = identidade.properties.principalId
output managedIdentityResourceId string = identidade.id
output containerAppUrl string = deployApp ? 'https://${aplicacao.outputs.containerAppFqdn}' : ''
output migrationJobName string = deployApp ? aplicacao.outputs.migrationJobName : ''

// A connection string do Application Insights NAO e devolvida aqui: leva a
// chave de ingestao, e o historico de deployments e legivel por quem tenha
// apenas Reader no grupo. Le-se quando for precisa, com:
//   az monitor app-insights component show -g <grupo> -a <nome> --query connectionString -o tsv
