/*
  Rede privada: uma VNet com duas sub-redes delegadas, e a zona DNS privada que
  faz o nome do servidor PostgreSQL resolver para o endereco interno.

  A razao de ser privada e a exigencia de restringir a base de dados a
  aplicacao. A alternativa -- acesso publico com regras de firewall -- nao a
  satisfaz: os enderecos de saida de um Container App em perfil Consumption nao
  sao estaveis, pelo que a unica regra que funcionaria seria "permitir os
  servicos do Azure", que abre a base a toda a plataforma e nao so a esta
  aplicacao.

  O preco desta escolha esta no guia: com a base sem acesso publico, as
  migracoes nao podem ser corridas a partir de um portatil. Correm de dentro,
  no job de migracao que vive no mesmo ambiente.
*/

param location string
param vnetName string
param appsSubnetName string
param dbSubnetName string

@description('Espaco de enderecos da VNet. Intervalo privado; nao ha nada de sensivel nele.')
param vnetAddressPrefix string

@description('Sub-rede do ambiente Container Apps. Minimo /27 num ambiente com perfis de carga.')
param appsSubnetPrefix string

@description('Sub-rede do PostgreSQL Flexible Server. Minimo /28, e nao pode alojar mais nada.')
param dbSubnetPrefix string

@description('Tem de terminar em .postgres.database.azure.com -- e um requisito do servico, nao uma convencao.')
param privateDnsZoneName string

resource vnet 'Microsoft.Network/virtualNetworks@2023-11-01' = {
  name: vnetName
  location: location
  properties: {
    addressSpace: {
      addressPrefixes: [
        vnetAddressPrefix
      ]
    }
    subnets: [
      {
        name: appsSubnetName
        properties: {
          addressPrefix: appsSubnetPrefix
          delegations: [
            {
              name: 'delegacao-container-apps'
              properties: {
                serviceName: 'Microsoft.App/environments'
              }
            }
          ]
        }
      }
      {
        name: dbSubnetName
        properties: {
          addressPrefix: dbSubnetPrefix
          delegations: [
            {
              name: 'delegacao-postgresql'
              properties: {
                serviceName: 'Microsoft.DBforPostgreSQL/flexibleServers'
              }
            }
          ]
        }
      }
    ]
  }
}

resource zonaDns 'Microsoft.Network/privateDnsZones@2020-06-01' = {
  name: privateDnsZoneName
  location: 'global'
}

resource ligacaoZonaDns 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2020-06-01' = {
  parent: zonaDns
  name: '${vnetName}-link'
  location: 'global'
  properties: {
    registrationEnabled: false
    virtualNetwork: {
      id: vnet.id
    }
  }
}

output appsSubnetId string = resourceId('Microsoft.Network/virtualNetworks/subnets', vnetName, appsSubnetName)
output dbSubnetId string = resourceId('Microsoft.Network/virtualNetworks/subnets', vnetName, dbSubnetName)
output privateDnsZoneId string = zonaDns.id

// A ligacao da zona a VNet tem de existir ANTES de o servidor ser criado, senao
// o servico recusa o pedido. Este output existe so para o main poder declarar
// essa dependencia sem ter de adivinhar o nome do recurso.
output privateDnsZoneLinkId string = ligacaoZonaDns.id
