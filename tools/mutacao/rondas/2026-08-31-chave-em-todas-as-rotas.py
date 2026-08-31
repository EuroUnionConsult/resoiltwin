"""Ronda do alargamento da chave a todas as rotas (decisoes 7 e 2, 31/08/2026).

De manha a chave cobria as oito rotas que escrevem, e a ronda desse dia
(`2026-08-31-chave-das-rotas-de-escrita.py`) mediu essa fronteira. A tarde o
ambito passou a ser «todas menos o `/health`», e a metade da fronteira que
antes exigia leitura aberta inverteu-se. Esta ronda mede a fronteira nova, e
mede-a nos dois sentidos.

Treze mutantes, agrupados pelas cinco maneiras de a mentir. Os tres
obrigatorios do enunciado estao ca:

- **a guarda deixa de ser aplicada a uma rota de LEITURA** (`r1`, `r2`). E o
  mutante que mede a coisa que este lote mudou. `r1` tira-a ao `jobs` e `r2` ao
  `timeseries`, que sao os dois routers que so leem: se os testes de leitura
  fossem os de ontem -- que exigiam resposta SEM chave --, estes dois mutantes
  nao so sobreviviam como faziam a suite passar melhor;
- **a guarda passa a ser aplicada ao `/health`** (`h1`). O outro sentido. E a
  unica isencao que existe, e existe porque a sonda de saude da plataforma
  chama a rota sem cabecalho nenhum: uma guarda a mais aqui nao aperta o
  sistema, desliga-o;
- **a geracao de casos a partir de `app.routes` passa a lista fixa** (`i1`,
  `i2`). Sao dois porque a pergunta tem duas metades e as respostas sao
  diferentes. `i1` poe uma lista fixa CURTA e tem de morrer nos pisos.
  **`i2` poe a lista fixa que e exactamente a de hoje, e a previsao e que
  SOBREVIVA** -- nenhum teste consegue distinguir hoje uma lista gerada de uma
  lista escrita a mao que esteja certa hoje. E um sobrevivente previsto e
  declarado, nao um achado: o que fecha essa metade e a verificacao feita fora
  da suite (acrescentar uma rota numa copia da arvore e confirmar que nascem
  casos novos e que caem), e o `i2` esta aqui para que essa dependencia fique
  medida em vez de afirmada.

Os restantes medem o que o resto da decisao afirma:

- **as quatro rotas de documentacao ficam fechadas** (`d1`, `d2`). `d1` tira a
  guarda ao router; `d2` e o acidente que se quis impossivel de cometer em
  silencio -- devolver o `/openapi.json` ao FastAPI, que o regista no
  `__init__` como rota do Starlette, portanto ANTES da nossa e sem dependencia
  nenhuma, e a partir dai o esquema sai a quem o pedir;
- **a escrita continua fechada** (`e1`, `e2`), que era o que a ronda da manha
  media e nao pode ter-se perdido ao mudar o sitio onde a guarda e aplicada;
- **a guarda continua a ser uma guarda** (`c1`, `v1`, `v2`, `g1`). `c1` volta a
  comparar com `==`; `v1` e `v2` sao as duas formas de uma chave por configurar
  abrir em vez de fechar; `g1` esvazia a lista de dependencias, que e o mutante
  que abre as vinte e tres rotas de uma vez com um caractere.
"""

# A lista que o `i2` usa: exactamente as vinte e quatro de hoje. Escrita aqui e
# nao gerada, porque gera-la seria o mutante nao ser um mutante.
_AS_DE_HOJE = (
    "TODAS_AS_ROTAS = ["
    "('/api/v1/aois/{code}/approve', 'POST'), ('/api/v1/health', 'GET'), "
    "('/api/v1/jobs', 'GET'), ('/api/v1/jobs/{job_id}', 'GET'), "
    "('/api/v1/observations', 'POST'), ('/api/v1/sites', 'GET'), "
    "('/api/v1/sites', 'POST'), ('/api/v1/sites/{code}', 'GET'), "
    "('/api/v1/sites/{code}/aois', 'GET'), ('/api/v1/sites/{code}/aois', 'POST'), "
    "('/api/v1/sites/{code}/eo/sync', 'POST'), ('/api/v1/sites/{code}/plots', 'GET'), "
    "('/api/v1/sites/{code}/plots', 'POST'), ('/api/v1/sites/{code}/timeseries', 'GET'), "
    "('/api/v1/sites/{code}/water/sync', 'POST'), "
    "('/api/v1/sites/{code}/weather/sync', 'POST'), "
    "('/docs', 'GET'), ('/docs', 'HEAD'), "
    "('/docs/oauth2-redirect', 'GET'), ('/docs/oauth2-redirect', 'HEAD'), "
    "('/openapi.json', 'GET'), ('/openapi.json', 'HEAD'), "
    "('/redoc', 'GET'), ('/redoc', 'HEAD')]"
)

MUTANTES = [
    # --- a guarda deixa de ser aplicada a uma rota de LEITURA ----------------
    ("r1",
     "src/resoiltwin/main.py",
     '    app.include_router(jobs.router, prefix="/api/v1", dependencies=EXIGE_CHAVE)',
     '    app.include_router(jobs.router, prefix="/api/v1")',
     "create_app",
     "ler o estado dos jobs volta a nao exigir credencial nenhuma"),
    ("r2",
     "src/resoiltwin/main.py",
     '    app.include_router(timeseries.router, prefix="/api/v1", dependencies=EXIGE_CHAVE)',
     '    app.include_router(timeseries.router, prefix="/api/v1")',
     "create_app",
     "ler as series de um sitio volta a nao exigir credencial nenhuma"),

    # --- a guarda passa a ser aplicada ao /health ----------------------------
    ("h1",
     "src/resoiltwin/main.py",
     '    app.include_router(health.router, prefix="/api/v1")',
     '    app.include_router(health.router, prefix="/api/v1", dependencies=EXIGE_CHAVE)',
     "create_app",
     "o /health passa a pedir chave, e a sonda de saude nao tem onde a por"),

    # --- a geracao de casos passa a lista fixa -------------------------------
    ("i1",
     "tests/test_api_auth.py",
     "TODAS_AS_ROTAS = _rotas_de(app)",
     'TODAS_AS_ROTAS = [("/api/v1/observations", "POST"), ("/api/v1/health", "GET")]',
     "(modulo)",
     "o inventario passa a lista fixa curta: quase nenhuma rota gera caso"),
    ("i2",
     "tests/test_api_auth.py",
     "TODAS_AS_ROTAS = _rotas_de(app)",
     _AS_DE_HOJE,
     "(modulo)",
     "o inventario passa a lista fixa igual a de hoje (SOBREVIVENTE previsto)"),

    # --- as quatro rotas de documentacao ficam fechadas ----------------------
    ("d1",
     "src/resoiltwin/main.py",
     "    app.include_router(docs.router, dependencies=EXIGE_CHAVE)",
     "    app.include_router(docs.router)",
     "create_app",
     "o esquema e o /docs voltam a sair a quem nao tem chave"),
    ("d2",
     "src/resoiltwin/main.py",
     "        openapi_url=None,",
     '        openapi_url="/openapi.json",',
     "create_app",
     "o FastAPI volta a registar o /openapi.json, sem guarda e antes do nosso"),

    # --- a escrita continua fechada -----------------------------------------
    ("e1",
     "src/resoiltwin/main.py",
     '    app.include_router(observations.router, prefix="/api/v1", dependencies=EXIGE_CHAVE)',
     '    app.include_router(observations.router, prefix="/api/v1")',
     "create_app",
     "gravar uma observacao volta a nao exigir credencial nenhuma"),
    ("e2",
     "src/resoiltwin/main.py",
     '    app.include_router(sites.router, prefix="/api/v1", dependencies=EXIGE_CHAVE)',
     '    app.include_router(sites.router, prefix="/api/v1")',
     "create_app",
     "criar sitios e aprovar AOI volta a nao exigir credencial nenhuma"),

    # --- a guarda continua a ser uma guarda ----------------------------------
    ("c1",
     "src/resoiltwin/api/auth.py",
     '    if not hmac.compare_digest(apresentada.encode("utf-8"), esperada.encode("utf-8")):',
     "    if apresentada != esperada:",
     "exigir_chave",
     "a comparacao volta a `==` e o tempo de resposta passa a contar a chave"),
    ("v1",
     "src/resoiltwin/api/auth.py",
     "    if not esperada:",
     "    if False:",
     "exigir_chave",
     "sem chave configurada a guarda deixa de fechar"),
    ("v2",
     "src/resoiltwin/api/auth.py",
     "    if not esperada:",
     "    if esperada is None:",
     "exigir_chave",
     "WRITE_API_KEY vazia passa a ser uma chave, e um X-API-Key vazio casa com ela"),
    ("g1",
     "src/resoiltwin/api/auth.py",
     "EXIGE_CHAVE = [Depends(exigir_chave)]",
     "EXIGE_CHAVE = []",
     "(modulo)",
     "a lista de dependencias fica vazia e as vinte e tres rotas abrem de uma vez"),
]
