"""Ronda da camada que guarda a chave (Fase F, Task 1, 31/08/2026).

A camada existe por uma razao so: um frontend que corre no navegador nao pode
guardar a chave que a API exige desde a manha de 31/08. Esta ronda pergunta se
a suite defende as quatro coisas que a fazem valer alguma coisa -- a chave vai
para a API, a chave nao volta, so passam leituras desta API, e nada disto
aparece no registo -- ou se ficou verde por construcao.

Dezasseis mutantes. Os tres obrigatorios do enunciado estao ca, e dois deles em
mais do que uma forma porque a mesma mentira tem mais do que um caminho:

- **a chave passa a ser servida ao navegador** -- `f1` pelo corpo (a guarda que
  varre a resposta antes de a mandar deixa de disparar), `f2` pelo envelope (os
  cabecalhos da API passam a ser copiados), `f5` pela propria camada (que passa
  a por a chave num cabecalho seu), `f4` por um corpo que a camada nao soube
  ler e copia na mesma. Sao quatro portas diferentes para a mesma rua, e duas
  delas so se veem com a API a colaborar com a fuga -- por isso e que ha duas
  aplicacoes de brincar em `test_console_camada.py` e nao uma;
- **o reencaminhamento aceita uma rota fora do previsto** -- `r1` deixa cair o
  prefixo (e entao o `/openapi.json`, que a decisao de 31/08 fechou de
  proposito, sai por aqui a quem nao tem chave), `r2` aceita um caminho que
  existe mas nao em `GET` (as oito rotas que escrevem passam a ser legiveis),
  `r3` tira a verificacao toda, `r4` poe a rota a aceitar os metodos que
  escrevem. `r5` e o sentido contrario e conta tanto como os outros: recusa
  tudo, porque uma porta soldada tambem nao e uma fechadura;
- **a chave entra num registo** -- `f3`.

⚠️ `f5` e `r5` nasceram depois da primeira corrida, e nao por gosto de simetria:
sem eles, `test_nenhuma_leitura_normal_deixa_sair_a_chave` e
`test_cada_leitura_da_api_e_alcancavel_pela_camada` eram os dois unicos testes
deste lote sem um mutante que os pusesse a cair -- ou seja, dois testes verdes
por construcao. A primeira corrida deu catorze em catorze e ficou a esconder
isso; foi a lista de apanhados, e nao a tabela, que o mostrou.

Os restantes medem o que sobra da decisao:

- **as geometrias nao passam** (`g1`, `g2`). ⛔ Os poligonos estao num
  repositorio privado desde 31/08. `g1` desliga o corte; `g2` e o mais
  interessante dos dois -- faz o corte depender da etiqueta `type`, ou seja
  passa a apanhar so o GeoJSON bem formado, e uma geometria mais magra passa;
- **a camada apresenta a chave, e e a dela** (`k1`, `k2`). `k1` deixa de a
  mandar; `k2` manda os cabecalhos do navegador em vez dos proprios, que e a
  forma de a camada deixar de guardar coisa nenhuma sem nenhum teste de fuga
  dar por isso;
- **os filtros da consola chegam a API** (`q1`). O lado positivo: uma camada
  que deitasse fora a query passava todos os testes de fuga e servia sempre
  tudo;
- **a excepcao a politica da chave e a camada, e nao mais nada** (`m1`). Poe a
  guarda no proprio router da consola: fecha-a a toda a gente, o que nao e
  proteger nada porque o navegador nao tem chave para apresentar.

⭐ O que se le a seguir a tabela e a lista de apanhados, mutante a mutante: um
mutante morto por dano colateral de outros testes deixa a sua propria guarda
sem medicao, ainda que a tabela diga "morto".
"""

CONSOLE = "src/resoiltwin/api/console.py"
MAIN = "src/resoiltwin/main.py"

MUTANTES = [
    # ---- a chave passa a ser servida ao navegador ----
    ("f1",
     CONSOLE,
     "    if chave and chave in texto:",
     "    if False:",
     "_resposta_para_o_navegador",
     "a chave volta para o navegador dentro do corpo"),
    ("f2",
     CONSOLE,
     "    return Response(content=texto, status_code=resposta.status_code, media_type=\"application/json\")",
     "    return Response(content=texto, status_code=resposta.status_code, "
     "media_type=\"application/json\", headers=dict(resposta.headers))",
     "_resposta_para_o_navegador",
     "os cabecalhos da API sao copiados para o navegador"),
    ("f5",
     CONSOLE,
     "    return Response(content=texto, status_code=resposta.status_code, media_type=\"application/json\")",
     "    return Response(content=texto, status_code=resposta.status_code, "
     "media_type=\"application/json\", headers={NOME_DO_CABECALHO: get_settings().write_api_key or \"\"})",
     "_resposta_para_o_navegador",
     "a propria camada poe a chave num cabecalho de todas as respostas"),
    ("f4",
     CONSOLE,
     "        logger.error(\"console refused a non-JSON answer from the API\")",
     "        return Response(content=resposta.text, status_code=502, media_type=\"text/plain\")",
     "_resposta_para_o_navegador",
     "um corpo que a camada nao soube ler e copiado na mesma"),

    # ---- a chave entra num registo ----
    ("f3",
     CONSOLE,
     "        logger.warning(\"console refused %s: not a read route of this API\", alvo)",
     "        logger.warning(\"console refused %s with %s\", alvo, get_settings().write_api_key)",
     "reencaminhar",
     "a chave entra na linha de registo da recusa"),

    # ---- o reencaminhamento aceita uma rota fora do previsto ----
    ("r1",
     CONSOLE,
     "    if not caminho.startswith(PREFIXO_DA_API + \"/\"):",
     "    if False:",
     "_e_leitura_da_api",
     "qualquer GET desta aplicacao passa, incluindo a documentacao"),
    ("r2",
     CONSOLE,
     "        if correspondencia == Match.FULL:",
     "        if correspondencia != Match.NONE:",
     "_e_leitura_da_api",
     "um caminho que so existe para escrever passa a ser legivel"),
    ("r3",
     CONSOLE,
     "    if not _e_leitura_da_api(aplicacao, alvo):",
     "    if False:",
     "reencaminhar",
     "a camada reencaminha o caminho que lhe derem"),
    ("r5",
     CONSOLE,
     "    if not _e_leitura_da_api(aplicacao, alvo):",
     "    if True:",
     "reencaminhar",
     "a camada recusa tudo, inclusive as leituras"),
    ("r4",
     CONSOLE,
     "@router.api_route(\"/{caminho:path}\", methods=[METODO_UNICO])",
     "@router.api_route(\"/{caminho:path}\", methods=[METODO_UNICO, \"POST\", \"PUT\", \"PATCH\", \"DELETE\"])",
     "(modulo)",
     "a camada aceita os metodos que escrevem"),

    # ---- as geometrias nao passam ----
    ("g1",
     CONSOLE,
     "    texto = json.dumps(_sem_geometria(corpo))",
     "    texto = json.dumps(corpo)",
     "_resposta_para_o_navegador",
     "as geometrias chegam ao navegador"),
    ("g2",
     CONSOLE,
     "        if \"coordinates\" in valor or \"geometries\" in valor or valor.get(\"type\") in TIPOS_GEOJSON:",
     "        if valor.get(\"type\") in TIPOS_GEOJSON:",
     "_sem_geometria",
     "so o GeoJSON com etiqueta de tipo e cortado"),

    # ---- a camada apresenta a chave, e e a dela ----
    ("k1",
     CONSOLE,
     "    return {NOME_DO_CABECALHO: get_settings().write_api_key or \"\", \"accept\": \"application/json\"}",
     "    return {\"accept\": \"application/json\"}",
     "_cabecalhos_para_a_api",
     "a camada nao apresenta chave nenhuma a API"),
    ("k2",
     CONSOLE,
     "            METODO_UNICO, alvo, params=pedido.url.query, headers=_cabecalhos_para_a_api()",
     "            METODO_UNICO, alvo, params=pedido.url.query, headers=dict(pedido.headers)",
     "reencaminhar",
     "os cabecalhos do navegador passam a ser os do pedido a API"),

    # ---- os filtros chegam a API ----
    ("q1",
     CONSOLE,
     "            METODO_UNICO, alvo, params=pedido.url.query, headers=_cabecalhos_para_a_api()",
     "            METODO_UNICO, alvo, params=\"\", headers=_cabecalhos_para_a_api()",
     "reencaminhar",
     "a query do navegador e deitada fora"),

    # ---- a excepcao a politica da chave ----
    ("m1",
     MAIN,
     "    app.include_router(console.router)",
     "    app.include_router(console.router, dependencies=EXIGE_CHAVE)",
     "create_app",
     "a consola passa a exigir a chave que o navegador nao tem"),
]
