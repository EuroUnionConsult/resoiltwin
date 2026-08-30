"""Ronda da correccao dos dois Important da revisao das dividas 3 e 4.

I1: o largar() usava `self.nome`, atributo publico que ninguem revalidava
    depois do criar(). O revisor executou-o e largou uma base que a corrida
    nao criou. Agora o alvo e `_nome_criado`, e `criada` e derivado.
I2: a corrida concorrente da IntegrityError (23505) e nao ProgrammingError
    (42P04); apanhar pela classe deixava a perdedora ver um erro cru.
Costura: apagar o aviso das sobras deixava a suite VERDE, porque a chamada
    vivia no conftest.py, fora do alcance das rondas.
"""

MUTANTES = [
    ("i1a", "tests/base_de_testes.py",
     "        alvo = self._nome_criado",
     "        alvo = self.nome",
     "largar",
     "o DROP volta a usar o atributo publico em vez do nome que o CREATE aceitou"),

    ("i1b", "tests/base_de_testes.py",
     "        self._nome_criado = self.nome",
     "        self._nome_criado = None",
     "criar",
     "o criar() nao regista o nome, portanto o largar() nunca larga nada"),

    ("i1c", "tests/base_de_testes.py",
     "        return self._nome_criado is not None",
     "        return True",
     "criada",
     "criada mente: diz que ha base criada mesmo antes do CREATE"),

    ("i2a", "tests/base_de_testes.py",
     'SQLSTATES_DE_NOME_TOMADO = frozenset({"42P04", "23505"})',
     'SQLSTATES_DE_NOME_TOMADO = frozenset({"42P04"})',
     "(modulo)",
     "so o 42P04: a corrida concorrente perdedora volta a ver um erro cru"),

    ("i2b", "tests/base_de_testes.py",
     '    return getattr(erro.orig, "sqlstate", None) in SQLSTATES_DE_NOME_TOMADO',
     "    return True",
     "nome_ja_tomado",
     "qualquer erro do CREATE passa por nome tomado, incluindo falta de permissao"),

    ("cos", "tests/base_de_testes.py",
     "    avisar_das_sobras(bases_de_outras_corridas(url_de_origem))",
     None,
     "base_para_esta_corrida",
     "a costura das sobras desaparece -- era isto que ficava verde no conftest"),
]
