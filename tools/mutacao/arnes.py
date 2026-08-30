"""Arnes de mutacao: corre uma ronda de mutantes contra a suite de testes.

O motor e permanente e testado (tests/test_arnes_de_mutacao.py). A lista de
mutantes e de UMA ronda e morre com ela -- vive num ficheiro de rondas/ e entra
aqui como argumento, nunca embutida no motor.

Uso:
    python tools/mutacao/arnes.py tools/mutacao/rondas/<ronda>.py

As doze guardas, e a falha real que deu origem a cada uma, estao no README ao
lado. Regra que nao se negoceia: "morto" exige um TESTE CAIDO, e nao apenas um
codigo de saida diferente de zero.
"""

import argparse
import ast
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

# ambito de uma linha que nao esta dentro de nenhuma funcao nem classe
MODULO = "(modulo)"

# estados de um mutante
VIVO = "SOBREVIVEU"
MORTO = "morto"
SUSPEITO = "MORTE SUSPEITA"
ESGOTADO = "TEMPO ESGOTADO"

# o que nunca e copiado para a arvore de trabalho
IGNORADOS = shutil.ignore_patterns(
    ".git", ".venv", "venv", "__pycache__", ".pytest_cache", ".ruff_cache",
    ".mypy_cache", "node_modules", "*.pyc",
)

# a sabotagem e acrescentada ao FIM do ficheiro sentinela: nao depende de uma
# unica linha existir la dentro, portanto nao parte no dia em que esse ficheiro
# mudar. Correr no fim do modulo continua a rebentar qualquer import dele.
SABOTAGEM = '\n\nraise RuntimeError("sabotagem do arnes: a copia tem de ser a fonte importada")\n'


class ArnesInvalido(RuntimeError):
    """Uma guarda disparou. A ronda nao mede nada e para aqui.

    Nunca e um resultado: e a recusa de produzir um resultado.
    """


@dataclass(frozen=True)
class Mutante:
    """Uma alteracao de uma linha, com o ambito que o autor diz ser o dela."""

    ident: str
    ficheiro: str          # caminho relativo a raiz do repositorio
    ancora: str            # linha exacta, unica no ficheiro
    substituto: str | None  # None apaga a linha
    ambito: str            # nome da funcao ou classe que a contem, ou MODULO
    descricao: str


@dataclass
class Execucao:
    """O resultado de uma corrida da suite inteira."""

    codigo: int | None     # None quando o tempo se esgotou
    saida: str
    apanhados: list[str]   # testes que cairam ou erraram, por nodeid
    passados: int
    recolha_partida: bool
    esgotou: bool = False


@dataclass
class Veredicto:
    ident: str
    ambito: str
    estado: str
    apanhados: list[str]
    descricao: str


@dataclass
class Resultado:
    veredictos: list[Veredicto] = field(default_factory=list)
    copia: Path | None = None

    @property
    def vivos(self) -> list[Veredicto]:
        return [v for v in self.veredictos if v.estado == VIVO]

    @property
    def suspeitos(self) -> list[Veredicto]:
        return [v for v in self.veredictos if v.estado in (SUSPEITO, ESGOTADO)]

    @property
    def mortos(self) -> list[Veredicto]:
        return [v for v in self.veredictos if v.estado == MORTO]

    def por_ident(self, ident: str) -> Veredicto:
        for veredicto in self.veredictos:
            if veredicto.ident == ident:
                return veredicto
        raise KeyError(ident)

    def tabela(self) -> str:
        # o "primeiro" e o primeiro por ordem alfabetica: quem quiser a lista
        # toda tem-na no veredicto
        linhas = ["| # | Mutante | Ambito | Resultado | Apanhados | Um dos testes que cai |",
                  "|---|---|---|---|---|---|"]
        for v in self.veredictos:
            primeiro = v.apanhados[0] if v.apanhados else "-"
            linhas.append(f"| {v.ident} | {v.descricao} | `{v.ambito}` | {v.estado} | "
                          f"{len(v.apanhados)} | `{primeiro}` |")
        linhas.append(f"\n{len(self.veredictos)} mutantes, {len(self.mortos)} mortos, "
                      f"{len(self.vivos)} sobreviventes, {len(self.suspeitos)} por inspeccionar")
        return "\n".join(linhas)


def sha256_do_ficheiro(caminho: Path) -> str:
    return hashlib.sha256(caminho.read_bytes()).hexdigest()


def raiz_do_repositorio(partida: Path | None = None) -> Path:
    """Sobe a partir de `partida` ate encontrar o pyproject.toml.

    A raiz e derivada, nunca escrita: um caminho absoluto desta maquina num
    ficheiro versionado e o oposto de uma ferramenta que outra pessoa possa
    correr.
    """
    actual = (partida or Path(__file__)).resolve()
    for candidato in [actual, *actual.parents]:
        if (candidato / "pyproject.toml").is_file():
            return candidato
    raise ArnesInvalido(f"nao encontrei um pyproject.toml a subir a partir de {actual}")


def ambito_da_linha(fonte: str, numero: int) -> str:
    """Nome da funcao ou classe MAIS INTERIOR que contem a linha `numero`."""
    arvore = ast.parse(fonte)
    melhor, inicio_mais_interior = MODULO, -1
    for no in ast.walk(arvore):
        if not isinstance(no, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        fim = getattr(no, "end_lineno", None) or no.lineno
        # entre os ambitos que contem a linha, o mais interior e o que comeca
        # mais tarde
        if no.lineno <= numero <= fim and no.lineno > inicio_mais_interior:
            melhor, inicio_mais_interior = no.name, no.lineno
    return melhor


def preparar_mutante(fonte: str, mutante: Mutante) -> str:
    """Aplica um mutante ao texto e devolve o resultado, ou levanta ArnesInvalido.

    Guardas 4, 5, 6 e 12 vivem todas aqui, sem tocar em disco nem correr nada.
    """
    linhas = fonte.splitlines()
    ocorrencias = [i for i, linha in enumerate(linhas) if linha == mutante.ancora]
    if len(ocorrencias) != 1:
        raise ArnesInvalido(
            f"[{mutante.ident}] a ancora aparece {len(ocorrencias)} vezes em {mutante.ficheiro}; "
            "uma ancora ambigua muta o sitio errado e o 'sobrevivente' e uma leitura falsa")
    indice = ocorrencias[0]

    encontrado = ambito_da_linha(fonte, indice + 1)
    if encontrado != mutante.ambito:
        raise ArnesInvalido(
            f"[{mutante.ident}] a linha esta em '{encontrado}' e nao em '{mutante.ambito}'")

    # guarda 12: um mutante que nao muda nada sobrevive sempre, e um
    # sobrevivente assim le-se como "os testes nao apanham isto"
    if mutante.substituto == mutante.ancora:
        raise ArnesInvalido(
            f"[{mutante.ident}] mutante nulo: o substituto e igual a ancora")

    novas = list(linhas)
    if mutante.substituto is None:
        del novas[indice]
    else:
        novas[indice] = mutante.substituto
    mutado = "\n".join(novas) + "\n"

    try:
        ast.parse(mutado)
    except SyntaxError as erro:
        raise ArnesInvalido(
            f"[{mutante.ident}] o mutante nao compila ({erro}); apagar uma linha que era o corpo "
            "todo de um if deixa um mutante que nunca chega a correr") from erro
    return mutado


def verificar_restauro(caminho: Path, digest: str) -> None:
    """Guarda 8: o ficheiro tem de voltar EXACTAMENTE ao que era."""
    actual = sha256_do_ficheiro(caminho)
    if actual != digest:
        raise ArnesInvalido(
            f"RESTAURO FALHADO em {caminho}: sha256 {actual} != {digest}. A arvore de trabalho "
            "ficou suja e tudo o que vier a seguir e lixo")


def _apanhados_e_recolha(saida: str) -> tuple[list[str], bool]:
    """Le do relatorio do pytest o que foi APANHADO por um teste.

    Uma linha ERROR sem '::' e um erro de RECOLHA: nenhum teste correu, logo
    nenhum teste apanhou nada.
    """
    apanhados, recolha_partida = set(), False
    for linha in saida.splitlines():
        if linha.startswith("FAILED "):
            apanhados.add(linha.split(" ")[1])
        elif linha.startswith("ERROR "):
            alvo = linha.split(" ")[1]
            if "::" in alvo:
                apanhados.add(alvo)
            else:
                recolha_partida = True
    return sorted(apanhados), recolha_partida


def _relatar(*partes) -> None:
    """Uma ronda demora minutos: sem flush, quem a redireccionou para um
    ficheiro so ve o que se passou no fim."""
    print(*partes, flush=True)


def _passados(saida: str) -> int:
    encontrado = re.search(r"(\d+) passed", saida)
    return int(encontrado.group(1)) if encontrado else 0


class Arnes:
    """Corre uma ronda de mutacao sobre uma COPIA da arvore, com guardas."""

    def __init__(self, raiz, mutantes, *, python=None, sentinela=None, timeout=900,
                 timeout_do_mutante=None, argumentos_do_pytest=(), escrever=_relatar):
        self.raiz = Path(raiz).resolve()
        self.mutantes = list(mutantes)
        # sys.executable por omissao: o interpretador que corre o arnes ja tem
        # o ambiente do projecto, e um caminho fixo para um .venv so funciona
        # numa maquina
        self.python = str(python or sys.executable)
        self.timeout = timeout
        # tecto por mutante. Separado de proposito: a base e a sabotagem
        # medem-se a si proprias e podem ser generosas, enquanto um mutante
        # muito mais lento do que a base ja esta bloqueado
        self.timeout_do_mutante = timeout if timeout_do_mutante is None else timeout_do_mutante
        self.argumentos = list(argumentos_do_pytest)
        self.escrever = escrever
        self.sentinela = str(sentinela) if sentinela else self._sentinela_por_omissao()
        self.copia: Path | None = None

    def _sentinela_por_omissao(self) -> str:
        """O __init__.py do pacote: qualquer import do codigo passa por ele.

        Nao depende do conteudo de ficheiro nenhum, ao contrario de sabotar uma
        string literal escolhida a dedo.
        """
        candidatos = sorted((self.raiz / "src").glob("*/__init__.py"))
        if not candidatos:
            raise ArnesInvalido(
                f"nao encontrei src/<pacote>/__init__.py em {self.raiz}; indica --sentinela")
        return str(candidatos[0].relative_to(self.raiz))

    # -- corrida da suite ---------------------------------------------------

    def _correr_suite(self, tecto: int | None = None) -> Execucao:
        ambiente = {c: v for c, v in os.environ.items() if not c.startswith("PYTEST_")}
        ambiente["PYTHONPATH"] = str(self.copia / "src")
        ambiente["PYTHONDONTWRITEBYTECODE"] = "1"
        comando = [self.python, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                   "--no-header", "--tb=no", "-rfE", *self.argumentos]
        try:
            # guarda 7: timeout. Um mutante que mate por BLOQUEIO e um build
            # pendurado em CI, e nao uma morte.
            corrida = subprocess.run(comando, cwd=self.copia, env=ambiente, capture_output=True,
                                     text=True, timeout=tecto or self.timeout)
        except subprocess.TimeoutExpired:
            return Execucao(codigo=None, saida="", apanhados=[], passados=0,
                            recolha_partida=False, esgotou=True)
        saida = corrida.stdout + corrida.stderr
        apanhados, recolha_partida = _apanhados_e_recolha(saida)
        return Execucao(codigo=corrida.returncode, saida=saida, apanhados=apanhados,
                        passados=_passados(saida), recolha_partida=recolha_partida)

    # -- guardas 1 a 3 ------------------------------------------------------

    def _copiar(self) -> None:
        """Guarda 1: mutar SEMPRE numa copia, nunca na arvore real."""
        if self.copia == self.raiz or self.copia.is_relative_to(self.raiz):
            raise ArnesInvalido(
                f"a arvore de trabalho {self.copia} esta dentro da arvore real {self.raiz}")
        shutil.copytree(self.raiz, self.copia, ignore=IGNORADOS, symlinks=True)

    def _exigir_base_verde(self) -> None:
        """Guarda 3: uma ronda sobre vermelho nao mede nada.

        Um so teste a cair por razao alheia faz o pytest devolver != 0 em TODOS
        os mutantes, e todos aparecem mortos sem que nenhum teste os tenha
        apanhado. Uma base que nao corre teste nenhum e a mesma mentira pelo
        lado de la.
        """
        execucao = self._correr_suite()
        if execucao.esgotou:
            raise ArnesInvalido(f"a base nao acabou em {self.timeout}s; nada disto e mensuravel")
        if execucao.codigo == 5:
            raise ArnesInvalido("a base nao recolheu teste nenhum; nao ha suite a medir")
        if execucao.codigo != 0:
            raise ArnesInvalido(
                "BASE VERMELHA antes de mutar: uma ronda sobre vermelho nao mede nada. "
                f"Caidos: {execucao.apanhados or execucao.saida[-400:]}")
        if execucao.passados == 0:
            raise ArnesInvalido("a base ficou verde sem correr teste nenhum; nao ha suite a medir")
        self.escrever(f"guarda 3 ok: base VERDE com {execucao.passados} testes")

    def _provar_que_a_copia_e_a_fonte(self) -> None:
        """Guarda 2: sabota a copia e exige que a suite caia.

        Sem isto, a ronda podia estar a importar o codigo da arvore REAL (um
        instalado em modo editavel chega para isso) e todos os mutantes
        'sobreviviam' por uma razao que nada tem a ver com os testes.
        """
        alvo = self.copia / self.sentinela
        if not alvo.is_file():
            raise ArnesInvalido(f"a sentinela {self.sentinela} nao existe na copia")
        original = alvo.read_bytes()
        digest = sha256_do_ficheiro(alvo)
        try:
            alvo.write_bytes(original + SABOTAGEM.encode())
            execucao = self._correr_suite()
            if execucao.esgotou:
                raise ArnesInvalido("a copia sabotada nao acabou dentro do tempo")
            if execucao.codigo == 0:
                raise ArnesInvalido(
                    f"a copia sabotada em {self.sentinela} deixou a suite VERDE: nao e a copia "
                    "que esta a ser importada, e a ronda inteira mediria a arvore errada")
        finally:
            alvo.write_bytes(original)
            verificar_restauro(alvo, digest)
        self.escrever("guarda 2 ok: a copia e mesmo a fonte importada")

    # -- a ronda ------------------------------------------------------------

    def _julgar(self, execucao: Execucao) -> str:
        if execucao.esgotou:
            return ESGOTADO
        if execucao.codigo == 0:
            return VIVO
        if execucao.apanhados:
            return MORTO
        # codigo != 0 e nenhum teste apanhado: quase sempre um mutante que
        # rebenta na RECOLHA (o pytest sai com 2 sem correr teste nenhum).
        # Contar isto como morte foi a terceira mentira do arnes num so dia.
        return SUSPEITO

    def _mutar(self) -> Resultado:
        resultado = Resultado(copia=self.copia)
        for mutante in self.mutantes:
            alvo = self.copia / mutante.ficheiro
            if not alvo.is_file():
                raise ArnesInvalido(f"[{mutante.ident}] {mutante.ficheiro} nao existe na copia")
            original = alvo.read_bytes()
            digest = sha256_do_ficheiro(alvo)
            # preparar_mutante ja confirmou que o ambito declarado e o real,
            # portanto o ambito do veredicto e o declarado
            mutado = preparar_mutante(original.decode(), mutante)
            try:
                alvo.write_text(mutado)
                # guarda 9: a SUITE INTEIRA, nunca so o ficheiro de testes que
                # se julga afectado
                execucao = self._correr_suite(self.timeout_do_mutante)
            finally:
                alvo.write_bytes(original)
                verificar_restauro(alvo, digest)
            estado = self._julgar(execucao)
            resultado.veredictos.append(
                Veredicto(mutante.ident, mutante.ambito, estado, execucao.apanhados,
                          mutante.descricao))
            razao = " -- rebentou na recolha" if execucao.recolha_partida else ""
            self.escrever(f"[{mutante.ident}] {estado}{razao} ({len(execucao.apanhados)} apanhados) "
                          f"{mutante.descricao}")
        return resultado

    def correr(self, manter: bool = False) -> Resultado:
        temporario = Path(tempfile.mkdtemp(prefix="arnes-"))
        self.copia = temporario / "arvore"
        try:
            self._copiar()
            self._exigir_base_verde()
            self._provar_que_a_copia_e_a_fonte()
            return self._mutar()
        finally:
            if manter:
                self.escrever(f"arvore de trabalho mantida em {self.copia}")
            else:
                shutil.rmtree(temporario, ignore_errors=True)


def carregar_ronda(caminho: Path) -> list[Mutante]:
    """Le a lista de mutantes de um ficheiro .py (variavel MUTANTES) ou .json."""
    caminho = Path(caminho).resolve()
    if not caminho.is_file():
        raise ArnesInvalido(f"ronda inexistente: {caminho}")
    if caminho.suffix == ".json":
        cru = json.loads(caminho.read_text())
    elif caminho.suffix == ".py":
        spec = importlib.util.spec_from_file_location(f"ronda_{caminho.stem}", caminho)
        modulo = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(modulo)
        cru = getattr(modulo, "MUTANTES", None)
        if cru is None:
            raise ArnesInvalido(f"{caminho} nao declara MUTANTES")
    else:
        raise ArnesInvalido(f"nao sei ler uma ronda de {caminho.suffix}; usa .py ou .json")

    mutantes = []
    for entrada in cru:
        if isinstance(entrada, Mutante):
            mutantes.append(entrada)
        elif isinstance(entrada, dict):
            mutantes.append(Mutante(**entrada))
        else:
            mutantes.append(Mutante(*entrada))
    identificadores = [m.ident for m in mutantes]
    repetidos = {i for i in identificadores if identificadores.count(i) > 1}
    if repetidos:
        raise ArnesInvalido(f"identificadores repetidos na ronda: {sorted(repetidos)}")
    return mutantes


def main(argumentos=None) -> int:
    analisador = argparse.ArgumentParser(description="arnes de mutacao")
    analisador.add_argument("ronda", help="ficheiro .py ou .json com a lista de mutantes")
    analisador.add_argument("--raiz", default=None, help="raiz do repositorio (por omissao, derivada)")
    analisador.add_argument("--python", default=None, help="interpretador (por omissao, o actual)")
    analisador.add_argument("--sentinela", default=None, help="ficheiro a sabotar na guarda 2")
    analisador.add_argument("--timeout", type=int, default=900, help="segundos por corrida")
    analisador.add_argument("--timeout-do-mutante", type=int, default=None,
                            help="tecto por mutante (por omissao, igual a --timeout)")
    analisador.add_argument("--so", nargs="*", default=None, help="correr so estes identificadores")
    analisador.add_argument("--manter", action="store_true", help="nao apagar a arvore de trabalho")
    opcoes = analisador.parse_args(argumentos)

    try:
        raiz = Path(opcoes.raiz).resolve() if opcoes.raiz else raiz_do_repositorio()
        mutantes = carregar_ronda(Path(opcoes.ronda))
        if opcoes.so:
            escolhidos = set(opcoes.so)
            mutantes = [m for m in mutantes if m.ident in escolhidos]
            if not mutantes:
                raise ArnesInvalido(f"nenhum mutante com identificador em {sorted(escolhidos)}")
        arnes = Arnes(raiz, mutantes, python=opcoes.python, sentinela=opcoes.sentinela,
                      timeout=opcoes.timeout, timeout_do_mutante=opcoes.timeout_do_mutante)
        resultado = arnes.correr(manter=opcoes.manter)
    except ArnesInvalido as erro:
        print(f"ABORTAR: {erro}", file=sys.stderr)
        return 2

    print()
    print(resultado.tabela())
    if resultado.suspeitos:
        print("\nATENCAO: uma morte sem teste caido nao e uma morte. Rever: "
              + ", ".join(v.ident for v in resultado.suspeitos))
    return 1 if (resultado.vivos or resultado.suspeitos) else 0


if __name__ == "__main__":
    raise SystemExit(main())
