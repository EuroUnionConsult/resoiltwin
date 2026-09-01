"""Tudo o que muda com a lingua, e nada mais.

O projecto e europeu e toda a interaccao com o consorcio e com quem avalia e em
ingles. **A consola responde em ingles quando ninguem escolhe nada**, e o
portugues continua disponivel.


Porque e que isto e um dicionario por lingua, e nao um catalogo de pares
---------------------------------------------------------------------------

A forma obvia -- `{"chave": ("English", "Portugues")}` -- torna a paridade
estrutural: nao ha maneira de escrever uma chave so numa lingua. Nao foi
escolhida, e a razao e o que estes textos sao.

Os textos desta consola carregam a tese do produto: que um valor de uma celula
de 9 km **nao e uma medicao na parcela**, que um intervalo **nao e um numero**,
que uma leitura saturada **nao e o valor do tecto**. Uma traducao que enfraqueca
qualquer uma delas destroi aquilo para que a consola existe -- e o defeito nao
se ve numa chave isolada, ve-se ao ler o bloco inteiro de uma lingua de fio a
pavio e reparar que a voz cedeu a meio. Dois dicionarios seguidos leem-se como
dois documentos; um catalogo de pares le-se como uma tabela, e numa tabela
ninguem le prosa.

O preco desta escolha e que a paridade deixa de ser estrutural, e por isso passa
a ser paga por um teste (`test_as_duas_linguas_tem_as_mesmas_chaves`). Uma chave
que exista so numa lingua e um texto que desaparece quando se muda de lingua, e
sem esse teste ninguem daria por isso.


O que acontece a uma chave em falta
------------------------------------

`Textos.__getitem__` **cai para o ingles e regista o erro**, em vez de levantar.
Uma consola cuja unica funcao e ser honesta nao pode ficar em branco -- nem dar
500 -- porque falta uma frase: a frase inglesa e degradada mas verdadeira, e o
resto da pagina continua a dizer o que tem a dizer. Quem impede que isso chegue
a ser publicado e o teste da paridade, que corre antes de qualquer entrega.


⚠️ Nao ha aqui nenhuma "lingua actual" ao nivel do modulo
-----------------------------------------------------------

A lingua viaja como argumento, pedido a pedido. A aplicacao e assincrona e dois
pedidos em linguas diferentes entrelacam-se dentro do mesmo processo: uma
variavel de modulo com a lingua "actual" servia a pagina de um em portugues ao
outro, sem erro nenhum e sem nada no registo.
"""

import logging

logger = logging.getLogger(__name__)

# ⭐ Ingles por omissao. Sem escolha nenhuma, e isto que sai.
LINGUA_POR_OMISSAO = "en"

# O nome do parametro na linha de endereco. Em ingles porque e ele que fica
# visivel a quem le o endereco, e `lang` e o que quem o escreve a mao ja espera.
PARAMETRO_DA_LINGUA = "lang"

# O que vai para o atributo `lang` do `<html>`: e ele que diz ao navegador como
# separar silabas e que aspas usar. `en-GB` e nao `en`, porque a consola escreve
# "Synchronisations" e "metres".
ETIQUETA_HTML = {"en": "en-GB", "pt": "pt-PT"}

# Como se nomeia cada lingua na propria lingua dela. Um "Portuguese" escrito em
# ingles nao ajuda quem procura o portugues; "Português" ajuda.
NOME_DA_LINGUA = {"en": "English", "pt": "Português"}

# A marca decimal. O separador de milhares e o mesmo nas duas (espaco insecavel,
# U+00A0) de proposito: o ponto nos milhares e ambiguo em qualquer lingua -- num
# numero como 1.234 leva quem le a duvidar se sao mil duzentos ou um virgula
# dois -- e a recomendacao do BIPM para escrita cientifica e precisamente o
# espaco. O que muda entre as duas linguas e so a marca decimal.
MARCA_DECIMAL = {"en": ".", "pt": ","}

# ⚠️ Em ingles a data escreve-se em ISO 8601, e nao em `%d/%m/%Y`. Nao e gosto:
# `09/08/2026` le-se como 9 de Agosto de um lado do Atlantico e como 8 de
# Setembro do outro, e esta consola e uma janela sobre uma base cujas datas ja
# viajam em ISO. Uma data ambigua num painel de proveniencia e exactamente a
# classe de erro que o resto do produto existe para nao cometer.
FORMATO_DO_MOMENTO = {"en": "%Y-%m-%d %H:%M", "pt": "%d/%m/%Y %H:%M"}
FORMATO_DO_DIA = {"en": "%Y-%m-%d", "pt": "%d/%m/%Y"}


# ---------------------------------------------------------------------------
# Ingles
# ---------------------------------------------------------------------------

INGLES = {
    # ------------------------------------------------------------ o involucro
    "nav.observacoes": "Observations",
    "nav.sincronizacoes": "Synchronisations",
    "nav.sitios": "Sites",
    "nav.lingua": "Language",
    "ambiente": "environment: {ambiente}",
    # ⚠️ A ressalva nao e um rodape decorativo: e a unica coisa nesta consola
    # que impede tres leituras erradas que a propria tabela sugere. Leva
    # marcacao, e por isso e o unico texto que entra numa pagina sem passar por
    # `e()`.
    "ressalva": (
        "This console shows what is recorded, and nothing else. "
        "<b>Nothing here has been agronomically validated.</b> "
        "The water balance is a model run over series already stored: it does not measure "
        "the soil water of this ground, and so it returns a range for as long as it does "
        "not know. And three provenances of one metric share a table because they are the "
        "same metric, not because they can be compared with one another."
    ),
    "falha.titulo": "Not everything could be read, and what is below is incomplete.",
    "falha.explicacao": (
        "This is not the same as being empty: some reads never answered, and what is "
        "missing below may well exist in the database."
    ),
    "falha.recusa": "{caminho}: the layer refused this read ({detalhe}).",
    "falha.estado": "{caminho}: the API answered {estado}.",

    # ---------------------------------------------------------- observacoes
    "obs.titulo": "Observations",
    "obs.resumo.uma": (
        "{total} observation matches this filter; showing the {devolvidas} most recent."
    ),
    "obs.resumo.varias": (
        "{total} observations match this filter; showing the {devolvidas} most recent."
    ),
    "obs.vazio": (
        "No observation matches this filter. This site may not hold this metric, or may "
        "not hold it from this source type."
    ),
    "filtro.sitio": "Site",
    "filtro.metrica": "Metric",
    "filtro.origem": "Source type",
    "filtro.linhas": "Rows",
    "filtro.botao": "Filter",
    "filtro.limpar": "clear",
    "filtro.todas_as_metricas": "all metrics",
    "filtro.todas_as_origens": "all source types",
    "coluna.quando": "When",
    "coluna.metrica": "Metric",
    "coluna.valor": "Value",
    "coluna.origem": "Source type",
    "coluna.qualidade": "Quality flag",
    "coluna.versao": "Version",
    "coluna.abrir": "provenance",
    # ⚠️ "solid" e "hatched" sao os dois canais que dizem a mesma coisa sem cor
    # nenhuma. O que a legenda tem de afirmar nao e onde a leitura esta, e sim o
    # que ela e: uma medicao neste terreno, ou nao.
    "legenda.solido": "solid: {lugar}",
    "legenda.tramado": "hatched: {lugar}",
    "legenda.escala": "provenance scale, from the most direct to the most distant:",

    # ------------------------------------------------------------- o painel
    "painel.titulo": "Provenance",
    "painel.escolha": (
        "Pick a row from the table to see where its value came from: what was measured, "
        "at what distance, with what instrument, and over which inputs."
    ),
    "painel.na_linha": "On the row itself",
    "prov.sem_proveniencia": "No structured provenance was recorded",
    "prov.porque_falta": (
        "This reading was written before the provenance field existed, so it carries no "
        "structured record of its inputs. What is known about it is what the row itself "
        "says, below."
    ),
    "prov.retido.geometry": "geometry withheld",
    "prov.retido.coordinate": "coordinate withheld",
    "prov.retido.outro": "withheld",
    "prov.sim": "yes",
    "prov.nao": "no",
    "prov.nao_registado": "not recorded",
    "linha.metrica": "Metric",
    "linha.unidade": "Unit",
    "linha.origem": "Source type",
    "linha.qualificador": "Value qualifier",
    "linha.qualidade": "Quality flag",
    "linha.parcela": "Plot",
    "linha.metodo": "Method",
    "linha.coleccao": "Source collection",
    "linha.versao": "Processing version",
    "linha.nota": "Note",

    # ------------------------------------------------------------- o valor
    # ⭐ "not measured in the parcel" e nao "outside the parcel". A frase
    # literal descreve um lugar; a que aqui esta nega uma medicao, que e a
    # afirmacao que este produto inteiro existe para nao apagar. Uma estacao a
    # 5,34 km esta mesmo fora da parcela -- e o que importa dizer e que o
    # numero que ali esta nao foi medido neste terreno.
    "valor.na_parcela": "measured in the parcel",
    "valor.fora_da_parcela": "not measured in the parcel",
    "valor.separador_de_intervalo": " to ",
    "valor.intervalo_incompleto": "incomplete range",
    "valor.sem_valor": "no value",

    # ------------------------------------------------------ sincronizacoes
    "sinc.titulo": "Synchronisations",
    "sinc.subtitulo": (
        "Every ingestion leaves a row. Several decisions in this system rest on failing "
        "loudly rather than losing data in silence, and failing loudly only beats losing "
        "in silence if somebody looks."
    ),
    "sinc.atencao.titulo": "Need attention ({quantas})",
    "sinc.atencao.subtitulo": (
        "A run lands here for having declared that it went wrong, for having stayed "
        "running and never finished, or for having reported success without writing "
        "anything when no other run of the same request wrote either."
    ),
    "sinc.atencao.vazio": (
        "No run is flagged. That does not mean all is well: it means there is nothing "
        "these three rules can see."
    ),
    "sinc.todas.titulo": "All runs ({quantas})",
    "sinc.todas.subtitulo": (
        "Uncovered days count the days of the requested window that fell outside the "
        "covered window. It is a count and not a verdict: an archive that publishes late "
        "and a genuinely lost series have the same shape and differ only in magnitude, "
        "and the threshold belongs to whoever reads."
    ),
    "sinc.todas.vazio": "There are no runs recorded.",
    "sinc.coluna.comecou": "Started",
    "sinc.coluna.tipo": "Type",
    "sinc.coluna.estado": "Status",
    "sinc.coluna.janelas": "Windows",
    "sinc.coluna.dias": "Uncovered days",
    "sinc.coluna.linhas": "Rows",
    "sinc.coluna.versao": "Version",
    "sinc.coluna.erro": "Error",
    "sinc.janela.pedida": "requested",
    "sinc.janela.coberta": "covered",
    "sinc.janela.ate": " to ",
    "sinc.nao_registada": "not recorded",
    # ⭐ "no requested window" e nao "not measurable". A celula esta vazia por
    # uma razao concreta -- a janela pedida nao ficou gravada, e sem ela nao ha
    # subtraccao nenhuma para fazer --, e nomear a causa e melhor do que
    # declarar uma impossibilidade que se leria como um defeito do sistema.
    "sinc.sem_janela_pedida": "no requested window",
    # ⭐ Os tres veredictos acusam a EXECUCAO, e nao descrevem um estado. E de
    # proposito: as tres formas de perder dados em silencio que este projecto ja
    # apanhou foram execucoes que declararam sucesso.
    "veredicto.failed": "said it failed",
    "veredicto.never_finished": "started and never finished",
    "veredicto.succeeded_without_writing": "reported success and wrote nothing",

    # -------------------------------------------------------------- sitios
    "sitios.titulo": "Sites",
    "sitios.subtitulo": (
        "Both sites, the areas of interest of each, and what each one holds on record."
    ),
    "sitios.areas": "Areas of interest",
    "sitios.aviso_contorno": (
        "This console does not serve the outline of any area: the polygons live in a "
        "private repository. The area in square metres and the provenance of the boundary "
        "are what there is to see here."
    ),
    "sitios.sem_areas": "This site has no areas of interest on record.",
    "sitios.parcelas": "Plots",
    "sitios.sem_parcelas": "No plots on record.",
    "sitios.inventario": "What this site holds",
    "sitios.sem_observacoes": "This site holds no observations yet.",
    "sitios.periodo": "{inicio} to {fim}",
    "sitios.par.finalidade": "purpose",
    "sitios.par.area": "area",
    "sitios.par.proveniencia": "geometry provenance",
    "sitios.par.estado": "status",
    "sitios.par.aprovada_por": "approved by",
    "sitios.par.cultura": "crop",
    "sitios.par.fuso": "time zone",
}


# ---------------------------------------------------------------------------
# Portugues de Portugal
# ---------------------------------------------------------------------------

PORTUGUES = {
    # ------------------------------------------------------------ o involucro
    "nav.observacoes": "Observações",
    "nav.sincronizacoes": "Sincronizações",
    "nav.sitios": "Sítios",
    "nav.lingua": "Língua",
    "ambiente": "ambiente: {ambiente}",
    "ressalva": (
        "Esta consola mostra o que está gravado, e nada mais. "
        "<b>Nada aqui foi validado agronomicamente.</b> "
        "O balanço hídrico é um modelo corrido sobre séries já guardadas: não mede a água "
        "do solo destes terrenos, e por isso devolve um intervalo enquanto não sabe. "
        "E três proveniências da mesma métrica aparecem na mesma tabela por serem a mesma "
        "métrica, não por se compararem entre si."
    ),
    "falha.titulo": "Nem tudo foi lido, e o que está em baixo está incompleto.",
    "falha.explicacao": (
        "Isto não é o mesmo que estar vazio: houve leituras que não chegaram a responder, "
        "e o que falta abaixo pode existir na base."
    ),
    "falha.recusa": "{caminho}: a camada recusou esta leitura ({detalhe}).",
    "falha.estado": "{caminho}: a API respondeu {estado}.",

    # ---------------------------------------------------------- observacoes
    "obs.titulo": "Observações",
    "obs.resumo.uma": (
        "{total} observação corresponde a este filtro; a mostrar a {devolvidas} mais recente."
    ),
    "obs.resumo.varias": (
        "{total} observações correspondem a este filtro; a mostrar as {devolvidas} mais "
        "recentes."
    ),
    "obs.vazio": (
        "Nenhuma observação corresponde a este filtro. Este sítio pode não ter esta "
        "métrica, ou não a ter desta origem."
    ),
    "filtro.sitio": "Sítio",
    "filtro.metrica": "Métrica",
    "filtro.origem": "Origem",
    "filtro.linhas": "Linhas",
    "filtro.botao": "Filtrar",
    "filtro.limpar": "limpar",
    "filtro.todas_as_metricas": "todas as métricas",
    "filtro.todas_as_origens": "todas as origens",
    "coluna.quando": "Quando",
    "coluna.metrica": "Métrica",
    "coluna.valor": "Valor",
    "coluna.origem": "Origem",
    "coluna.qualidade": "Qualidade",
    "coluna.versao": "Versão",
    "coluna.abrir": "proveniência",
    "legenda.solido": "sólido: {lugar}",
    "legenda.tramado": "tramado: {lugar}",
    "legenda.escala": "escala de proveniência, do mais directo ao mais distante:",

    # ------------------------------------------------------------- o painel
    "painel.titulo": "Proveniência",
    "painel.escolha": (
        "Escolha uma linha da tabela para ver de onde veio o valor dela: o que foi "
        "medido, a que distância, com que instrumento e sobre que entradas."
    ),
    "painel.na_linha": "Na própria linha",
    "prov.sem_proveniencia": "Sem proveniência estruturada",
    "prov.porque_falta": (
        "Esta leitura foi gravada antes de o campo de proveniência existir, e por isso "
        "não traz o registo estruturado das entradas. O que se sabe dela é o que está na "
        "própria linha, abaixo."
    ),
    "prov.retido.geometry": "geometria retida",
    "prov.retido.coordinate": "coordenada retida",
    "prov.retido.outro": "retido",
    "prov.sim": "sim",
    "prov.nao": "não",
    "prov.nao_registado": "não registado",
    "linha.metrica": "Métrica",
    "linha.unidade": "Unidade",
    "linha.origem": "Origem",
    "linha.qualificador": "Qualificador do valor",
    "linha.qualidade": "Marca de qualidade",
    "linha.parcela": "Parcela",
    "linha.metodo": "Método",
    "linha.coleccao": "Colecção de origem",
    "linha.versao": "Versão de processamento",
    "linha.nota": "Nota",

    # ------------------------------------------------------------- o valor
    "valor.na_parcela": "na parcela",
    "valor.fora_da_parcela": "fora da parcela",
    "valor.separador_de_intervalo": " a ",
    "valor.intervalo_incompleto": "intervalo incompleto",
    "valor.sem_valor": "sem valor",

    # ------------------------------------------------------ sincronizacoes
    "sinc.titulo": "Sincronizações",
    "sinc.subtitulo": (
        "Cada ingestão deixa uma linha. Várias decisões deste sistema assentam em falhar "
        "alto em vez de perder em silêncio, e falhar alto só é melhor do que perder em "
        "silêncio se alguém olhar."
    ),
    "sinc.atencao.titulo": "Precisam de atenção ({quantas})",
    "sinc.atencao.subtitulo": (
        "Uma execução entra aqui por ter declarado que correu mal, por ter ficado a "
        "correr sem nunca acabar, ou por ter dito que sim sem escrever nada quando "
        "nenhuma outra execução do mesmo pedido escreveu."
    ),
    "sinc.atencao.vazio": (
        "Nenhuma execução está assinalada. Isto não quer dizer que esteja tudo bem: quer "
        "dizer que não há nada que estas três regras vejam."
    ),
    "sinc.todas.titulo": "Todas as execuções ({quantas})",
    "sinc.todas.subtitulo": (
        "Os dias por cobrir são a contagem dos dias da janela pedida que ficaram fora da "
        "janela coberta. É uma contagem e não um veredicto: um arquivo que publica com "
        "atraso e uma série genuinamente perdida têm a mesma forma e só diferem em "
        "magnitude, e o limiar é de quem lê."
    ),
    "sinc.todas.vazio": "Não há execuções registadas.",
    "sinc.coluna.comecou": "Começou",
    "sinc.coluna.tipo": "Tipo",
    "sinc.coluna.estado": "Estado",
    "sinc.coluna.janelas": "Janelas",
    "sinc.coluna.dias": "Dias por cobrir",
    "sinc.coluna.linhas": "Linhas",
    "sinc.coluna.versao": "Versão",
    "sinc.coluna.erro": "Erro",
    "sinc.janela.pedida": "pedida",
    "sinc.janela.coberta": "coberta",
    "sinc.janela.ate": " a ",
    "sinc.nao_registada": "não registada",
    "sinc.sem_janela_pedida": "sem janela pedida",
    "veredicto.failed": "declarou que correu mal",
    "veredicto.never_finished": "ficou a correr e nunca acabou",
    "veredicto.succeeded_without_writing": "disse que sim e não escreveu nada",

    # -------------------------------------------------------------- sitios
    "sitios.titulo": "Sítios",
    "sitios.subtitulo": (
        "Os dois sítios, as áreas de interesse de cada um, e o que cada um tem gravado."
    ),
    "sitios.areas": "Áreas de interesse",
    "sitios.aviso_contorno": (
        "O contorno de cada área não é servido por esta consola: os polígonos estão num "
        "repositório privado. A área em metros quadrados e a proveniência do traçado são "
        "o que há para ver aqui."
    ),
    "sitios.sem_areas": "Este sítio não tem áreas de interesse registadas.",
    "sitios.parcelas": "Parcelas",
    "sitios.sem_parcelas": "Sem parcelas registadas.",
    "sitios.inventario": "O que este sítio tem",
    "sitios.sem_observacoes": "Este sítio ainda não tem observações.",
    "sitios.periodo": "{inicio} a {fim}",
    "sitios.par.finalidade": "finalidade",
    "sitios.par.area": "área",
    "sitios.par.proveniencia": "proveniência da geometria",
    "sitios.par.estado": "estado",
    "sitios.par.aprovada_por": "aprovada por",
    "sitios.par.cultura": "cultura",
    "sitios.par.fuso": "fuso",
}


# ---------------------------------------------------------------------------
# Os rotulos dos campos da evidencia
# ---------------------------------------------------------------------------

# ⚠️ Estes vivem a parte dos textos das paginas por terem outra regra de falha.
# Um campo da evidencia que ninguem tenha nomeado aparece na mesma, **pelo nome
# cru**: um campo novo tem de ser visivel antes de ser bonito, e um painel que
# escondesse o que nao sabe nomear fazia nascer campos invisiveis. Os textos das
# paginas nao tem esse comportamento -- uma chave em falta ali e um defeito, e
# nao um campo novo.

ROTULOS_EM_INGLES = {
    "aggregation_operator": "Aggregation operator",
    "aggregation_period_hours": "Aggregated period (h)",
    "aoi_code": "Area of interest",
    "area_aoi": "Bounding box of the area of interest",
    "area_expanded": "Area widened by the request",
    "area_requested": "Bounding box requested from the archive",
    "available_water_capacity_mm": "Reservoir capacity (mm)",
    "capacity_is_measured": "Capacity measured on the ground",
    "cell_lat": "Cell latitude",
    "cell_lon": "Cell longitude",
    "cell_size_deg": "Cell side (degrees)",
    "cell_size_km_ew": "Cell side, east-west (km)",
    "cell_size_km_ns": "Cell side, north-south (km)",
    "days_since_restart": "Days since the model restarted",
    "determined": "Value determined",
    "distance_km": "Distance to the site (km)",
    "field": "Field read at the source",
    "input_selection_rule": "Rule for choosing the inputs",
    "inputs": "Inputs",
    "masked_days_dropped": "Days dropped by the mask",
    "max_cloud": "Maximum cloud accepted (%)",
    "measured_at_site": "Measured in the parcel",
    "method": "Method",
    "model_version": "Model version",
    "night_radiation_dropped": "Night-time readings dropped",
    "no_data_pixels": "Pixels with no data",
    "provenances_available": "Provenances available",
    "replicates": "Replicates",
    "request_hash": "Fingerprint of the request",
    "resolution_m": "Resolution (m)",
    "runoff_max_mm": "Maximum runoff (mm)",
    "runoff_min_mm": "Minimum runoff (mm)",
    "sampled_pixels": "Pixels sampled",
    "scl_classes_excluded": "SCL classes excluded",
    "scl_mask": "SCL mask applied",
    "segment": "Segment",
    "site_code": "Site",
    "site_lat": "Site latitude",
    "site_lon": "Site longitude",
    "site_point_source": "Source of the site point",
    "source_file": "Source file",
    "source_url": "Source address",
    "station_id": "Station",
    "station_lat": "Station latitude",
    "station_lon": "Station longitude",
    "station_name": "Station name",
    "station_search_radius_km": "Station search radius (km)",
    "stations_considered": "Stations considered",
    "variable": "Variable in the archive",
    "window_end": "End of the reading window",
}

ROTULOS_EM_PORTUGUES = {
    "aggregation_operator": "Operador de agregação",
    "aggregation_period_hours": "Período agregado (h)",
    "aoi_code": "Área de interesse",
    "area_aoi": "Caixa da área de interesse",
    "area_expanded": "Área alargada pelo pedido",
    "area_requested": "Caixa pedida ao arquivo",
    "available_water_capacity_mm": "Capacidade do reservatório (mm)",
    "capacity_is_measured": "Capacidade medida no terreno",
    "cell_lat": "Latitude da célula",
    "cell_lon": "Longitude da célula",
    "cell_size_deg": "Lado da célula (graus)",
    "cell_size_km_ew": "Lado da célula, nascente-poente (km)",
    "cell_size_km_ns": "Lado da célula, norte-sul (km)",
    "days_since_restart": "Dias desde o reinício do modelo",
    "determined": "Valor determinado",
    "distance_km": "Distância ao sítio (km)",
    "field": "Campo lido na origem",
    "input_selection_rule": "Regra de escolha das entradas",
    "inputs": "Entradas",
    "masked_days_dropped": "Dias descartados pela máscara",
    "max_cloud": "Nuvem máxima aceite (%)",
    "measured_at_site": "Medido na parcela",
    "method": "Método",
    "model_version": "Versão do modelo",
    "night_radiation_dropped": "Leituras nocturnas descartadas",
    "no_data_pixels": "Píxeis sem dado",
    "provenances_available": "Proveniências disponíveis",
    "replicates": "Réplicas",
    "request_hash": "Impressão do pedido",
    "resolution_m": "Resolução (m)",
    "runoff_max_mm": "Escoamento máximo (mm)",
    "runoff_min_mm": "Escoamento mínimo (mm)",
    "sampled_pixels": "Píxeis amostrados",
    "scl_classes_excluded": "Classes SCL excluídas",
    "scl_mask": "Máscara SCL aplicada",
    "segment": "Segmento",
    "site_code": "Sítio",
    "site_lat": "Latitude do sítio",
    "site_lon": "Longitude do sítio",
    "site_point_source": "Origem do ponto do sítio",
    "source_file": "Ficheiro de origem",
    "source_url": "Endereço da origem",
    "station_id": "Estação",
    "station_lat": "Latitude da estação",
    "station_lon": "Longitude da estação",
    "station_name": "Nome da estação",
    "station_search_radius_km": "Raio de procura de estações (km)",
    "stations_considered": "Estações consideradas",
    "variable": "Variável no arquivo",
    "window_end": "Fim da janela de leitura",
}


# ---------------------------------------------------------------------------
# As tabelas, e o acesso a elas
# ---------------------------------------------------------------------------

# ⚠️ **Os dicionarios de chaves, e o teste da paridade percorre esta lista.**
# Uma tabela nova que fique de fora e uma tabela sem paridade medida -- e uma
# chave so numa lingua e um texto que desaparece quando se muda de lingua.
TABELAS = {
    "textos": {"en": INGLES, "pt": PORTUGUES},
    "rotulos": {"en": ROTULOS_EM_INGLES, "pt": ROTULOS_EM_PORTUGUES},
}

# As outras tabelas por lingua: uma so entrada por lingua, e nao um dicionario
# de chaves. Tem a sua propria paridade -- cada lingua tem de estar em todas --
# porque uma lingua que faltasse a uma delas dava um `KeyError` a desenhar.
AJUSTES_POR_LINGUA = {
    "etiqueta_html": ETIQUETA_HTML,
    "nome_da_lingua": NOME_DA_LINGUA,
    "marca_decimal": MARCA_DECIMAL,
    "formato_do_momento": FORMATO_DO_MOMENTO,
    "formato_do_dia": FORMATO_DO_DIA,
}

LINGUAS = tuple(TABELAS["textos"])


def lingua_pedida(bruto: str | None) -> str:
    """A lingua a servir, a partir do que veio na linha de endereco.

    ⭐ **Sem escolha nenhuma, sai o ingles.** E o que sai tambem para uma
    escolha que nao existe: `?lang=de` nao e um erro para mostrar a ninguem --
    e um pedido que esta consola nao consegue satisfazer, e a resposta e a
    lingua por omissao. Levantar um 400 ali punha um endereco escrito a mao a
    derrubar a pagina.

    Aceita `pt-PT` e `PT` alem de `pt`: o que a pessoa escreve a mao raramente
    tem a forma exacta, e recusar por causa de uma maiuscula nao defende nada.
    """
    if not bruto:
        return LINGUA_POR_OMISSAO
    curta = bruto.strip().lower().replace("_", "-").split("-")[0]
    return curta if curta in TABELAS["textos"] else LINGUA_POR_OMISSAO


class Textos:
    """Os textos de uma lingua, com o ingles por rede de seguranca.

    Uma chave que falte na lingua pedida cai para o ingles e deixa um erro no
    registo. Ver o cabecalho do modulo: uma consola que existe para ser honesta
    nao pode ficar em branco por faltar uma frase, e quem impede que isso chegue
    a ser publicado e o teste da paridade.
    """

    __slots__ = ("lingua", "_proprios")

    def __init__(self, lingua: str):
        self.lingua = lingua if lingua in TABELAS["textos"] else LINGUA_POR_OMISSAO
        self._proprios = TABELAS["textos"][self.lingua]

    def __getitem__(self, chave: str) -> str:
        try:
            return self._proprios[chave]
        except KeyError:
            logger.error(
                "console text %r is missing in %r; falling back to %r",
                chave, self.lingua, LINGUA_POR_OMISSAO,
            )
            return INGLES[chave]

    def formatar(self, chave: str, **campos) -> str:
        return self[chave].format(**campos)

    def rotulo(self, chave: str) -> str:
        """O nome de um campo da evidencia, ou o nome cru se ninguem o nomeou."""
        proprios = TABELAS["rotulos"][self.lingua]
        return proprios.get(chave) or ROTULOS_EM_INGLES.get(chave, chave)

    @property
    def etiqueta_html(self) -> str:
        return ETIQUETA_HTML[self.lingua]

    @property
    def marca_decimal(self) -> str:
        return MARCA_DECIMAL[self.lingua]


def de(lingua: str | None) -> Textos:
    """Os textos da lingua pedida. E o unico caminho para eles."""
    return Textos(lingua_pedida(lingua))


__all__ = [
    "AJUSTES_POR_LINGUA",
    "LINGUAS",
    "LINGUA_POR_OMISSAO",
    "NOME_DA_LINGUA",
    "PARAMETRO_DA_LINGUA",
    "TABELAS",
    "Textos",
    "de",
    "lingua_pedida",
]
