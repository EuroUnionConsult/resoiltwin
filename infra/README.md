# Infrastructure

Azure infrastructure for ReSoilTwin, as Bicep templates.

> **None of this has been deployed.** No resource was created and no
> subscription was authenticated against while these files were written. They
> are validated by reading the application code and the service documentation,
> and by building and running the container image locally. They have **not been
> compiled** — the Bicep CLI was not available and was not installed.
>
> The first step of [`../docs/deployment.md`](../docs/deployment.md) compiles
> them. Do that before anything else.

## Files

| | |
|---|---|
| `main.bicep` | Everything a **Contributor** can create. Deployed in two passes — platform, then application. |
| `main.bicepparam` | Parameters, placeholders only. The database password is never in here; it is passed on the command line. |
| `role-assignments.bicep` | ⚠️ **Privileged.** The two role assignments that variant A needs. Requires Owner or User Access Administrator. Separate on purpose, so the half a Contributor can run completes instead of failing midway. |
| `modules/network.bicep` | Virtual network, two delegated subnets, private DNS zone. |
| `modules/postgres.bicep` | PostgreSQL Flexible Server 16, PostGIS allow-listed, TLS required, no public endpoint. |
| `modules/keyvault.bicep` | Key Vault, in RBAC or access-policy mode. |
| `modules/registry.bicep` | Container registry. |
| `modules/observability.bicep` | Log Analytics workspace and Application Insights. |
| `modules/app.bicep` | Container Apps environment, the API, and the migration job. |

## Where the decisions are

The guide is [`../docs/deployment.md`](../docs/deployment.md): ordered steps,
how long each takes, and how to check it worked.

What the templates deliberately leave undecided — region, whether the API is
public, who holds the credentials, how the API gets authenticated — is in
[`../docs/fase-e-decisoes-pendentes.md`](../docs/fase-e-decisoes-pendentes.md).
Read it before deploying. One of those decisions is that **the API has no
authentication of any kind**, which is a reasonable thing to accept on
`localhost` and not a reasonable thing to accept on a public HTTPS name.

## Nothing secret is in here

No subscription id, no tenant id, no credential, no real resource name. The
tenant comes from `subscription().tenantId` at deploy time; the region defaults
to the resource group's own; every globally-unique name is derived from
`uniqueString(resourceGroup().id)`. Placeholders are named for what they are.
