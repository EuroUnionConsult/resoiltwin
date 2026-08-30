"""Ronda sobre a guarda de intervalo fisico do IPMA, que passou a DESCARTAR.

Ate 30/08/2026 `_garantir_plausivel` levantava, e o `sync_ipma` faz rollback
de tudo o que a corrida escreveu: uma leitura absurda de UM campo de UMA
estacao derrubava a corrida inteira -- as outras quatro metricas e as 24 horas
que vinham boas. O feed do IPMA e uma janela deslizante de 24 h sem arquivo,
portanto a hora que sai da janela nao volta, e a estacao que passa a publicar
-9999 volta a falhar na hora seguinte: um campo mau parava a serie do sitio
indefinidamente.

O que fica: a leitura e descartada, contada POR CAMPO, avisada no log com um
exemplo, e a contagem sobe ate ao `evidence` de cada linha
(`out_of_range_dropped`). Um descarte nao contado seria trocar um defeito por
outro -- a guarda existe para dar sinal de que a origem mudou de convencao.

A ronda cobre tambem os dois itens menores da mesma revisao: o rasto no
`job.error` e o caso realista de uma estacao presente numas horas e ausente
noutras, que nenhum duplo exercia.

Cada mutante afirma uma coisa falsa sobre isto. Se sobreviver, ha um pedaco
que nenhum teste esta a defender.
"""

MUTANTES = [
    # --- o coracao da correccao: descartar, e nao derrubar -----------------
    ("d1",
     "src/resoiltwin/weather/ipma.py",
     "                fora_do_intervalo[campo] = fora_do_intervalo.get(campo, 0) + 1",
     "                raise ValueError(f'{campo} fora do intervalo fisico')",
     "linhas_da_estacao",
     "o descarte volta a derrubar a corrida inteira"),

    ("d2",
     "src/resoiltwin/weather/ingest.py",
     '            "out_of_range_dropped": fora_do_intervalo,',
     None,
     "_observacao_de_estacao",
     "a contagem de descartes cai do evidence"),

    ("d3",
     "src/resoiltwin/weather/ipma.py",
     "                fora_do_intervalo[campo] = fora_do_intervalo.get(campo, 0) + 1",
     "                fora_do_intervalo['campo'] = fora_do_intervalo.get('campo', 0) + 1",
     "linhas_da_estacao",
     "a contagem nao distingue o campo: tudo cai no mesmo balde"),

    # --- a guarda em si -----------------------------------------------------
    ("d4",
     "src/resoiltwin/weather/ipma.py",
     "            if not _plausivel(metrica, valor):",
     "            if False:",
     "linhas_da_estacao",
     "a guarda nunca dispara: o -9999 entra na serie como temperatura"),

    ("d5",
     "src/resoiltwin/weather/ipma.py",
     "    return minimo <= valor <= maximo",
     "    return minimo <= valor",
     "_plausivel",
     "so o piso e verificado: qualquer valor acima do tecto passa"),

    ("d6",
     "src/resoiltwin/weather/ipma.py",
     "    return minimo <= valor <= maximo",
     "    return valor <= maximo",
     "_plausivel",
     "so o tecto e verificado: qualquer valor abaixo do piso passa"),

    # --- o que se descarta continua a ter de aparecer -----------------------
    ("d7",
     "src/resoiltwin/weather/ipma.py",
     "    _avisar_do_descarte(identificador, fora_do_intervalo, exemplos)",
     None,
     "linhas_da_estacao",
     "o descarte deixa de ir ao log: fica so no evidence"),

    ("d8",
     "src/resoiltwin/weather/ipma.py",
     "                exemplos.setdefault(campo, (instante, bruto, valor))",
     None,
     "linhas_da_estacao",
     "o aviso deixa de ter exemplo e nao diz por onde comecar a olhar"),

    ("d10",
     "src/resoiltwin/weather/ipma.py",
     "            quantos, campo, identificador, minimo, maximo, UNIDADE_POR_METRICA[metrica],",
     '            quantos, "um campo", identificador, minimo, maximo, '
     "UNIDADE_POR_METRICA[metrica],",
     "_avisar_do_descarte",
     "o aviso deixa de nomear o campo que a origem estragou"),

    ("d11",
     "src/resoiltwin/weather/ipma.py",
     "    for campo, quantos in sorted(fora_do_intervalo.items()):",
     "    for campo, quantos in sorted(fora_do_intervalo.items())[:0]:",
     "_avisar_do_descarte",
     "o aviso nunca chega a sair, mesmo com a funcao a ser chamada"),

    ("d12",
     "migrations/env.py",
     "    fileConfig(config.config_file_name, disable_existing_loggers=False)",
     "    fileConfig(config.config_file_name)",
     "(modulo)",
     "as migracoes voltam a desligar em silencio os loggers do projecto"),

    # --- a estacao presente numas horas e ausente noutras -------------------
    ("d9",
     "src/resoiltwin/weather/ipma.py",
     "        if identificador not in registos:",
     "        if False:",
     "linhas_da_estacao",
     "uma hora em que a estacao nao aparece deixa de ser saltada"),

    # --- o rasto no job.error ----------------------------------------------
    ("r1",
     "src/resoiltwin/weather/ingest.py",
     "    rasto = _cauda_do_rasto(erro, espaco)",
     '    rasto = ""',
     "_texto_do_erro",
     "o job.error volta a nao ter rasto nenhum"),

    ("r2",
     "src/resoiltwin/weather/ingest.py",
     '    return f"{texto}{_CABECA_DO_RASTO}{rasto}" if rasto else texto',
     '    return f"{texto}{_CABECA_DO_RASTO}{rasto}"',
     "_texto_do_erro",
     "uma falha sem rasto acaba num cabecalho seguido de nada"),

    ("r3",
     "src/resoiltwin/weather/ingest.py",
     '    return quadros if len(quadros) <= espaco else "..." + quadros[-(espaco - 3):]',
     '    return quadros if len(quadros) <= espaco else quadros[:espaco]',
     "_cauda_do_rasto",
     "guarda-se a CABECA do rasto, que e sempre a mesma, e nao a cauda"),

    ("r4",
     "src/resoiltwin/weather/ingest.py",
     "    texto = texto[:_LIMITE_ERRO]",
     "    texto = texto[:0]",
     "_texto_do_erro",
     "a mensagem desaparece e sobra so o rasto"),
]
