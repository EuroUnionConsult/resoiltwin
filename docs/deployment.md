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
first.** Three of the ones that used to block step 2 are now settled and are
assumed by this guide: the region is **West Europe** (decision 1), there is
**one environment, `dev`** (decision 5), and **the API is not public** — every
route except `/api/v1/health` requires the shared key, reading included
(decisions 2 and 7). **The console has a password of its own** and answers
nothing without it (decision 2, entry of 01/09/2026); it is a separate guard
from the key, because a browser cannot present the key. Secrets use variant B
below, which is decision 8. What is
still open — who holds the credentials, the database user, scheduling, backup
retention, the budget — is listed there and none of it blocks a first
deployment.

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

The application needs five kinds of secret at runtime: the database URL, the
key every API route checks, the pair that opens the console, the Copernicus Data
Space credentials, and the Climate Data Store key. Where those live, and how the
application gets them, depends on **what role you hold**.

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
- A resource group in **West Europe** (decision 1):
  `az group create --name <group> --location westeurope`. The templates do not
  name a region — `location` is inherited from the resource group, so this is
  the one place the choice is made.
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

> **Why the two passes are invoked differently.** The first pass uses
> `--parameters infra/main.bicepparam` with no `-f`: a `.bicepparam` names its own
> template through `using`, and the CLI accepts `--parameters` **only once** when
> one is given. The second pass needs a dozen runtime values that do not belong in
> a versioned file, so it passes the template with `-f` and supplies each value as
> `KEY=VALUE` — the form that does allow the flag to repeat.

## Step 2 — supply the values that are not in the file (5 minutes)

`environmentTag` is already `dev`, which is the decided environment — one, for
development (decision 5). A second environment later is this same deployment
with another tag, in another resource group; nothing in the files has to change
for it.

**Nothing in `infra/main.bicepparam` is edited.** The three values that are not
in it — the deployer's object ID, the PostgreSQL administrator login and its
password — are read **from the environment** by `readEnvironmentVariable`, so
that a person's identifier and a credential never land in a file this public
repository tracks. Export all three now, in the shell you will use for the rest
of this guide:

```bash
export RESOILTWIN_DEPLOYER_OBJECT_ID="$(az ad signed-in-user show --query id -o tsv)"
export RESOILTWIN_PG_ADMIN_LOGIN='<the login you choose>'

read -rs RESOILTWIN_PG_ADMIN_PASSWORD    # typed, not echoed
export RESOILTWIN_PG_ADMIN_PASSWORD
```

**Do all three, and do them before step 3.** `readEnvironmentVariable` has no
default here, so a missing variable is not a warning — the next command fails
while compiling the parameters, before it reaches Azure at all.

`RESOILTWIN_PG_ADMIN_LOGIN` is yours to choose. It cannot be `azure_superuser`,
`azure_pg_admin`, `admin`, `administrator`, `root`, `guest` or `public`, and it
cannot start with `pg_`.

**The password is never written to a file.** It lives in this shell, goes into
the deployment, and is then stored in the vault in step 4.

**Verify** — that all three are set, without printing the password:

```bash
printenv RESOILTWIN_DEPLOYER_OBJECT_ID > /dev/null && \
printenv RESOILTWIN_PG_ADMIN_LOGIN     > /dev/null && \
printenv RESOILTWIN_PG_ADMIN_PASSWORD  > /dev/null && echo "all three set"
```

---

## Step 3 — preview, then create the platform (15–25 minutes)

The first pass creates everything except the application. Preview it first:

```bash
GROUP=<your-resource-group>     # the three RESOILTWIN_* exports from step 2 must be in this shell

az deployment group what-if \
  -g "$GROUP" \
  --parameters infra/main.bicepparam
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
  --parameters infra/main.bicepparam
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
  --value "postgresql+psycopg://${RESOILTWIN_PG_ADMIN_LOGIN}:${RESOILTWIN_PG_ADMIN_PASSWORD}@${FQDN}:5432/resoiltwin?sslmode=require"
```

`sslmode=require` is not optional. The server refuses connections that are not
encrypted, and psycopg will not negotiate TLS unless the URL asks for it.

Then the key every API route checks. This one is not optional at all: since
decision 2 the key guards **reading as well as writing**, so without it the
deployed API answers 503 on everything except `GET /api/v1/health` — step 9
depends on that distinction. It has no default value anywhere; a default in a
public repository would be the same key in every installation.

```bash
az keyvault secret set --vault-name "$VAULT" --name write-api-key \
  --value "$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
```

Generate it, do not invent it, and do not reuse one from another environment.
Read it back when a client needs it (`az keyvault secret show --vault-name
"$VAULT" --name write-api-key --query value -o tsv`) rather than keeping a copy
anywhere else.

What this key does and does not do is in the README under *Every route needs a
key*, and the reasoning is decisions 2 and 7 of `fase-e-decisoes-pendentes.md`.
In one line: it keeps out whoever does not hold it, and it does not record who
did.

Then the pair that opens the console. The console is three read-only views over
the same database, served by the same container under `/console`. The browser
cannot hold the API key — that is why the console holds it on the browser's
behalf — so without a guard of its own, publishing it would reopen to anyone who
finds the address exactly the reading that decision 2 closed. **This one is not
optional either if you intend to open the console at all.**

```bash
az keyvault secret set --vault-name "$VAULT" --name console-user \
  --value "console"

az keyvault secret set --vault-name "$VAULT" --name console-password \
  --value "$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
```

Generate the password, do not invent it, and do not reuse the API key for it.
They are two guards with two reasons: the key keeps the data from whoever does
not hold it, the console password keeps the public address from whoever merely
found it.

`console-user` is **not** a secret in the sense the password is — the browser
displays it in the box that asks for the credentials, and it travels in clear
text in the same header. It is in the vault anyway so that the pair rotates in
one place, and so that half of a credential does not sit in the deployment
history and in the revision's configuration for ever, readable by anyone with
Reader on the group. Pick another name if you prefer; `console` is the
application's own default, and leaving the secret out altogether is fine — the
templates then omit the variable and the default applies. What must not happen
is the variable arriving **empty**: an empty `CONSOLE_USER` does not fall back
to the default, it overrides it, and the console then answers 503 while the log
blames the password. The templates leave the variable out when the value is
empty precisely so this cannot happen from here.

Without the password, every route under `/console` answers 503 and none of them
serves a single row. It does not affect the API, which decides by the key above,
and it does not stop the application from starting — the same trade as the key,
for the same reason.

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
  --parameters deployApp=true \
  --parameters postgresAdministratorLogin="$RESOILTWIN_PG_ADMIN_LOGIN" \
  --parameters postgresAdministratorPassword="$RESOILTWIN_PG_ADMIN_PASSWORD" \
  --parameters secretsMode=rbac \
  --parameters containerImage="$REGISTRY/resoiltwin-api:$TAG" \
  --parameters databaseUrlSecretUri="${VAULT_URI}secrets/database-url" \
  --parameters writeApiKeySecretUri="${VAULT_URI}secrets/write-api-key" \
  --parameters consoleUserSecretUri="${VAULT_URI}secrets/console-user" \
  --parameters consolePasswordSecretUri="${VAULT_URI}secrets/console-password" \
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
  --parameters deployApp=true \
  --parameters postgresAdministratorLogin="$RESOILTWIN_PG_ADMIN_LOGIN" \
  --parameters postgresAdministratorPassword="$RESOILTWIN_PG_ADMIN_PASSWORD" \
  --parameters secretsMode=deployTime \
  --parameters containerImage="$REGISTRY/resoiltwin-api:$TAG" \
  --parameters databaseUrlValue="$(az keyvault secret show --vault-name "$VAULT" --name database-url --query value -o tsv)" \
  --parameters writeApiKeyValue="$(az keyvault secret show --vault-name "$VAULT" --name write-api-key --query value -o tsv)" \
  --parameters consoleUserValue="$(az keyvault secret show --vault-name "$VAULT" --name console-user --query value -o tsv)" \
  --parameters consolePasswordValue="$(az keyvault secret show --vault-name "$VAULT" --name console-password --query value -o tsv)" \
  --parameters cdseClientIdValue="$(az keyvault secret show --vault-name "$VAULT" --name cdse-client-id --query value -o tsv)" \
  --parameters cdseClientSecretValue="$(az keyvault secret show --vault-name "$VAULT" --name cdse-client-secret --query value -o tsv)" \
  --parameters cdsApiKeyValue="$(az keyvault secret show --vault-name "$VAULT" --name cds-api-key --query value -o tsv)" \
  --parameters registryUsername="$(az acr credential show --name <registry-name> --query username -o tsv)" \
  --parameters registryPassword="$(az acr credential show --name <registry-name> --query passwords[0].value -o tsv)"
```

If you did not set the Copernicus or Climate Data Store secrets, drop those
lines — an empty value is treated as "not configured" and the corresponding
environment variables are left out entirely, rather than being set to an empty
string that looks configured and is not. The same holds for the console pair,
with one difference worth knowing: drop `consolePasswordValue` and the console
closes (503 everywhere under `/console`), while dropping `consoleUserValue`
alone is harmless — the application falls back to its own default user name.

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

`/api/v1/health` is the only route that answers without a key — the platform
probe calls it with no credential, which is why it is exempt.

**This does not prove the database is reachable.** The health route reads the
settings object and nothing else — it was verified on 30/08/2026 answering 200
inside a container whose `DATABASE_URL` pointed at a host that does not exist.

First check that the API is closed to whoever does not hold the key:

```bash
curl -s -o /dev/null -w '%{http_code}\n' "$URL/api/v1/sites"
curl -s -o /dev/null -w '%{http_code}\n' -X POST "$URL/api/v1/sites"
curl -s -o /dev/null -w '%{http_code}\n' "$URL/docs"
```

Expect `401` on all three. A `503` means the `write-api-key` secret did not
reach the container — the application is up, `/health` answers, and nothing else
will be served until it does. Anything else means the request got past the guard,
which means **the API is readable, or writable, by anyone who finds the name**;
stop and fix that before going further.

Then hold the key and check that the database is actually reachable:

```bash
KEY=$(az keyvault secret show --vault-name "$VAULT" --name write-api-key --query value -o tsv)

curl -s "$URL/api/v1/sites" -H "X-API-Key: $KEY"
```

An empty array `[]` is the answer you want: it means the guard let the request
through, it reached PostgreSQL over TLS, the schema is there, and the table is
empty. A 500 means the application is up and the database is not.

```bash
curl -s -o /dev/null -w '%{http_code}\n' -X POST "$URL/api/v1/sites" \
  -H "X-API-Key: $KEY"
```

Expect `422` — the guard let it through and the empty body was refused.

The interactive documentation is behind the key too, and a browser cannot put a
header on an address bar, so `$URL/docs` will not open by typing it. Fetch the
schema instead and read it locally:

```bash
curl -s "$URL/openapi.json" -H "X-API-Key: $KEY" > openapi.json
```

### The console is guarded separately — check it separately

The console is not behind the API key: a browser cannot put a header on an
address bar, so the key would make it unusable. It is behind a password of its
own. Check first that it refuses:

```bash
curl -s -o /dev/null -w '%{http_code}\n' "$URL/console"
curl -s -o /dev/null -w '%{http_code}\n' "$URL/console/observacoes"
curl -s -o /dev/null -w '%{http_code}\n' "$URL/console/sitios"
```

Expect `401` on all three, and a `WWW-Authenticate: Basic` header with them.

A `503` means the pair did not reach the container — same distinction as for the
key. ⚠️ **The log blames `CONSOLE_PASSWORD` in that case even when the password
did arrive and `CONSOLE_USER` arrived empty**, because the guard treats a missing
half and an empty half alike. If the password is in the vault and the console
still answers 503, check the user variable before suspecting the password:

```bash
az containerapp show -g "$GROUP" -n <container-app-name> \
  --query "properties.template.containers[0].env[?starts_with(name,'CONSOLE')].name" -o tsv
```

Both names should be listed, or `CONSOLE_USER` absent altogether — an absent
`CONSOLE_USER` takes the application's default, an empty one does not.

**A `200` is the failure that matters**: it means the console is serving the
database to anyone who finds the address, which is the exact thing this password
exists to prevent. Stop and fix it before going further.

The status code is not enough on its own — confirm nothing came with it:

```bash
curl -s "$URL/console/observacoes" | head -c 300; echo
```

You should get a short refusal and nothing else: no table, no site code, no
value, no date. If any data is in that body, the guard ran too late.

A wrong password must be indistinguishable from no password at all:

```bash
curl -s -o /dev/null -w '%{http_code}\n' -u "console:definitely-not-the-password" \
  "$URL/console/observacoes"
```

Expect `401` again, with the same body as above. Then present the real pair and
confirm the console does open:

```bash
CONSOLE_USER=$(az keyvault secret show --vault-name "$VAULT" --name console-user --query value -o tsv 2>/dev/null || echo console)
CONSOLE_PASS=$(az keyvault secret show --vault-name "$VAULT" --name console-password --query value -o tsv)

curl -s -o /dev/null -w '%{http_code}\n' -u "$CONSOLE_USER:$CONSOLE_PASS" "$URL/console/observacoes"
curl -s -u "$CONSOLE_USER:$CONSOLE_PASS" "$URL/console/observacoes" | grep -c '<table'
```

Expect `200` and at least one table. If the status is `200` and the page holds
no rows, the console reached the API and the database is empty — which is the
normal state of a fresh installation, and step 8 is the proof the schema exists.

In a browser, `$URL/console` now raises the browser's own credentials box. That
is why HTTP basic was chosen here and not a header: it is the one scheme a
browser can answer from the address bar.

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
   by asking for a station sync, which needs no *external* credential:
   `POST /api/v1/sites/{code}/weather/sync` — it does need the `X-API-Key`
   header, like every route except `/api/v1/health`.
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
