# ReSoilTwin

Backend de digital twin de solo, com dados geoespaciais em PostGIS. Serve o
projeto ReSoilTwin da Euro Union Consult, no âmbito da candidatura ao
programa TRAILS4SOIL.

## O que isto é

- Um modelo de dados PostGIS para sítios, áreas de interesse (AOIs), parcelas
  e pontos de observação, com proveniência explícita em cada valor.
- Uma API FastAPI para registar sítios/AOIs/parcelas, ingerir observações e
  consultar séries temporais por site/métrica/parcela/tipo de fonte.
- Um motor de features que deriva Vapour Pressure Deficit (VPD) a partir de
  temperatura do ar e humidade relativa (equação de Tetens).
- Um seed com os dados reais da campanha de campo de Turcifal, 22–24 de
  agosto de 2026: 27 leituras de rastreio (`observed_screening`) mais 4
  valores de VPD derivados (`derived`).

Isto é a Fase A de um plano maior. Está feito e verificado ponta a ponta
(ver `docs/evidence/2026-08-28-fase-a.md`); as fases seguintes (conector
Copernicus, camada meteorológica, emulador, Azure, frontend) estão descritas
em `docs/plans/2026-08-28-fase-a-backend-dados-reais.md` e não estão
implementadas.

## O que isto NÃO é

- **Não há dados de satélite.** O conector Copernicus (Sentinel via CDSE) é
  a Fase B do plano e está bloqueado por duas coisas fora do código: AOIs
  ainda provisórias e uma credencial CDSE por confirmar. Nenhuma chamada foi
  feita à API Copernicus nesta fase.
- **Não há sensores instalados.** O único instrumento no seed é um
  DUO TERRA multi-parâmetro de rastreio de retalho, `calibration_status =
  uncalibrated`. Não existe estação meteorológica nem sonda calibrada no
  terreno.
- **Não há validação agronómica.** Os valores derivados (VPD) são cálculos
  físicos sobre leituras de rastreio, não medições de referência
  confirmadas em laboratório ou por perito.
- **Não há autenticação.** A API não implementa Entra ID nem qualquer outro
  mecanismo de autorização. Nesta fase corre apenas em `localhost` e não
  deve ser exposta publicamente.

## Requisitos

- Python 3.12
- Docker Desktop (base de dados local)

## Configuração local

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env
```

## Base de dados

```bash
docker compose up -d db
```

A base de dados fica disponível em `127.0.0.1:55433` (porta escolhida para
não colidir com outros projetos que usem a 55432; o bind é deliberadamente a
`127.0.0.1` e não a `0.0.0.0`, para não expor a base de dados de
desenvolvimento à rede local).

## Migrações

```bash
alembic upgrade head
```

Há cinco migrações (`0001`–`0005`): sítios/AOIs/parcelas/pontos de
observação/instrumentos, depois observações com valores censurados e em
intervalo, depois a constraint que obriga o `value_qualifier` a corresponder
aos campos de valor preenchidos, depois os domínios dos enums, a coerência
entre censura e qualificador e a coluna `derived_from`, e por fim a correcção
dessas duas últimas guardas para que passem a morder no caminho de escrita que
o código de produção usa.

As migrações não importam nada do pacote `resoiltwin`: o texto SQL das
constraints está escrito por extenso dentro de cada uma. Uma migração é um
artefacto congelado e tem de continuar a correr no dia em que um módulo da
aplicação mudar de nome — caso contrário deixa de ser possível construir uma
base do zero a partir da história.

A suite de testes constrói a base de teste com `alembic upgrade head`, e não
a partir dos modelos — assim uma migração partida falha em todos os testes em
vez de só falhar na primeira base real criada em produção.

### O que a base impõe (e porque não basta o Python)

`Mapped[SourceType]` com `mapped_column(String(32))` é decorativo: o
SQLAlchemy trata o valor como texto e não valida nada. Um job de ingestão que
escreva pelo ORM — que é como as fases seguintes vão escrever, sem passar pela
validação Pydantic da API — conseguia gravar `source_type = 'observed'`, o
valor que o enum omite deliberadamente. A migração `0004` põe a regra na única
camada que nenhuma fase contorna:

| Constraint | O que impede |
|---|---|
| `ck_observation_source_type_domain` | `source_type` fora do enum (`observed`, `totalmente_inventado`) |
| `ck_observation_quality_flag_domain` | `quality_flag` fora do enum |
| `ck_observation_value_qualifier_domain` | `value_qualifier` fora do enum |
| `ck_observation_processing_version_not_blank` | `processing_version` vazio ou só com espaços |
| `ck_censoring_flag_matches_qualifier` | uma leitura marcada como saturada mas guardada como escalar exacto (e o mesmo para `range_value`/`range`) |
| `ck_derived_needs_method_and_inputs` | um `derived` sem `method` e sem forma de documentar as entradas |
| `ck_aoi_status_domain` | `status = 'Approved'` (maiúscula) a contornar a guarda de aprovação |
| `ck_aoi_geometry_provenance_domain` | `geometry_provenance` fora do enum |

Nos **modelos**, as listas de valores são geradas a partir de
`src/resoiltwin/enums.py` (ver `src/resoiltwin/constraints.py`) e não escritas
à mão. Nas **migrações** estão congeladas por extenso. Que os dois lados
continuem a dizer o mesmo é verificado por `tests/test_schema_parity.py`, que
compara cada `CheckConstraint` declarada nos modelos com a constraint do mesmo
nome na base construída por `alembic upgrade head`, nos dois sentidos, com as
definições normalizadas pelo próprio PostgreSQL. Este teste é necessário
porque o autogenerate do Alembic 1.13 não compara CheckConstraints: uma
divergência não apareceria em lado nenhum até à primeira base construída de
raiz.

Duas notas sobre a forma destas guardas, porque as duas foram erradas à
primeira:

- `ck_censoring_flag_matches_qualifier` é uma implicação **num só sentido**
  (saturado obriga a censurado), não uma equivalência. `quality_flag` é uma
  avaliação de qualidade e `value_qualifier` é a semântica do valor; exigir o
  par tornava impossível gravar um valor censurado ainda por avaliar, e
  `unchecked` é o valor por omissão do modelo.
- Em JSONB há dois nulos: o SQL NULL e o literal JSON `null`. O SQLAlchemy
  grava `None` como o segundo se a coluna não for declarada com
  `none_as_null=True`, e por isso `evidence IS NOT NULL` era sempre verdadeiro
  e a guarda de linhagem não mordia. Pela mesma razão, um CHECK que avalie a
  NULL **passa**: as condições sobre `evidence` e `derived_from` estão
  envolvidas em `COALESCE` de propósito.

### Auditar um valor derivado para trás

`observations.derived_from` guarda os identificadores das observações que
produziram um valor. Os 4 VPD do seed apontam para as leituras de temperatura
do ar e humidade relativa do mesmo instante, e o valor guardado é reprodutível
a partir delas — é o que o teste
`test_vpd_can_be_audited_back_to_the_measurements_that_produced_it` verifica.
Não é chave estrangeira porque o PostgreSQL não suporta foreign keys sobre
elementos de um array; `evidence` continua a ser a alternativa aceite para os
derivados cuja origem não é uma observação (a camada meteorológica da Fase C
terá tabela própria).

## Seed

```bash
source .venv/bin/activate
python -c "from resoiltwin.db import SessionLocal; from seeds.turcifal_2026_08 import seed_turcifal; s=SessionLocal(); print(seed_turcifal(s)); s.close()"
```

Carrega a campanha de campo de Turcifal. É idempotente — reexecutar não
duplica. Devolve `{'sites': 1, 'plots': 2, 'instruments': 1, 'observations':
27, 'derived': 4}`.

## Testes

```bash
pytest
```

## Correr a API localmente

```bash
uvicorn resoiltwin.main:app --reload
```

Exemplos:

```bash
curl "http://127.0.0.1:8000/api/v1/sites/EUC-TUR-01/timeseries?metric=soil_moisture_screening&plot=TUR-CANOPY"
curl "http://127.0.0.1:8000/api/v1/sites/EUC-TUR-01/timeseries?metric=vpd"
```

Os outputs reais destes dois comandos, correndo contra a porta 8123 durante
a verificação de 28/08/2026, estão em
`docs/evidence/2026-08-28-fase-a.md`.

## `source_type`: o que cada valor significa

Cada observação carrega um `source_type` explícito. Não existe valor por
omissão — quem grava a observação tem de decidir a que categoria pertence.

| `source_type` | Significado |
|---|---|
| `observed_screening` | Leitura de instrumento de rastreio de retalho, **não calibrado**. É o que as 27 leituras da campanha de Turcifal são. |
| `observed_reference` | Leitura de sensor calibrado e rastreável. Não existe nenhuma no seed actual. |
| `observed_lab` | Resultado de análise laboratorial. |
| `satellite_observed` | Derivado de uma aquisição Sentinel via Copernicus. Fase B, ainda não implementada. |
| `weather_observed` | Leitura de estação meteorológica. Fase C, ainda não implementada. |
| `reanalysis` | Produto de modelo tipo ERA5-Land — não é medição directa. Fase C. |
| `simulated` | Saída do emulador de balanço hídrico. Fase D, ainda não implementada. Nunca é efeito real medido no terreno. |
| `derived` | Produto calculado sobre as camadas acima. É o que os 4 valores de VPD do seed são: calculados pela equação de Tetens a partir de temperatura e humidade, **não medidos** directamente. |

### Porque é que `observed` não existe

O enum `SourceType` (`src/resoiltwin/enums.py`) omite deliberadamente um
valor genérico `observed`. Um valor assim seria ambíguo entre a leitura de
um instrumento de rastreio de retalho e a leitura de um sensor calibrado —
e essa ambiguidade destruía exactamente a distinção de que a auditabilidade
do produto (MRV — measurement, reporting, verification) depende. Ao obrigar
a escolha explícita entre `observed_screening`, `observed_reference` e
`observed_lab`, qualquer consulta à API já traz a proveniência do dado sem
ter de se voltar ao instrumento de origem para saber se é fiável.

## Porque é que o repositório vive fora de `~/Documents`

`~/Documents` neste Mac está sincronizado com o iCloud, que gere ficheiros
"dataless" (mantidos apenas na nuvem até serem abertos). O `git` bloqueia
indefinidamente a ler um ficheiro dataless, o que parte operações normais do
repositório de forma imprevisível. Por isso este repositório vive em
`~/Cods/resoiltwin`, fora de qualquer pasta sincronizada com o iCloud.

## Dívida técnica conhecida

- **Fase E (Azure), Key Vault sem Managed Identity.** A arquitectura desenhada
  assume Managed Identity e RBAC de menor privilegio. As permissoes disponiveis
  na subscricao de desenvolvimento nao permitem criar atribuicoes de papel, pelo
  que a Fase E usa Key Vault em **access policies** e connection strings. E menos
  seguro do que a arquitectura desenhada e esta declarado como divida tecnica, nao
  apresentado como o design final. Migra-se quando as permissoes mudarem.
- **Dois dos quatro polígonos geográficos do projecto são provisórios.**
  Nenhuma AOI está carregada na base de dados — a tabela `aois` está vazia,
  e o seed de Turcifal não cria nenhuma. O que existe é a delimitação em
  papel: `EUC-TUR-EO1` é hoje um retângulo inventado de 2×2 km e
  `EUC-PTO-EO1` tem área real mas centroide estimado. Quando forem
  carregados, a constraint `ck_aoi_provisional_never_approved` (em
  `migrations/versions/0001_sites_and_plots.py`) impede que qualquer AOI com
  `geometry_provenance = provisional_pending_kml` fique com
  `status = approved`. Isto é deliberado — resolve-se confirmando os
  limites reais no terreno (geojson.io, cerca de 20 minutos), mas alguém
  que conheça o terreno tem de o fazer; não é um passo de código.
