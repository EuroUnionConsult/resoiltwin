/*
  ⚠️ FICHEIRO PRIVILEGIADO. Nao corre com Contributor.

  Isto e a metade da variante "identidade gerida" que exige
  Microsoft.Authorization/roleAssignments/write -- ou seja, Owner ou User
  Access Administrator na subscricao ou no grupo de recursos. Esta a parte por
  duas razoes:

    1. Para que a metade que um Contributor PODE correr (infra/main.bicep) corra
       ate ao fim, em vez de rebentar a meio e deixar recursos criados pela
       metade a custar dinheiro.
    2. Para que o compromisso seja um passo visivel no guia, com um dono
       identificado, e nao uma linha escondida num template de 300 linhas.

  Se ninguem correr este ficheiro, a alternativa e o modo deployTime, e a
  divida que ele traz esta descrita em docs/deployment.md e em
  docs/fase-e-decisoes-pendentes.md, decisao 4.

  Correr DEPOIS da primeira passagem do main.bicep (que cria a identidade, o
  registo e o cofre) e ANTES da segunda (que cria a aplicacao).
*/

targetScope = 'resourceGroup'

@description('principalId da identidade atribuida pelo utilizador. Sai do output managedIdentityPrincipalId da primeira passagem do main.bicep.')
param managedIdentityPrincipalId string

@description('Nome do registo. Sai do output registryName.')
param registryName string

@description('Nome do cofre. Sai do output keyVaultName.')
param keyVaultName string

// Identificadores dos papeis internos do Azure. Sao constantes publicas e
// iguais em todas as subscricoes -- nao revelam nada sobre esta.
var papelAcrPull = '7f951dda-4ed3-4680-a7ca-43fe172d538d'
var papelKeyVaultSecretsUser = '4633458b-17de-408a-b874-0445c86b69e6'

resource registo 'Microsoft.ContainerRegistry/registries@2023-07-01' existing = {
  name: registryName
}

resource cofre 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: keyVaultName
}

// AcrPull: permite a aplicacao puxar a imagem sem a conta administrativa do
// registo. E a atribuicao que torna possivel desligar essa conta.
resource atribuicaoAcrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: registo
  // O nome de uma atribuicao de papel e um GUID determinista pelo triplo
  // (ambito, principal, papel). Assim, correr isto duas vezes nao cria uma
  // segunda atribuicao nem falha -- e idempotente.
  name: guid(registo.id, managedIdentityPrincipalId, papelAcrPull)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', papelAcrPull)
    principalId: managedIdentityPrincipalId
    principalType: 'ServicePrincipal'
  }
}

// Key Vault Secrets User: permite a aplicacao LER os segredos em execucao.
// So leitura -- nao escreve nem lista versoes de chaves.
resource atribuicaoKeyVaultSecretsUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: cofre
  name: guid(cofre.id, managedIdentityPrincipalId, papelKeyVaultSecretsUser)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', papelKeyVaultSecretsUser)
    principalId: managedIdentityPrincipalId
    principalType: 'ServicePrincipal'
  }
}

output acrPullAssignmentId string = atribuicaoAcrPull.id
output keyVaultSecretsUserAssignmentId string = atribuicaoKeyVaultSecretsUser.id
