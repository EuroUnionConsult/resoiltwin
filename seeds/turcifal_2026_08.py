from datetime import datetime

from sqlalchemy import select

from resoiltwin.enums import QualityFlag, SourceType, ValueQualifier
from resoiltwin.features import VPD_PROCESSING_VERSION, vapour_pressure_deficit
from resoiltwin.models import Instrument, Observation, Plot, Site

FIELD_VERSION = "field-campaign-v1"
SITE_CODE = "EUC-TUR-01"
CANOPY, GRASS = "TUR-CANOPY", "TUR-GRASS"


def _ts(text: str) -> datetime:
    return datetime.fromisoformat(f"{text}+01:00")


# (timestamp, plot, metric, unit, numeric, vmin, vmax, qualifier, quality, notes, evidence)
READINGS = [
    ("2026-08-22T11:00", GRASS,  "light_screening", "instrument_scale", 2000.0, None, None,
     ValueQualifier.censored_high, QualityFlag.saturated_high, None, None),
    ("2026-08-22T11:00", CANOPY, "light_screening", "instrument_scale", 1900.0, None, None,
     ValueQualifier.mean_of_replicates, QualityFlag.repeated, "3 repeticoes estaveis", None),
    ("2026-08-22T14:37", CANOPY, "air_temperature", "degC", 30.0, None, None,
     ValueQualifier.exact, QualityFlag.valid, None, None),
    ("2026-08-22T14:37", CANOPY, "relative_humidity", "percent", 30.0, None, None,
     ValueQualifier.exact, QualityFlag.valid, None, None),
    ("2026-08-22T14:45", CANOPY, "soil_moisture_screening", "instrument_scale_0_10", 7.3, None, None,
     ValueQualifier.mean_of_replicates, QualityFlag.repeated, "media de 3 replicas",
     {"replicates": [8, 7, 7], "window_end": "2026-08-22T14:47+01:00"}),
    ("2026-08-22T14:53", GRASS,  "soil_moisture_screening", "instrument_scale_0_10", 7.3, None, None,
     ValueQualifier.mean_of_replicates, QualityFlag.repeated, "media de 3 replicas",
     {"replicates": [7, 7, 8]}),
    ("2026-08-22T16:21", CANOPY, "ph_screening", "pH", None, 7.0, 8.0,
     ValueQualifier.range, QualityFlag.range_value, "leituras 8 / ~7,5 / 7",
     {"replicates": [8, 7.5, 7], "window_end": "2026-08-22T16:26+01:00"}),
    ("2026-08-22T17:56", GRASS,  "ph_screening", "pH", None, 7.0, 7.5,
     ValueQualifier.range, QualityFlag.range_value, None, None),
    ("2026-08-22T17:56", CANOPY, "light_screening", "instrument_scale", 300.0, None, None,
     ValueQualifier.exact, QualityFlag.approximate, "canopy_shade", None),
    ("2026-08-22T17:56", GRASS,  "light_screening", "instrument_scale", 400.0, None, None,
     ValueQualifier.exact, QualityFlag.approximate, "diffuse_shade, sem sol directo", None),
    ("2026-08-22T17:57", GRASS,  "light_screening", "instrument_scale", 2000.0, None, None,
     ValueQualifier.censored_high, QualityFlag.saturated_high,
     "direct_sun; minuto ajustado de 17:56 para 17:57 para desambiguar da leitura "
     "'diffuse_shade, sem sol directo' do mesmo plot (TUR-GRASS) e minuto no relatorio de "
     "origem -- uq_observation_identity rejeitaria duas leituras identicas em site/plot/"
     "observed_at/metric/source_type. O valor e o timestamp de origem sao 17:56; ver relatorio §2.",
     None),
    ("2026-08-22T18:05", CANOPY, "air_temperature", "degC", 25.0, None, None,
     ValueQualifier.exact, QualityFlag.valid, None, None),
    ("2026-08-22T18:05", CANOPY, "relative_humidity", "percent", 60.0, None, None,
     ValueQualifier.exact, QualityFlag.valid, None, None),
    ("2026-08-23T08:00", CANOPY, "air_temperature", "degC", 24.0, None, None,
     ValueQualifier.exact, QualityFlag.valid, None, None),
    ("2026-08-23T08:00", CANOPY, "relative_humidity", "percent", 70.0, None, None,
     ValueQualifier.exact, QualityFlag.valid, None, None),
    ("2026-08-23T09:45", CANOPY, "light_screening", "instrument_scale", 800.0, None, None,
     ValueQualifier.exact, QualityFlag.valid, None, None),
    ("2026-08-23T09:45", GRASS,  "light_screening", "instrument_scale", 2000.0, None, None,
     ValueQualifier.censored_high, QualityFlag.saturated_high, None, None),
    ("2026-08-24T13:48", CANOPY, "light_screening", "instrument_scale", 1800.0, None, None,
     ValueQualifier.exact, QualityFlag.valid, None, None),
    ("2026-08-24T13:48", GRASS,  "light_screening", "instrument_scale", 2000.0, None, None,
     ValueQualifier.censored_high, QualityFlag.saturated_high, None, None),
    ("2026-08-24T13:48", CANOPY, "air_temperature", "degC", 26.0, None, None,
     ValueQualifier.exact, QualityFlag.valid, None, None),
    ("2026-08-24T13:48", CANOPY, "relative_humidity", "percent", 80.0, None, None,
     ValueQualifier.exact, QualityFlag.valid, None, None),
    ("2026-08-24T13:48", GRASS,  "air_temperature", "degC", 26.0, None, None,
     ValueQualifier.exact, QualityFlag.valid, None, None),
    ("2026-08-24T13:48", GRASS,  "relative_humidity", "percent", 80.0, None, None,
     ValueQualifier.exact, QualityFlag.valid, None, None),
    ("2026-08-24T15:30", CANOPY, "ph_screening", "pH", None, 7.0, 8.0,
     ValueQualifier.range, QualityFlag.range_value, None, None),
    ("2026-08-24T15:30", GRASS,  "ph_screening", "pH", None, 7.0, 8.0,
     ValueQualifier.range, QualityFlag.range_value, None, None),
    ("2026-08-24T15:55", CANOPY, "soil_moisture_screening", "instrument_scale_0_10", 6.0, None, None,
     ValueQualifier.mean_of_replicates, QualityFlag.repeated, "media estavel no periodo",
     {"window_end": "2026-08-24T17:19+01:00"}),
    ("2026-08-24T15:55", GRASS,  "soil_moisture_screening", "instrument_scale_0_10", 8.0, None, None,
     ValueQualifier.mean_of_replicates, QualityFlag.repeated, "media estavel no periodo",
     {"window_end": "2026-08-24T17:19+01:00"}),
]

# (timestamp, temperatura, humidade relativa) para o VPD derivado
VPD_INPUTS = [
    ("2026-08-22T14:37", 30.0, 30.0),
    ("2026-08-22T18:05", 25.0, 60.0),
    ("2026-08-23T08:00", 24.0, 70.0),
    ("2026-08-24T13:48", 26.0, 80.0),
]


def _get_or_create(session, model, *, defaults=None, **lookup):
    obj = session.scalar(select(model).filter_by(**lookup))
    if obj is None:
        obj = model(**lookup, **(defaults or {}))
        session.add(obj)
        session.flush()
    return obj


def seed_turcifal(session) -> dict:
    """Carrega a campanha de campo de 22-24/08/2026 em EUC-TUR-01.

    Idempotente: reexecutar nao duplica. Todas as leituras entram como
    observed_screening -- instrumentos de rastreio, nao calibrados. O VPD
    entra como derived, com a sua propria processing_version.
    """
    site = _get_or_create(
        session, Site, code=SITE_CODE,
        defaults={"name": "Turcifal - micro-site de citrinos", "crop_type": "citrus"},
    )
    canopy = _get_or_create(
        session, Plot, code=CANOPY,
        defaults={"site_id": site.id, "name": "Sob copa do limoeiro", "purpose": "canopy"},
    )
    grass = _get_or_create(
        session, Plot, code=GRASS,
        defaults={"site_id": site.id, "name": "Relvado / prado aberto", "purpose": "open_grass"},
    )
    instrument = _get_or_create(
        session, Instrument, code="DUO-TERRA-01",
        defaults={
            "model": "DUO TERRA (multi-parametro de rastreio)", "grade": "screening",
            "scale_max": 2000.0, "calibration_status": "uncalibrated",
            "limitations": (
                "Luz satura no topo de escala (>=2000). pH de baixa resolucao, "
                "reportado como intervalo. Humidade do solo em escala relativa 0-10, "
                "nao em conteudo volumetrico."
            ),
        },
    )
    plots = {CANOPY: canopy.id, GRASS: grass.id}

    inserted = 0
    for ts, plot_code, metric, unit, num, vmin, vmax, qual, flag, note, evidence in READINGS:
        observed_at = _ts(ts)
        exists = session.scalar(
            select(Observation).filter_by(
                site_id=site.id, plot_id=plots[plot_code], observed_at=observed_at,
                metric=metric, source_type=SourceType.observed_screening,
                processing_version=FIELD_VERSION,
            )
        )
        if exists:
            continue
        session.add(Observation(
            site_id=site.id, plot_id=plots[plot_code], instrument_id=instrument.id,
            observed_at=observed_at, metric=metric, unit=unit,
            value_numeric=num, value_min=vmin, value_max=vmax, value_qualifier=qual,
            source_type=SourceType.observed_screening, quality_flag=flag,
            processing_version=FIELD_VERSION, method="manual_screening", notes=note,
            evidence=evidence,
        ))
        inserted += 1

    # os ids sao precisos ja a seguir, para ligar cada VPD as duas leituras que
    # o produziram; sem flush as linhas novas ainda nao existem na transaccao
    session.flush()

    derived = 0
    for ts, temp_c, rh in VPD_INPUTS:
        observed_at = _ts(ts)
        exists = session.scalar(
            select(Observation).filter_by(
                site_id=site.id, plot_id=canopy.id, observed_at=observed_at,
                metric="vpd", source_type=SourceType.derived,
                processing_version=VPD_PROCESSING_VERSION,
            )
        )
        if exists:
            continue
        # ligacao estrutural as origens: sem isto, auditar um VPD para tras so
        # daria os NUMEROS de entrada guardados em evidence, nunca as linhas que
        # os produziram. Com os ids, a cadeia VPD -> temperatura + humidade e
        # percorrivel na base e o valor pode ser recalculado a partir dela.
        sources = session.scalars(
            select(Observation).where(
                Observation.site_id == site.id,
                Observation.plot_id == canopy.id,
                Observation.observed_at == observed_at,
                Observation.metric.in_(("air_temperature", "relative_humidity")),
                Observation.source_type == SourceType.observed_screening,
                Observation.processing_version == FIELD_VERSION,
            ).order_by(Observation.metric)
        ).all()
        if len(sources) != 2:
            raise RuntimeError(
                f"VPD de {ts}: esperava a temperatura e a humidade relativa na base, "
                f"encontrei {len(sources)}. Um derivado sem as origens completas nao "
                "e auditavel e nao pode ser gravado."
            )
        session.add(Observation(
            site_id=site.id, plot_id=canopy.id, observed_at=observed_at,
            metric="vpd", unit="kPa", derived_from=[o.id for o in sources],
            value_numeric=round(vapour_pressure_deficit(temp_c, rh), 4),
            value_qualifier=ValueQualifier.exact,
            source_type=SourceType.derived, quality_flag=QualityFlag.valid,
            processing_version=VPD_PROCESSING_VERSION,
            method="tetens_saturation_vapour_pressure",
            notes="Derivado de temperatura do ar e humidade relativa; nao e medicao directa.",
            evidence={"inputs": {"air_temperature_degC": temp_c, "relative_humidity_pct": rh}},
        ))
        derived += 1

    session.commit()
    return {
        "sites": 1, "plots": 2, "instruments": 1,
        "observations": inserted, "derived": derived,
    }
