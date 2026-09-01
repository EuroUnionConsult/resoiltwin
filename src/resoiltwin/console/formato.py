"""A forma de um valor no ecra. Tres regras, e nenhuma delas e negociavel.

⭐ **Um intervalo desenha-se como intervalo.** O balanco hidrico devolve
`value_min`/`value_max` com o qualificador `range` enquanto nao sabe onde esta o
valor. O meio desse intervalo -- 46,56 mm entre 0 e 93,12 -- e um numero que
ninguem mediu e que se le como "cerca de metade do reservatorio", quando o que a
base diz e "algures entre vazio e cheio". Nao ha aqui nenhum caminho por onde um
`range` saia como um numero: `apresentar_valor` nunca olha para `value_numeric`
nesse ramo, e a base garante que ele e `NULL`.

⭐ **Uma leitura saturada mostra-se como um limite.** 2000 numa escala que satura
a 2000 nao e uma medida: e tudo o que o instrumento consegue dizer, e o valor
real e maior ou igual. O qualificador `censored_high` e o que grava isso, e o
`>=` e o que o mostra. Sem o simbolo, o que fica na celula e exactamente o
numero cru -- ou seja, a deformacao que o modelo de dados inteiro existe para
impedir, reposta na ultima camada.

⭐ **Solido = medido na parcela. Tramado = nao.** Uma estacao a 5,34 km e uma
celula de ~9 km nao sao medicoes no sitio, e a trama di-lo sem legenda nenhuma.
E um canal independente da cor de proposito: cerca de 8% dos homens tem
dificuldade com vermelho/verde, e esta distincao e a que este produto existe
para nao apagar.

E os numeros escrevem-se na lingua da pagina: a marca decimal muda com ela --
virgula em portugues, ponto em ingles --, e o separador de milhares e o mesmo
nas duas, um espaco insecavel. O ponto nos milhares nao e usado em lingua
nenhuma desta consola: num numero como 1.234 leva quem le a duvidar se sao mil
duzentos ou um virgula dois, e a recomendacao do BIPM para escrita cientifica e
precisamente o espaco.
"""

from dataclasses import dataclass
from typing import Any

from resoiltwin.console import paleta
from resoiltwin.console.textos import LINGUA_POR_OMISSAO, MARCA_DECIMAL, Textos
from resoiltwin.enums import SourceType, ValueQualifier

# Espaco insecavel (U+00A0). Insecavel e nao normal: um numero partido ao meio
# por uma mudanca de linha deixa de ser um numero.
ESPACO_DE_MILHARES = " "

# Os dois simbolos nao se traduzem, e e essa a razao de estarem aqui e nao em
# `textos.py`: sao notacao matematica e leem-se igual em qualquer lingua. Uma
# traducao deles seria uma oportunidade para um deles se perder.
MAIOR_OU_IGUAL = "≥"
MENOR_OU_IGUAL = "≤"

# O separador de um intervalo (" a ", " to ") esta em `textos.py`, e e uma
# palavra e nao um travessao nas duas linguas: num intervalo escrito com trace,
# "7,0-8,0" le-se com facilidade como uma subtraccao, e num numero negativo fica
# ambiguo mesmo.
CHAVE_DO_SEPARADOR = "valor.separador_de_intervalo"

# Casas decimais por unidade. Fixas e nao adaptadas ao valor, para que uma
# coluna de numeros alinhe pela virgula; os indices normalizados levam quatro
# porque a terceira casa deles ainda distingue coberturas diferentes.
CASAS_POR_UNIDADE = {"index": 4}
CASAS_POR_OMISSAO = 2

# As origens que sao uma medicao NA parcela quando a propria linha nao diz.
#
# ⚠️ O satelite esta aqui e a estacao nao, e a fronteira nao e "remoto contra
# presencial" -- e espacial. O Sentinel-2 amostra os pixeis da propria area de
# interesse a 10 m; a estacao mais proxima mede o ar dela, a quilometros. A
# celula de reanalise idem, com ~9 km de lado. O que separa nao e o instrumento:
# e se o que foi medido foi este terreno.
ORIGENS_NA_PARCELA = frozenset({
    SourceType.observed_screening,
    SourceType.observed_reference,
    SourceType.observed_lab,
    SourceType.satellite_observed,
})


def numero(valor: float | int | None, casas: int = CASAS_POR_OMISSAO,
           textos: Textos | None = None) -> str:
    """Um numero na lingua da pagina.

    Sem `textos`, escreve-se na lingua por omissao -- que e o ingles, tal como
    tudo o resto nesta consola.
    """
    if valor is None:
        return ""
    marca = textos.marca_decimal if textos is not None else MARCA_DECIMAL[LINGUA_POR_OMISSAO]
    texto = f"{valor:,.{casas}f}"
    # a troca faz-se em duas passagens com um marcador pelo meio: uma so
    # passagem trocava o ponto que a primeira acabou de escrever.
    return texto.replace(",", "\x00").replace(".", marca).replace("\x00", ESPACO_DE_MILHARES)


def casas_para(unidade: str | None) -> int:
    return CASAS_POR_UNIDADE.get(unidade or "", CASAS_POR_OMISSAO)


@dataclass(frozen=True)
class ValorApresentado:
    """O texto que vai para a celula, e a forma que ele tem.

    A `forma` viaja ao lado do texto para que a folha de estilo possa marcar a
    celula (`data-forma`) sem voltar a interpretar o valor. Duas
    interpretacoes do mesmo campo em sitios diferentes divergem.
    """

    texto: str
    forma: str


def apresentar_valor(linha: dict[str, Any], textos: Textos) -> ValorApresentado:
    """O valor de uma observacao, na forma que ele realmente tem.

    ⚠️ A `forma` NAO se traduz, e e por isso que ela viaja ao lado do texto.
    Ela vai para `data-forma` no HTML e e lida pela folha de estilo e pelos
    testes; traduzida, uma pagina em ingles e uma em portugues passavam a
    marcar a mesma celula de duas maneiras diferentes.
    """
    unidade = linha.get("unit")
    casas = casas_para(unidade)
    qualificador = linha.get("value_qualifier")

    if qualificador == ValueQualifier.range:
        minimo, maximo = linha.get("value_min"), linha.get("value_max")
        if minimo is None or maximo is None:
            # a base nao deixa isto acontecer (ck_range_needs_both_bounds), e se
            # acontecer nao se inventa um numero para tapar o buraco.
            return ValorApresentado(textos["valor.intervalo_incompleto"], "indeterminado")
        separador = textos[CHAVE_DO_SEPARADOR]
        return ValorApresentado(
            f"{numero(minimo, casas, textos)}{separador}{numero(maximo, casas, textos)}",
            "intervalo",
        )

    if qualificador == ValueQualifier.censored_high:
        return ValorApresentado(
            f"{MAIOR_OU_IGUAL}{ESPACO_DE_MILHARES}"
            f"{numero(linha.get('value_numeric'), casas, textos)}",
            "censurado_alto",
        )

    if qualificador == ValueQualifier.censored_low:
        return ValorApresentado(
            f"{MENOR_OU_IGUAL}{ESPACO_DE_MILHARES}"
            f"{numero(linha.get('value_numeric'), casas, textos)}",
            "censurado_baixo",
        )

    if linha.get("value_numeric") is not None:
        forma = "media" if qualificador == ValueQualifier.mean_of_replicates else "exacto"
        return ValorApresentado(numero(linha["value_numeric"], casas, textos), forma)

    if linha.get("value_text"):
        return ValorApresentado(str(linha["value_text"]), "texto")

    return ValorApresentado(textos["valor.sem_valor"], "indeterminado")


def medido_na_parcela(linha: dict[str, Any]) -> bool:
    """Se este valor foi medido neste terreno.

    A linha diz de si propria primeiro. `measured_at_site` existe na evidencia
    exactamente para isto -- para que a pergunta se responda sem interpretar
    distancias -- e por isso ganha a qualquer regra sobre origens. A deducao
    pela origem e so o que resta para as linhas que nasceram antes do campo.
    """
    evidencia = linha.get("evidence") or {}
    if isinstance(evidencia, dict) and isinstance(evidencia.get("measured_at_site"), bool):
        return evidencia["measured_at_site"]
    return linha.get("source_type") in ORIGENS_NA_PARCELA


def lugar_da_medicao(linha: dict[str, Any], textos: Textos) -> str:
    """A mesma distincao, por escrito: o canal que se le sem cor nenhuma.

    ⭐ Em ingles a frase e "not measured in the parcel" e nao "outside the
    parcel". A literal descreve um lugar; esta nega uma medicao, que e a
    afirmacao que este produto existe para nao apagar. Ver `textos.py`.
    """
    chave = "valor.na_parcela" if medido_na_parcela(linha) else "valor.fora_da_parcela"
    return textos[chave]


@dataclass(frozen=True)
class Faixa:
    """Onde uma barra comeca e acaba, em percentagem do dominio."""

    rampa: str
    inicio: float
    fim: float
    aberta_em_cima: bool = False


def faixa_do_valor(linha: dict[str, Any]) -> Faixa | None:
    """A posicao deste valor dentro do dominio da metrica, quando ele existe.

    ⚠️ Devolve `None` para tudo o que nao tenha um dominio que nao seja
    inventado. Uma barra desenha um eixo, e um eixo e uma afirmacao: dizer onde
    "meio" fica numa barra de temperatura e escolher uma escala que nada neste
    projecto sustenta. So os indices normalizados (que vivem entre -1 e 1 por
    construcao) e a agua disponivel (que vive entre zero e a capacidade escrita
    na propria evidencia) tem eixo aqui.

    Um intervalo devolve a banda inteira, e e essa a razao de isto existir: e a
    unica forma de desenhar um intervalo sem escolher um ponto dentro dele.
    """
    dominio = paleta.DOMINIOS.get(linha.get("metric") or "")
    if dominio is None:
        return None
    rampa, minimo, maximo = dominio
    if maximo is None:
        evidencia = linha.get("evidence") or {}
        maximo = evidencia.get(paleta.CAPACIDADE_NA_EVIDENCIA) if isinstance(evidencia, dict) else None
        if not isinstance(maximo, (int, float)) or maximo <= minimo:
            return None

    def posicao(valor: float) -> float:
        return max(0.0, min(100.0, (valor - minimo) / (maximo - minimo) * 100.0))

    qualificador = linha.get("value_qualifier")
    if qualificador == ValueQualifier.range:
        if linha.get("value_min") is None or linha.get("value_max") is None:
            return None
        return Faixa(rampa, posicao(linha["value_min"]), posicao(linha["value_max"]))
    if linha.get("value_numeric") is None:
        return None
    fim = posicao(linha["value_numeric"])
    if qualificador == ValueQualifier.censored_high:
        # o valor real e MAIOR ou igual: a barra vai dali para cima e fica
        # aberta, em vez de acabar no numero como se ele fosse a medida.
        return Faixa(rampa, fim, 100.0, aberta_em_cima=True)
    return Faixa(rampa, 0.0, fim)
