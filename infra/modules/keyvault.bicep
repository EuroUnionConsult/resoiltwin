/*
  Key Vault, em duas variantes -- e a escolha entre elas nao e uma preferencia,
  e uma consequencia de que papel tem na subscricao quem corre o deployment.
  O guia (docs/deployment.md) explica o compromisso por extenso.

  useRbac = true   (variante "identidade gerida")
      O cofre autoriza por RBAC. A aplicacao le os segredos em execucao atraves
      da sua identidade gerida, e nenhum segredo passa pelo deployment. Exige
      atribuir o papel "Key Vault Secrets User" a essa identidade, e criar
      atribuicoes de papel precisa de Microsoft.Authorization/roleAssignments/write
      -- ou seja, Owner ou User Access Administrator. Um Contributor NAO o pode
      fazer. As atribuicoes estao em infra/role-assignments.bicep, num ficheiro
      a parte, para que a metade privilegiada seja um passo visivel e nao um
      deployment que rebenta a meio.

  useRbac = false  (variante "politicas de acesso")
      O cofre autoriza por access policies, que um Contributor pode definir.
      O cofre continua a ser o registo unico dos segredos, mas a aplicacao NAO
      os le de la em execucao: quem faz o deployment le-os e passa-os como
      parametros seguros para os secrets do Container App.

      Porque nao referenciar o cofre a partir do Container App nesta variante:
      a documentacao das Key Vault references dos Container Apps descreve uma
      unica forma de autorizar a identidade -- o papel RBAC "Key Vault Secrets
      User" -- e nao documenta politicas de acesso como alternativa (ao
      contrario do App Service, onde as duas vias estao documentadas). Nao foi
      possivel testar, e assumir que funcionava seria construir o arranque da
      aplicacao sobre uma suposicao.
*/

param location string
param keyVaultName string

@description('true = autorizacao RBAC (exige Owner/User Access Administrator para as atribuicoes). false = politicas de acesso (basta Contributor).')
param useRbac bool

@description('Object ID do principal que faz o deployment e que precisa de escrever os segredos. So usado quando useRbac = false. Deixar vazio nao concede nada a ninguem.')
param deployerObjectId string = ''

@minValue(7)
@maxValue(90)
param softDeleteRetentionInDays int

@description('Irreversivel. Uma vez ligada, o cofre nao pode ser purgado e o nome fica retido durante todo o periodo de soft delete, mesmo depois de apagado. Para um ambiente descartavel isso costuma ser um estorvo, nao uma proteccao.')
param enablePurgeProtection bool

var politicasDeAcesso = (!useRbac && !empty(deployerObjectId)) ? [
  {
    tenantId: subscription().tenantId
    objectId: deployerObjectId
    permissions: {
      secrets: [
        'get'
        'list'
        'set'
      ]
    }
  }
] : []

resource cofre 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: keyVaultName
  location: location
  properties: {
    // subscription().tenantId resolve no momento do deployment. Nenhum
    // identificador de inquilino fica escrito neste repositorio.
    tenantId: subscription().tenantId
    sku: {
      family: 'A'
      name: 'standard'
    }
    enableRbacAuthorization: useRbac
    accessPolicies: politicasDeAcesso
    enableSoftDelete: true
    softDeleteRetentionInDays: softDeleteRetentionInDays
    // A API recusa o valor false explicito nesta propriedade: ou vem true, ou
    // nao vem de todo. Dai o null em vez de false.
    enablePurgeProtection: enablePurgeProtection ? true : null
    publicNetworkAccess: 'Enabled'
    networkAcls: {
      bypass: 'AzureServices'
      defaultAction: 'Allow'
    }
  }
}

output keyVaultId string = cofre.id
output keyVaultName string = cofre.name
output keyVaultUri string = cofre.properties.vaultUri
