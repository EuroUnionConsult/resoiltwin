/*
  Azure Container Registry.

  adminUserEnabled e a outra metade do compromisso da identidade gerida. Puxar
  uma imagem de um ACR privado exige que quem puxa tenha a permissao
  Microsoft.ContainerRegistry/registries/pull/read, e ha exactamente duas
  formas de a ter:

    - atribuir o papel AcrPull a uma identidade gerida -- o que e uma
      atribuicao de papel, e portanto fora do alcance de um Contributor;
    - usar a conta administrativa do registo, que e um par
      utilizador/palavra-passe guardado como secret do Container App.

  Com useRbac = true esta conta fica desligada e nao existe credencial nenhuma.
  Com useRbac = false ela e a unica via, e e uma credencial de longa duracao
  que ninguem roda -- e essa a divida, dita por extenso.
*/

param location string
param registryName string

@allowed([
  'Basic'
  'Standard'
  'Premium'
])
param skuName string

@description('Ligar apenas na variante de politicas de acesso, onde nao ha AcrPull possivel.')
param adminUserEnabled bool

resource registo 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: registryName
  location: location
  sku: {
    name: skuName
  }
  properties: {
    adminUserEnabled: adminUserEnabled
    publicNetworkAccess: 'Enabled'
  }
}

output registryId string = registo.id
output registryName string = registo.name
output loginServer string = registo.properties.loginServer
