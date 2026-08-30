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
import subprocess
import tempfile
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


# escritos aos pedacos de proposito: este ficheiro tambem e varrido, e ter os
# literais inteiros aqui punha o teste a falhar por causa de si mesmo
CAMINHOS_DE_MAQUINA = ("/" + "Users/", "/" + "home/", ".venv/bin/" + "python")


RUIDO = {".git", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache", "node_modules"}

# Pastas e ficheiros de topo do PROJECTO. Servem o recurso de baixo, e nao sao
# uma lista de excluir: uma lista de excluir cresce em silencio a cada pasta de
# trabalho nova (.superpowers e os diffs de revisao la dentro citam caminhos de
# maquina de propria natureza), e o dia em que se esquecer uma e o dia em que a
# suite fica vermelha por uma razao que nada tem a ver com o codigo.
PASTAS_DO_PROJECTO = (".github", "docs", "migrations", "scripts", "seeds", "src", "tests", "tools")
FICHEIROS_DE_TOPO = ("*.py", "*.toml", "*.ini", "*.md", "*.yml", "*.yaml", ".env.example",
                     ".gitignore")


def varrer_arvore() -> list[Path]:
    caminhos = [c for pasta in PASTAS_DO_PROJECTO for c in (RAIZ / pasta).rglob("*")
                if not RUIDO.intersection(c.parts)]
    for padrao in FICHEIROS_DE_TOPO:
        caminhos.extend(RAIZ.glob(padrao))
    return sorted(set(caminhos))


def ficheiros_a_varrer() -> tuple[list[Path], str]:
    """Os ficheiros versionados -- ou as pastas do projecto, onde nao ha git.

    A regra e "nenhum caminho desta maquina em ficheiro VERSIONADO", e varrer a
    arvore de trabalho deixava um ficheiro de ronda por versionar, deixado por
    outra pessoa, a decidir a cor da suite de toda a gente.

    Mas ha um sitio onde a pergunta nao tem resposta: dentro da COPIA que o
    proprio arnes faz, que exclui o `.git` de proposito (guarda 1). Sem recurso,
    a suite fica vermelha dentro da copia e o arnes recusa-se a medir seja o que
    for -- foi exactamente o que aconteceu na primeira tentativa desta ronda, e
    a guarda 3 apanhou-o. O recurso e um SUPERCONJUNTO do que o git segue, e
    `test_o_recurso_sem_git_varre_tudo_o_que_o_git_segue` prende isso.
    """
    listagem = subprocess.run(["git", "ls-files", "-z"], cwd=RAIZ, capture_output=True,
                              text=True, timeout=60)
    seguidos = [n for n in listagem.stdout.split("\0") if n] if listagem.returncode == 0 else []
    if len(seguidos) > 20:
        return [RAIZ / nome for nome in seguidos], "git ls-files"
    return varrer_arvore(), "pastas do projecto (sem git)"


def test_nenhum_ficheiro_versionado_traz_caminhos_desta_maquina():
    caminhos, origem = ficheiros_a_varrer()
    lidos = 0
    for caminho in caminhos:
        if not caminho.is_file():
            continue
        try:
            texto = caminho.read_text()
        except UnicodeDecodeError:
            continue
        lidos += 1
        for proibido in CAMINHOS_DE_MAQUINA:
            assert proibido not in texto, f"{caminho.relative_to(RAIZ)} contem {proibido!r}"
    assert lidos > 20, f"quase nada foi lido de facto ({origem}: {lidos} ficheiros)"


def test_o_recurso_sem_git_varre_tudo_o_que_o_git_segue():
    """A guarda contra a lista de pastas envelhecer em silencio.

    No dia em que houver codigo versionado numa pasta de topo nova, isto cai --
    e cai aqui, no repositorio a serio, e nao la dentro da copia onde ja ninguem
    perceberia porque.
    """
    seguidos, origem = ficheiros_a_varrer()
    if origem != "git ls-files":
        pytest.skip("sem checkout git neste sitio: nao ha com que comparar")
    do_recurso = set(varrer_arvore())
    em_falta = sorted(str(c.relative_to(RAIZ)) for c in seguidos
                      if c.is_file() and c not in do_recurso)
    assert em_falta == [], f"o recurso sem git nao varre estes ficheiros versionados: {em_falta}"


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
    with pytest.raises(ArnesInvalido, match="mesma arvore que o original"):
        arnes.preparar_mutante(CALCULO, nulo)


def test_guarda_12_recusa_um_mutante_que_so_acrescenta_um_espaco():
    """A igualdade literal deixava passar `LIMITE = 10 `.

    O mutante compila, e semanticamente identico ao original, sobrevive sempre,
    e le-se como "os testes nao apanham isto" -- exactamente o falso achado que
    a guarda 12 existe para impedir, escrito com um caracter a mais.
    """
    com_espaco = Mutante("espaco", CALCULO_REL, "LIMITE = 10", "LIMITE = 10 ",
                         arnes.MODULO, "substituto igual a ancora mais um espaco")
    assert com_espaco.substituto != com_espaco.ancora, "a igualdade literal nao apanha isto"
    with pytest.raises(ArnesInvalido, match="mesma arvore que o original"):
        arnes.preparar_mutante(CALCULO, com_espaco)


def test_guarda_12_recusa_um_mutante_que_so_mexe_num_comentario():
    fonte = "LIMITE = 10  # o tecto\n"
    so_comentario = Mutante("com", CALCULO_REL, "LIMITE = 10  # o tecto",
                            "LIMITE = 10  # o tecto, revisto", arnes.MODULO, "so o comentario")
    with pytest.raises(ArnesInvalido, match="mesma arvore que o original"):
        arnes.preparar_mutante(fonte, so_comentario)


def test_um_mutante_a_serio_passa_a_guarda_12():
    """Controlo positivo: a guarda 12 nao pode ser um `raise` incondicional."""
    assert "LIMITE = 100" in arnes.preparar_mutante(CALCULO, M_LIMITE)


def test_o_fim_do_ficheiro_e_preservado():
    """Num ficheiro sem newline final, acrescentar um fazia o mutante de uma
    linha mexer tambem na ultima."""
    fonte = "LIMITE = 10\nOUTRO = 2"
    mutante = Mutante("fim", CALCULO_REL, "LIMITE = 10", "LIMITE = 100",
                      arnes.MODULO, "primeira linha")
    assert arnes.preparar_mutante(fonte, mutante) == "LIMITE = 100\nOUTRO = 2"


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


def test_guarda_1_recusa_um_tmpdir_que_chega_a_arvore_por_link_simbolico(tmp_path, monkeypatch):
    """O caso que a plataforma produz por omissao, e que o teste acima nao ve.

    `is_relative_to` e lexical. O `tmp_path` do pytest ja vem resolvido, por
    isso o teste acima acerta por acaso do fixture. Aqui o TMPDIR e alcancado
    por um LINK SIMBOLICO que aponta para dentro da arvore real -- que e a
    forma de `/var` -> `/private/var` do macOS. Sem resolver a copia, a guarda
    nao dispara e o `copytree` recursa a arvore real sobre si propria.
    """
    raiz = construir_arvore(tmp_path / "arvore")
    (raiz / "tmp").mkdir()
    atalho = tmp_path / "atalho"
    atalho.symlink_to(raiz / "tmp", target_is_directory=True)
    assert not atalho.is_relative_to(raiz), "o atalho tem de enganar a comparacao lexical"
    assert atalho.resolve().is_relative_to(raiz), "e tem de apontar mesmo para dentro da arvore"

    monkeypatch.setattr(tempfile, "tempdir", str(atalho))
    motor = arnes.Arnes(raiz, [M_LIMITE], timeout=120, escrever=lambda *_: None)
    with pytest.raises(ArnesInvalido, match="esta dentro da arvore real"):
        motor.correr()
    assert list((raiz / "tmp").iterdir()) == [], "nao pode ter ficado nada copiado la dentro"


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


def test_guarda_2_prova_que_a_sabotagem_foi_mesmo_escrita(arvore_nova, monkeypatch):
    """A outra metade da guarda 2, que o teste da sentinela orfa nao cobre.

    A guarda so verifica `codigo != 0`. Com uma SABOTAGEM inerte -- uma string
    vazia, um comentario -- ela aborta com a MESMA mensagem, e um arnes que
    nao sabota nada passava no teste da sentinela orfa tal e qual. Este espia o
    ficheiro sentinela no momento de cada corrida e exige que a segunda o tenha
    encontrado alterado, e alterado por codigo que rebenta.
    """
    motor = arnes.Arnes(arvore_nova, [], timeout=120, escrever=lambda *_: None)
    vistos = []
    corrida_real = motor._correr_suite

    def espiar(*argumentos, **nomeados):
        vistos.append((motor.copia / motor.sentinela).read_text())
        return corrida_real(*argumentos, **nomeados)

    monkeypatch.setattr(motor, "_correr_suite", espiar)
    motor.correr()

    assert len(vistos) == 2, "esperava duas corridas: a base e a sabotada"
    intacto, sabotado = vistos
    assert intacto == (arvore_nova / motor.sentinela).read_text(), "a base correu com a sentinela intacta"
    assert sabotado != intacto, "a sentinela nao chegou a ser sabotada"
    assert sabotado.startswith(intacto), "a sabotagem tem de ser acrescentada ao fim"

    cauda = sabotado[len(intacto):]
    assert cauda.strip(), "a sabotagem nao acrescentou codigo nenhum"
    try:
        exec(compile(cauda, "<sabotagem>", "exec"), {})  # noqa: S102
    except BaseException:  # noqa: BLE001 - qualquer rebentacao serve, e o que se quer
        pass
    else:
        pytest.fail("a sabotagem nao rebenta quando o modulo e executado")


def test_guarda_2_aceita_o_init_do_pacote_como_sentinela(arvore_nova):
    motor = arnes.Arnes(arvore_nova, [], escrever=lambda *_: None)
    assert motor.sentinela == "src/brinquedo/__init__.py"


def test_a_sentinela_deste_repositorio_e_o_pacote_e_a_suite_importa_o():
    """Prende a escolha implicita.

    `_sentinela_por_omissao` escolhe o primeiro `src/*/__init__.py` por ordem
    ALFABETICA. No dia em que `src/` ganhar um segundo pacote que ordene antes
    de `resoiltwin`, a sentinela mudava em silencio para um pacote que pode nao
    ser importado, e a ronda passava a abortar sem ninguem perceber porque.
    """
    assert arnes.Arnes(RAIZ, []).sentinela == "src/resoiltwin/__init__.py"
    assert "resoiltwin" in (RAIZ / "tests" / "conftest.py").read_text()


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


def test_guarda_3_aborta_quando_a_base_esta_verde_sem_correr_nada(tmp_path):
    """O ramo mais insidioso da guarda 3: e o unico que recusa uma base VERDE.

    Com tudo marcado `skip`, o pytest sai com 0 e nenhum teste correu. Sem esta
    recusa, a ronda inteira mediria uma suite que nao mede nada e todos os
    mutantes sobreviviam.
    """
    saltado = "import pytest\n\n\n@pytest.mark.skip\ndef test_nada():\n    assert False\n"
    raiz = construir_arvore(tmp_path, teste_um=saltado, teste_dois=None)
    motor = arnes.Arnes(raiz, [M_LIMITE], timeout=120, escrever=lambda *_: None)
    with pytest.raises(ArnesInvalido, match="verde sem correr teste nenhum"):
        motor.correr()


def test_guarda_3_aborta_quando_a_propria_base_estoira_o_tempo(tmp_path):
    lento = 'def test_lento():\n    __import__("time").sleep(30)\n'
    raiz = construir_arvore(tmp_path, teste_um=lento, teste_dois=None)
    motor = arnes.Arnes(raiz, [M_LIMITE], timeout=2, escrever=lambda *_: None)
    with pytest.raises(ArnesInvalido, match="a base nao acabou em 2s"):
        motor.correr()


# --------------------------------------------------------------------------
# guarda 7: timeout
# --------------------------------------------------------------------------

def test_guarda_7_um_mutante_que_bloqueia_nao_conta_como_morto(arvore_nova):
    """Um mutante que mata por BLOQUEIO seria um build pendurado em CI."""
    # tecto largo para a base e para a sabotagem (nao ha nada de anormal nelas,
    # e um tecto apertado seria uma falha intermitente numa maquina lenta) e
    # tecto apertado para o mutante, que e o unico que se espera bloquear
    motor = arnes.Arnes(arvore_nova, [M_BLOQUEIO, M_LIMITE], timeout=120, timeout_do_mutante=2,
                        escrever=lambda *_: None)
    resultado = motor.correr()
    veredicto = resultado.por_ident("bloqueio")
    assert veredicto.estado == arnes.ESGOTADO
    assert veredicto not in resultado.mortos
    assert veredicto in resultado.suspeitos

    # controlo negativo, e e ele que torna o de cima uma medicao: sob o MESMO
    # tecto de dois segundos, um mutante que NAO bloqueia nao pode dar TEMPO
    # ESGOTADO. Sem isto, o teste passava na mesma numa maquina cheia -- por a
    # suite ter demorado e nao por o mutante ter bloqueado -- e era um teste
    # que nao podia falhar.
    assert resultado.por_ident("limite").estado == arnes.MORTO


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
    # a linha inteira, e nao "1 mortos": esse tambem casava com "11 mortos"
    assert ("3 mutantes, 1 mortos, 1 sobreviventes, 1 por inspeccionar"
            in ronda_de_referencia.tabela().splitlines())


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
