"""O painel que diz de onde veio um valor.

Duas decisoes moldam este ficheiro.

⭐ **Uma linha sem proveniencia estruturada di-lo.** Um painel vazio le-se como
"nao ha nada a dizer sobre isto", e o que se passa e o contrario: ha, e nao
ficou gravado. As 27 leituras de campo da base de producao estao nesse caso --
foram escritas antes de o campo `evidence` existir --, e o painel delas tem de
dizer isso e mostrar o que a linha tem (o metodo, a nota, a versao), em vez de
ficar em branco.

**O painel mostra a evidencia inteira, e nao uma seleccao.** A tentacao e a
lista curta e bonita; o custo dela e que um campo novo nasce invisivel, e quem
olha nao tem maneira de saber que existe. Aqui traduzem-se os campos conhecidos
e mostram-se os outros pelo nome cru -- feio, e honesto.

⛔ **As coordenadas nao chegam aqui.** Foram cortadas uma camada antes, em
`api/console.py`, e chegam ja como uma marca de retido. Este ficheiro nao as
reconhece nem as procura: o corte tem de estar no unico sitio por onde tudo
passa, e nao repetido em cada sitio que desenha. O que este ficheiro faz e
mostrar o retido COMO retido -- "existe e nao e mostrado" nao e o mesmo que
"nao existe", e essa distincao e a mesma que vale em todo o modelo.
"""

from dataclasses import dataclass, field
from typing import Any

from resoiltwin.console.formato import CASAS_POR_OMISSAO, numero
from resoiltwin.console.textos import Textos

# A marca que a camada deixa no lugar do que reteve. Le-se de `api/console.py`
# e nao se copia: duas copias divergem, e a divergencia aqui fazia um valor
# retido passar a mostrar-se como um campo desconhecido chamado "withheld".
CHAVE_DE_RETIDO = "withheld"

# ⚠️ As razoes de retido, o "sem proveniencia" e o porque de faltar vivem em
# `textos.py`, e as chaves que aqui se leem sao as que la estao. O texto e o
# unico que muda com a lingua: o que se afirma -- "existe e nao e mostrado" nao
# e o mesmo que "nao existe" -- e o mesmo nas duas.
CHAVES_DE_RAZAO = {
    "geometry": "prov.retido.geometry",
    "coordinate": "prov.retido.coordinate",
}

# Os rotulos dos campos da evidencia estao em `textos.py`, uma tabela por
# lingua. Os que nao estao la aparecem na mesma, pelo nome cru: um campo novo
# tem de ser visivel antes de ser bonito.

PRIMEIROS = (
    "measured_at_site",
    "distance_km",
    "cell_size_km_ns",
    "cell_size_km_ew",
    "station_name",
    "variable",
    "aoi_code",
)


@dataclass(frozen=True)
class Campo:
    rotulo: str
    valor: str
    retido: bool = False
    filhos: tuple["Campo", ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class Painel:
    estruturada: bool
    da_evidencia: tuple[Campo, ...]
    da_linha: tuple[Campo, ...]


def _valor(bruto: Any, textos: Textos) -> tuple[str, bool, tuple[Campo, ...]]:
    """(texto, retido, filhos) para um valor qualquer vindo da evidencia."""
    if isinstance(bruto, dict):
        razao = bruto.get(CHAVE_DE_RETIDO)
        if isinstance(razao, str) and len(bruto) == 1:
            chave = CHAVES_DE_RAZAO.get(razao, "prov.retido.outro")
            return textos[chave], True, ()
        return "", False, tuple(_campos(bruto, textos))
    if isinstance(bruto, bool):
        return textos["prov.sim" if bruto else "prov.nao"], False, ()
    if isinstance(bruto, (int, float)):
        casas = 0 if isinstance(bruto, int) else CASAS_POR_OMISSAO
        return numero(bruto, casas, textos), False, ()
    if isinstance(bruto, list):
        partes = []
        for item in bruto:
            texto, _, _ = _valor(item, textos)
            partes.append(texto)
        return ", ".join(partes), False, ()
    if bruto is None:
        return textos["prov.nao_registado"], False, ()
    return str(bruto), False, ()


def _campos(evidencia: dict[str, Any], textos: Textos) -> list[Campo]:
    conhecidos = [chave for chave in PRIMEIROS if chave in evidencia]
    resto = sorted(chave for chave in evidencia if chave not in conhecidos)
    campos = []
    for chave in conhecidos + resto:
        texto, retido, filhos = _valor(evidencia[chave], textos)
        campos.append(Campo(textos.rotulo(chave), texto, retido, filhos))
    return campos


# Os campos da propria linha, e a chave do rotulo de cada um. ⚠️ Sao os nomes
# fixados em ingles no README e nas rotas -- `source type`, `quality flag`,
# `processing version` --, e por isso o rotulo ingles nao inventa sinonimos.
DA_LINHA = (
    ("linha.metrica", "metric"),
    ("linha.unidade", "unit"),
    ("linha.origem", "source_type"),
    ("linha.qualificador", "value_qualifier"),
    ("linha.qualidade", "quality_flag"),
    ("linha.parcela", "plot_code"),
    ("linha.metodo", "method"),
    ("linha.coleccao", "source_collection"),
    ("linha.versao", "processing_version"),
    ("linha.nota", "notes"),
)


def _da_linha(linha: dict[str, Any], textos: Textos) -> tuple[Campo, ...]:
    """O que a propria linha diz, e que nao depende da evidencia nenhuma.

    Aparece sempre, e nao so quando a evidencia falta: sao campos diferentes com
    significados diferentes, e mostrar um no lugar do outro conforme o que
    houver fazia o painel mudar de sentido sem avisar.
    """
    return tuple(
        Campo(textos[chave], str(linha.get(campo)))
        for chave, campo in DA_LINHA
        if linha.get(campo) not in (None, "")
    )


def painel_de(linha: dict[str, Any], textos: Textos) -> Painel:
    evidencia = linha.get("evidence")
    estruturada = isinstance(evidencia, dict) and bool(evidencia)
    return Painel(
        estruturada=estruturada,
        da_evidencia=tuple(_campos(evidencia, textos)) if estruturada else (),
        da_linha=_da_linha(linha, textos),
    )
