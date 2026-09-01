"""Ronda da senha a porta da consola (decisao 2, 31/08/2026, a noite).

A consola lia sem credencial. A camada da Task 1 guarda a chave da API para o
navegador -- que e o desenho certo -- e ao faze-lo reabriu a leitura a quem
alcancasse o endereco; a decisao 2 tinha fechado essa leitura precisamente
porque estes dados nao sao publicos. O que este lote poe e uma porta a frente da
consola, com autenticacao HTTP basica, sem tocar na autenticacao da API.

Dezasseis mutantes, agrupados pelas cinco maneiras de mentir sobre esta porta.
Os quatro obrigatorios do enunciado estao ca:

- **a guarda deixa de ser aplicada a uma rota da consola** (`p1`, `p2`, `p3`).
  Sao tres porque as rotas da consola nascem em dois routers e o segundo e um
  apanha-tudo. `p1` tira a guarda ao router das paginas, `p2` ao apanha-tudo --
  que e o pior dos dois, porque uma rota de dados que caia la sem passar pela
  guarda expoe exactamente o que a porta existe para tapar --, e `p3` esvazia a
  lista de dependencias, que abre as sete rotas de uma vez com um caractere;
- **a comparacao volta a `==`** (`c1`). E o mutante que diz que o tempo de
  resposta nao interessa;
- **a guarda aceita senha vazia** (`v1`, `v2`). `v1` desliga a recusa por senha
  por configurar, e entao um cabecalho ausente da o par `("", "")` que casa com
  o par `("", "")` configurado -- credencial nenhuma a casar com credencial
  nenhuma, e a consola aberta precisamente na instalacao que se esqueceu do
  segredo. `v2` e a mesma falha escrita da forma "natural": `if senha_esperada:`
  a volta da conferencia;
- **a geracao de casos passa a lista fixa** (`i1`, `i2`). Sao dois porque a
  pergunta tem duas metades e as respostas sao diferentes. `i1` poe uma lista
  fixa CURTA e tem de morrer nos pisos. **`i2` poe a lista fixa que e
  exactamente a de hoje, e a previsao e que SOBREVIVA** -- nenhum teste
  consegue distinguir hoje uma lista gerada de uma lista escrita a mao que
  esteja certa hoje. E um sobrevivente previsto e declarado, nao um achado: o
  que fecha essa metade e a verificacao feita fora da suite (acrescentar uma
  rota de consola numa copia da arvore e confirmar que nascem casos novos e que
  caem), que esta no relatorio.

Os restantes medem o que o resto da decisao afirma:

- **as duas recusas continuam indistinguiveis** (`d1`, `d2`). `d1` compara os
  dois campos separadamente, ligados por `and`, que e a forma que vaza qual
  deles estava errado -- e cai pelo numero de chamadas a `compare_digest`, que
  e a unica maneira de medir isto sem cronometro. `d2` responde ao utilizador
  errado com outro texto;
- **o 401 continua a ser uma porta e nao uma parede** (`w1`, `w2`). `w1` tira o
  `WWW-Authenticate` e o navegador deixa de ter onde pedir a senha; `w2` troca o
  401 por 403, que o navegador nao usa para pedir credenciais;
- **a porta e da consola e de mais nada** (`a1`, `a2`). `a1` poe a guarda da
  consola num router da API, `a2` tira a chave da API a um router que a tem.
  Sao o outro sentido da fronteira: um lote que so mede o que fechou nao mede
  o que nao devia ter fechado;
- **a senha nao sai** (`s1`, `s2`). `s1` escreve o par apresentado no registo,
  `s2` devolve a senha configurada num cabecalho da resposta.
"""

# A lista que o `i2` usa: exactamente as sete de hoje. Escrita aqui e nao
# gerada, porque gera-la seria o mutante nao ser um mutante.
_AS_DE_HOJE = (
    "ROTAS_DA_CONSOLA = ["
    "('/console', 'GET'), ('/console/', 'GET'), "
    "('/console/estilo.css', 'GET'), ('/console/observacoes', 'GET'), "
    "('/console/sincronizacoes', 'GET'), ('/console/sitios', 'GET'), "
    "('/console/{caminho:path}', 'GET')]"
)

_DUAS_COMPARACOES = (
    "    if not (hmac.compare_digest(utilizador.encode(\"utf-8\"), "
    "utilizador_esperado.encode(\"utf-8\")) and hmac.compare_digest("
    "senha.encode(\"utf-8\"), senha_esperada.encode(\"utf-8\"))):"
)

MUTANTES = [
    # --- a guarda deixa de ser aplicada a uma rota da consola ---------------
    ("p1",
     "src/resoiltwin/main.py",
     "    app.include_router(console_views.router, dependencies=EXIGE_SENHA_DA_CONSOLA)",
     "    app.include_router(console_views.router)",
     "create_app",
     "as tres vistas da consola voltam a servir dados a quem so conhece o endereco"),
    ("p2",
     "src/resoiltwin/main.py",
     "    app.include_router(console.router, dependencies=EXIGE_SENHA_DA_CONSOLA)",
     "    app.include_router(console.router)",
     "create_app",
     "o apanha-tudo volta a reencaminhar leituras da API sem senha nenhuma"),
    ("p3",
     "src/resoiltwin/api/console_auth.py",
     "EXIGE_SENHA_DA_CONSOLA = [Depends(exigir_senha_da_consola)]",
     "EXIGE_SENHA_DA_CONSOLA = []",
     "(modulo)",
     "a porta desaparece das sete rotas de uma vez"),

    # --- a comparacao volta a `==` ------------------------------------------
    ("c1",
     "src/resoiltwin/api/console_auth.py",
     "    if not hmac.compare_digest(apresentado, esperado):",
     "    if apresentado != esperado:",
     "exigir_senha_da_consola",
     "a comparacao para no primeiro byte diferente e o tempo diz o prefixo certo"),

    # --- a guarda aceita senha vazia ----------------------------------------
    ("v1",
     "src/resoiltwin/api/console_auth.py",
     "    if not utilizador_esperado or not senha_esperada:",
     "    if False:",
     "exigir_senha_da_consola",
     "sem senha configurada a consola abre: o par vazio casa com o par vazio"),
    # v2 reformulado a 01/09/2026. A versao anterior inseria `if not
    # senha_esperada: return` DEPOIS da guarda que ja levanta 503 nesse caso --
    # codigo morto, mutante equivalente por construccao, e sobreviveu por isso e
    # nao por falta de teste. Esta versao ataca a metade que a v1 nao cobre: a
    # guarda deixar de exigir o UTILIZADOR. Com ela, uma instalacao que defina a
    # senha e esqueca o utilizador aceita quem apresente utilizador vazio e a
    # senha certa -- metade do par a valer pelo par inteiro.
    ("v2",
     "src/resoiltwin/api/console_auth.py",
     "    if not utilizador_esperado or not senha_esperada:",
     "    if not senha_esperada:",
     "exigir_senha_da_consola",
     "a guarda deixa de exigir o utilizador: metade do par vale pelo par inteiro"),

    # --- a geracao de casos passa a lista fixa ------------------------------
    ("i1",
     "tests/test_console_auth.py",
     "ROTAS_DA_CONSOLA = _rotas_da_consola(app)",
     "ROTAS_DA_CONSOLA = [(\"/console/observacoes\", \"GET\")]",
     "(modulo)",
     "o inventario passa a uma lista fixa curta e deixa de gerar casos"),
    ("i2",
     "tests/test_console_auth.py",
     "ROTAS_DA_CONSOLA = _rotas_da_consola(app)",
     _AS_DE_HOJE,
     "(modulo)",
     "o inventario passa a lista fixa que e exactamente a de hoje "
     "(SOBREVIVENTE PREVISTO)"),

    # --- as duas recusas continuam indistinguiveis --------------------------
    ("d1",
     "src/resoiltwin/api/console_auth.py",
     "    if not hmac.compare_digest(apresentado, esperado):",
     _DUAS_COMPARACOES,
     "exigir_senha_da_consola",
     "os dois campos sao comparados a parte e o tempo total diz qual falhou"),
    ("d2",
     "src/resoiltwin/api/console_auth.py",
     "            status.HTTP_401_UNAUTHORIZED,",
     "            status.HTTP_401_UNAUTHORIZED,\n"
     "            _RECUSADO if utilizador == utilizador_esperado else \"Unknown user\",",
     "exigir_senha_da_consola",
     "a resposta diz se o utilizador estava certo"),

    # --- o 401 continua a ser uma porta e nao uma parede --------------------
    ("w1",
     "src/resoiltwin/api/console_auth.py",
     "            headers={\"WWW-Authenticate\": DESAFIO},",
     None,
     "exigir_senha_da_consola",
     "o navegador deixa de ter onde pedir a senha"),
    ("w2",
     "src/resoiltwin/api/console_auth.py",
     "            status.HTTP_401_UNAUTHORIZED,",
     "            status.HTTP_403_FORBIDDEN,",
     "exigir_senha_da_consola",
     "recusa com um codigo que nao faz o navegador pedir credenciais"),

    # --- a porta e da consola e de mais nada --------------------------------
    ("a1",
     "src/resoiltwin/main.py",
     "    app.include_router(health.router, prefix=PREFIXO_DA_API)",
     "    app.include_router(health.router, prefix=PREFIXO_DA_API, "
     "dependencies=EXIGE_SENHA_DA_CONSOLA)",
     "create_app",
     "a sonda de saude passa a precisar da senha da consola e a revisao nunca fica saudavel"),
    ("a2",
     "src/resoiltwin/main.py",
     "    app.include_router(sites.router, prefix=PREFIXO_DA_API, dependencies=EXIGE_CHAVE)",
     "    app.include_router(sites.router, prefix=PREFIXO_DA_API, "
     "dependencies=EXIGE_SENHA_DA_CONSOLA)",
     "create_app",
     "a senha da consola substitui a chave da API nas rotas dos sitios"),

    # --- a senha nao sai ----------------------------------------------------
    ("s1",
     "src/resoiltwin/api/console_auth.py",
     "            \"wrong\" if pedido.headers.get(\"authorization\") else \"missing\",",
     "            f\"wrong ({utilizador}:{senha})\" if senha else \"missing\",",
     "exigir_senha_da_consola",
     "o par apresentado vai para o registo do servidor"),
    ("s2",
     "src/resoiltwin/api/console_auth.py",
     "            headers={\"WWW-Authenticate\": DESAFIO},",
     "            headers={\"WWW-Authenticate\": DESAFIO, \"X-Console-Expected\": senha_esperada},",
     "exigir_senha_da_consola",
     "a senha configurada volta num cabecalho da resposta"),
]
