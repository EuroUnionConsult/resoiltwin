"""Testes do arnes de mutacao.

O arnes foi a principal guarda de qualidade da Fase C e mentiu de tres formas
diferentes num so dia. Nenhuma guarda entra no repositorio com a palavra de
quem a escreveu: cada uma tem aqui um teste que a poe a disparar.

Desenho, e nao e negociavel: estes testes NAO correm a suite real do projecto.
Montam uma arvore de brincar -- tres modulos e dois ficheiros de teste -- e
correm o arnes sobre ela. Cada guarda testa-se por construcao: monta-se a
arvore no estado que faz a guarda disparar, e afirma-se que dispara.
"""

import hashlib
import importlib.util
import json
import shutil
import textwrap
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]

# o arnes e carregado PELO CAMINHO, a partir da raiz onde este teste vive.
# Assim, quando o proprio arnes e mutado (o arnes corrido sobre si mesmo), o
# que estes testes exercitam e o arnes da COPIA -- que e o unico que faz a
# ronda significar alguma coisa.
_spec = importlib.util.spec_from_file_location(
    "arnes_sob_teste", RAIZ / "tools" / "mutacao" / "arnes.py")
arnes = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(arnes)

Mutante = arnes.Mutante
ArnesInvalido = arnes.ArnesInvalido


# --------------------------------------------------------------------------
# a arvore de brincar
# --------------------------------------------------------------------------

CALCULO = '''\
"""Modulo de brincar: existe so para o arnes ter o que mutar."""

LIMITE = 10


def soma(a, b):
    return a + b


def dentro_do_limite(valor):
    if valor > LIMITE:
        return False
    return True


def classificar(valores):
    saida = []
    for valor in valores:
        if valor < 0:
            continue
        saida.append(valor)
    return saida


def par(numero):
    if numero % 2 == 0:
        return True
    return False


def impar(numero):
    if numero % 2 == 1:
        return True
    return False
'''

# ninguem importa este modulo: serve para provar que a guarda 2 dispara quando
# a sentinela nao esta no caminho de import da suite
ORFAO = '"""Ninguem importa isto."""\n\nVALOR = 1\n'

TESTE_UM = '''\
from brinquedo.calculo import soma


def test_a_soma_da_cinco():
    assert soma(2, 3) == 5
'''

TESTE_DOIS = '''\
import pytest

from brinquedo.calculo import classificar, dentro_do_limite


def test_o_limite_e_respeitado():
    if dentro_do_limite(11):
        # pytest.fail levanta Failed, que deriva de BaseException e nao de
        # Exception: um arnes com `except Exception` dava este mutante como vivo
        pytest.fail("11 esta acima do limite e passou na mesma")


def test_os_negativos_sao_descartados():
    assert classificar([-1, 2, -3]) == [2]
'''

PYPROJECT = '''\
[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
'''


def construir_arvore(raiz: Path, *, teste_um: str = TESTE_UM, teste_dois: str = TESTE_DOIS) -> Path:
    (raiz / "src" / "brinquedo").mkdir(parents=True, exist_ok=True)
    (raiz / "tests").mkdir(parents=True, exist_ok=True)
    (raiz / "pyproject.toml").write_text(PYPROJECT)
    (raiz / "src" / "brinquedo" / "__init__.py").write_text("")
    (raiz / "src" / "brinquedo" / "calculo.py").write_text(CALCULO)
    (raiz / "src" / "brinquedo" / "orfao.py").write_text(ORFAO)
    if teste_um is not None:
        (raiz / "tests" / "test_um.py").write_text(teste_um)
    if teste_dois is not None:
        (raiz / "tests" / "test_dois.py").write_text(teste_dois)
    return raiz


CALCULO_REL = "src/brinquedo/calculo.py"

M_SOBREVIVENTE = Mutante("sobrevivente", CALCULO_REL, "    return a + b", "    return b + a",
                         "soma", "trocar a ordem das parcelas da soma")
M_LIMITE = Mutante("limite", CALCULO_REL, "LIMITE = 10", "LIMITE = 100",
                   arnes.MODULO, "subir o limite para 100")
M_RECOLHA = Mutante("recolha", CALCULO_REL, "LIMITE = 10", "LIMITE = 1 / 0",
                    arnes.MODULO, "rebentar no import, antes de qualquer teste correr")
M_BLOQUEIO = Mutante("bloqueio", CALCULO_REL, "    return a + b",
                     '    __import__("time").sleep(30); return a + b',
                     "soma", "matar por bloqueio em vez de por falha")


@pytest.fixture(scope="session")
def arvore(tmp_path_factory):
    return construir_arvore(tmp_path_factory.mktemp("brinquedo"))


@pytest.fixture
def arvore_nova(tmp_path):
    return construir_arvore(tmp_path)


@pytest.fixture(scope="session")
def ronda_de_referencia(arvore):
    """Uma ronda unica com um sobrevivente, uma morte a serio e uma suspeita.

    Fica com a arvore de trabalho por apagar para que se possa afirmar que o
    ficheiro mutado voltou ao que era.
    """
    motor = arnes.Arnes(arvore, [M_SOBREVIVENTE, M_LIMITE, M_RECOLHA],
                        timeout=120, escrever=lambda *_: None)
    try:
        # com manter=True o arnes nao apaga a arvore de trabalho, nem quando
        # aborta -- e para isso que ela serve. Limpar aqui, e nao a seguir ao
        # yield, senao uma guarda a disparar deixa a copia para tras
        yield motor.correr(manter=True)
    finally:
        if motor.copia is not None:
            shutil.rmtree(motor.copia.parent, ignore_errors=True)


def instantaneo(raiz: Path) -> dict:
    saida = {}
    for caminho in sorted(raiz.rglob("*")):
        if not caminho.is_file() or "__pycache__" in caminho.parts:
            continue
        dados = caminho.read_bytes()
        saida[str(caminho.relative_to(raiz))] = (
            len(dados), caminho.stat().st_mtime_ns, hashlib.sha256(dados).hexdigest())
    return saida


# --------------------------------------------------------------------------
# raiz derivada, e nenhum caminho desta maquina
# --------------------------------------------------------------------------

def test_a_raiz_do_repositorio_e_derivada_do_pyproject():
    assert arnes.raiz_do_repositorio(Path(__file__)) == RAIZ
    assert (RAIZ / "pyproject.toml").is_file()


def test_a_raiz_recusa_uma_arvore_sem_pyproject(tmp_path):
    with pytest.raises(ArnesInvalido, match="pyproject"):
        arnes.raiz_do_repositorio(tmp_path / "sem" / "nada")


def test_o_arnes_nao_traz_caminhos_desta_maquina():
    """Nenhum caminho absoluto de uma maquina em ficheiro versionado."""
    for caminho in sorted((RAIZ / "tools").rglob("*")):
        if not caminho.is_file() or "__pycache__" in caminho.parts:
            continue
        texto = caminho.read_text()
        assert "/Users/" not in texto, caminho
        assert "/home/" not in texto, caminho
        assert ".venv/bin/python" not in texto, caminho


# --------------------------------------------------------------------------
# carregar a ronda de um ficheiro, nunca embutida no motor
# --------------------------------------------------------------------------

def test_a_ronda_le_se_de_um_ficheiro_py(tmp_path):
    ficheiro = tmp_path / "ronda.py"
    ficheiro.write_text(textwrap.dedent('''\
        MUTANTES = [
            ("a", "src/x.py", "linha", "outra", "funcao", "descricao"),
        ]
        '''))
    (mutante,) = arnes.carregar_ronda(ficheiro)
    assert mutante.ident == "a"
    assert mutante.substituto == "outra"


def test_a_ronda_le_se_de_um_ficheiro_json(tmp_path):
    ficheiro = tmp_path / "ronda.json"
    ficheiro.write_text(json.dumps([{
        "ident": "b", "ficheiro": "src/x.py", "ancora": "linha", "substituto": None,
        "ambito": "funcao", "descricao": "apagar a linha"}]))
    (mutante,) = arnes.carregar_ronda(ficheiro)
    assert mutante.ident == "b"
    assert mutante.substituto is None


def test_a_ronda_recusa_identificadores_repetidos(tmp_path):
    ficheiro = tmp_path / "ronda.py"
    ficheiro.write_text(textwrap.dedent('''\
        MUTANTES = [
            ("a", "src/x.py", "um", "dois", "f", "d"),
            ("a", "src/x.py", "tres", "quatro", "f", "d"),
        ]
        '''))
    with pytest.raises(ArnesInvalido, match="repetidos"):
        arnes.carregar_ronda(ficheiro)


# --------------------------------------------------------------------------
# guarda 4: ancora de linha unica
# --------------------------------------------------------------------------

def test_guarda_4_recusa_uma_ancora_que_aparece_duas_vezes():
    """`        return True` esta em `par` E em `impar`.

    Foi assim que `job.status = JobStatus.running` passou a existir nos dois
    caminhos de ingestao e o arnes passou a mutar o sitio errado -- o
    "sobrevivente" resultante seria uma leitura falsa.
    """
    assert CALCULO.count("\n        return True\n") == 2
    ambiguo = Mutante("amb", CALCULO_REL, "        return True", "        return False",
                      "par", "mutar uma linha que existe duas vezes")
    with pytest.raises(ArnesInvalido, match="aparece 2 vezes"):
        arnes.preparar_mutante(CALCULO, ambiguo)


def test_guarda_4_recusa_uma_ancora_que_nao_existe():
    fantasma = Mutante("fan", CALCULO_REL, "    return a - b", "    return 0",
                       "soma", "ancora que ja nao existe no ficheiro")
    with pytest.raises(ArnesInvalido, match="aparece 0 vezes"):
        arnes.preparar_mutante(CALCULO, fantasma)


# --------------------------------------------------------------------------
# guarda 5: ast.parse do mutante
# --------------------------------------------------------------------------

def test_guarda_5_recusa_um_mutante_que_nao_compila():
    """Apagar o `continue` deixa um `if` sem corpo."""
    sem_corpo = Mutante("cont", CALCULO_REL, "            continue", None,
                        "classificar", "apagar o continue e deixar o if sem corpo")
    with pytest.raises(ArnesInvalido, match="nao compila"):
        arnes.preparar_mutante(CALCULO, sem_corpo)


def test_guarda_5_deixa_passar_um_mutante_que_compila():
    mutado = arnes.preparar_mutante(CALCULO, M_LIMITE)
    assert "LIMITE = 100" in mutado
    assert "LIMITE = 10\n" not in mutado


# --------------------------------------------------------------------------
# guarda 6: ast.walk confirma o ambito
# --------------------------------------------------------------------------

def test_guarda_6_recusa_um_ambito_declarado_errado():
    """A linha esta no modulo; o autor diz que esta em `soma`."""
    errado = Mutante("amb6", CALCULO_REL, "LIMITE = 10", "LIMITE = 100",
                     "soma", "linha atribuida a funcao errada")
    with pytest.raises(ArnesInvalido, match="esta em '\\(modulo\\)' e nao em 'soma'"):
        arnes.preparar_mutante(CALCULO, errado)


def test_guarda_6_encontra_o_ambito_mais_interior():
    fonte = textwrap.dedent('''\
        class Fora:
            def metodo(self):
                def dentro():
                    return 1
                return dentro
        ''')
    assert arnes.ambito_da_linha(fonte, 1) == "Fora"
    assert arnes.ambito_da_linha(fonte, 2) == "metodo"
    assert arnes.ambito_da_linha(fonte, 4) == "dentro"


def test_guarda_6_reconhece_uma_linha_de_modulo():
    assert arnes.ambito_da_linha(CALCULO, 3) == arnes.MODULO


# --------------------------------------------------------------------------
# guarda 12: mutante nulo
# --------------------------------------------------------------------------

def test_guarda_12_recusa_um_mutante_que_nao_muda_nada():
    nulo = Mutante("nulo", CALCULO_REL, "LIMITE = 10", "LIMITE = 10",
                   arnes.MODULO, "substituto igual a ancora")
    with pytest.raises(ArnesInvalido, match="o substituto e igual a ancora"):
        arnes.preparar_mutante(CALCULO, nulo)


# --------------------------------------------------------------------------
# guarda 8: restauro verificado por sha256
# --------------------------------------------------------------------------

def test_guarda_8_deteta_um_restauro_falhado(tmp_path):
    ficheiro = tmp_path / "x.py"
    ficheiro.write_text("a = 1\n")
    digest = arnes.sha256_do_ficheiro(ficheiro)
    arnes.verificar_restauro(ficheiro, digest)  # intacto: nao levanta
    ficheiro.write_text("a = 2\n")
    with pytest.raises(ArnesInvalido, match="RESTAURO FALHADO"):
        arnes.verificar_restauro(ficheiro, digest)


def test_guarda_8_o_ficheiro_mutado_volta_ao_que_era(ronda_de_referencia, arvore):
    copiado = ronda_de_referencia.copia / CALCULO_REL
    assert copiado.read_text() == (arvore / CALCULO_REL).read_text()


# --------------------------------------------------------------------------
# guarda 1: nunca escrever na arvore real
# --------------------------------------------------------------------------

def test_guarda_1_a_ronda_nao_toca_na_arvore_real(arvore_nova):
    antes = instantaneo(arvore_nova)
    motor = arnes.Arnes(arvore_nova, [M_LIMITE], timeout=120, escrever=lambda *_: None)
    resultado = motor.correr()
    assert resultado.veredictos, "a ronda tinha de produzir um veredicto"
    assert instantaneo(arvore_nova) == antes


def test_guarda_1_recusa_uma_arvore_de_trabalho_dentro_da_arvore_real(arvore_nova):
    motor = arnes.Arnes(arvore_nova, [M_LIMITE], escrever=lambda *_: None)
    motor.copia = arvore_nova / "dentro"
    with pytest.raises(ArnesInvalido, match="esta dentro da arvore real"):
        motor._copiar()


# --------------------------------------------------------------------------
# guarda 2: a copia tem de ser a fonte importada
# --------------------------------------------------------------------------

def test_guarda_2_aborta_quando_a_sentinela_nao_e_importada(arvore_nova):
    """orfao.py nao e importado por ninguem: sabota-lo nao derruba nada.

    Uma sentinela assim nao prova nada, e uma guarda 2 que a aceitasse era
    decorativa.
    """
    motor = arnes.Arnes(arvore_nova, [M_LIMITE], timeout=120,
                        sentinela="src/brinquedo/orfao.py", escrever=lambda *_: None)
    with pytest.raises(ArnesInvalido, match="deixou a suite VERDE"):
        motor.correr()


def test_guarda_2_aceita_o_init_do_pacote_como_sentinela(arvore_nova):
    motor = arnes.Arnes(arvore_nova, [], escrever=lambda *_: None)
    assert motor.sentinela == "src/brinquedo/__init__.py"


def test_o_tecto_do_mutante_segue_o_tecto_geral_quando_nao_e_dado(arvore_nova):
    assert arnes.Arnes(arvore_nova, [], timeout=42).timeout_do_mutante == 42
    assert arnes.Arnes(arvore_nova, [], timeout=42, timeout_do_mutante=7).timeout_do_mutante == 7


# --------------------------------------------------------------------------
# guarda 3: base verde
# --------------------------------------------------------------------------

def test_guarda_3_aborta_com_a_base_vermelha(tmp_path):
    """A mentira da manha: um teste alheio a cair sempre.

    O pytest devolve != 0 em TODOS os mutantes e todos aparecem mortos sem que
    nenhum teste os tenha apanhado.
    """
    raiz = construir_arvore(tmp_path, teste_um=TESTE_UM.replace("== 5", "== 6"))
    motor = arnes.Arnes(raiz, [M_LIMITE], timeout=120, escrever=lambda *_: None)
    with pytest.raises(ArnesInvalido, match="BASE VERMELHA"):
        motor.correr()


def test_guarda_3_aborta_quando_a_base_nao_recolhe_testes(tmp_path):
    raiz = construir_arvore(tmp_path, teste_um=None, teste_dois=None)
    motor = arnes.Arnes(raiz, [M_LIMITE], timeout=120, escrever=lambda *_: None)
    with pytest.raises(ArnesInvalido, match="nao recolheu teste nenhum"):
        motor.correr()


# --------------------------------------------------------------------------
# guarda 7: timeout
# --------------------------------------------------------------------------

def test_guarda_7_um_mutante_que_bloqueia_nao_conta_como_morto(arvore_nova):
    """Um mutante que mata por BLOQUEIO seria um build pendurado em CI."""
    # tecto largo para a base e para a sabotagem (nao ha nada de anormal nelas,
    # e um tecto apertado seria uma falha intermitente numa maquina lenta) e
    # tecto apertado para o mutante, que e o unico que se espera bloquear
    motor = arnes.Arnes(arvore_nova, [M_BLOQUEIO], timeout=120, timeout_do_mutante=2,
                        escrever=lambda *_: None)
    resultado = motor.correr()
    veredicto = resultado.por_ident("bloqueio")
    assert veredicto.estado == arnes.ESGOTADO
    assert veredicto not in resultado.mortos
    assert veredicto in resultado.suspeitos


# --------------------------------------------------------------------------
# guardas 9, 10 e 11: o que conta como morte
# --------------------------------------------------------------------------

def test_guarda_9_a_suite_inteira_apanha_o_ficheiro_de_testes_alheio(ronda_de_referencia):
    """O mutante esta em calculo.py e quem o apanha vive em test_dois.py.

    Um arnes que corresse so o ficheiro de testes "obvio" dava-o como vivo.
    """
    veredicto = ronda_de_referencia.por_ident("limite")
    assert veredicto.estado == arnes.MORTO
    assert all("test_dois.py" in nodeid for nodeid in veredicto.apanhados)


def test_guarda_11_uma_falha_por_pytest_fail_conta_como_morte(ronda_de_referencia):
    """A mentira da tarde: pytest.fail levanta Failed, que deriva de
    BaseException, e um `except Exception` deixava-a passar como vivo.

    O arnes le o codigo de saida de um subprocesso, portanto nao tem por onde
    engolir a excepcao -- e este teste e que o prova.
    """
    veredicto = ronda_de_referencia.por_ident("limite")
    assert "test_o_limite_e_respeitado" in " ".join(veredicto.apanhados)


def test_guarda_10_um_mutante_que_rebenta_na_recolha_nao_e_morte(ronda_de_referencia):
    """A mentira da noite: o pytest sai com 2 sem correr teste nenhum."""
    veredicto = ronda_de_referencia.por_ident("recolha")
    assert veredicto.estado == arnes.SUSPEITO
    assert veredicto.apanhados == []
    assert veredicto in ronda_de_referencia.suspeitos
    assert veredicto not in ronda_de_referencia.mortos


def test_um_mutante_inocuo_e_declarado_sobrevivente(ronda_de_referencia):
    veredicto = ronda_de_referencia.por_ident("sobrevivente")
    assert veredicto.estado == arnes.VIVO
    assert veredicto.apanhados == []


def test_a_tabela_declara_as_tres_contagens(ronda_de_referencia):
    tabela = ronda_de_referencia.tabela()
    assert "1 mortos" in tabela
    assert "1 sobreviventes" in tabela
    assert "1 por inspeccionar" in tabela


# --------------------------------------------------------------------------
# leitura do relatorio do pytest
# --------------------------------------------------------------------------

def test_um_erro_de_recolha_nao_conta_como_teste_apanhado():
    saida = "ERROR tests/test_um.py - ZeroDivisionError: division by zero\n"
    apanhados, recolha_partida = arnes._apanhados_e_recolha(saida)
    assert apanhados == []
    assert recolha_partida is True


def test_um_erro_dentro_de_um_teste_conta_como_apanhado():
    saida = "ERROR tests/test_um.py::test_x - RuntimeError: boom\n"
    apanhados, recolha_partida = arnes._apanhados_e_recolha(saida)
    assert apanhados == ["tests/test_um.py::test_x"]
    assert recolha_partida is False
