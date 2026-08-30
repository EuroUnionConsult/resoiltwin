"""A base de dados da suite: uma por corrida, e nunca a de producao.

O que estes testes defendem esta escrito em `tests/base_de_testes.py`. Em
resumo: nao ha `DROP DATABASE` sobre uma base que este processo nao criou, e o
que garante isso nao e o nome -- e o servidor recusar um `CREATE` sobre um nome
que ja existe.

Dois destes testes criam bases de dados a serio no servidor. Sao bases de
brincar, com nome proprio e apagadas no fim: nenhum deles chega perto da base
real. Provar isto com afirmacoes sobre strings nao provava nada -- o acidente
que se quer impedir acontece no servidor, nao no Python.
"""

import os
import warnings

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError, OperationalError

from resoiltwin.config import get_settings
from tests.base_de_testes import (
    BaseDeTestes,
    DestinoRecusado,
    SobrasDeCorridasAnteriores,
    avisar_das_sobras,
    base_para_esta_corrida,
    bases_de_outras_corridas,
    com_outra_base,
    nome_da_base,
    nome_ja_tomado,
    nome_para_esta_corrida,
)

# host onde nao esta nada a ouvir: se uma guarda de nome deixar de disparar
# antes de se ligar, o que sai daqui e um OperationalError e nao um
# DestinoRecusado -- o que prende tambem a ORDEM, e nao so a existencia da
# guarda.
URL_INALCANCAVEL = "postgresql+psycopg://resoiltwin:pw@127.0.0.1:1/resoiltwin"


def _de_brincar(etiqueta: str) -> str:
    """Nome de uma base de experiencia deste processo, para nao colidir com nada."""
    return f"resoiltwin_test_brincar_{etiqueta}_{os.getpid()}"


def _largar_a_forca(url_de_manutencao: str, nome: str) -> None:
    """Rede de seguranca dos testes que criam a base a mao.

    Quando um destes testes falha -- que e o que acontece a cada ronda de
    mutacao -- o `largar()` do codigo em prova pode nao ter corrido, e a base
    fica no servidor. Uma suite que enche o servidor sempre que falha era
    trocar a divida por outra. So se larga o que este ficheiro criou.
    """
    admin = create_engine(url_de_manutencao, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{nome}" WITH (FORCE)'))
    finally:
        admin.dispose()


def _existe(url_de_manutencao: str, nome: str) -> bool:
    admin = create_engine(url_de_manutencao, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            return conn.scalar(
                text("SELECT count(*) FROM pg_database WHERE datname = :n"), {"n": nome}
            ) == 1
    finally:
        admin.dispose()


@pytest.fixture
def base_de_brincar():
    """Cria bases a serio no servidor e larga-as no fim, aconteca o que acontecer.

    Existe para que os testes desta guarda possam encenar o acidente -- uma
    base que JA EXISTE no destino -- sem o encenar sobre a base real.
    """
    origem = get_settings().database_url
    manutencao = com_outra_base(origem, "postgres")
    criadas: list[str] = []

    def criar(nome: str, com_prova: bool = False) -> str:
        admin = create_engine(manutencao, isolation_level="AUTOCOMMIT")
        try:
            with admin.connect() as conn:
                conn.execute(text(f'DROP DATABASE IF EXISTS "{nome}" WITH (FORCE)'))
                conn.execute(text(f'CREATE DATABASE "{nome}"'))
        finally:
            admin.dispose()
        criadas.append(nome)
        if com_prova:
            # uma linha la dentro: e ela que prova, no fim, que a base nao foi
            # largada e recriada pelas costas do teste
            dentro = create_engine(com_outra_base(origem, nome))
            try:
                with dentro.begin() as conn:
                    conn.execute(text("CREATE TABLE prova (valor text)"))
                    conn.execute(text("INSERT INTO prova VALUES ('nao me apagues')"))
            finally:
                dentro.dispose()
        return nome

    yield criar

    admin = create_engine(manutencao, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            for nome in criadas:
                conn.execute(text(f'DROP DATABASE IF EXISTS "{nome}" WITH (FORCE)'))
    finally:
        admin.dispose()


def _ler_prova(origem: str, nome: str) -> list[str]:
    eng = create_engine(com_outra_base(origem, nome))
    try:
        with eng.connect() as conn:
            return list(conn.scalars(text("SELECT valor FROM prova")))
    finally:
        eng.dispose()


# -- a guarda que interessa: nunca largar o que nao criamos -------------------


def test_uma_base_que_ja_existia_nao_e_criada_nem_largada(base_de_brincar):
    """O acidente encenado: o destino dos testes aponta a uma base a serio.

    E a guarda de que tudo isto depende. Aqui a base de brincar faz de base de
    producao -- existe, tem uma linha la dentro, e nao e nossa. O nome dela
    passa a guarda do nome de proposito (tem o prefixo de teste), para que o
    que a salve seja a segunda guarda e nao a primeira.
    """
    origem = get_settings().database_url
    alheia = base_de_brincar(_de_brincar("alheia"), com_prova=True)

    base = BaseDeTestes(origem, nome=alheia)
    with pytest.raises(DestinoRecusado) as erro:
        base.criar()
    assert alheia in str(erro.value)
    assert base.criada is False

    # e, tendo recusado criar, tem de recusar tambem largar
    with pytest.raises(DestinoRecusado):
        base.largar()

    # a prova: a base continua la, com o que tinha dentro
    assert _existe(com_outra_base(origem, "postgres"), alheia)
    assert _ler_prova(origem, alheia) == ["nao me apagues"]


def _erro_do_servidor(sqlstate: str) -> DBAPIError:
    """Um erro do driver como o SQLAlchemy o entrega, com o sqlstate pedido.

    Fabricado e nao provocado no servidor de proposito: provocar um 23505 a
    serio exige duas corridas a criar o mesmo nome no mesmo instante, e um
    42501 exige um utilizador sem CREATEDB. Nenhuma das duas coisas cabe numa
    suite, e o que se quer prender aqui e a CLASSIFICACAO -- que le o sqlstate
    e mais nada.
    """
    class _Orig(Exception):
        pass

    orig = _Orig("erro do servidor")
    orig.sqlstate = sqlstate
    return DBAPIError("CREATE DATABASE ...", {}, orig)


def test_a_corrida_concorrente_perdedora_ve_a_mensagem_e_nao_um_erro_cru():
    """23505 e nome tomado tanto quanto 42P04, e chega noutra classe.

    O `CREATE DATABASE` e atomico: duas corridas a criar o mesmo nome sao
    serializadas no indice unico do pg_database, e a perdedora recebe
    `IntegrityError`/23505 -- nao `ProgrammingError`/42P04, que e o que o
    servidor manda quando o nome ja la estava antes de nos chegarmos.
    Classificar pela classe da excepcao deixava a perdedora ver o erro cru
    justamente no cenario que este modulo existe para cobrir.
    """
    assert nome_ja_tomado(_erro_do_servidor("23505")) is True
    assert nome_ja_tomado(_erro_do_servidor("42P04")) is True


def test_um_erro_que_nao_e_nome_tomado_sobe_como_esta():
    """Falta de permissao nao e "a base ja existe", e nao pode ser dito como tal.

    O 42501 insufficient_privilege chega na MESMA classe que o 42P04. Apanhar
    pela classe dizia a quem nao tem CREATEDB que a base ja existe -- falso, e
    manda-o procurar no sitio errado. Sao precisos os dois lados: o que a
    classificacao aceita, e o que ela tem de deixar passar.
    """
    assert nome_ja_tomado(_erro_do_servidor("42501")) is False
    assert nome_ja_tomado(_erro_do_servidor("53300")) is False
    assert nome_ja_tomado(_erro_do_servidor("")) is False


def test_larga_a_base_que_criou_e_nao_a_que_o_atributo_disser(base_de_brincar):
    """O alvo do DROP e o nome que o CREATE aceitou, e nao um atributo publico.

    Ate 30/08/2026 o `largar()` validava um booleano e largava o que estivesse
    em `self.nome` naquele instante: `criar()`, trocar o atributo, `largar()`,
    e saia um DROP DATABASE sobre uma base alheia -- incluindo uma que a guarda
    do nome recusa. A frase "nunca sai daqui um DROP sobre uma base que este
    processo nao criou" era, tal e qual, falsa.
    """
    origem = get_settings().database_url
    manutencao = com_outra_base(origem, "postgres")
    alheia = base_de_brincar(_de_brincar("intocavel"), com_prova=True)

    base = BaseDeTestes(origem)
    base.criar()
    minha = base.nome
    try:
        base.nome = alheia          # o atributo publico passa a mentir
        base.largar()
    finally:
        _largar_a_forca(manutencao, minha)

    assert _existe(manutencao, alheia)
    assert _ler_prova(origem, alheia) == ["nao me apagues"]
    assert not _existe(manutencao, minha)


def test_largar_recusa_uma_base_que_esta_corrida_nao_criou():
    """A guarda vive dentro do `largar()`, e nao so no caminho do `with`.

    Sem ligacao nenhuma: se o `largar()` chegasse a falar com o servidor antes
    de verificar de quem e a base, o que saia daqui era um erro de ligacao.
    """
    base = BaseDeTestes(URL_INALCANCAVEL, nome="resoiltwin_test_nunca_criada")
    with pytest.raises(DestinoRecusado) as erro:
        base.largar()
    assert "nao a criou" in str(erro.value)


# -- a guarda do nome --------------------------------------------------------


def test_o_destino_nao_pode_ser_a_base_do_database_url():
    """Um destino igual a base para onde o DATABASE_URL aponta e recusado."""
    base = BaseDeTestes(URL_INALCANCAVEL, nome="resoiltwin")
    with pytest.raises(DestinoRecusado) as erro:
        base.criar()
    assert "MESMA base" in str(erro.value)


def test_um_destino_sem_o_prefixo_de_teste_e_recusado():
    base = BaseDeTestes(URL_INALCANCAVEL, nome="resoiltwin_arquivo_2026")
    with pytest.raises(DestinoRecusado):
        base.criar()


def test_um_nome_que_nao_e_um_identificador_e_recusado():
    """O nome entra por interpolacao num CREATE/DROP DATABASE.

    Nao ha ligacao de parametros possivel para o nome de uma base, portanto o
    que o filtra e esta guarda.
    """
    base = BaseDeTestes(URL_INALCANCAVEL, nome='resoiltwin_test_x" ; DROP DATABASE "resoiltwin')
    with pytest.raises(DestinoRecusado):
        base.criar()


def test_a_guarda_do_nome_dispara_antes_de_qualquer_ligacao():
    """Um destino que passe a guarda do nome chega mesmo a tentar ligar-se.

    Controlo negativo do teste acima: sem ele, uma guarda que recusasse TUDO
    fazia os tres testes anteriores passar sem defender coisa nenhuma.
    """
    base = BaseDeTestes(URL_INALCANCAVEL, nome="resoiltwin_test_boa_1")
    with pytest.raises(OperationalError):
        base.criar()


# -- uma base por processo ---------------------------------------------------


def test_o_nome_da_base_traz_o_processo_e_nao_se_repete():
    """Duas corridas nao podem pedir o mesmo nome.

    O pid diz de quem e a base quando sobra uma no servidor; a parte aleatoria
    e o que impede que um pid reciclado colida com essa sobra.
    """
    primeiro, segundo = nome_para_esta_corrida(), nome_para_esta_corrida()
    assert primeiro != segundo
    assert f"_{os.getpid()}_" in primeiro
    assert primeiro.startswith("resoiltwin_test_")


def test_a_base_da_corrida_e_largada_mesmo_quando_o_corpo_rebenta():
    """Requisito 2: uma base por corrida nao pode ficar a acumular.

    A base existe mesmo dentro do bloco -- confirmado no servidor, nao pela
    ausencia de excepcao -- e deixa de existir depois dele, ainda que se saia
    por uma excepcao.
    """
    origem = get_settings().database_url
    manutencao = com_outra_base(origem, "postgres")
    base = BaseDeTestes(origem)

    class Rebentou(RuntimeError):
        pass

    try:
        with pytest.raises(Rebentou):
            with base:
                assert _existe(manutencao, base.nome)
                raise Rebentou("a suite falhou a meio")

        assert not _existe(manutencao, base.nome)
    finally:
        _largar_a_forca(manutencao, base.nome)


def test_a_base_e_largada_mesmo_com_uma_ligacao_aberta():
    """Um teste que rebenta com uma ligacao por fechar nao pode deixar a base.

    Sem terminar as ligacoes, o `DROP DATABASE` falha e a base fica no
    servidor -- que era o problema que esta divida veio fechar.
    """
    origem = get_settings().database_url
    manutencao = com_outra_base(origem, "postgres")
    base = BaseDeTestes(origem)
    base.criar()
    pendurada = create_engine(base.url)
    conn = pendurada.connect()
    try:
        conn.execute(text("SELECT 1"))
        base.largar()
        assert not _existe(manutencao, base.nome)
    finally:
        # a ligacao ja foi terminada pelo servidor; devolve-la ao pool poe o
        # SQLAlchemy a tentar um ROLLBACK sobre uma coisa que ja nao existe
        conn.invalidate()
        pendurada.dispose()
        _largar_a_forca(manutencao, base.nome)


# -- as sobras de outras corridas --------------------------------------------


def test_as_sobras_de_outras_corridas_sao_listadas_e_nao_largadas(base_de_brincar):
    """Listar, nunca largar: uma delas pode ser de uma corrida a decorrer.

    E a lista tem de ser SO das bases de teste: se trouxesse a base do
    DATABASE_URL, a mensagem convidava quem a lesse a largar a base real.
    """
    origem = get_settings().database_url
    sobra = base_de_brincar(_de_brincar("sobra"))

    listadas = bases_de_outras_corridas(origem)

    assert sobra in listadas
    assert nome_da_base(origem) not in listadas
    assert "postgres" not in listadas
    # continua la depois de ter sido listada
    assert _existe(com_outra_base(origem, "postgres"), sobra)


def test_uma_base_alheia_com_nome_parecido_nao_entra_na_lista(base_de_brincar):
    """`_` e um jogador no LIKE do SQL: sozinho, casa com qualquer caracter.

    Sem o ESCAPE, o padrao `resoiltwin_test%` apanhava tambem uma base chamada
    `resoiltwin2test_...` -- e a mensagem convidava a largar a base de outra
    pessoa.
    """
    origem = get_settings().database_url
    alheia = base_de_brincar(f"resoiltwin2test_arquivo_{os.getpid()}")
    assert alheia not in bases_de_outras_corridas(origem)


def test_a_base_da_corrida_avisa_das_sobras_antes_de_existir(base_de_brincar):
    """A costura entre listar e avisar, num sitio que uma ronda alcanca.

    Enquanto esteve dentro do `conftest.py`, apagar a chamada ao aviso deixava
    a suite verde: nao havia teste nenhum sobre a ligacao entre as duas metades,
    so sobre cada uma delas.

    E o aviso sai ANTES de a base desta corrida ser criada -- por isso e que
    ela propria nunca aparece na lista, sem filtro nenhum a exclui-la.
    """
    origem = get_settings().database_url
    sobra = base_de_brincar(_de_brincar("costura"))

    with pytest.warns(SobrasDeCorridasAnteriores, match=sobra):
        base = base_para_esta_corrida(origem)

    assert base.nome not in bases_de_outras_corridas(origem)
    assert base.criada is False


def test_as_sobras_saem_como_aviso_e_nao_como_texto_engolido():
    """Numa corrida VERDE, o que uma fixture de sessao imprime nao aparece.

    E a corrida verde e precisamente aquela em que isto precisa de ser lido --
    um aviso engolido nao e um aviso.
    """
    with pytest.warns(SobrasDeCorridasAnteriores, match="resoiltwin_test_de_ontem"):
        avisar_das_sobras(["resoiltwin_test_de_ontem"])


def test_sem_sobras_nao_ha_aviso():
    """Controlo negativo: um aviso que sai sempre deixa de se ler."""
    with warnings.catch_warnings():
        warnings.simplefilter("error", SobrasDeCorridasAnteriores)
        avisar_das_sobras([])


# -- derivar a url sem estragar o resto dela ---------------------------------


def test_trocar_a_base_nao_toca_no_utilizador_com_o_mesmo_nome():
    """O defeito que o `.replace("/resoiltwin", ...)` teria.

    Nesta url o utilizador chama-se `resoiltwin` e a base tambem: um replace
    por substring trocava os dois e a ligacao passava a autenticar-se com um
    utilizador que nao existe.
    """
    url = "postgresql+psycopg://resoiltwin:pw@localhost:55433/resoiltwin"
    assert com_outra_base(url, "resoiltwin_test_9") == (
        "postgresql+psycopg://resoiltwin:pw@localhost:55433/resoiltwin_test_9"
    )


def test_a_query_da_url_nao_entra_no_nome_da_base():
    url = "postgresql+psycopg://u:pw@h:5432/resoiltwin?sslmode=require"
    assert nome_da_base(url) == "resoiltwin"
    assert com_outra_base(url, "resoiltwin_test_9") == (
        "postgresql+psycopg://u:pw@h:5432/resoiltwin_test_9?sslmode=require"
    )
