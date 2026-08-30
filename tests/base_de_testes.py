"""A base de dados que a suite cria para si: uma por corrida, e nunca a real.

Ate 30/08/2026 o `conftest.py` fixava o nome `resoiltwin_test` e comecava a
sessao com `DROP DATABASE IF EXISTS resoiltwin_test`. Duas consequencias, e
nenhuma delas era teorica neste projecto:

- **duas corridas ao mesmo tempo atropelam-se.** Uma ronda de mutacao corre a
  suite dentro de uma copia da arvore, mas a copia liga-se a MESMA base; um
  `pytest` local ao lado apaga a base debaixo da ronda, e os resultados que
  saem dai nao valem nada. Estava escrito como regra no README do arnes, e uma
  regra escrita nao e uma guarda;
- **o destino do `DROP` era derivado, e uma derivacao pode estar errada.** Ja
  houve neste repositorio um `DATABASE_URL` mal escrito que levou um comando
  destrutivo a base real e custou 139 observacoes.

Este modulo fecha as duas coisas, e o que fecha a segunda nao e o nome.

**O nome nao chega.** Um nome so prova aquilo que quem o escreveu quis dizer:
uma base chamada `resoiltwin_test_1` pode perfeitamente ser a base a serio de
alguem, e uma derivacao com um defeito produz o nome errado com toda a
confianca do mundo. O que distingue de forma fiavel uma base de testes de uma
base a serio e uma coisa que o servidor sabe e nos nao podemos fingir: **quem
a criou**. Uma base que existia antes de esta corrida comecar nao e nossa.

Dai as duas guardas, por esta ordem:

1. **o nome** -- barata, e da uma mensagem que se percebe. Recusa um destino
   que seja a propria base do `DATABASE_URL`, que nao tenha o prefixo de
   teste, ou que traga caracteres que nao entram num identificador. E a
   primeira a disparar porque e a que explica melhor o engano;
2. **a criacao** -- a que vale. O `CREATE DATABASE` corre **sem** `IF NOT
   EXISTS` e **sem** um `DROP` antes: se o nome ja estiver tomado, e o
   servidor que recusa, atomicamente. E `largar()` recusa-se a correr enquanto
   `criar()` nao tiver corrido com exito nesta corrida. Juntas, dao a
   propriedade que interessa: **nunca sai daqui um `DROP DATABASE` sobre uma
   base que este processo nao criou.** Se a guarda do nome tiver um buraco, ou
   se um dia alguem mudar a derivacao e apontar isto a base real, o `CREATE`
   falha porque ela existe, `criar()` levanta, e nada e largado. A base real
   nao e protegida por nos acertarmos no nome; e protegida por ela ja existir.
"""

import os
import re
import secrets
import warnings

from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

# prefixo do nome de qualquer base criada por uma corrida de testes: e o que a
# guarda do nome exige de um destino.
PREFIXO = "resoiltwin_test_"

# e a familia inteira, para reconhecer sobras. Mais curta do que o PREFIXO de
# proposito: apanha tambem o `resoiltwin_test` sem sufixo do desenho anterior a
# 30/08/2026, que e a sobra que qualquer maquina com historia neste projecto
# tem la neste momento.
FAMILIA = "resoiltwin_test"

# base de manutencao a que nos ligamos para criar e largar as outras. Ligar-nos
# a base do DATABASE_URL para isto -- que era o que o conftest fazia -- abria
# uma ligacao em AUTOCOMMIT contra a base REAL so para lhe correr comandos ao
# lado. `postgres` existe em qualquer instalacao e nao tem nada dentro.
BASE_DE_MANUTENCAO = "postgres"

# um identificador que vai por interpolacao para dentro de um DROP DATABASE
# tem de ser reconhecivel a olho. Nao ha aqui ligacao de parametros possivel:
# o Postgres nao aceita um placeholder no nome de uma base.
IDENTIFICADOR = re.compile(r"^[a-z][a-z0-9_]{0,62}$")

# as duas maneiras de o servidor dizer "esse nome ja esta tomado", e sao mesmo
# duas:
#   42P04 duplicate_database -- o nome ja la estava quando o CREATE chegou;
#   23505 unique_violation   -- DUAS corridas a criar o mesmo nome ao mesmo
#     tempo. O Postgres serializa-as no indice unico do pg_database, e a
#     perdedora recebe isto e nao 42P04. E o cenario exacto que este modulo
#     existe para cobrir: ficar so pelo 42P04 fazia a corrida perdedora ver um
#     erro cru em vez da mensagem que explica o que aconteceu.
# Qualquer outro sqlstate NAO e nome tomado e tem de subir como esta. O 42501
# insufficient_privilege, por exemplo, tambem chega aqui como ProgrammingError:
# apanha-lo pela classe da excepcao dizia a quem nao tem CREATEDB que a base ja
# existe, o que e falso e manda-o procurar no sitio errado.
SQLSTATES_DE_NOME_TOMADO = frozenset({"42P04", "23505"})


class SobrasDeCorridasAnteriores(UserWarning):
    """Ha bases de teste no servidor que nao sao desta corrida."""


class DestinoRecusado(RuntimeError):
    """Uma guarda disparou: este destino nao vai ser criado nem largado.

    Nunca e um resultado. E a recusa de mexer numa base que pode nao ser nossa.
    """


def nome_ja_tomado(erro: DBAPIError) -> bool:
    """O servidor recusou o CREATE por o nome ja estar tomado?

    Classifica pelo sqlstate e nao pela classe da excepcao: as duas formas de
    "nome tomado" chegam em classes diferentes (`ProgrammingError` e
    `IntegrityError`) e a classe `ProgrammingError` traz tambem erros que nao
    tem nada que ver com isto. Ver SQLSTATES_DE_NOME_TOMADO.
    """
    return getattr(erro.orig, "sqlstate", None) in SQLSTATES_DE_NOME_TOMADO


def nome_da_base(url: str) -> str:
    """O ultimo segmento do caminho de uma url de ligacao.

    Nao se usa `.replace("/resoiltwin", ...)`: a url tem "//resoiltwin" no
    protocolo e no utilizador, e um replace ingenuo troca tambem o nome de
    utilizador. E a query (`?sslmode=require`) sai antes, senao passava a
    fazer parte do nome.
    """
    return url.split("?", 1)[0].rsplit("/", 1)[-1]


def com_outra_base(url: str, nome: str) -> str:
    """A mesma url de ligacao, a apontar a outra base. Preserva a query."""
    caminho, _, query = url.partition("?")
    trocado = caminho.rsplit("/", 1)[0] + "/" + nome
    return f"{trocado}?{query}" if query else trocado


def nome_para_esta_corrida() -> str:
    """Um nome que nenhuma outra corrida usa.

    O pid identifica quem e o dono -- e o que permite, ao ver uma base a mais
    no servidor, perceber de que corrida veio. Mas o pid sozinho nao chega: o
    sistema operativo reutiliza-os, e uma sobra de uma corrida abatida a tiro
    tomaria o nome de uma corrida futura. Como o `CREATE` nao apaga o que
    encontra, essa colisao nao seria perigosa -- seria uma corrida a abortar
    sem defeito nenhum. Os seis digitos aleatorios tiram-lhe a hipotese.
    """
    return f"{PREFIXO}{os.getpid()}_{secrets.token_hex(3)}"


def bases_de_outras_corridas(url: str) -> list[str]:
    """Bases da familia de teste que existem no servidor.

    Chama-se ANTES de criarmos a nossa, e e so por isso que a nossa nao entra
    na lista: nao ha aqui filtro nenhum a excluir-nos. Um parametro `excepto`
    existiu ate 30/08/2026 e nenhum chamador de producao o usava -- so um
    teste, o que faz dele um caminho que corre sem servir ninguem.

    Deliberadamente NAO sao largadas. Uma delas pode ser de uma corrida a
    decorrer neste momento -- que e precisamente o caso que este modulo existe
    para tornar seguro -- e apagar a base de uma suite em execucao seria
    repetir o defeito com outro nome. Um `DROP` que ninguem pediu tambem nao e
    coisa que uma suite de testes deva fazer por sua conta.

    Ficam listadas para quem correu a suite decidir. O caminho normal ja nao
    produz sobras: `largar()` corre no `finally` do gestor de contexto e
    portanto tambem quando a suite falha. O que sobra vem de uma corrida morta
    a meio -- um SIGKILL, a maquina a desligar-se -- e isso nao e frequente ao
    ponto de justificar apagar o que nao se sabe de quem e.
    """
    admin = create_engine(com_outra_base(url, BASE_DE_MANUTENCAO), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            # ESCAPE porque `_` e um jogador no LIKE: sem isto o padrao
            # apanhava tambem um `resoiltwin-testes` de alguem
            nomes = conn.execute(
                text("SELECT datname FROM pg_database WHERE datname LIKE :padrao ESCAPE '!' "
                     "ORDER BY datname"),
                {"padrao": FAMILIA.replace("_", "!_") + "%"},
            ).scalars().all()
    finally:
        admin.dispose()
    return list(nomes)


def avisar_das_sobras(sobras: list[str]) -> None:
    """Poe as sobras a vista de quem correu a suite, sem lhes tocar.

    `warnings.warn` e nao `print`: o pytest engole o que uma fixture de sessao
    escreve numa corrida verde -- que e exactamente a corrida em que isto
    precisa de ser lido -- e mostra sempre o sumario de avisos.

    A mensagem nao manda largar nada. Esta lista sai do NOME, que e a unica
    coisa que ha para olhar de fora, e o nome nao prova de quem e a base --
    e o que este ficheiro comeca por dizer. Quem a ler sabe se tem uma corrida
    a decorrer; o modulo nao sabe.
    """
    if not sobras:
        return
    warnings.warn(
        f"bases com nome da familia de teste no servidor: {', '.join(sobras)}. "
        "Esta suite nao lhes toca: uma delas pode ser de uma corrida a decorrer, e o nome "
        "sozinho nao prova que sao de teste. Quem souber que nao ha corrida nenhuma a "
        "decorrer e o unico que pode decidir larga-las.",
        SobrasDeCorridasAnteriores,
        stacklevel=2,
    )


class BaseDeTestes:
    """Uma base de dados criada para esta corrida, e largada no fim dela.

    Usa-se como gestor de contexto:

        with BaseDeTestes(settings.database_url) as base:
            ...  # base.url aponta a base nova, ja criada e vazia

    Se `criar()` levantar, o `__exit__` nunca chega a correr -- e a semantica
    do `with` em Python -- portanto `largar()` nunca e chamado sobre uma base
    que nao foi criada aqui. A guarda dentro do `largar()` continua a valer
    para quem o chame a mao.
    """

    def __init__(self, url_de_origem: str, nome: str | None = None):
        self.url_de_origem = url_de_origem
        self.nome = nome or nome_para_esta_corrida()
        self.url = com_outra_base(url_de_origem, self.nome)
        self.url_de_manutencao = com_outra_base(url_de_origem, BASE_DE_MANUTENCAO)
        # o nome que o CREATE aceitou, e o UNICO que o DROP alguma vez usa.
        # `self.nome` e um atributo publico: quem lhe mexer depois do criar()
        # muda o que este objecto diz, e nao o que ele larga. Ate 30/08/2026 o
        # largar() validava um booleano e largava `self.nome` -- bastava trocar
        # o atributo entre as duas chamadas para pôr um DROP DATABASE sobre uma
        # base alheia, e a frase "nunca sai daqui um DROP sobre uma base que
        # este processo nao criou" era falsa.
        self._nome_criado: str | None = None

    @property
    def criada(self) -> bool:
        """Esta corrida criou uma base que ainda nao largou?

        Derivado, e nao um booleano a parte: um booleano e mais uma coisa que
        pode ficar dessincronizada do nome que interessa.
        """
        return self._nome_criado is not None

    # -- guarda 1: o nome ---------------------------------------------------

    def verificar_o_nome(self) -> None:
        """Recusa um destino que se leia como uma base a serio.

        Barata e clara, mas nao e ela que impede o acidente: um nome so diz o
        que quem o escreveu quis dizer. Quem impede e a guarda 2.
        """
        if not IDENTIFICADOR.match(self.nome):
            raise DestinoRecusado(
                f"'{self.nome}' nao e um identificador de base aceitavel; o nome vai por "
                "interpolacao para dentro de um CREATE/DROP DATABASE e tem de ser legivel a olho")
        origem = nome_da_base(self.url_de_origem)
        if self.nome == origem:
            raise DestinoRecusado(
                f"o destino dos testes e '{self.nome}', que e a MESMA base para onde o "
                "DATABASE_URL aponta. A suite cria e larga a base em que corre: se corresse "
                "nessa, largava-a.")
        if not self.nome.startswith(PREFIXO):
            raise DestinoRecusado(
                f"'{self.nome}' nao comeca por '{PREFIXO}'; a suite so cria bases que se "
                "reconhecam como suas")

    # -- guarda 2: quem a criou ---------------------------------------------

    def criar(self) -> None:
        """Cria a base. Sem `IF NOT EXISTS`, e sem `DROP` nenhum antes.

        E aqui que a base real fica a salvo, e nao na guarda do nome: uma base
        que ja existe faz este `CREATE` falhar, e uma corrida que nao criou
        nada nunca larga nada. Ninguem tem de acertar no nome para que a base
        real sobreviva -- basta ela existir.
        """
        self.verificar_o_nome()
        admin = create_engine(self.url_de_manutencao, isolation_level="AUTOCOMMIT")
        try:
            with admin.connect() as conn:
                try:
                    conn.execute(text(f'CREATE DATABASE "{self.nome}"'))
                except DBAPIError as erro:
                    if not nome_ja_tomado(erro):
                        raise
                    raise DestinoRecusado(
                        f"'{self.nome}' ja existe no servidor: esta corrida nao a criou, "
                        "portanto nao e dela e nao vai ser tocada. Se e mesmo uma sobra de "
                        "uma corrida anterior, larga-a a mao.") from erro
        finally:
            admin.dispose()
        self._nome_criado = self.nome

    def largar(self) -> None:
        """Larga a base -- se e so se esta corrida a criou.

        `WITH (FORCE)` porque uma ligacao esquecida por um teste que rebentou a
        meio faria o `DROP` falhar e a base ficar para tras; sobre uma base que
        acabamos de criar, terminar as ligacoes nao tira nada a ninguem.
        """
        alvo = self._nome_criado
        if alvo is None:
            raise DestinoRecusado(
                f"recusado largar '{self.nome}': esta corrida nao a criou. Um DROP DATABASE "
                "sobre uma base que ja ca estava e exactamente o acidente que este modulo "
                "existe para impedir.")
        admin = create_engine(self.url_de_manutencao, isolation_level="AUTOCOMMIT")
        try:
            with admin.connect() as conn:
                conn.execute(text(f'DROP DATABASE IF EXISTS "{alvo}" WITH (FORCE)'))
        finally:
            admin.dispose()
        self._nome_criado = None

    def __enter__(self) -> "BaseDeTestes":
        self.criar()
        return self

    def __exit__(self, *_excepcao) -> bool:
        self.largar()
        return False


def base_para_esta_corrida(url_de_origem: str) -> BaseDeTestes:
    """A base desta corrida, com o aviso das sobras dado antes de a criar.

    Existe para que a costura entre as duas coisas viva num ficheiro que uma
    ronda de mutacao consegue alcancar. Enquanto esteve dentro do
    `conftest.py`, apagar a linha do aviso deixava a suite verde: a regra que
    mantem o `conftest` fora das rondas (os mutantes interessantes que la vivem
    apontam a suite a base real) nao cobria esta chamada, e "sao todos da mesma
    forma" era mais largo do que o argumento aguentava.

    A ordem tambem interessa: as sobras sao listadas ANTES de a nossa existir,
    portanto sao todas alheias por construcao e nao e preciso filtro nenhum.
    """
    avisar_das_sobras(bases_de_outras_corridas(url_de_origem))
    return BaseDeTestes(url_de_origem)
