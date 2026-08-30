"""Ronda sobre a base de dados que a suite cria para si.

A divida numero 3 da Fase C. O `conftest.py` fixava o nome `resoiltwin_test` e
fazia-lhe `DROP DATABASE` a cada arranque: duas corridas ao mesmo tempo
atropelavam-se, e o unico obstaculo entre esse `DROP` e uma base a serio era
uma derivacao de string acertar.

Cada mutante afirma uma coisa falsa sobre a nova guarda. Se sobreviver, ha um
pedaco dela que nenhum teste esta a defender.

**Nenhum mutante desta ronda pode chegar a base real, e isso e por desenho e
nao por sorte.** Os testes que encenam um nome perigoso -- a base do
`DATABASE_URL`, um nome com aspas para dentro do `DROP DATABASE` -- fazem-no
todos contra `127.0.0.1:1`, onde nao esta nada a ouvir. Com a guarda do nome
desligada, o que sai de la e um erro de ligacao, nao um comando executado.

**O `tests/conftest.py` fica de fora desta ronda, de proposito.** Os mutantes
interessantes que la vivem sao todos da mesma forma -- apontar a suite, ou as
migracoes, a base do `DATABASE_URL` -- e correr um seria fazer de proposito
exactamente aquilo que este commit existe para tornar impossivel. O que se
mede aqui e o modulo que decide o destino; o `conftest` limita-se a chama-lo.
"""

FICHEIRO = "tests/base_de_testes.py"

MUTANTES = [
    # -- a guarda que interessa ---------------------------------------------
    ("b1",
     FICHEIRO,
     "        if not self.criada:",
     "        if False:",
     "largar",
     "sai um DROP DATABASE sobre uma base que esta corrida nao criou"),

    ("b12",
     FICHEIRO,
     '                conn.execute(text(f\'DROP DATABASE IF EXISTS "{self.nome}" WITH (FORCE)\'))',
     '                conn.execute(text(f\'DROP DATABASE IF EXISTS "{self.nome}"\'))',
     "largar",
     "uma ligacao esquecida impede o DROP e a base fica a acumular no servidor"),

    # -- a guarda do nome ----------------------------------------------------
    ("b2",
     FICHEIRO,
     "        self.verificar_o_nome()",
     None,
     "criar",
     "a guarda do nome nunca chega a correr"),

    ("b3",
     FICHEIRO,
     "        if self.nome == origem:",
     "        if False:",
     "verificar_o_nome",
     "o destino dos testes pode ser a propria base do DATABASE_URL"),

    ("b4",
     FICHEIRO,
     "        if not self.nome.startswith(PREFIXO):",
     "        if False:",
     "verificar_o_nome",
     "um destino sem o prefixo de teste passa na guarda"),

    ("b5",
     FICHEIRO,
     "        if not IDENTIFICADOR.match(self.nome):",
     "        if False:",
     "verificar_o_nome",
     "um nome com aspas entra por interpolacao no CREATE/DROP DATABASE"),

    # -- uma base por processo -----------------------------------------------
    ("b6",
     FICHEIRO,
     '    return f"{PREFIXO}{os.getpid()}_{secrets.token_hex(3)}"',
     '    return f"{PREFIXO}fixo"',
     "nome_para_esta_corrida",
     "o nome da base nao depende do processo: duas corridas voltam a partilhar base"),

    # -- derivar a url -------------------------------------------------------
    ("b7",
     FICHEIRO,
     '    trocado = caminho.rsplit("/", 1)[0] + "/" + nome',
     "    trocado = caminho.replace(nome_da_base(caminho), nome)",
     "com_outra_base",
     "a base troca-se por substring, e um utilizador com o mesmo nome vai atras"),

    ("b8",
     FICHEIRO,
     '    return url.split("?", 1)[0].rsplit("/", 1)[-1]',
     '    return url.rsplit("/", 1)[-1]',
     "nome_da_base",
     "a query da url passa a fazer parte do nome da base"),

    # -- as sobras -----------------------------------------------------------
    ("b9",
     FICHEIRO,
     '                {"padrao": FAMILIA.replace("_", "!_") + "%"},',
     '                {"padrao": "%"},',
     "bases_de_outras_corridas",
     "a lista de sobras traz todas as bases do servidor, a real inclusive"),

    ("b10",
     FICHEIRO,
     "    return [n for n in nomes if n != excepto]",
     "    return []",
     "bases_de_outras_corridas",
     "nenhuma sobra e alguma vez reportada"),

    ("b11",
     FICHEIRO,
     "    if not sobras:",
     "    if True:",
     "avisar_das_sobras",
     "o aviso das sobras nunca sai"),
]
