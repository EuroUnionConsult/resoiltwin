// Parametros da PRIMEIRA passagem (plataforma). Nenhum valor real aqui: o
// repositorio e publico.
//
// ⛔ A palavra-passe do PostgreSQL NAO vai neste ficheiro. Passa-se na linha de
//    comando, e o guia mostra como. Um marcador de posicao num ficheiro
//    versionado tem o mau habito de ser substituido por um valor real e
//    commitado por engano.
//
// Correr com:
//   az deployment group create -g <grupo> -f infra/main.bicep \
//     --parameters infra/main.bicepparam \
//     --parameters postgresAdministratorPassword="$SENHA"

using 'main.bicep'

param projectName = 'resoiltwin'
param environmentTag = 'dev'

// Primeira passagem: so a plataforma.
param deployApp = false

// 'deployTime' e o valor por omissao porque e o unico que um Contributor
// consegue levar ate ao fim. Trocar para 'rbac' exige que alguem com Owner ou
// User Access Administrator corra infra/role-assignments.bicep entre as duas
// passagens.
param secretsMode = 'deployTime'

// Object ID de quem faz o deployment, para lhe dar escrita nos segredos do
// cofre no modo deployTime. Obter com:
//   az ad signed-in-user show --query id -o tsv
param deployerObjectId = '<OBJECT-ID-DE-QUEM-FAZ-O-DEPLOYMENT>'

// Nao pode ser azure_superuser, azure_pg_admin, admin, administrator, root,
// guest nem public, nem comecar por pg_.
param postgresAdministratorLogin = '<LOGIN-ADMINISTRATIVO-DO-POSTGRES>'

// Dimensionamento de um ambiente de desenvolvimento. Ver a estimativa de custo
// no guia antes de subir qualquer um destes.
param postgresSkuName = 'Standard_B1ms'
param postgresSkuTier = 'Burstable'
param postgresStorageSizeGb = 32
param postgresBackupRetentionDays = 7
param postgresGeoRedundantBackup = false

param containerRegistrySku = 'Basic'
param logRetentionInDays = 30
param logDailyQuotaGb = 1

param minReplicas = 1
param maxReplicas = 2
param containerCpu = '0.5'
param containerMemory = '1Gi'
