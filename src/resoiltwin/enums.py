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
    documented_exact = "documented_exact"                # coordenadas confirmadas em documento
    surveyed = "surveyed"                                # levantado em campo/GNSS
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
