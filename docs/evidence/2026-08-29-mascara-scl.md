# Evidência — máscara SCL ao pixel, e o que ela diz sobre 24/08 (29/08/2026)

Esta nota responde a uma pergunta que ficou aberta a 28/08/2026: **os índices
anómalos de 24 de Agosto sobre Campo Real eram contaminação por nuvem, ou eram
sinal?**

A nota da Fase B (`docs/evidence/2026-08-29-fase-b.md`) deixou a pergunta em aberto
de forma deliberada — *"os valores são anómalos; nenhuma das duas explicações foi
excluída; excluir uma delas exige uma máscara de nuvens ao pixel, que este pipeline
não aplica"*. O pipeline passou a aplicá-la. Esta nota traz os números.

**Esta nota substitui a formulação provisória de 28/08 e há um registo anterior a
corrigir.** Ver a secção final.

Todos os números abaixo foram recolhidos a 29/08/2026, entre as **12:06 e as 13:15
UTC**, contra a base `resoiltwin` local e contra o Copernicus Data Space Ecosystem.
Nada foi reaproveitado da nota da Fase B a não ser, onde está dito, os valores `v1`
que continuam gravados na base e foram relidos daí.

---

## Resposta curta

**Em 24/08/2026, 57 432 dos 62 750 pixels de Campo Real — 91,5% da AOI — foram
excluídos pela máscara SCL como nuvem, sombra ou cirro.** Removidos esses pixels, o
NDVI sobe de 0,2111 para 0,4130 e o NDRE de 0,1531 para 0,3018, ambos de volta à
gama do resto da série: **a queda do NDVI e do NDRE era nuvem**. O NDMI **não**
volta ao normal — sobe ainda mais, de 0,1847 para 0,2313, quatro vezes acima do
máximo do resto da série mascarada.

Mas os 5 318 pixels que sobram são **8,5% da AOI**, e não são uma amostra aleatória
dela: são exactamente as janelas que calharam estar limpas numa paisagem 92%
encoberta. A média sobre eles não é comparável com as médias sobre a AOI inteira dos
outros dias. **24/08 não é uma data utilizável para nenhuma afirmação ao nível da
paisagem — nem a favor nem contra a hipótese do solo.**

E, a caminho desta resposta, a razão de existir esta tarefa fica demonstrada com
números: **a percentagem de nuvem da cena não prevê a contaminação da AOI.**

---

## O que foi corrido

Dois `sync` reais, um por AOI, pelas rotas HTTP, com a máscara ligada (`scl_mask`
por omissão é `true`), na janela **2026-08-01 a 2026-08-29**.

```bash
cd ~/Cods/resoiltwin && source .venv/bin/activate
set -a && . ./.env && set +a
alembic upgrade head
uvicorn resoiltwin.main:app --host 127.0.0.1 --port 8031 &

API=http://127.0.0.1:8031/api/v1
curl -X POST $API/sites/EUC-TUR-01/eo/sync -H 'Content-Type: application/json' \
  -d '{"aoi_code":"EUC-TUR-EO1","date_from":"2026-08-01","date_to":"2026-08-29","scl_mask":true}'
curl -X POST $API/sites/EUC-PTO-01/eo/sync -H 'Content-Type: application/json' \
  -d '{"aoi_code":"EUC-PTO-EO1","date_from":"2026-08-01","date_to":"2026-08-29","scl_mask":true}'
```

Resposta real dos dois:

```
HTTP 202
{"id":"66a47279-1757-42ca-a385-a07b8f4f3a68","aoi_id":"352d4000-ff52-459a-ad30-07a9c1279431",
 "job_type":"eo_sync","status":"succeeded","date_from":"2026-08-01","date_to":"2026-08-29",
 "request_hash":"0a4bb5ac47a3e414703d16fb7dd96bc9ee69abc665f760b8b968c8a2ddbbd50b",
 "started_at":"2026-08-29T12:06:14.795521Z","finished_at":"2026-08-29T12:06:18.398835Z",
 "rows_written":33,"error":null}

HTTP 202
{"id":"b0edfb53-acc5-4e1a-ae02-d8958e9be2ff","aoi_id":"b93ce717-a8fa-4f3a-a8df-76e7debce3e7",
 "job_type":"eo_sync","status":"succeeded","date_from":"2026-08-01","date_to":"2026-08-29",
 "request_hash":"9489a99418a19be61f5bb9d1b14e4cb397a8910c12f54f74dda360add41e6ac3",
 "started_at":"2026-08-29T12:06:27.891775Z","finished_at":"2026-08-29T12:06:29.336565Z",
 "rows_written":21,"error":null}
```

**Os dois vieram `succeeded`, e é o `status` que o diz, não o 202.** `sync_aoi()` não
propaga falhas: um job que rebente na Statistical API sai igualmente com 202 e com
`status: "failed"`. Foi o campo `status` que se leu, nos dois.

33 linhas = 11 datas × 3 índices. 21 = 7 × 3. Os mesmos totais da Fase B, porque as
mesmas datas continuam a ter aquisição — a máscara não elimina datas, altera valores.

**A janela foi até 29/08 de propósito**, um dia à frente do fim da Fase B. Não
apareceu nenhuma data nova: a última aquisição utilizável de Turcifal continua a ser
24/08. O Catalog explica porquê — ver a tabela de nebulosidade mais abaixo.

### O `v1` ficou intacto

```
$ contagem por source_type e processing_version
('derived',             'vpd-tetens-v1',                     4)
('observed_screening',  'field-campaign-v1',                27)
('satellite_observed',  's2-ndvi-ndmi-ndre-scl-v2+9d560fddf3f1', 54)
('satellite_observed',  's2-ndvi-ndmi-ndre-v1+f03f9beed32d',     54)
total 139
```

As 54 linhas originais continuam lá, com a `processing_version` antiga
(`s2-ndvi-ndmi-ndre-v1+f03f9beed32d`), e as 54 novas entram ao lado com
`s2-ndvi-ndmi-ndre-scl-v2+9d560fddf3f1`. 85 → 139. **As duas séries coexistem, que é
o que torna esta comparação possível de todo:** a `processing_version` faz parte da
identidade da observação (`uq_observation_identity`), portanto a série mascarada não
substitui nem apaga a não mascarada.

---

## A comparação, data a data — `EUC-TUR-01` / Campo Real

A coluna **contrib** é `sampleCount − noDataCount`, não o campo `valid_pixels` do
`evidence` — que, apesar do nome, guarda o `sampleCount` e inclui os descartados. É a
armadilha já registada na Fase B, e continua por corrigir.

| data | NDVI v1 | NDVI v2 | Δ | NDMI v1 | NDMI v2 | Δ | NDRE v1 | NDRE v2 | Δ | contrib v1 | contrib v2 | pixels excluídos | % da AOI |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-08-01 | 0,4851 | 0,4852 | +0,0001 | 0,0543 | 0,0543 | +0,0000 | 0,3395 | 0,3395 | +0,0001 | 62 750 | 62 702 | 48 | **0,08%** |
| 2026-08-04 | 0,3966 | 0,4848 | +0,0882 | 0,0748 | 0,0591 | −0,0157 | 0,2847 | 0,3455 | +0,0608 | 62 750 | 32 253 | 30 497 | **48,60%** |
| 2026-08-06 | 0,4657 | 0,4658 | +0,0001 | 0,0278 | 0,0279 | +0,0001 | 0,2999 | 0,3000 | +0,0000 | 62 750 | 62 702 | 48 | 0,08% |
| 2026-08-08 | 0,4338 | 0,4338 | +0,0000 | 0,0248 | 0,0248 | +0,0000 | 0,3072 | 0,3072 | +0,0000 | 62 750 | 62 734 | 16 | 0,03% |
| 2026-08-09 | 0,3485 | 0,4380 | +0,0895 | 0,0768 | 0,0584 | −0,0184 | 0,2268 | 0,2948 | +0,0680 | 62 750 | 24 449 | 38 301 | **61,04%** |
| 2026-08-11 | 0,4749 | 0,4750 | +0,0001 | 0,0311 | 0,0312 | +0,0001 | 0,3321 | 0,3321 | +0,0000 | 62 750 | 62 698 | 52 | 0,08% |
| 2026-08-16 | 0,4611 | 0,4611 | +0,0000 | 0,0139 | 0,0140 | +0,0001 | 0,3028 | 0,3028 | −0,0000 | 62 750 | 62 706 | 44 | 0,07% |
| 2026-08-18 | 0,4415 | 0,4415 | +0,0000 | 0,0108 | 0,0109 | +0,0001 | 0,3111 | 0,3111 | +0,0000 | 62 750 | 62 718 | 32 | 0,05% |
| 2026-08-19 | 0,4107 | 0,4431 | +0,0324 | 0,0373 | 0,0317 | −0,0056 | 0,2733 | 0,2948 | +0,0216 | 62 750 | 45 015 | 17 735 | **28,26%** |
| 2026-08-21 | 0,4641 | 0,4641 | +0,0001 | 0,0303 | 0,0303 | +0,0000 | 0,3256 | 0,3257 | +0,0000 | 62 750 | 62 706 | 44 | 0,07% |
| **2026-08-24** | **0,2111** | **0,4130** | **+0,2019** | **0,1847** | **0,2313** | **+0,0465** | **0,1531** | **0,3018** | **+0,1486** | **62 750** | **5 318** | **57 432** | **91,53%** |

Duas leituras de sanidade antes de qualquer conclusão:

- **Nos dias limpos a v2 reproduz a v1 até à quarta casa decimal.** Isso é o que se
  quer de uma máscara: onde não há nuvem, não muda nada. Não é um *no-op*, no entanto
  — 16 a 52 pixels (0,03–0,08%) são sempre excluídos, dispersos, e o efeito nas
  médias é da ordem de 0,0001.
- **Nos dias parcialmente mascarados, a máscara move sempre os três índices no mesmo
  sentido:** NDVI e NDRE **sobem**, NDMI **desce** (04/08, 09/08, 19/08). É o sentido
  esperado — a nuvem baixa NDVI/NDRE e sobe NDMI, portanto tirá-la faz o inverso.
  **24/08 é a única data que quebra este padrão:** NDVI e NDRE sobem como nas outras,
  mas o NDMI **também sobe**. Isto está registado, não explicado.

---

## A pergunta concreta: 24 de Agosto

**Quantos pixels foram excluídos:** 57 432 de 62 750, ou seja **91,53% da AOI**.
Sobram **5 318 pixels** — 8,47% da área, cerca de 53 ha dos 623,6 ha de Campo Real.

**Os índices dos que sobraram continuam anómalos?** Depende do índice, e a resposta
tem três partes:

| índice | v1 (24/08) | v2 (24/08) | gama da série v2 sem 24/08 | veredicto |
|---|---|---|---|---|
| NDVI | 0,2111 | 0,4130 | 0,4338 – 0,4852 | volta praticamente ao normal; fica marginalmente abaixo do mínimo |
| NDRE | 0,1531 | 0,3018 | 0,2948 – 0,3455 | **dentro** da gama; deixa de ser anómalo |
| NDMI | 0,1847 | **0,2313** | 0,0109 – 0,0591 | **continua anómalo, e piora**: 3,9× o máximo da série |

1. **A queda do NDVI e do NDRE era nuvem.** Não é inferência: os pixels que a
   produziam foram identificados um a um pela SCL como nuvem, sombra ou cirro, e
   removê-los devolve valores dentro da série. A hipótese "contaminação" está
   confirmada para estes dois índices.

2. **A subida do NDMI não se explica por remoção de nuvem — ao contrário, agrava-se.**
   Nas outras três datas parcialmente encobertas, tirar nuvem *baixou* o NDMI. Aqui
   subiu-o.

3. **E ainda assim isto não sustenta a hipótese do solo.** Com 8,47% da AOI a
   sobreviver, a média da v2 de 24/08 **não é a mesma quantidade** que as médias dos
   outros dias: é a média sobre um recorte de 53 ha escolhido pela geometria das
   nuvens, não sobre os 623,6 ha da AOI. Comparar 0,2313 com o 0,0303 de 21/08 é
   comparar duas áreas diferentes. Há ainda um mecanismo concreto de contaminação
   residual: a nossa máscara **mantém** a classe SCL 7 (*unclassified*), e numa cena
   92% encoberta os pixels sobreviventes são desproporcionadamente adjacentes a
   nuvem, onde a SCL é menos fiável e onde cirros finos e penumbra escapam.

**Conclusão sobre 24/08, e é o terceiro dos três resultados possíveis:**
foram excluídos muitos pixels **e sobram poucos demais para significar**. A data
serve para dizer que a paisagem estava encoberta; não serve para dizer nada sobre a
água na paisagem, nem para confirmar nem para negar o que a sonda leu no solo.

---

## O contraexemplo: 1 de Agosto, e a demonstração que motiva a tarefa

A Fase B levantou a suspeita certa: a nebulosidade da **cena** não prevê a
contaminação da **AOI**. Com a máscara ao pixel isso deixa de ser argumento e passa a
ser medida. Consulta ao Catalog do Copernicus feita a 29/08/2026, sem filtro de
nuvem, para a mesma AOI e janela, ao lado da fracção da AOI que a SCL mascarou:

| data | nuvem da **cena** (`eo:cloud_cover`) | % da **AOI** mascarada | |
|---|---|---|---|
| 2026-08-01 | 15,50 / **29,13** | **0,08%** | ← cena quase no limiar, AOI limpa |
| 2026-08-04 | 24,54 | 48,60% | |
| 2026-08-06 | 0,04 | 0,08% | |
| 2026-08-08 | 0,46 | 0,03% | |
| 2026-08-09 | **7,24** | **61,04%** | ← cena quase limpa, AOI maioritariamente encoberta |
| 2026-08-11 | 5,86 / 11,44 | 0,08% | |
| 2026-08-16 | 2,16 | 0,07% | |
| 2026-08-18 | 18,03 | 0,05% | |
| 2026-08-19 | 17,82 | 28,26% | |
| 2026-08-21 | 0,12 / 0,50 | 0,07% | |
| 2026-08-24 | 29,94 | 91,53% | |

**Os dois casos assinalados matam a métrica da cena como indicador:**

- **01/08 tem uma cena a 29,13%** — a segunda mais nublada da janela, a um passo do
  limiar de 30% que a teria excluído — **e 0,08% da AOI mascarada.** A nuvem estava
  toda fora de Campo Real. Foi o NDVI mais alto de toda a série, e continua a sê-lo
  depois de mascarado (0,4852).
- **09/08 tem uma cena a 7,24%** — das mais limpas — **e 61,04% da AOI mascarada.**
  Uma data que qualquer filtro de cena teria aceite sem hesitar tinha quase dois
  terços da nossa área debaixo de nuvem. O NDVI que a Fase B publicou para esse dia
  (0,3485, o mais baixo da série depois de 24/08) era uma média com 61% de nuvem
  dentro.

Sobre as duas séries de 11 pontos, a correlação entre nebulosidade da cena e fracção
mascarada da AOI é **r = 0,51** (Pearson) e **ρ = 0,47** (Spearman). **Estes números
não devem ser citados como estimativas** — com n = 11 e uma distribuição destas são
descritivos e nada mais; estão aqui só para dizer que nem sequer a ordenação se
aguenta. O que sustenta a conclusão são os dois casos acima, não o coeficiente.

**Consequência prática, e vale para lá desta janela:** `maxCloudCoverage` ao nível da
cena não é um controlo de qualidade da AOI. Não é inútil — evita gastar pedidos em
cenas inteiramente encobertas — mas não diz nada sobre o que se passa por cima dos
nossos polígonos. Só a contagem ao pixel diz.

### Porque é que não apareceu data nova até 29/08

O Catalog, consultado sem filtro de nuvem, mostra três passagens que o `sync` não
usou, todas por estarem acima do limiar de 30%:

```
2026-08-14  cloud_cover=[80.40]   acima do limiar
2026-08-26  cloud_cover=[73.82]   acima do limiar
2026-08-28  cloud_cover=[33.52]   acima do limiar, por pouco
```

Ou seja: a janela alargada até 29/08 apanhou duas passagens novas (26 e 28), e
nenhuma entrou. A de 28/08, a 33,52%, falha o limiar por 3,5 pontos — e, à luz da
tabela acima, **não se pode dizer se a AOI estava ou não encoberta nesse dia**: a
percentagem da cena não o diz. Repetir esse dia com um limiar mais alto e ler a
contagem ao pixel é o que responderia, e fica por fazer.

---

## `EUC-PTO-01` / Parque de Requesende — a máscara não muda nada

| data | NDVI v1 | NDVI v2 | NDMI v1 | NDMI v2 | NDRE v1 | NDRE v2 | contrib v1 | contrib v2 | excluídos |
|---|---|---|---|---|---|---|---|---|---|
| 2026-08-06 | 0,4074 | 0,4074 | 0,0207 | 0,0207 | 0,2683 | 0,2683 | 1 095 | 1 095 | 0 |
| 2026-08-08 | 0,4041 | 0,4041 | 0,0171 | 0,0171 | 0,2851 | 0,2851 | 1 095 | 1 095 | 0 |
| 2026-08-09 | 0,4091 | 0,4091 | 0,0112 | 0,0112 | 0,2817 | 0,2817 | 1 095 | 1 095 | 0 |
| 2026-08-11 | 0,3393 | 0,3393 | 0,0047 | 0,0047 | 0,2456 | 0,2456 | 1 095 | 1 095 | 0 |
| 2026-08-16 | 0,4377 | 0,4377 | 0,0045 | 0,0045 | 0,2916 | 0,2916 | 1 095 | 1 095 | 0 |
| 2026-08-18 | 0,4072 | 0,4072 | 0,0131 | 0,0131 | 0,2931 | 0,2931 | 1 095 | 1 095 | 0 |
| 2026-08-21 | 0,4135 | 0,4135 | 0,0204 | 0,0204 | 0,2983 | 0,2983 | 1 095 | 1 095 | 0 |

**Zero pixels excluídos em todas as sete datas, e os valores idênticos à quarta casa.**
As sete datas que o Porto tem são as sete em que a cena estava limpa sobre ele; as
datas nubladas (01, 04, 19 e 24 de Agosto, todas acima de 30% no Porto) nunca chegaram
a entrar. É um controlo útil: mostra que a v2 não introduz deriva sistemática, e que
o que se vê em Turcifal a 24/08 é nuvem localizada, não um artefacto do novo script.

Os 1 406 `no_data_pixels` do Porto continuam a ser geometria — pixels da caixa
envolvente fora do polígono irregular do parque — e não nuvem.

**Limitação nova, e é preciso registá-la:** na v2 o `no_data_pixels` passa a somar
duas coisas diferentes — pixels fora do polígono **e** pixels excluídos pela SCL — sem
as distinguir. Em Turcifal são separáveis porque a v1 dá 0 fora do polígono; no Porto
são separáveis porque a SCL excluiu 0. Numa AOI irregular com nuvem parcial deixariam
de o ser. Gravar as duas contagens em separado fica como dívida técnica.

---

## O que mudou no código

**`processing_version` no `IngestionJobRead`.** Até aqui, pela API, não se conseguia
dizer se um job tinha corrido com máscara sem ir à tabela de observações — e um job
que escrevesse zero linhas não tinha sequer onde ser lido. A coluna foi acrescentada
a `ingestion_jobs` (migração `0007`), é preenchida no momento em que o job é criado
(antes da rede, para que um job falhado também a declare) e sai na resposta das duas
rotas.

A coluna é **anulável e não há backfill**. Os jobs anteriores à migração — incluindo
os dois desta nota, que correram antes de a coluna existir — lêem `null`, e `null`
significa *"não registado"*, não *"sem máscara"*. Preenchê-los com a versão que se
presume que usaram seria escrever proveniência que ninguém observou, que é o
contrário do que esta coluna existe para permitir:

```
$ curl -s $API/jobs/66a47279-1757-42ca-a385-a07b8f4f3a68
{"id":"66a47279-...","job_type":"eo_sync","status":"succeeded",
 "request_hash":"0a4bb5ac...","processing_version":null,
 "rows_written":33,"error":null}
HTTP 200
```

A versão destes dois jobs é recuperável pelas linhas que escreveram
(`s2-ndvi-ndmi-ndre-scl-v2+9d560fddf3f1`), que é exactamente o trabalho manual que o
campo passa a evitar de agora em diante.

Quatro testes novos cobrem-no: a versão declarada pelo job coincide com a que ficou
nas observações; as duas escolhas de máscara são distinguíveis só pela rota; **um job
`failed` declara na mesma a versão com que tentou correr** — o caso que justifica
guardá-la no job em vez de a deduzir das observações; e o `GET /jobs/{id}` devolve o
mesmo que o `POST`.

---

## Registo anterior a corrigir

A nota da Fase B (`docs/evidence/2026-08-29-fase-b.md`, secção *"A anomalia de
2026-08-24, e o que não se pode concluir dela"*) diz:

> os valores de 2026-08-24 são **anómalos** face ao resto da série; **nenhuma** das
> duas explicações — sinal real ou contaminação — foi excluída.

**Esta formulação fica substituída.** Com a máscara ao pixel:

- Para o **NDVI e o NDRE**, a explicação por contaminação está **confirmada**, não
  apenas não excluída. 91,53% da AOI era nuvem, sombra ou cirro; removida, os valores
  voltam à série.
- Para o **NDMI**, nenhuma das duas explicações foi excluída — e o valor mascarado
  não ajuda a decidir, porque assenta em 8,47% da AOI.
- A afirmação de que houve **"a primeira correspondência solo↔satélite do projecto"**
  a 24/08 continua sem suporte, e agora por uma razão documentada em vez de uma
  suspeita: o valor citado vinha de uma AOI 92% encoberta.

**E há uma segunda correcção, sobre o raciocínio e não sobre a conclusão.** A
retratação feita a 28/08 atribuiu a anomalia a nuvem. A única medida de nuvem que
existia nessa data eram os 29,94% da cena — e esta nota mostra que esse número não
sustentava a inferência: 01/08, a 29,13%, tinha 0,08% da AOI mascarada, e 09/08, a
7,24%, tinha 61%. **A conclusão estava certa; o indicador em que assentava não
funciona.** Quem repita o argumento na forma *"era nuvem, a cena tinha 30%"* está a
usar uma métrica que os dados desta nota mostram não servir. A prova é a contagem ao
pixel, e só essa.

---

## O que esta nota continua a não confirmar

As três ressalvas da Fase B mantêm-se por inteiro, e a máscara não toca em nenhuma:

1. **O satélite não mede humidade do solo.** NDVI, NDMI e NDRE respondem ao coberto
   vegetal. A única medição de solo do projecto continua a ser a sonda de rastreio.
2. **Nada disto é validação agronómica.** Sem calibração, sem correlação estabelecida,
   sobre 29 dias de Agosto de 2026 e duas áreas.
3. **Continua a não haver camada meteorológica nem Sentinel-1.** Sem balanço hídrico,
   nenhum índice espectral se converte em afirmação sobre água no solo; e sem radar,
   os dias encobertos não têm cobertura nenhuma — 24/08 é precisamente o dia em que
   isso teria feito diferença.

Acrescenta-se uma quarta, específica desta fase:

4. **A máscara SCL não é verdade absoluta.** É a classificação do próprio produto L2A,
   com os seus falsos positivos e negativos, e mantemos a classe 7 (*unclassified*)
   por ser superfície real na esmagadora maioria dos casos. Numa cena maioritariamente
   encoberta essa escolha deixa entrar mais dúvida do que numa cena limpa.

---

## Suite de testes e análise estática

```
$ pytest -q
........................................................................ [ 35%]
........................................................................ [ 71%]
.........................................................                [100%]
201 passed in 4.95s

$ ruff check .
All checks passed!
```

197 testes antes desta tarefa, 201 depois. Nenhum toca a rede: as respostas do
Copernicus são simuladas por transporte HTTP de teste. As únicas chamadas reais foram
os **dois** `sync` desta nota e **uma** consulta ao Catalog para a tabela de
nebulosidade.
