# Infrastructure

Azure infrastructure for ReSoilTwin, as Bicep templates.

> **These templates were written before anything was deployed**, and the note
> that said so stayed here until 1 September 2026, by which time it was false.
> It is replaced rather than deleted, because the sequence is the point: the
> files were validated by reading the application code and the service
> documentation, and by building the image locally — not by running them.
>
> **They have since been run.** The development environment was deployed on
> 31 August 2026 into `rg-resoiltwin-dev`, and the API and the console are
> serving from it. What that deployment produced — the resource list and the
> two deployment records — is in the evidence package, not here: this directory
> holds what is *asked for*, and a deployment record is what was *obtained*.
>
> A note like the one this replaces is worth watching for. It was true when
> written, nobody touched it, and it quietly became the most confident false
> sentence in the repository.

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
