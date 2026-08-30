# Deploying ReSoilTwin to Azure

This guide is written so that whoever has the authority to create resources can
follow it end to end without asking the author anything. Every step says how
long it takes and how to check that it worked.

> **Nothing described here has been run.** No resource was created, no
> subscription was authenticated against, and no `az login` was performed while
> these files were written. They were validated by reading the application code
> and the service documentation, and by building and running the container image
> locally. The Bicep templates have **not been compiled** — step 1 does that,
> and it is the first thing to do.

Decisions that only the project owner can make are collected separately, in
[`fase-e-decisoes-pendentes.md`](fase-e-decisoes-pendentes.md). **Read that
first.** Several of them — which resource group, which region, whether the API
is public — have to be settled before step 2, and one of them (authentication)
should be settled before the API is reachable from the internet at all.

---

## What gets created

| | |
|---|---|
| Database | PostgreSQL Flexible Server 16, PostGIS enabled, TLS required, no public endpoint |
| Network | One virtual network, two delegated subnets, one private DNS zone |
| Secrets | Key Vault, in one of two authorisation modes — see below |
| Images | Container Registry |
| Application | Container Apps environment, the API, and a job that runs the migrations |
| Observability | Log Analytics workspace and Application Insights |

**No blob storage.** Nothing in this system stores a file. Observations go to
PostgreSQL; the only file that is ever written is the NetCDF the Climate Data
Store client downloads, and that lives inside a `TemporaryDirectory` that is
deleted in the same function. A storage account would be an empty resource with
a key to look after, so it is not here. The day something needs to persist a
file — an export, a raster cache, an uploaded KML for an AOI — is the day to add
it, and that day is not today.

---

## The one compromise you have to choose

The application needs three kinds of secret at runtime: the database URL, the
Copernicus Data Space credentials, and the Climate Data Store key. Where those
live, and how the application gets them, depends on **what role you hold**.

### Variant A — managed identity (`secretsMode: 'rbac'`)

The application carries a user-assigned managed identity. Key Vault authorises
by RBAC, the identity holds *Key Vault Secrets User*, and Container Apps
resolves each secret from the vault at runtime. The identity also holds
*AcrPull*, so the registry's administrator account stays switched off. **No
credential passes through the deployment, and none is stored outside the vault.**

**Requires `Microsoft.Authorization/roleAssignments/write` — Owner or User
Access Administrator.** A Contributor cannot create role assignments, and this
variant is not partially available to one: without both assignments the
application cannot pull its own image and cannot read a single secret.

### Variant B — access policies (`secretsMode: 'deployTime'`, the default)

Key Vault authorises by access policies, which a Contributor *can* set. The
vault remains the system of record for the secrets. But the application does
**not** read them from the vault at runtime: whoever deploys reads them and
passes them as secure parameters into the Container App's own secrets. Image
pull uses the registry's administrator account.

This is the variant this project can actually run today, and it was declared as
accepted technical debt in
[`fase-b-condicoes-de-entrada.md`](fase-b-condicoes-de-entrada.md), section 6.
What it costs, said plainly:

- a copy of every secret lives in the Container App's configuration, not only
  in the vault, and rotating one means redeploying;
- the registry administrator account is a long-lived username and password that
  nothing rotates;
- the secrets pass through a deployment, so whoever runs it sees them.

Two smaller things worth knowing. Container Apps' Key Vault references are
documented as authorising through the RBAC role *Key Vault Secrets User* only —
unlike App Service, the documentation does not offer access policies as an
alternative. That is why variant B does not simply keep the vault reference and
swap the authorisation model: it was not possible to test that, and building the
application's startup on an untested assumption is worse than stating the
limit. And the role assignments live in a **separate file**,
`infra/role-assignments.bicep`, so that the half a Contributor *can* run
completes instead of failing midway and leaving half-created resources behind.

Moving from B to A later does not require renaming anything: the managed
identity is created in both variants, and is simply unused in B.

---

## Prerequisites

- The Azure CLI. If it is not installed, install it from Microsoft's
  instructions — this guide does not vendor an installer.
- **The Bicep CLI**, which is a separate component of the Azure CLI and is
  *not* installed by default. It was not installed on the machine where these
  templates were written, which is why step 1 exists.
- Docker, to build and push the image.
- A resource group, in a region you have chosen deliberately. See decision 1.
- Contributor on that resource group at minimum; Owner or User Access
  Administrator if you want variant A.

---

## Step 0 — confirm which subscription you are pointed at (1 minute)

```bash
az account show --query "{subscription:name, id:id, tenant:tenantId}" -o table
```

Do this every time. Getting this wrong is how resources end up in the wrong
place and how the wrong database gets touched.

---

## Step 1 — compile the templates (2–5 minutes)

```bash
az bicep install          # or: az bicep upgrade
az bicep build --file infra/main.bicep --stdout > /dev/null
az bicep build --file infra/role-assignments.bicep --stdout > /dev/null
```

**Verify:** both commands exit 0 and print no error. Warnings about unused
parameters are fine.

If either fails to compile, stop and fix the template before going further —
nothing downstream is worth doing against a template that does not build.

---

## Step 2 — fill in the parameters (5 minutes)

Copy `infra/main.bicepparam` and replace the two placeholders:

```bash
az ad signed-in-user show --query id -o tsv     # -> deployerObjectId
```

`postgresAdministratorLogin` is yours to choose. It cannot be
`azure_superuser`, `azure_pg_admin`, `admin`, `administrator`, `root`, `guest`
or `public`, and it cannot start with `pg_`.

**The password is never written to a file.** It is passed on the command line in
the next step and then stored in the vault.

---

## Step 3 — preview, then create the platform (15–25 minutes)

The first pass creates everything except the application. Preview it first:

```bash
GROUP=<your-resource-group>
read -rs PGPASS                    # type the password; it is not echoed

az deployment group what-if \
  -g "$GROUP" \
  -f infra/main.bicep \
  --parameters infra/main.bicepparam \
  --parameters postgresAdministratorPassword="$PGPASS"
```

Read the output. It should propose creating a virtual network, a private DNS
zone and its link, a PostgreSQL flexible server plus one database and three
server parameters, a Key Vault, a container registry, a Log Analytics
workspace, an Application Insights component and a managed identity. If it
proposes deleting or modifying anything, stop — you are pointed at a group that
already has something in it.

Then create:

```bash
az deployment group create \
  -g "$GROUP" \
  -n resoiltwin-plataforma \
  -f infra/main.bicep \
  --parameters infra/main.bicepparam \
  --parameters postgresAdministratorPassword="$PGPASS"
```

**The PostgreSQL server dominates the wall-clock time** — injecting a flexible
server into a delegated subnet takes roughly 10 to 20 minutes on its own.
Everything else finishes in two or three.

**Verify:**

```bash
az deployment group show -g "$GROUP" -n resoiltwin-plataforma \
  --query properties.outputs -o json
```

You should get back the server FQDN, the database name, the vault name and URI,
the registry login server and name, and the managed identity's principal and
resource IDs. Keep this output — the next steps consume it.

Confirm PostGIS is allow-listed, which is the one server setting the schema
cannot do without:

```bash
az postgres flexible-server parameter show \
  -g "$GROUP" -s <postgres-server-name> -n azure.extensions \
  --query value -o tsv
```

Expect `POSTGIS`.

---

## Step 4 — store the secrets (5 minutes)

Compose the database URL by hand. This is deliberate: the template does not
build it, so that the password never enters the deployment history, and so that
the choice of *which database user the API runs as* is a conscious one rather
than a side effect.

```bash
FQDN=<postgres-server-fqdn-from-step-3>
VAULT=<key-vault-name-from-step-3>

az keyvault secret set --vault-name "$VAULT" --name database-url \
  --value "postgresql+psycopg://<login>:${PGPASS}@${FQDN}:5432/resoiltwin?sslmode=require"
```

`sslmode=require` is not optional. The server refuses connections that are not
encrypted, and psycopg will not negotiate TLS unless the URL asks for it.

The four external credentials are genuinely optional and each one gates exactly
one connector. Set the pairs you have:

```bash
az keyvault secret set --vault-name "$VAULT" --name cdse-client-id     --value "<...>"
az keyvault secret set --vault-name "$VAULT" --name cdse-client-secret --value "<...>"
az keyvault secret set --vault-name "$VAULT" --name cds-api-key        --value "<...>"
```

Leave any of them out and the corresponding sync route answers 503 naming the
missing variables. It does not stop the application from starting, and it does
not affect the station feed, which needs no credential at all.

**Verify:** `az keyvault secret list --vault-name "$VAULT" --query "[].name" -o tsv`

---

## Step 5 — build and push the image (10–15 minutes, mostly upload)

```bash
REGISTRY=<registry-login-server-from-step-3>
TAG=$(git rev-parse --short HEAD)

az acr login --name <registry-name-from-step-3>

docker build --platform linux/amd64 -t "$REGISTRY/resoiltwin-api:$TAG" .
docker push "$REGISTRY/resoiltwin-api:$TAG"
```

**Tag with the commit, never `latest`.** With `latest` there is no way to know
which revision is running and no way to go back.

`--platform linux/amd64` matters if you build on an Apple Silicon machine;
without it you push an arm64 image that Container Apps will refuse to start.

**Verify:**

```bash
az acr repository show-tags --name <registry-name> --repository resoiltwin-api -o tsv
```

The image has been built and run locally and is known to work: it starts as a
non-root user, all four native dependencies load, `alembic heads` reports
`0009`, and the API answers on `/api/v1/health`. It carries **no `apt` packages
beyond the base image** — see the comment at the top of the `Dockerfile` for why
the base must stay Debian and must not become Alpine.

---

## Step 6 — variant A only: assign the roles (2 minutes)

**Skip this step entirely if you are using variant B.**

This is the privileged half. It needs Owner or User Access Administrator.

```bash
az deployment group create \
  -g "$GROUP" \
  -n resoiltwin-papeis \
  -f infra/role-assignments.bicep \
  --parameters managedIdentityPrincipalId=<managed-identity-principal-id-from-step-3> \
  --parameters registryName=<registry-name> \
  --parameters keyVaultName=<key-vault-name>
```

**Verify:**

```bash
az role assignment list --assignee <managed-identity-principal-id> \
  --query "[].{role:roleDefinitionName, scope:scope}" -o table
```

Expect exactly two rows: `AcrPull` and `Key Vault Secrets User`.

The assignment names are deterministic GUIDs derived from scope, principal and
role, so re-running this is idempotent — it neither duplicates nor fails.

---

## Step 7 — deploy the application (5–10 minutes)

### Variant A

```bash
VAULT_URI=<key-vault-uri-from-step-3>

az deployment group create \
  -g "$GROUP" -n resoiltwin-aplicacao \
  -f infra/main.bicep \
  --parameters infra/main.bicepparam \
  --parameters postgresAdministratorPassword="$PGPASS" \
  --parameters deployApp=true \
  --parameters secretsMode=rbac \
  --parameters containerImage="$REGISTRY/resoiltwin-api:$TAG" \
  --parameters databaseUrlSecretUri="${VAULT_URI}secrets/database-url" \
  --parameters cdseClientIdSecretUri="${VAULT_URI}secrets/cdse-client-id" \
  --parameters cdseClientSecretSecretUri="${VAULT_URI}secrets/cdse-client-secret" \
  --parameters cdsApiKeySecretUri="${VAULT_URI}secrets/cds-api-key"
```

Use the **versionless** secret URIs, as written above. With a version pinned,
rotating a secret means redeploying; without one, Container Apps picks up the
new version on its own.

### Variant B

Read the secrets back out of the vault and the registry credentials out of the
registry, and pass them in:

```bash
az deployment group create \
  -g "$GROUP" -n resoiltwin-aplicacao \
  -f infra/main.bicep \
  --parameters infra/main.bicepparam \
  --parameters postgresAdministratorPassword="$PGPASS" \
  --parameters deployApp=true \
  --parameters secretsMode=deployTime \
  --parameters containerImage="$REGISTRY/resoiltwin-api:$TAG" \
  --parameters databaseUrlValue="$(az keyvault secret show --vault-name "$VAULT" --name database-url --query value -o tsv)" \
  --parameters cdseClientIdValue="$(az keyvault secret show --vault-name "$VAULT" --name cdse-client-id --query value -o tsv)" \
  --parameters cdseClientSecretValue="$(az keyvault secret show --vault-name "$VAULT" --name cdse-client-secret --query value -o tsv)" \
  --parameters cdsApiKeyValue="$(az keyvault secret show --vault-name "$VAULT" --name cds-api-key --query value -o tsv)" \
  --parameters registryUsername="$(az acr credential show --name <registry-name> --query username -o tsv)" \
  --parameters registryPassword="$(az acr credential show --name <registry-name> --query passwords[0].value -o tsv)"
```

If you did not set the Copernicus or Climate Data Store secrets, drop those
lines — an empty value is treated as "not configured" and the corresponding
environment variables are left out entirely, rather than being set to an empty
string that looks configured and is not.

**Verify:** the deployment returns a `containerAppUrl`. Do not curl it yet — the
schema does not exist.

---

## Step 8 — run the migrations (2–5 minutes)

The schema is built by migrations and by nothing else. There is no
`create_all` path anywhere in this application.

```bash
az containerapp job start -g "$GROUP" -n <migration-job-name-from-step-7>
```

**Verify:**

```bash
az containerapp job execution list -g "$GROUP" -n <migration-job-name> \
  --query "[0].{name:name, status:properties.status}" -o table
```

Wait for `Succeeded`. If it says `Failed`, read the logs before doing anything
else:

```bash
az containerapp job logs show -g "$GROUP" -n <migration-job-name> \
  --container migrate
```

A successful run is also the proof that PostGIS exists: migration `0001` begins
with `CREATE EXTENSION IF NOT EXISTS postgis`, and every table with a geometry
column depends on it. If the extension were missing or not allow-listed, this
job is where it would fail.

> ⚠️ **`upgrade`, never `downgrade`.** The job runs `alembic upgrade head` and
> there is no path in this infrastructure that runs a downgrade. Do not add one.
> An `alembic downgrade` has already destroyed this project's development
> database twice. Reverting a migration against real data is a decision for a
> person with a backup in hand, not something a pipeline does on its own.
>
> The job also retries **zero** times, deliberately: re-running a migration that
> failed halfway applies it again on top of a partial state.

**Why a job and not the container's entrypoint.** Running `alembic upgrade head`
at startup satisfies the letter of "migrations run before serving" and misses
the point: whenever there is more than one replica — which there is every time a
new revision replaces an old one — two processes run the upgrade concurrently
against the same database, and Alembic takes no lock that prevents it. A job
runs once, has a result you can read, and fails visibly.

---

## Step 9 — confirm it actually works (5 minutes)

```bash
URL=<container-app-url-from-step-7>

curl -s "$URL/api/v1/health"
```

Expect `{"status":"ok","service":"ReSoilTwin API","environment":"dev"}`.

**This does not prove the database is reachable.** The health route reads the
settings object and nothing else — it was verified on 30/08/2026 answering 200
inside a container whose `DATABASE_URL` pointed at a host that does not exist.
For a real check, ask for something that reads a table:

```bash
curl -s "$URL/api/v1/sites"
```

An empty array `[]` is the answer you want: it means the request reached
PostgreSQL over TLS, the schema is there, and the table is empty. A 500 means
the application is up and the database is not.

Then check the logs arrived:

```bash
az containerapp logs show -g "$GROUP" -n <container-app-name> --tail 50
```

---

## Cost

**These are order-of-magnitude figures for a development environment, not a
quote.** No live pricing was queried while writing this, and prices vary by
region, currency and whatever agreement the subscription sits under. Check the
Azure pricing calculator before committing to anything.

| | Rough monthly share |
|---|---|
| Container App, 0.5 vCPU / 1 GiB, `minReplicas: 1` | the largest single item |
| PostgreSQL `Standard_B1ms` + 32 GB + 7-day backups | the second largest |
| Container Registry, Basic | small and flat |
| Log Analytics / Application Insights | small at this volume, capped at 1 GB/day |
| Key Vault, VNet, private DNS zone | negligible |

A development environment of this shape plausibly lands in the **low tens to
around a hundred euros a month**, and what dominates it is **the always-on
container plus the database** — together they are most of the bill; everything
else is rounding.

Two things that move the number, both worth deciding rather than discovering:

- **`minReplicas: 1` is what makes the container always-on.** Dropping it to 0
  cuts that line substantially, at the price of a cold start on the first
  request after an idle period and a rebuilt connection pool each time. For a
  demo environment that nobody is watching, 0 is often the better trade.
- **Outbound internet from a VNet-integrated environment.** The application must
  reach Copernicus, the Climate Data Store and the station feed. Azure has been
  retiring default outbound access for new virtual networks, and if this
  environment needs an explicit outbound path — a NAT gateway — that is a
  meaningful monthly addition plus data processing charges. **I could not verify
  which applies to a Container Apps environment created today.** Check it during
  step 3, and if outbound calls fail from inside the environment, this is the
  first thing to look at.

---

## Things to verify at deploy time, because they could not be verified here

1. **The templates have never been compiled.** Step 1 is not a formality.
2. **Outbound internet from the VNet-integrated environment**, as above. Test it
   by asking for a station sync, which needs no credential:
   `POST /api/v1/sites/{code}/weather/sync`.
3. **Long-running syncs will be cut off at the client.** The Climate Data Store
   client polls with a ceiling of **900 seconds**, and a reanalysis sync issues
   one request per month in the window. Container Apps ingress disconnects an
   idle request after **4 minutes** by default, and raising that (to at most 30
   minutes) requires the environment's premium ingress mode, which is not the
   default and is not configured here. The server-side job keeps running and
   still writes its rows; it is the HTTP client that gets dropped. Read the
   result from `GET /api/v1/jobs` rather than from the response body. Making
   these syncs properly asynchronous is application work, not infrastructure
   work.
4. **Application Insights will be empty.** Container stdout is collected into
   Log Analytics by the environment with no code change, and that works. But
   traces, dependencies and request metrics require the application to emit
   telemetry, and there is no instrumentation dependency in `pyproject.toml`
   today. The resource is created so the wiring is in place; filling it needs a
   deliberate change to the application.
5. **The API runs as the PostgreSQL administrator.** The migration job has to:
   PostGIS is an untrusted extension and `CREATE EXTENSION` requires membership
   of `azure_pg_admin`, which only the admin login has. The API does not have
   that requirement and should not have that privilege. Creating a
   least-privileged role is a SQL step a template cannot perform — see decision
   9.

---

## Tearing it down

```bash
az group delete --name "$GROUP"
```

If `keyVaultEnablePurgeProtection` was set to `true`, the vault cannot be purged
and its **name stays reserved for the whole soft-delete window** even after the
group is gone. That is why it defaults to `false` here: for a disposable
environment it is an obstacle rather than a protection. For production it is the
opposite, and should be turned on.
