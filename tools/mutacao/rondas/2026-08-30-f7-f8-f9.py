"""Ronda sobre os tres ultimos achados da caca a falhas silenciosas.

F8 -- a linha de satelite afirmava `quality_flag = valid` por um literal sem
condicao nenhuma, e o campo `valid_pixels` contava pixeis AMOSTRADOS debaixo de
um nome que promete validos.

F7 -- o job de EO declarava sempre a janela PEDIDA, e nao havia guarda nenhuma
contra um dia devolvido fora dela; alem disso os duplos ignoravam a janela e o
corpo do pedido nunca era afirmado.

F9 -- cinco funcoes que so alguma vez viram uma coleccao de um, mais o unico
descarte deste projecto que nao se contava a si proprio.

Os mutantes de `cdse.py::statistics` (f7e, f7f) e os de `_janela_coberta` com
serie vazia existem por uma razao particular: tres dos testes novos deste lote
PASSAM tanto na versao anterior como na nova, porque fecham lacunas de teste
sobre codigo que nao mudou. A unica forma de mostrar que nao sao vacuos e um
mutante que os derrube.

Cada mutante afirma uma coisa falsa sobre o dominio. Sobreviver quer dizer que
ha comportamento que nenhum teste esta a defender.
"""

MUTANTES = [
    # ------------------------------------------------------------------ F8
    ("f8a",
     "src/resoiltwin/eo/ingest.py",
     "        quality_flag=QualityFlag.unchecked,",
     "        quality_flag=QualityFlag.valid,",
     "_observacao",
     "a linha de satelite volta a afirmar qualidade sem ninguem a verificar"),

    ("f8b",
     "src/resoiltwin/eo/cdse.py",
     '            "contributing_pixels": min(s.get("sampleCount", 0) - s.get("noDataCount", 0)',
     '            "contributing_pixels": min(s.get("sampleCount", 0) - 0 * s.get("noDataCount", 0)',
     "_normalizar",
     "os pixeis descartados deixam de ser subtraidos: contribuiram todos"),

    ("f8c",
     "src/resoiltwin/eo/cdse.py",
     '                                       for s in stats.values()),',
     '                                       for s in stats.values()) '
     '- max(s.get("noDataCount", 0) for s in stats.values()),',
     "_normalizar",
     "a subtraccao passa a cruzar bandas: min(amostras) - max(descartes)"),

    ("f8d",
     "src/resoiltwin/eo/cdse.py",
     '            "sampled_pixels": min(s.get("sampleCount", 0) for s in stats.values()),',
     '            "sampled_pixels": max(s.get("sampleCount", 0) for s in stats.values()),',
     "_normalizar",
     "um pixel invalido so em ndmi desaparece atras da contagem do ndvi"),

    ("f8e",
     "src/resoiltwin/eo/ingest.py",
     '            "contributing_pixels": linha["contributing_pixels"],',
     None,
     "_observacao",
     "a contagem real nao chega a linha: quem le nao pode aplicar criterio nenhum"),

    # ------------------------------------------------------------------ F7
    ("f7a",
     "src/resoiltwin/eo/ingest.py",
     "        _garantir_dentro_da_janela(linhas, inicio, fim)",
     None,
     "sync_aoi",
     "um dia fora da janela pedida entra debaixo de um job que diz outra coisa"),

    ("f7b",
     "src/resoiltwin/eo/ingest.py",
     "        job.date_from, job.date_to = _janela_coberta(linhas, inicio, fim)",
     None,
     "sync_aoi",
     "o job volta a declarar a janela pedida e nao a que cobriu"),

    ("f7c",
     "src/resoiltwin/eo/ingest.py",
     "    return dias[0], dias[-1]",
     "    return inicio, fim",
     "_janela_coberta",
     "a janela coberta e calculada e deitada fora: declara-se a pedida"),

    ("f7d",
     "src/resoiltwin/eo/ingest.py",
     "        return inicio, fim",
     "        return date(1970, 1, 1), date(1970, 1, 1)",
     "_janela_coberta",
     "zero aquisicoes passa a declarar uma janela inventada"),

    ("f7e",
     "src/resoiltwin/eo/cdse.py",
     '                "timeRange": {"from": f"{date_from}T00:00:00Z", '
     '"to": f"{date_to}T23:59:59Z"},',
     '                "timeRange": {"from": f"{date_from}T00:00:00Z", '
     '"to": f"{date_from}T23:59:59Z"},',
     "statistics",
     "a janela pedida a origem acaba no dia em que comeca"),

    ("f7f",
     "src/resoiltwin/eo/cdse.py",
     '                "resx": resolution_m, "resy": resolution_m,',
     '                "resx": 10, "resy": 10,',
     "statistics",
     "a resolucao do chamador e ignorada e vai sempre 10 m"),

    # ------------------------------------------------------------------ F9
    ("f9a",
     "src/resoiltwin/weather/cds.py",
     '_NOMES_TEMPO = ("time", "valid_time")',
     '_NOMES_TEMPO = ("time",)',
     "(modulo)",
     "a grafia valid_time do ECMWF deixa de ser reconhecida"),

    ("f9b",
     "src/resoiltwin/weather/cds.py",
     '_NOMES_LAT = ("lat", "latitude")',
     '_NOMES_LAT = ("lat",)',
     "(modulo)",
     "a grafia latitude do ECMWF deixa de ser reconhecida"),

    ("f9c",
     "src/resoiltwin/weather/cds.py",
     "    return min(abs(b - a) for a, b in zip(valores, valores[1:], strict=False))",
     "    return max(abs(b - a) for a, b in zip(valores, valores[1:], strict=False))",
     "_passo_da_grelha",
     "o passo da grelha passa a ser o maior vao: a guarda de meio passo alarga"),

    ("f9d",
     "src/resoiltwin/weather/cds.py",
     "        return dims.index(nome_tempo), dims.index(nome_lat), dims.index(nome_lon)",
     "        return 0, 1, 2",
     "_posicoes_das_dimensoes",
     "a ordem das dimensoes deixa de ser lida do ficheiro e assume-se"),

    ("f9e",
     "src/resoiltwin/weather/ipma.py",
     "    for instante in sorted(observacoes):",
     "    for instante in sorted(observacoes)[:2]:",
     "linhas_da_estacao",
     "a serie e truncada: as horas depois de um buraco no feed desaparecem"),

    ("f9f",
     "src/resoiltwin/weather/ipma.py",
     "                ilegiveis += 1",
     None,
     "stations",
     "uma feature saltada volta a nao ser contada"),

    ("f9g",
     "src/resoiltwin/weather/ipma.py",
     "                       stations_unreadable=self._estacoes_ilegiveis)",
     "                       stations_unreadable=0)",
     "nearest_station",
     "a escolha declara sempre zero features ilegiveis"),

    ("f9h",
     "src/resoiltwin/weather/ingest.py",
     '            "stations_unreadable": estacao["stations_unreadable"],',
     None,
     "_observacao_de_estacao",
     "a contagem existe no cliente e nao chega ao evidence da linha"),
]
