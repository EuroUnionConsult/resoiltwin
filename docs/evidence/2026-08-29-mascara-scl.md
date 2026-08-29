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

> **Aviso de reprodutibilidade.** A base de desenvolvimento foi apagada por acidente
> mais tarde no mesmo dia e reposta a partir do zero. **Os valores desta nota foram
> todos reconfirmados na reposição, número a número.** Os identificadores não: os UUID
> de jobs e AOI citados abaixo, e os `started_at`/`finished_at`, são da execução
> original das 12:06 e não voltam. Ver *"A base foi reposta — o que se reproduz e o
> que não"*, no fim.

---

## Resposta curta

**Em 24/08/2026, 57 432 dos 62 750 pixels de Campo Real — 91,5% da AOI — foram
excluídos pela máscara SCL como nuvem, sombra ou cirro.** Os pixels que produziam a
queda foram identificados **um a um** pela classificação da cena, e removê-los move
os índices fortemente na direcção esperada: o NDVI sobe de 0,2111 para 0,4130, o NDRE
de 0,1531 para 0,3018. **A queda do NDVI e do NDRE em 24/08 era nuvem: isso fica
confirmado.**

**O que não fica confirmado é o valor que sobra.** Os 5 318 pixels restantes são
**8,5% da AOI**, e não são uma amostra aleatória dela: são exactamente as janelas que
calharam estar limpas numa paisagem 92% encoberta. E isso vale para os três índices
ao mesmo tempo — 0,4130, 0,3018 e 0,2313 são **a mesma média sobre os mesmos 5 318
pixels**. Nenhum dos três é uma estimativa do índice verdadeiro de 24/08 sobre a AOI,
e nenhum dos três se compara com as médias sobre a AOI inteira dos outros dias.

**As duas afirmações são separadas de propósito, e a nota de 28/08 não as separava.**
Uma é sobre a *causa* da queda e está demonstrada pela contagem ao pixel; a outra
seria sobre o *nível* do índice naquele dia e não está. **24/08 explica-se, mas não se
mede.**

Fica ainda registada uma observação que é sobre o mesmo dia e sobrevive inteira a esta
ressalva, porque compara 24/08 consigo próprio: nas outras três datas parcialmente
encobertas, tirar nuvem *baixou* o NDMI; aqui **subiu-o**, de 0,1847 para 0,2313. Isto
está registado, não explicado.

E, a caminho desta resposta, a razão de existir esta tarefa fica demonstrada com
números: **a percentagem de nuvem da cena não decide se a AOI está contaminada.** Há
associação entre as duas — não é ruído — mas ela quebra-se exactamente nos casos em
que precisaríamos dela.

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

Esta contagem descreve o estado da base às 12:06. Depois de a base ter sido apagada e
reposta, ainda a 29/08, a contagem é a mesma — 139, com a mesma repartição — mas as
54 linhas `v1` já não são as originais de 28/08: foram reingeridas. Ver a secção
final.

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

- **Nos dias limpos a v2 reproduz a v1 até à terceira casa decimal.** Isso é o que se
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

Há **duas** comparações possíveis com estes números, e só uma delas é legítima.

**A comparação que se aguenta é `v1` contra `v2` no mesmo dia.** Mesma data, mesma
AOI, mesma aquisição: a única diferença entre as duas médias é a remoção dos pixels
que a SCL classificou como nuvem, sombra ou cirro. O que ela mede é o efeito da
contaminação, e mede-o bem.

| índice | v1 (24/08) | v2 (24/08) | Δ | o que a diferença mostra |
|---|---|---|---|---|
| NDVI | 0,2111 | 0,4130 | **+0,2019** | os pixels removidos estavam a puxar o NDVI para baixo — sentido esperado da nuvem |
| NDRE | 0,1531 | 0,3018 | **+0,1486** | idem, e é o maior salto de NDRE de toda a série |
| NDMI | 0,1847 | 0,2313 | **+0,0465** | **sobe**, ao contrário das outras três datas mascaradas, onde a remoção de nuvem baixou o NDMI |

**A comparação que não se aguenta é 24/08 contra o resto da série.** As médias dos
outros dias são sobre os 623,6 ha da AOI; a de 24/08 é sobre um recorte de ~53 ha
escolhido pela geometria das nuvens. São quantidades diferentes com o mesmo nome. A
tabela abaixo fica como descrição — **não como veredicto** — e vale para os três
índices por igual:

| índice | v2 (24/08) | gama da série v2 sem 24/08 | leitura descritiva |
|---|---|---|---|
| NDVI | 0,4130 | 0,4338 – 0,4852 | **fica abaixo do mínimo da gama**, não dentro dela |
| NDRE | 0,3018 | 0,2948 – 0,3455 | cai dentro da gama |
| NDMI | 0,2313 | 0,0109 – 0,0591 | 3,9× o máximo da gama (0,2313 / 0,0591 = 3,91) |

**Nenhuma das três linhas é um veredicto sobre 24/08**, e é aqui que a versão anterior
desta nota se contradizia: usava o argumento dos 8,47% para anular o NDMI e ao mesmo
tempo aceitava o NDVI e o NDRE como valores comparáveis com os outros dias. É a mesma
média sobre os mesmos 5 318 pixels. Ou os três valem como estimativa da AOI, ou
nenhum vale — e nenhum vale.

Dito isto, o que se conclui:

1. **A queda do NDVI e do NDRE era nuvem, e isso está confirmado.** Não é inferência:
   os pixels que a produziam foram identificados um a um pela SCL como nuvem, sombra
   ou cirro, e removê-los move os dois índices +0,2019 e +0,1486 na direcção esperada.
   A hipótese "contaminação" está confirmada **como explicação da queda**.

2. **O que está confirmado é a explicação, não o nível.** Que a queda era nuvem não
   torna 0,4130 o NDVI de Campo Real a 24/08. E, de facto, 0,4130 **não** volta à gama
   da série: fica abaixo do mínimo (0,4338). O NDRE volta à gama; o NDVI aproxima-se
   sem lá entrar.

3. **A subida do NDMI não se explica por remoção de nuvem — ao contrário, agrava-se.**
   Nas outras três datas parcialmente encobertas, tirar nuvem *baixou* o NDMI. Aqui
   subiu-o. Esta é uma comparação de sentido, entre dias, sobre a direcção do efeito da
   máscara — não sobre o nível — e por isso sobrevive à ressalva da amostragem.

4. **E nenhum dos três valores sustenta ou nega a hipótese do solo.** Com 8,47% da AOI
   a sobreviver, a média da v2 de 24/08 **não é a mesma quantidade** que as médias dos
   outros dias. Há ainda um mecanismo concreto de contaminação residual: a nossa
   máscara **mantém** a classe SCL 7 (*unclassified*), e numa cena 92% encoberta os
   pixels sobreviventes são desproporcionadamente adjacentes a nuvem, onde a SCL é
   menos fiável e onde cirros finos e penumbra escapam.

**Conclusão sobre 24/08:** a data **explica-se** — a queda era nuvem, demonstrada ao
pixel — e **não se mede**: sobram poucos pixels demais, e escolhidos de forma
enviesada demais, para que qualquer dos três valores mascarados seja o índice da
paisagem naquele dia. Serve para dizer que a paisagem estava encoberta e que foi isso
que produziu a anomalia; não serve para dizer nada sobre a água na paisagem, nem para
confirmar nem para negar o que a sonda leu no solo.

### O critério, enunciado — e não são só 24/08

A versão anterior desta nota traçava a linha nos 8,47% sem nunca a enunciar, e por
omissão abençoava as outras datas parcialmente mascaradas. Isso não se aguenta: se o
argumento é que os pixels sobreviventes são escolhidos pela geometria das nuvens, ele
aplica-se com quase toda a força a 09/08, cuja `v2` é uma média sobre **39% da AOI**.

**Critério adoptado, e é uma convenção declarada e não uma descoberta:** uma data só
é usada para uma afirmação ao nível da paisagem sobre `EUC-TUR-EO1` quando **pelo
menos dois terços da AOI contribuem para a média**. Abaixo disso, a média descreve um
recorte seleccionado pela nuvem e o valor só pode ser citado com a fracção mascarada
colada a ele. Os dois terços não saem dos dados — o que sai dos dados é a ordenação;
o corte é uma escolha, e fica escrita para poder ser contestada.

| data | % da AOI mascarada | % que contribui | estatuto |
|---|---|---|---|
| 2026-08-19 | 28,26% | 71,74% | acima do corte; utilizável, **mas citar sempre com os 28% mascarados** |
| 2026-08-04 | 48,60% | 51,40% | **abaixo do corte** — não utilizável para afirmação ao nível da paisagem |
| 2026-08-09 | 61,04% | 38,96% | **abaixo do corte** — não utilizável |
| 2026-08-24 | 91,53% | 8,47% | muito abaixo do corte — não utilizável, e é o caso desta nota |

**19/08 está perto da linha.** O corte é dois terços (66,7%) e 19/08 contribui com
71,74% — cerca de **5 pontos percentuais acima**, a margem mais estreita de todas as
datas avaliadas. Um corte a 75%, também defensável como convenção, passava-a para o
lado não utilizável. O estatuto de 19/08 depende da escolha do corte mais do que
qualquer outra data desta tabela.

As sete restantes datas de Turcifal têm 0,03–0,08% mascarados e não são afectadas.

**Consequência para o que já foi publicado:** os NDVI de 04/08, 09/08 e 19/08 saíram
na nota da Fase B como valores da série, sem ressalva nenhuma, e **os três estão
contaminados** — 0,3966, 0,3485 e 0,4107 são médias com 48,60%, 61,04% e 28,26% de
nuvem lá dentro. A nota da Fase B leva agora um aviso no topo a nomear as três.

---

## O contraexemplo: 1 de Agosto, e a demonstração que motiva a tarefa

A Fase B levantou a suspeita certa: a nebulosidade da **cena** não permite decidir se
a **AOI** está contaminada. Com a máscara ao pixel isso deixa de ser argumento e passa
a ser medida. Consulta ao Catalog do Copernicus feita a 29/08/2026, sem filtro de
nuvem, para a mesma AOI e janela, ao lado da fracção da AOI que a SCL mascarou:

**Critério de leitura da coluna do meio, e é preciso declará-lo:** quatro datas têm
**duas cenas**, e a tabela mostra as duas separadas por `/`. Onde mais abaixo se usa
**um** número por data — na ordenação e nos coeficientes — esse número é o
**máximo** das duas. É a escolha conservadora para a pergunta em causa (queremos saber
se a métrica da cena *deixa passar* contaminação), mas é uma escolha, e muda os
resultados: ver a nota sobre os coeficientes.

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

**Os dois casos assinalados matam a métrica da cena como indicador para decidir
data a data — não como indicador em geral, ver a associação de conjunto mais
abaixo:**

- **01/08 tem uma cena a 29,13%** — pelo critério do máximo, a segunda mais nublada da
  janela, a um passo do limiar de 30% que a teria excluído — **e 0,08% da AOI
  mascarada.** A nuvem estava toda fora de Campo Real. Foi o NDVI mais alto de toda a
  série, e continua a sê-lo depois de mascarado (0,4852). **Este caso depende do
  critério:** 01/08 tem duas cenas, 15,50 e 29,13; pelo mínimo seria a 5.ª mais
  nublada e deixaria de ser espectacular. O caso seguinte não depende de critério
  nenhum.
- **09/08 tem uma cena a 7,24%** — das mais limpas — **e 61,04% da AOI mascarada.**
  Uma data que qualquer filtro de cena teria aceite sem hesitar tinha quase dois
  terços da nossa área debaixo de nuvem. O NDVI que a Fase B publicou para esse dia
  (0,3485, o mais baixo da série depois de 24/08) era uma média com 61% de nuvem
  dentro. **09/08 tem cena única**, portanto este contraexemplo é imune ao critério
  do parágrafo anterior e sustenta o argumento sozinho.

Sobre as duas séries de 11 pontos, a correlação entre nebulosidade da cena e fracção
mascarada da AOI é, **pelo máximo**, **r = 0,511** (Pearson) e **ρ = 0,520**
(Spearman, postos médios em empates, como em `scipy.stats.spearmanr`). Pelo
**mínimo** dá **r = 0,681** e **ρ = 0,543**. Os quatro valores são calculados sobre a
coluna "% da AOI mascarada" **como a tabela a mostra**, arredondada a duas casas;
sobre as contagens de pixels excluídos, sem arredondar, o ρ do mínimo dá **0,548**
— a diferença é o arredondamento a decidir empates que nos dados em bruto não
existem (ver a seguir), não uma correcção ao número.

**Correcção a uma versão anterior desta nota, que citava ρ = 0,473.** Esse valor sai
de postos **ordinais**, com os empates desfeitos pela ordem de ordenação. Com a
definição padrão o coeficiente é 0,520. A correcção não muda nada da conclusão, e é
justamente por isso que se faz: o número estava errado e não custava nada corrigi-lo.

**Uma nota sobre os empates, porque a descrição anterior estava errada.** "0,08%"
aparece três vezes na coluna arredondada (01/08, 06/08, 11/08) e "0,07%" duas
(16/08, 21/08) — mas isso é um efeito do arredondamento, não da contagem de pixels:
em bruto essas três datas têm 48, 48 e 52 pixels excluídos. Os empates genuínos são
**48/48** (01/08 e 06/08) e **44/44** (16/08 e 21/08); 11/08 (52 pixels) fica perto
mas não empatado. O argumento sobre a fragilidade da métrica da cena aguenta-se de
qualquer forma — a ordenação por postos é praticamente igual com ou sem os
pseudo-empates —, mas a descrição dos empates estava errada e fica corrigida aqui.

**Como ler estes quatro números:** com n = 11 e uma distribuição destas são
descritivos e nada mais, e a diferença entre 0,511 e 0,681 conforme se toma o máximo
ou o mínimo mostra bem quanta liberdade há na escolha. O que se pode dizer é que **há
associação positiva e moderada** — mais nuvem na cena tende a acompanhar mais nuvem
na AOI — e que essa associação **não serve para decidir data a data**, que é o que os
dois casos acima mostram. O que sustenta a conclusão são os casos, não o coeficiente.

**Consequência prática, e vale para lá desta janela:** `maxCloudCoverage` ao nível da
cena não é um controlo de qualidade da AOI. **Não é inútil, e não se deve dizer que
não prevê nada** — a associação está lá, e o filtro evita gastar pedidos em cenas
inteiramente encobertas. O que ele não faz é dizer o que se passa por cima dos nossos
polígonos num dia concreto, que é a decisão que temos de tomar. Só a contagem ao pixel
diz isso.

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

- Para a **queda do NDVI e do NDRE**, a explicação por contaminação está
  **confirmada**, não apenas não excluída. 91,53% da AOI era nuvem, sombra ou cirro, e
  removê-la move os dois índices +0,2019 e +0,1486 na direcção esperada.
- **Confirmada como explicação da queda, não como medida do que está por baixo.** O
  NDRE mascarado cai dentro da gama da série; o **NDVI mascarado não** — 0,4130 fica
  abaixo do mínimo, 0,4338. E nenhum dos dois é comparável com os outros dias, porque
  assenta nos mesmos 8,47% da AOI que desqualificam o NDMI.
- Para o **NDMI**, nenhuma das duas explicações foi excluída — e o valor mascarado
  não ajuda a decidir, pela mesma razão e não por outra.
- A afirmação de que houve **"a primeira correspondência solo↔satélite do projecto"**
  a 24/08 continua sem suporte, e agora por uma razão documentada em vez de uma
  suspeita: o valor citado vinha de uma AOI 92% encoberta.

**E há uma segunda correcção, sobre o raciocínio e não sobre a conclusão.** A
retratação feita a 28/08 atribuiu a anomalia a nuvem. A única medida de nuvem que
existia nessa data eram os 29,94% da cena — e esta nota mostra que esse número não
sustentava a inferência: 01/08, a 29,13%, tinha 0,08% da AOI mascarada, e 09/08, a
7,24%, tinha 61%. **A conclusão estava certa; o indicador em que assentava não decide
o caso.** Quem repita o argumento na forma *"era nuvem, a cena tinha 30%"* está a
apoiar-se numa métrica que, isolada e num dia concreto, os dados desta nota mostram
não bastar. A prova é a contagem ao pixel, e só essa.

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

## A base foi reposta — o que se reproduz e o que não

Depois de esta nota estar escrita, ainda a 29/08/2026, a base `resoiltwin` de
desenvolvimento foi **apagada por acidente**: um `alembic downgrade base` destinado a
um clone isolado correu contra ela, porque a variável de ambiente exportada não era a
que o `Settings` lê e a ligação caiu no valor por omissão — que é a base real. Zero
linhas em todas as tabelas.

A base foi reposta a partir do zero por `scripts/restore_dev_data.py`: o seed de campo,
depois o site do Porto e as duas AOI pelas rotas HTTP com as geometrias lidas dos
mesmos GeoJSON, depois quatro sincronizações Copernicus na mesma janela — cada AOI com
e sem máscara, o que recria as séries `v1` e `v2` lado a lado. Os quatro jobs vieram
`succeeded`, com 33 + 21 + 33 + 21 linhas, e a base voltou às 139 observações com a
mesma repartição por `source_type` e `processing_version`.

**O que se reproduziu, e é o que importa:** *todos* os valores desta nota. As três
tabelas de índices — Campo Real `v1`/`v2`, as contagens de pixels, e as sete datas do
Porto — foram recalculadas contra a base reposta e batem certo **à quarta casa
decimal, célula a célula**. Em particular os números centrais: 24/08 com NDVI `v1`
0,2111 e `v2` 0,4130, NDRE 0,1531 → 0,3018, NDMI 0,1847 → 0,2313, e **57 432 pixels
excluídos de 62 750**. O Copernicus devolve hoje o mesmo que devolveu às 12:06.

**O que não se reproduz, e nunca reproduziria:**

- **Os UUID dos jobs.** Os dois citados acima — `66a47279-1757-42ca-a385-a07b8f4f3a68`
  e `b0edfb53-acc5-4e1a-ae02-d8958e9be2ff` — **já não existem na base.** São chaves
  geradas a cada execução. Quem tentar `GET /jobs/66a47279-…` para verificar esta nota
  recebe **404**, e isso não é sinal de nada estar errado. O mesmo vale para os UUID
  das AOI (`352d4000-…`, `b93ce717-…`) citados nos corpos das respostas.
- **Os `started_at` / `finished_at`.** As marcas de 29/08 às 12:06 são da execução
  original.
- **Os `created_at`** de todas as linhas.

**Os `request_hash` das duas sincronizações desta nota reproduzem-se**, e foram
reconfirmados: `0a4bb5ac…` e `9489a994…`, os mesmos que estão publicados acima. É o
que se espera — o hash é derivado do pedido (AOI, janela, colecção, versão de
processamento, resolução, limiar de nuvem) e não da execução.

Uma ressalva sobre a série `v1`: na reposição ela foi reingerida na janela **01–29/08**,
para ficar a par da `v2`, e a Fase B tinha-a corrido até **28/08**. Os valores são
exactamente os mesmos — não há aquisição a 29/08 — mas o `request_hash` muda com a
janela, portanto os hashes `v1` que a nota da Fase B publica (`03c9afcd…`,
`efece715…`) já não existem na base. Quem os procurar não os encontra, e isso não é
sinal de nada estar errado.

Duas consequências que ficam registadas por serem lição e não detalhe. Primeira: o
`Settings` deste projecto **não tem `env_prefix`**, portanto exportar
`RESOILTWIN_DATABASE_URL` não configura nada e a ligação cai silenciosamente na base
por omissão — que é a de desenvolvimento. Antes de qualquer comando que escreva,
confirmar com `python -c "from resoiltwin.config import get_settings;
print(get_settings().database_url)"`. Segunda: a reposição passou a ser um comando, e
está documentada no `README.md`.

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
nebulosidade — e, mais tarde no mesmo dia, os **quatro** `sync` da reposição.

Depois desta nota o repositório passou a 203 testes: dois novos de paridade de schema,
que fixam a largura das colunas `VARCHAR` entre modelos e migrações. Vieram da
migração `0008`, que alinhou `ingestion_jobs.processing_version` (era `String(64)`) com
`observations.processing_version` (`String(80)`) — a mesma versão de processamento
guardada em duas larguras diferentes, o que faria uma versão com mais de 64 caracteres
ser aceite numa tabela e recusada na outra.
