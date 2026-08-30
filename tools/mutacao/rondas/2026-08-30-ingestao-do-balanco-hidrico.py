"""Ronda sobre a ingestao do balanco hidrico (Fase D, Task 3).

Esta camada nao inventa nenhum numero: pega em duas series que ja estao na
base, corre um modelo puro e grava o que sai. Todas as formas de errar aqui
produzem uma linha com proveniencia completa e ar de correcta -- que e
exactamente a classe de defeito que este projecto persegue, e a razao pela qual
uma tabela verde a primeira nao prova nada.

Cinco grupos, e os cinco mutantes obrigatorios estao la dentro:

- **o que a linha DIZ QUE E** (`source_type`): um balanco gravado como `derived`
  ou como leitura de sensor calibrado e uma mentira que nenhuma constraint
  apanha -- as duas passam o esquema inteiro.
- **o que a linha admite NAO SABER** (`exact` vs `range`): ⭐ o mutante `r1`
  grava o minimo do intervalo como valor exacto. Passa TODAS as CHECK
  constraints da base, porque a linha e perfeitamente bem formada: o que ela faz
  e reinventar em silencio o estado inicial do reservatorio, que ninguem mediu.
  Se este sobreviver, todo o trabalho da Task 2 para nao inventar esse numero
  fica desfeito na camada seguinte, sem deixar rasto.
- **a capacidade utilizavel**, que domina o resultado e que ninguem mediu
  nestes sitios: fora do `evidence` a linha nao e auditavel, e fora da
  `processing_version` duas capacidades colidem e a segunda serie desaparece.
- **a proveniencia das entradas**: qual foi escolhida, quais estavam
  disponiveis, e a proibicao de misturar duas proveniencias na mesma serie.
- **as recusas**, que existem todas porque a alternativa e um numero errado
  com ar de certo: sem entradas, com duas versoes de processamento, com a
  unidade errada, com mais do que um valor por dia, sem um dia em comum.

Quatro mutantes (`d2`, `d3`, `a1`, `a2`) mudam `weather/ingest.py`, e nao por
engano: esta camada REUTILIZA de la a resolucao do sitio e a desduplicacao pela
chave de seis colunas, em vez de as copiar. Uma reutilizacao que nenhum teste
meu defende e uma dependencia por medir -- se eu mudar de ideias e passar a
copiar, tem de haver um teste que caia.
"""

INGEST = "src/resoiltwin/water/ingest.py"
METEO = "src/resoiltwin/weather/ingest.py"

MUTANTES = [
    # --- o que a linha diz que e ---------------------------------------------
    ("s1", INGEST,
     "        source_type=SourceType.simulated,",
     "        source_type=SourceType.derived,",
     "_observacao_de_agua",
     "o balanco passa por produto derivado de observacoes, e nao por simulacao"),

    ("s2", INGEST,
     "        source_type=SourceType.simulated,",
     "        source_type=SourceType.observed_reference,",
     "_observacao_de_agua",
     "a saida de um modelo passa por leitura de um sensor calibrado"),

    # --- o intervalo indeterminado -------------------------------------------
    ("r1", INGEST,
     "    determinado = dia.determinado",
     "    determinado = True",
     "_observacao_de_agua",
     "⭐ o dia indeterminado e gravado como `exact` com o MINIMO do intervalo"),

    ("r2", INGEST,
     "    determinado = dia.determinado",
     "    determinado = False",
     "_observacao_de_agua",
     "o dia determinado e gravado como intervalo de largura zero"),

    ("r3", INGEST,
     "        value_numeric=dia.agua_disponivel_min_mm if determinado else None,",
     "        value_numeric=(dia.agua_disponivel_min_mm + dia.agua_disponivel_max_mm) / 2,",
     "_observacao_de_agua",
     "a media do intervalo entra na linha do dia indeterminado"),

    ("r4", INGEST,
     "        value_min=None if determinado else dia.agua_disponivel_min_mm,",
     "        value_min=None,",
     "_observacao_de_agua",
     "o limite inferior do intervalo desaparece da linha"),

    # --- a capacidade utilizavel ---------------------------------------------
    ("c1", INGEST,
     '            "available_water_capacity_mm": dia.capacidade_utilizavel_mm,',
     None,
     "_observacao_de_agua",
     "a capacidade que domina o resultado cai do `evidence`"),

    ("c2", INGEST,
     '            "capacity_is_measured": False,',
     '            "capacity_is_measured": True,',
     "_observacao_de_agua",
     "a capacidade escolhida a dedo passa por medida"),

    ("c3", INGEST,
     '    return f"{VERSAO_DO_BALANCO}+awc{capacidade_utilizavel_mm:g}mm"',
     "    return VERSAO_DO_BALANCO",
     "processing_version_do_balanco",
     "a capacidade sai da identidade da linha: duas capacidades colidem"),

    ("c4", INGEST,
     "    solo = Solo(capacidade_utilizavel_mm=float(capacidade_mm))",
     "    solo = Solo(capacidade_utilizavel_mm=abs(float(capacidade_mm)) or 1.0)",
     "sync_water_balance",
     "uma capacidade impossivel e corrigida em silencio em vez de recusada"),

    ("c5", INGEST,
     "def sync_water_balance(session, site_code, date_from, date_to, capacidade_mm)"
     " -> IngestionJob:",
     "def sync_water_balance(session, site_code, date_from, date_to, capacidade_mm=100.0)"
     " -> IngestionJob:",
     "sync_water_balance",
     "a capacidade ganha um valor por omissao a dominar todas as corridas"),

    # --- a proveniencia das entradas -----------------------------------------
    ("p1", INGEST,
     '        "source_type": escolha.source_type,',
     None,
     "_evidencia_da_entrada",
     "a proveniencia de cada serie de entrada cai do `evidence`"),

    ("p2", INGEST,
     '        "provenances_available": list(escolha.proveniencias_disponiveis),',
     None,
     "_evidencia_da_entrada",
     "a linha diz o que foi escolhido e cala o que estava disponivel"),

    ("p3", INGEST,
     "PRECEDENCIA_DAS_ENTRADAS = (SourceType.reanalysis, SourceType.weather_observed)",
     "PRECEDENCIA_DAS_ENTRADAS = (SourceType.weather_observed, SourceType.reanalysis)",
     "(modulo)",
     "a precedencia inverte-se sem que nada na linha mude"),

    ("p4", INGEST,
     "    filas = [fila for fila in filas if str(fila.source_type) == escolhida]",
     "    filas = list(filas)",
     "_entrada_escolhida",
     "a serie deixa de ser filtrada pela proveniencia escolhida: as duas misturam-se"),

    ("p5", INGEST,
     "            if antes != agora:",
     "            if False:",
     "_garantir_que_as_entradas_nao_mudaram",
     "reescrever a janela com outra proveniencia deixa de ser assinalado"),

    # --- as recusas ----------------------------------------------------------
    ("n1", INGEST,
     "    if not disponiveis:",
     "    if False:",
     "_entrada_escolhida",
     "uma serie de entrada sem uma unica linha deixa de ser nomeada como tal"),

    ("n2", INGEST,
     "    if not dias:",
     "    if False:",
     "_dias_com_todas_as_entradas",
     "duas series que nao partilham um dia deixam de o dizer"),

    ("n3", INGEST,
     "    if len(versoes) > 1:",
     "    if False:",
     "_entrada_escolhida",
     "duas versoes de processamento da mesma serie deixam de ser recusadas"),

    ("n4", INGEST,
     "    if unidades != [UNIDADE_DAS_ENTRADAS]:",
     "    if False:",
     "_entrada_escolhida",
     "uma entrada em metros passa por milimetros"),

    ("n5", INGEST,
     "        if dia in valor_por_dia:",
     "        if False:",
     "_entrada_escolhida",
     "uma serie horaria e agregada em silencio em vez de recusada"),

    ("n6", INGEST,
     "    _garantir_janela_valida(inicio, fim)",
     None,
     "sync_water_balance",
     "uma janela invertida deixa de ser recusada antes de o job existir"),

    # --- a interseccao e a janela --------------------------------------------
    ("x1", INGEST,
     "    comuns = set.intersection(*conjuntos.values())",
     "    comuns = set.union(*conjuntos.values())",
     "_dias_com_todas_as_entradas",
     "um dia com chuva e sem ET0 passa a ser balancado"),

    ("x2", INGEST,
     "    sem_a_outra = {nome: len(conjunto - comuns) for nome, conjunto in conjuntos.items()}",
     "    sem_a_outra = {nome: 0 for nome in conjuntos}",
     "_dias_com_todas_as_entradas",
     "os dias que ficaram por balancar deixam de ser contados na linha"),

    ("x3", INGEST,
     "        job.date_from, job.date_to = dias[0], dias[-1]",
     None,
     "sync_water_balance",
     "o job declara a janela PEDIDA em vez da que balancou"),

    ("x4", INGEST,
     "            Observation.observed_at < _momento(fim + timedelta(days=1)),",
     None,
     "_entrada_escolhida",
     "a janela pedida deixa de ter fim: entram dias que o job nao pediu"),

    ("x5", INGEST,
     "            Observation.observed_at >= _momento(inicio),",
     None,
     "_entrada_escolhida",
     "a janela pedida deixa de ter inicio"),

    # --- o resto do `evidence` -----------------------------------------------
    ("e1", INGEST,
     '            "segment": dia.segmento,',
     None,
     "_observacao_de_agua",
     "o troco a que o dia pertence cai da linha: dois pontos com um buraco pelo meio"
     " parecem contiguos"),

    ("e2", INGEST,
     '            "runoff_min_mm": dia.escoamento_min_mm,',
     None,
     "_observacao_de_agua",
     "o escoamento cai da linha: um dia cheio e um dia que perdeu 200 mm ficam iguais"),

    ("e3", INGEST,
     "        derived_from=[escolha.id_por_dia[dia.data] for escolha in escolhas.values()],",
     "        derived_from=None,",
     "_observacao_de_agua",
     "a cadeia ate as linhas de entrada exactas fica por escrever"),

    # --- o que esta camada REUTILIZA de weather/ingest.py --------------------
    ("d1", METEO,
     "            Observation.processing_version == processing_version,",
     None,
     "_identidades_existentes",
     "a desduplicacao ignora a processing_version"),

    ("d2", METEO,
     "        if (quando, metrica) in ja_existem:",
     "        if False:",
     "_gravar",
     "a desduplicacao deixa de existir: a segunda corrida reescreve tudo"),

    ("a1", METEO,
     "    if site is None:",
     "    if False:",
     "_sitio_e_aoi_aprovada",
     "um sitio inexistente deixa de ser recusado com uma mensagem propria"),

    ("a2", METEO,
     "    if not aois:",
     "    if False:",
     "_sitio_e_aoi_aprovada",
     "um sitio sem AOI aprovada deixa de ser recusado com uma mensagem propria"),
]
