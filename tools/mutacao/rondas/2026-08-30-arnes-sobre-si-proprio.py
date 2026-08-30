"""Ronda do arnes contra o proprio arnes.

Uma ronda e descartavel e morre com o dia. Esta fica porque responde a uma
pergunta que se faz a qualquer ferramenta nova: os testes dela sao vacuos?

Cada mutante desliga UMA guarda de tools/mutacao/arnes.py. Se o teste dessa
guarda estiver a medir alguma coisa, o mutante morre; se sobreviver, o teste
existe mas nao prova nada.

    python tools/mutacao/arnes.py \\
        tools/mutacao/rondas/2026-08-30-arnes-sobre-si-proprio.py

Cada mutante corre a suite INTEIRA do repositorio, que e onde vivem os testes
do arnes. O `g7` custa meio minuto a mais: e o unico caminho para provar que a
falta do timeout se nota.
"""

ARNES = "tools/mutacao/arnes.py"

# esta ancora tem plicas E aspas: cadeias CRUAS, para nao passar por dois niveis
# de escape. Foi ai que uma ancora saiu errada numa ronda da Fase C -- e o arnes
# abortou, que e exactamente o que devia fazer.
ANCORA_SABOTAGEM = (
    r"""SABOTAGEM = '\n\nraise RuntimeError("sabotagem do arnes: """
    r"""a copia tem de ser a fonte importada")\n'"""
)

MUTANTES = [
    ("g1", ARNES,
     "        if copia == self.raiz or copia.is_relative_to(self.raiz):",
     "        if False:",
     "_copiar", "guarda 1: deixar a arvore de trabalho cair dentro da arvore real"),

    ("g1b", ARNES,
     "        copia = self.copia.resolve()",
     "        copia = self.copia",
     "_copiar", "guarda 1: comparar sem resolver, que e a forma que o macOS produz"),

    ("g2", ARNES,
     "            if execucao.codigo == 0:",
     "            if False:",
     "_provar_que_a_copia_e_a_fonte",
     "guarda 2: aceitar uma sentinela sabotada que nao derruba a suite"),

    ("g2b", ARNES,
     "            alvo.write_bytes(original + SABOTAGEM.encode())",
     "            alvo.write_bytes(original)",
     "_provar_que_a_copia_e_a_fonte", "guarda 2: sabotar sem sabotar nada"),

    ("g2c", ARNES,
     ANCORA_SABOTAGEM,
     r'SABOTAGEM = "\n\n# sabotagem inerte\n"',
     "(modulo)", "guarda 2: sabotagem inerte, que nao rebenta ao ser importada"),

    ("g3", ARNES,
     "        if execucao.codigo != 0:",
     "        if False:",
     "_exigir_base_verde", "guarda 3: deixar mutar sobre uma base vermelha"),

    ("g3b", ARNES,
     "        if execucao.codigo == 5:",
     "        if False:",
     "_exigir_base_verde", "guarda 3: nao distinguir a base que nao recolhe teste nenhum"),

    ("g3c", ARNES,
     "        if execucao.passados == 0:",
     "        if False:",
     "_exigir_base_verde", "guarda 3: aceitar uma base verde que nao correu teste nenhum"),

    # o ramo `esgotou` da guarda 3 nao se pode ancorar na linha do `if`: ela e
    # identica, letra por letra, a do `_julgar`, e o arnes recusa uma ancora
    # ambigua. Ancorada no `raise`, que e unico.
    ("g3d", ARNES,
     '            raise ArnesInvalido(f"a base nao acabou em {self.timeout}s; nada disto e mensuravel")',
     "            pass",
     "_exigir_base_verde", "guarda 3: nao recusar uma base que estoira o tempo"),

    ("g4", ARNES,
     "    if len(ocorrencias) != 1:",
     "    if False:",
     "preparar_mutante", "guarda 4: aceitar uma ancora ambigua ou inexistente"),

    ("g5", ARNES,
     "        ast.parse(mutado)",
     "        pass",
     "preparar_mutante", "guarda 5: nao verificar que o mutante compila"),

    ("g6", ARNES,
     "    if encontrado != mutante.ambito:",
     "    if False:",
     "preparar_mutante", "guarda 6: nao confirmar o ambito declarado"),

    ("g6b", ARNES,
     "        if no.lineno <= numero <= fim and no.lineno > inicio_mais_interior:",
     "        if no.lineno <= numero <= fim and no.lineno < inicio_mais_interior:",
     "ambito_da_linha", "guarda 6: escolher o ambito de fora em vez do mais interior"),

    ("g7", ARNES,
     "                                     text=True, timeout=tecto or self.timeout)",
     "                                     text=True)",
     "_correr_suite", "guarda 7: correr a suite sem tecto de tempo"),

    ("g7b", ARNES,
     "                execucao = self._correr_suite(self.timeout_do_mutante)",
     "                execucao = self._correr_suite()",
     "_mutar", "guarda 7: ignorar o tecto por mutante e usar o da base"),

    ("g8", ARNES,
     "    if actual != digest:",
     "    if False:",
     "verificar_restauro", "guarda 8: nao verificar o restauro por sha256"),

    ("g9", ARNES,
     '                   "--no-header", "--tb=no", "-rfE", *self.argumentos]',
     '                   "--no-header", "--tb=no", "-rfE", "-k", "soma", *self.argumentos]',
     "_correr_suite", "guarda 9: estreitar a corrida em vez de correr a suite inteira"),

    ("g10", ARNES,
     "        return SUSPEITO",
     "        return MORTO",
     "_julgar", "guarda 10: contar como morte um mutante que rebenta na recolha"),

    ("g11", ARNES,
     '        if linha.startswith("FAILED "):',
     "        if False:",
     "_apanhados_e_recolha", "guarda 11: deixar de ler os testes caidos do relatorio"),

    ("g12", ARNES,
     "    if ast.dump(ast.parse(mutado)) == ast.dump(ast.parse(fonte)):",
     "    if False:",
     "preparar_mutante", "guarda 12: aceitar um mutante que nao muda nada"),

    ("g12b", ARNES,
     "    if ast.dump(ast.parse(mutado)) == ast.dump(ast.parse(fonte)):",
     "    if mutante.substituto == mutante.ancora:",
     "preparar_mutante", "guarda 12: voltar a igualdade literal, que deixa passar um espaco"),
]
