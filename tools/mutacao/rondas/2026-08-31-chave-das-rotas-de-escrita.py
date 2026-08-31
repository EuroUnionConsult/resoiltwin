"""Ronda da chave partilhada das rotas de escrita (decisao 7, 31/08/2026).

Catorze mutantes sobre a unica fronteira que este lote acrescentou. Estao
agrupados pelas quatro maneiras de a mentir, e as quatro obrigatorias do
enunciado estao todas ca:

- **a guarda deixa de ser aplicada a uma rota que escreve** (`g1`--`g5`). Uma
  por ficheiro, para que a linha da ancora seja unica em cada um. E o mutante
  que mede a unica coisa que interessa saber sobre estes testes: se cobrem cada
  rota ou se cobrem uma e presumem as outras. `g1` e a aprovacao de AOI, que e
  a rota de que a proveniencia depende;
- **a comparacao volta a `==`** (`c1`). Nao ha teste de tempo que apanhe isto
  sem ser instavel; quem o apanha e o teste que espia `hmac.compare_digest` e
  exige que a chave passe la;
- **a guarda passa a aceitar chave vazia** (`v1`, `v2`). `v1` desliga a guarda
  do "nao ha chave configurada"; `v2` e a variante insidiosa, que so deixa
  passar `WRITE_API_KEY=` vazia -- e ai `compare_digest(b"", b"")` e True e um
  `X-API-Key:` vazio casa com credencial nenhuma;
- **a guarda passa a ser aplicada tambem as leituras** (`l1`, `l2`). Para
  provar que a fronteira esta pinada nos dois sentidos e nao so num. `l2` poe a
  guarda no `/health`, que e o que uma sonda de disponibilidade chama sem
  cabecalho nenhum -- e como `health.py` nao importa a lista, o substituto
  vai-a buscar por `__import__`, que e feio de proposito: um mutante nao tem de
  ser bonito, tem de ser valido.

Os restantes quatro medem as afirmacoes que a decisao faz e que nao estao na
lista obrigatoria: as duas recusas serem indistinguiveis (`n1`, `n2`), a chave
nao sair no registo (`s1`), e a documentacao gerada dizer que a rota precisa de
chave (`d1` -- que muda o `/docs` sem mudar o comportamento, e por isso so pode
morrer pelo teste do OpenAPI).
"""

MUTANTES = [
    # --- a guarda deixa de ser aplicada a uma rota que escreve ---------------
    ("g1",
     "src/resoiltwin/api/sites.py",
     '@router.post("/aois/{code}/approve", response_model=AoiRead, dependencies=EXIGE_CHAVE_DE_ESCRITA)',
     '@router.post("/aois/{code}/approve", response_model=AoiRead)',
     "(modulo)",
     "aprovar uma AOI volta a nao exigir credencial nenhuma"),
    ("g2",
     "src/resoiltwin/api/observations.py",
     "    dependencies=EXIGE_CHAVE_DE_ESCRITA,",
     None,
     "(modulo)",
     "gravar uma observacao volta a nao exigir credencial nenhuma"),
    ("g3",
     "src/resoiltwin/api/eo.py",
     "    dependencies=EXIGE_CHAVE_DE_ESCRITA,",
     None,
     "(modulo)",
     "a sincronizacao Copernicus volta a nao exigir credencial nenhuma"),
    ("g4",
     "src/resoiltwin/api/weather.py",
     "    dependencies=EXIGE_CHAVE_DE_ESCRITA,",
     None,
     "(modulo)",
     "a sincronizacao meteorologica volta a nao exigir credencial nenhuma"),
    ("g5",
     "src/resoiltwin/api/water.py",
     "    dependencies=EXIGE_CHAVE_DE_ESCRITA,",
     None,
     "(modulo)",
     "a sincronizacao do balanco hidrico volta a nao exigir credencial nenhuma"),

    # --- a comparacao volta a ser por igualdade ------------------------------
    ("c1",
     "src/resoiltwin/api/auth.py",
     '    if not hmac.compare_digest(apresentada.encode("utf-8"), esperada.encode("utf-8")):',
     "    if apresentada != esperada:",
     "exigir_chave_de_escrita",
     "a comparacao volta a `==` e o tempo de resposta passa a contar a chave"),

    # --- a guarda passa a aceitar chave vazia --------------------------------
    ("v1",
     "src/resoiltwin/api/auth.py",
     "    if not esperada:",
     "    if False:",
     "exigir_chave_de_escrita",
     "sem chave configurada a guarda deixa de fechar"),
    ("v2",
     "src/resoiltwin/api/auth.py",
     "    if not esperada:",
     "    if esperada is None:",
     "exigir_chave_de_escrita",
     "WRITE_API_KEY vazia passa a ser uma chave, e um X-API-Key vazio casa com ela"),

    # --- a guarda passa a ser aplicada tambem as leituras --------------------
    ("l1",
     "src/resoiltwin/api/sites.py",
     '@router.get("/sites", response_model=list[SiteRead])',
     '@router.get("/sites", response_model=list[SiteRead], dependencies=EXIGE_CHAVE_DE_ESCRITA)',
     "(modulo)",
     "listar sitios passa a pedir chave, e e uma leitura"),
    ("l2",
     "src/resoiltwin/api/health.py",
     '@router.get("/health")',
     '@router.get("/health", dependencies=__import__("resoiltwin.api.auth", fromlist=["a"]).EXIGE_CHAVE_DE_ESCRITA)',
     "(modulo)",
     "a sonda de disponibilidade passa a precisar da chave de escrita"),

    # --- as duas recusas deixam de ser indistinguiveis -----------------------
    ("n1",
     "src/resoiltwin/api/auth.py",
     '        logger.warning("write request refused: no %s header", NOME_DO_CABECALHO)',
     '        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "no X-API-Key header")',
     "exigir_chave_de_escrita",
     "a resposta diz se o cabecalho faltava ou se a chave e que estava errada"),
    ("n2",
     "src/resoiltwin/api/auth.py",
     "    auto_error=False,",
     "    auto_error=True,",
     "(modulo)",
     "o cabecalho em falta passa a 403 do FastAPI, e a chave errada fica em 401"),

    # --- a chave sai no registo ----------------------------------------------
    ("s1",
     "src/resoiltwin/api/auth.py",
     '        logger.warning("write request refused: %s did not match", NOME_DO_CABECALHO)',
     '        logger.warning("write refused: %s is not %s", apresentada, esperada)',
     "exigir_chave_de_escrita",
     "o registo passa a escrever a chave apresentada e a esperada"),

    # --- a documentacao gerada deixa de dizer que a rota precisa de chave ----
    ("d1",
     "src/resoiltwin/api/auth.py",
     "def exigir_chave_de_escrita(apresentada: str | None = Security(_cabecalho_da_chave)) -> None:",
     'def exigir_chave_de_escrita(apresentada: str | None = __import__("fastapi").Header(None, alias=NOME_DO_CABECALHO)) -> None:',  # noqa: E501
     "exigir_chave_de_escrita",
     "a guarda continua a funcionar mas o /docs deixa de dizer que a rota pede chave"),
]
