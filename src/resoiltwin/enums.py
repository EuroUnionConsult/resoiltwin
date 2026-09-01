from enum import StrEnum


class SourceType(StrEnum):
    """De onde vem um valor. Nao existe valor por omissao: quem grava tem de decidir.

    Nota: o valor 'observed' foi deliberadamente omitido. Era ambiguo entre
    um instrumento de rastreio de retalho e um sensor calibrado, e apagava
    exactamente a distincao de que a auditabilidade MRV depende.
    """

    observed_screening = "observed_screening"      # instrumento de rastreio, nao calibrado
    observed_reference = "observed_reference"      # sensor calibrado, rastreavel
    observed_lab = "observed_lab"                  # analise laboratorial
    satellite_observed = "satellite_observed"      # derivado de aquisicao Sentinel
    weather_observed = "weather_observed"          # estacao meteorologica
    reanalysis = "reanalysis"                      # ERA5-Land e afins: modelo, nao medicao
    simulated = "simulated"                        # saida do emulador; NAO e medicao
    derived = "derived"                            # produto calculado sobre as camadas acima

    @staticmethod
    def is_measurement(value: "SourceType") -> bool:
        """True apenas para origens que sao medicoes fisicas."""
        return value in {
            SourceType.observed_screening,
            SourceType.observed_reference,
            SourceType.observed_lab,
            SourceType.satellite_observed,
            SourceType.weather_observed,
        }


class QualityFlag(StrEnum):
    unchecked = "unchecked"
    valid = "valid"
    repeated = "repeated"                      # media de repeticoes no mesmo ponto
    saturated_high = "saturated_high"          # instrumento no topo de escala
    saturated_low = "saturated_low"
    range_value = "range_value"                # leitura dada como intervalo
    approximate = "approximate"
    suspect = "suspect"
    rejected = "rejected"
    laboratory_confirmed = "laboratory_confirmed"


class ValueQualifier(StrEnum):
    """Como o numero se relaciona com a grandeza real."""

    exact = "exact"
    mean_of_replicates = "mean_of_replicates"
    censored_high = "censored_high"            # o valor real e >= value_numeric
    censored_low = "censored_low"
    range = "range"                            # o valor real esta entre value_min e value_max


class AoiStatus(StrEnum):
    draft = "draft"
    approved = "approved"
    rejected = "rejected"


class GeometryProvenance(StrEnum):
    """Como o poligono foi feito. Ordenado do mais preso ao terreno para o menos.

    `digitised_from_basemap` e `constructed_extent` nasceram a 01/09/2026 de um
    erro que estas quatro linhas nao tinham palavra para evitar: as duas AOI
    reais estavam declaradas `surveyed` -- levantado em campo -- e nenhuma das
    duas pisou o terreno. Uma e uma caixa desenhada a volta de um ponto, a
    outra um contorno tracado sobre mapa base. Escolher o menos errado dos
    quatro valores antigos era repetir o mesmo defeito noutra palavra.

    Sao DOIS valores e nao um porque afirmam coisas diferentes. Um contorno
    tracado diz "isto e o limite de uma feicao que existe, tal como o mapa base
    a mostra" -- afirmacao verificavel, e cuja margem de erro e a do mapa e a da
    mao. Uma caixa construida nao afirma limite nenhum: e um recorte de analise
    escolhido, e perguntar-lhe "que exactidao tem esta fronteira?" nao tem
    resposta porque nao ha fronteira nenhuma no terreno a que a comparar. Fundir
    as duas num so valor voltava a por uma palavra a cobrir duas verdades, que e
    exactamente o que a auditoria apanhou.
    """

    documented_exact = "documented_exact"                # coordenadas confirmadas em documento
    surveyed = "surveyed"                                # levantado em campo/GNSS
    digitised_from_basemap = "digitised_from_basemap"    # tracado sobre mapa base, a seguir limites visiveis
    constructed_extent = "constructed_extent"            # recorte construido; nao e limite de nada no terreno
    derived_from_metrics = "derived_from_metrics"        # area real, posicao estimada
    provisional_pending_kml = "provisional_pending_kml"  # inventado; NAO usar em relatorio


class JobStatus(StrEnum):
    """Estado de uma execucao de ingestao. Uma so direccao de vida: pending ->
    running -> (succeeded | failed). Nao ha estado de retomar nem de cancelado
    -- a fase seguinte, que agenda a ingestao, e que decide o que fazer com um
    job failed."""

    pending = "pending"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
