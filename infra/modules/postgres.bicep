/*
  Azure Database for PostgreSQL Flexible Server, versao 16 -- a mesma do
  postgis/postgis:16-3.4 que o docker-compose usa em desenvolvimento.

  Tres coisas que este ficheiro tem de acertar, e porque:

  1. PostGIS. A migracao 0001 comeca com `CREATE EXTENSION IF NOT EXISTS
     postgis` e todas as colunas de geometria dependem dela. No Flexible Server
     uma extensao so pode ser criada se estiver na lista `azure.extensions`, que
     e um parametro de servidor -- e este ficheiro poe-la la. Nao chega: o
     postgis e uma extensao *untrusted*, pelo que o `CREATE EXTENSION` exige
     pertenca ao papel `azure_pg_admin`. O login administrativo do servidor tem
     essa pertenca; um utilizador de aplicacao criado a mao nao tem. E por isso
     que o job de migracao corre com as credenciais administrativas e a API nao.

  2. TLS. `require_secure_transport` ja vem ligado por omissao; fica aqui
     escrito de proposito, para que uma alteracao futura seja uma alteracao
     visivel neste ficheiro e nao uma omissao silenciosa.

  3. Rede. Com `delegatedSubnetResourceId` preenchido o servidor nasce sem
     ponto de entrada publico. Repare-se que `publicNetworkAccess` NAO e
     definido aqui: no modo de acesso privado o servico deriva-o, e defini-lo
     explicitamente faz o pedido ser recusado.
*/

param location string
param serverName string
param databaseName string
param dbSubnetId string
param privateDnsZoneId string

@description('Login administrativo. Nao pode ser azure_superuser, azure_pg_admin, admin, administrator, root, guest nem public, nem comecar por pg_.')
param administratorLogin string

@secure()
@description('Passada como parametro seguro; nunca fica em ficheiro versionado nem no historico de deployments.')
param administratorPassword string

@description('Burstable serve um ambiente de desenvolvimento. Producao pede GeneralPurpose -- e so a tier GeneralPurpose ou superior suporta alta disponibilidade.')
param skuName string

@allowed([
  'Burstable'
  'GeneralPurpose'
  'MemoryOptimized'
])
param skuTier string

param storageSizeGb int

@minValue(7)
@maxValue(35)
@description('Retencao dos backups automaticos, em dias. O minimo do servico e 7.')
param backupRetentionDays int

param geoRedundantBackup bool

var parametrosDeServidor = [
  {
    // Sem isto, `CREATE EXTENSION postgis` na migracao 0001 falha com
    // "extension is not allow-listed", e nenhuma tabela com geometria chega
    // a existir.
    nome: 'azure.extensions'
    valor: 'POSTGIS'
  }
  {
    nome: 'require_secure_transport'
    valor: 'on'
  }
  {
    nome: 'ssl_min_protocol_version'
    valor: 'TLSv1.2'
  }
]

resource servidor 'Microsoft.DBforPostgreSQL/flexibleServers@2024-08-01' = {
  name: serverName
  location: location
  sku: {
    name: skuName
    tier: skuTier
  }
  properties: {
    version: '16'
    administratorLogin: administratorLogin
    administratorLoginPassword: administratorPassword
    storage: {
      storageSizeGB: storageSizeGb
      autoGrow: 'Enabled'
    }
    backup: {
      backupRetentionDays: backupRetentionDays
      geoRedundantBackup: geoRedundantBackup ? 'Enabled' : 'Disabled'
    }
    network: {
      delegatedSubnetResourceId: dbSubnetId
      privateDnsZoneArmResourceId: privateDnsZoneId
    }
    highAvailability: {
      // Burstable nao suporta alta disponibilidade. Ligar isto num ambiente de
      // desenvolvimento obriga a subir de tier e mais do que duplica o custo.
      mode: 'Disabled'
    }
  }
}

resource baseDeDados 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2024-08-01' = {
  parent: servidor
  name: databaseName
  properties: {
    charset: 'UTF8'
    collation: 'en_US.utf8'
  }
}

// @batchSize(1) e obrigatorio: o servico so aceita uma alteracao de parametros
// de cada vez, e um lote paralelo faz as restantes falhar com conflito.
@batchSize(1)
resource parametros 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-08-01' = [for p in parametrosDeServidor: {
  parent: servidor
  name: p.nome
  properties: {
    value: p.valor
    source: 'user-override'
  }
  dependsOn: [
    baseDeDados
  ]
}]

output serverFqdn string = servidor.properties.fullyQualifiedDomainName
output serverName string = servidor.name
output databaseName string = baseDeDados.name
