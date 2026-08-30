/*
  Log Analytics e Application Insights.

  O Application Insights e criado em modo workspace-based (WorkspaceResourceId
  preenchido) porque o modo classico esta descontinuado e os recursos classicos
  deixaram de poder ser criados.

  Sobre "logs sem segredos": nao ha nada nesta camada que possa impedir a
  aplicacao de escrever um segredo num log -- se a aplicacao o escrever, ele e
  ingerido. O que garante a ausencia de segredos e do lado do codigo, e esta
  verificado: nenhum modulo de src/ escreve DATABASE_URL nem as credenciais
  para o log, o SQLAlchemy e construido sem echo, e a mensagem de
  MissingDatabaseUrlError nomeia a variavel sem nunca imprimir o valor. O unico
  sitio do repositorio que imprime uma URL de ligacao e
  scripts/restore_dev_data.py, que passa por url_sem_segredo() antes de o
  fazer, e esse script nao vai na imagem.

  A consequencia pratica para quem continuar: qualquer logging novo que inclua
  uma URL de ligacao tem de passar pela mesma redaccao.
*/

param location string
param logAnalyticsName string
param applicationInsightsName string

@minValue(30)
@maxValue(730)
@description('Retencao dos logs. 30 dias e o minimo faturado; abaixo disso nao ha poupanca.')
param retentionInDays int

@description('Tecto diario de ingestao, em GB. -1 desliga o tecto. Um tecto e a unica proteccao contra uma fatura de observabilidade a fugir, e o custo de a atingir e perder logs ate ao dia seguinte.')
param dailyQuotaGb int

resource workspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: logAnalyticsName
  location: location
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: retentionInDays
    workspaceCapping: {
      dailyQuotaGb: dailyQuotaGb
    }
    features: {
      enableLogAccessUsingOnlyResourcePermissions: true
    }
  }
}

resource applicationInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: applicationInsightsName
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: workspace.id
    IngestionMode: 'LogAnalytics'
    publicNetworkAccessForIngestion: 'Enabled'
    publicNetworkAccessForQuery: 'Enabled'
  }
}

output workspaceId string = workspace.id
output workspaceCustomerId string = workspace.properties.customerId
output applicationInsightsId string = applicationInsights.id
output applicationInsightsConnectionString string = applicationInsights.properties.ConnectionString
