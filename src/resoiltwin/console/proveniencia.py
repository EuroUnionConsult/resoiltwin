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

# A marca que a camada deixa no lugar do que reteve. Le-se de `api/console.py`
# e nao se copia: duas copias divergem, e a divergencia aqui fazia um valor
# retido passar a mostrar-se como um campo desconhecido chamado "withheld".
CHAVE_DE_RETIDO = "withheld"

RAZOES_DE_RETIDO = {
    "geometry": "geometria retida",
    "coordinate": "coordenada retida",
}

SEM_PROVENIENCIA = "Sem proveniência estruturada"

# Porque e que falta, e e isto que distingue este painel de um painel vazio.
PORQUE_FALTA = (
    "Esta leitura foi gravada antes de o campo de proveniência existir, e por isso não "
    "traz o registo estruturado das entradas. O que se sabe dela é o que está na própria "
    "linha, abaixo."
)

# Os campos da evidencia que sabemos nomear. Os que nao estao aqui aparecem na
# mesma, pelo nome cru: um campo novo tem de ser visivel antes de ser bonito.
ROTULOS = {
    "aggregation_operator": "Operador de agregação",
    "aggregation_period_hours": "Período agregado (h)",
    "aoi_code": "Área de interesse",
    "area_aoi": "Caixa da área de interesse",
    "area_expanded": "Área alargada pelo pedido",
    "area_requested": "Caixa pedida ao arquivo",
    "available_water_capacity_mm": "Capacidade do reservatório (mm)",
    "capacity_is_measured": "Capacidade medida no terreno",
    "cell_lat": "Latitude da célula",
    "cell_lon": "Longitude da célula",
    "cell_size_deg": "Lado da célula (graus)",
    "cell_size_km_ew": "Lado da célula, nascente-poente (km)",
    "cell_size_km_ns": "Lado da célula, norte-sul (km)",
    "days_since_restart": "Dias desde o reinício do modelo",
    "determined": "Valor determinado",
    "distance_km": "Distância ao sítio (km)",
    "field": "Campo lido na origem",
    "input_selection_rule": "Regra de escolha das entradas",
    "inputs": "Entradas",
    "masked_days_dropped": "Dias descartados pela máscara",
    "max_cloud": "Nuvem máxima aceite (%)",
    "measured_at_site": "Medido na parcela",
    "method": "Método",
    "model_version": "Versão do modelo",
    "night_radiation_dropped": "Leituras nocturnas descartadas",
    "no_data_pixels": "Píxeis sem dado",
    "provenances_available": "Proveniências disponíveis",
    "replicates": "Réplicas",
    "request_hash": "Impressão do pedido",
    "resolution_m": "Resolução (m)",
    "runoff_max_mm": "Escoamento máximo (mm)",
    "runoff_min_mm": "Escoamento mínimo (mm)",
    "sampled_pixels": "Píxeis amostrados",
    "scl_classes_excluded": "Classes SCL excluídas",
    "scl_mask": "Máscara SCL aplicada",
    "segment": "Segmento",
    "site_code": "Sítio",
    "site_lat": "Latitude do sítio",
    "site_lon": "Longitude do sítio",
    "site_point_source": "Origem do ponto do sítio",
    "source_file": "Ficheiro de origem",
    "source_url": "Endereço da origem",
    "station_id": "Estação",
    "station_lat": "Latitude da estação",
    "station_lon": "Longitude da estação",
    "station_name": "Nome da estação",
    "station_search_radius_km": "Raio de procura de estações (km)",
    "stations_considered": "Estações consideradas",
    "variable": "Variável no arquivo",
    "window_end": "Fim da janela de leitura",
}

# Os primeiros a aparecer, por esta ordem: sao os que respondem "isto foi medido
# aqui?", que e a pergunta com que se abre um painel de proveniencia.
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


def _rotulo(chave: str) -> str:
    return ROTULOS.get(chave, chave)


def _valor(bruto: Any) -> tuple[str, bool, tuple[Campo, ...]]:
    """(texto, retido, filhos) para um valor qualquer vindo da evidencia."""
    if isinstance(bruto, dict):
        razao = bruto.get(CHAVE_DE_RETIDO)
        if isinstance(razao, str) and len(bruto) == 1:
            return RAZOES_DE_RETIDO.get(razao, "retido"), True, ()
        return "", False, tuple(_campos(bruto))
    if isinstance(bruto, bool):
        return ("sim" if bruto else "não"), False, ()
    if isinstance(bruto, (int, float)):
        casas = 0 if isinstance(bruto, int) else CASAS_POR_OMISSAO
        return numero(bruto, casas), False, ()
    if isinstance(bruto, list):
        partes = []
        for item in bruto:
            texto, _, _ = _valor(item)
            partes.append(texto)
        return ", ".join(partes), False, ()
    if bruto is None:
        return "não registado", False, ()
    return str(bruto), False, ()


def _campos(evidencia: dict[str, Any]) -> list[Campo]:
    conhecidos = [chave for chave in PRIMEIROS if chave in evidencia]
    resto = sorted(chave for chave in evidencia if chave not in conhecidos)
    campos = []
    for chave in conhecidos + resto:
        texto, retido, filhos = _valor(evidencia[chave])
        campos.append(Campo(_rotulo(chave), texto, retido, filhos))
    return campos


def _da_linha(linha: dict[str, Any]) -> tuple[Campo, ...]:
    """O que a propria linha diz, e que nao depende da evidencia nenhuma.

    Aparece sempre, e nao so quando a evidencia falta: sao campos diferentes com
    significados diferentes, e mostrar um no lugar do outro conforme o que
    houver fazia o painel mudar de sentido sem avisar.
    """
    candidatos = (
        ("Métrica", linha.get("metric")),
        ("Unidade", linha.get("unit")),
        ("Origem", linha.get("source_type")),
        ("Qualificador do valor", linha.get("value_qualifier")),
        ("Marca de qualidade", linha.get("quality_flag")),
        ("Parcela", linha.get("plot_code")),
        ("Método", linha.get("method")),
        ("Colecção de origem", linha.get("source_collection")),
        ("Versão de processamento", linha.get("processing_version")),
        ("Nota", linha.get("notes")),
    )
    return tuple(
        Campo(rotulo, str(valor)) for rotulo, valor in candidatos if valor not in (None, "")
    )


def painel_de(linha: dict[str, Any]) -> Painel:
    evidencia = linha.get("evidence")
    estruturada = isinstance(evidencia, dict) and bool(evidencia)
    return Painel(
        estruturada=estruturada,
        da_evidencia=tuple(_campos(evidencia)) if estruturada else (),
        da_linha=_da_linha(linha),
    )
