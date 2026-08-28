# Fase B — condições de entrada

Escrito no fecho da Fase A (28/08/2026, HEAD `af766ea`, 111 testes). Reúne o que as revisões
deixaram por corrigir e o que quem continuar precisa de saber antes de escrever o conector
Copernicus.

Nada nesta lista bloqueia o que a Fase A entrega. Tudo nela morde na Fase B, porque a Fase B
escreve por **jobs do lado do servidor**, e não por `POST /observations`.

---

## 1. Uma migração `0006` com quatro buracos da mesma família

São todos a mesma forma de defeito: uma guarda que parece imposta e não morde no caminho que o
código de produção usa. Três foram fechados durante a Fase A (`source_type` sem domínio,
`evidence` a `null` JSON, `derived_from` vazio); estes quatro ficaram.

| Buraco | Onde | Porque importa |
|---|---|---|
| `method = ''` ou `'   '` num `derived` | `ck_derived_needs_method_and_inputs` só exige `IS NOT NULL` | `method` é o "como" de um valor derivado. Em branco satisfaz a guarda e não documenta nada |
| `evidence = {}` | `jsonb_typeof('{}')` é `'object'` | **Alcançável pela rota pública** com 201. Recipiente vazio que não documenta origens |
| `derived_from = [NULL]` | `array_length` conta 1 | Só por ORM/jobs — que é o escritor da Fase B |
| `NULLS NOT DISTINCT` sem teste de comportamento | `uq_observation_identity` | É o que faz a deduplicação funcionar para linhas com `plot_id` NULL. As séries EO terão `plot_id` NULL. Os dois testes de 409 passam sempre `plot_code`, logo nunca exercitam o caso |

Fazer numa só migração. A razão de não os separar: a Fase B é exactamente o escritor que produz
recipientes vazios.

## 2. Um 500 anterior à Fase A, ainda vivo

`value_numeric = NaN` passa a validação Pydantic, **a linha é gravada**, e depois a serialização
da resposta rebenta com `Out of range float values are not JSON compliant`. O cliente vê um erro
de servidor e a escrita já ficou feita — pior do que um 500 normal, porque não é seguro repetir.

## 3. Limites do teste de paridade modelos↔migrações

`tests/test_schema_parity.py` compara `pg_get_constraintdef` e apanha:

- valor acrescentado a um enum sem migração correspondente
- constraint declarada no modelo que nenhuma migração cria, e o inverso
- constraint com nome diferente nos dois lados (falha nos dois sentidos)

**Não apanha:**

- mudança de tipo ou comprimento de coluna (`String(32)` → `String(64)` sem migração passa)
- remoção de `postgresql_nulls_not_distinct` de uma `UniqueConstraint`

Isto é uma regressão de cobertura consciente face ao `diff` de `pg_dump` que substituiu, que
cobria o schema inteiro. Se a Fase B acrescentar colunas com frequência, vale a pena reintroduzir
uma comparação de schema completo como teste.

## 4. Armadilhas que vão morder quem continuar

**Um `CHECK` que avalie a NULL passa.** Qualquer sub-expressão de uma constraint que possa dar
NULL tem de ser reduzida a um booleano definido, normalmente com `COALESCE`. O gatilho não é a
coluna ser anulável — é a expressão: `array_length('{}', 1)` devolve NULL para um array vazio
mesmo numa coluna `NOT NULL`, e `jsonb_typeof(NULL)` devolve NULL. Ambos já produziram guardas
cegas neste projecto. Atenção ao valor do `COALESCE`: num `CHECK` quer-se que o desconhecido dê
`FALSE`; num `WHERE` a correcção vai ao contrário.

**O Alembic 1.13 não compara `CheckConstraint`s no autogenerate.** Qualquer constraint nova entra
na migração à mão. O `alembic check` também não a vê, e na imagem PostGIS devolve ruído de
`spatial_ref_sys` que enterra qualquer sinal real.

**A imagem `postgis/postgis:16-3.4` traz `tiger_geocoder` e `topology`** — cerca de 40 tabelas
alheias. Qualquer autogenerate produz centenas de linhas a apagá-las. Todas as migrações deste
projecto foram escritas ou limpas à mão por causa disto.

**As migrações não importam nada do pacote `resoiltwin`.** É deliberado: uma migração que dependa
de código de aplicação deixa de correr no dia em que esse código mudar de sítio, e a história
deixa de ser reconstruível. `src/resoiltwin/constraints.py` é fonte única para os **modelos**;
as migrações levam os literais congelados.

**A ordem de avaliação de `CHECK`s no PostgreSQL é alfabética por nome.** Vários testes afirmam
sobre o nome da constraint que dispara. Quem acrescentar uma constraint com nome alfabeticamente
anterior tem de reverificar esses testes.

**`Site.timezone` e `Instrument.scale_max` existem e nenhum código os lê.** O primeiro vai
enganar quem implementar filtros por "dia local"; o segundo tem um docstring que promete marcar
saturações e não marca. Fechar a saturação a sério exige limites de escala **por métrica** —
`scale_max` é um valor único num instrumento multi-parâmetro e não serve para pH nem para
humidade do solo.

## 5. O que continua por implementar, por decisão

- `GET /api/v1/sites/{code}/observations` — nada a jusante depende dele; a Fase F (frontend) é
  que define de que forma precisa dos dados em bruto.
- `src/resoiltwin/api/deps.py` — nenhum módulo o importa; `get_session` vem sempre de
  `resoiltwin.db`.
- Rotas de `observation_points` — a sub-árvore existe no modelo e não há forma de a povoar.
  `ObservationCreate.observation_point_code` e o seu `_resolve` são código morto até lá.

## 6. Bloqueios fora do código

**Os dois polígonos de Earth Observation não existem.** `EUC-TUR-EO1` (Campo Real) nunca foi
delimitado; `EUC-PTO-EO1` tem área e perímetro documentados — que determinam univocamente um
rectângulo de **343,5 × 111,1 m**, erro 0,0000% — mas a posição e a rotação são desconhecidas.
A base impede-os de serem aprovados por constraint, e é assim que deve ser: o Statistical API
sobre um polígono inventado devolve estatísticas de sítio nenhum.

**A credencial CDSE está por confirmar.** O UUID disponível pode ser o OAuth Client ID ou o
Configuration/Instance ID; só o primeiro, com o respectivo secret, serve para as APIs Catalog,
Statistical e Process.

**Azure:** as permissões disponíveis na subscrição de desenvolvimento não permitem criar
atribuições de papel, logo Managed Identity não é possível. A Fase E usa Key Vault em *access policies* mais
connection strings, declarado como dívida técnica no README.
