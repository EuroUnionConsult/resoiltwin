import pytest
from sqlalchemy.exc import IntegrityError

from resoiltwin.enums import AoiStatus, GeometryProvenance
from resoiltwin.geo import geojson_to_wkt_element
from resoiltwin.models import Aoi, ObservationPoint, Plot, Site

SQUARE = {
    "type": "Polygon",
    "coordinates": [[
        [-9.24034, 39.03725], [-9.24016, 39.03725],
        [-9.24016, 39.03739], [-9.24034, 39.03739], [-9.24034, 39.03725],
    ]],
}


def test_site_code_is_unique(session):
    session.add(Site(code="EUC-TUR-01", name="Turcifal", crop_type="citrus"))
    session.commit()
    session.add(Site(code="EUC-TUR-01", name="Duplicado", crop_type="citrus"))
    with pytest.raises(IntegrityError):
        session.commit()


def test_aoi_defaults_to_draft(session):
    site = Site(code="EUC-TUR-02", name="Turcifal 2")
    aoi = Aoi(
        site=site, code="EUC-TUR-EO2", purpose="earth_observation",
        geometry=geojson_to_wkt_element(SQUARE),
        geometry_provenance=GeometryProvenance.provisional_pending_kml,
    )
    session.add(aoi)
    session.commit()
    assert aoi.status == AoiStatus.draft
    assert aoi.approved_by is None


def test_provisional_aoi_cannot_be_approved(session):
    """Um poligono inventado nunca pode ficar approved: e a guarda que impede
    que um numero sem base escape para um relatorio.

    Afirma sobre o NOME da constraint: com approved_by preenchido, a unica que
    pode disparar e ck_aoi_provisional_never_approved. Sem esta verificacao o
    teste passaria com a constraint apagada, desde que outra qualquer falhasse.
    """
    site = Site(code="EUC-TUR-03", name="Turcifal 3")
    aoi = Aoi(
        site=site, code="EUC-TUR-EO3", purpose="earth_observation",
        geometry=geojson_to_wkt_element(SQUARE),
        geometry_provenance=GeometryProvenance.provisional_pending_kml,
        status=AoiStatus.approved, approved_by="site-manager",
    )
    session.add(aoi)
    with pytest.raises(IntegrityError) as exc:
        session.commit()
    assert "ck_aoi_provisional_never_approved" in str(exc.value)


def test_a_traced_or_constructed_area_can_be_approved(session):
    """A decisao tomada a 01/09/2026, presa por um teste.

    A guarda de aprovacao recusa `provisional_pending_kml` -- geometria cuja
    POSICAO e inventada -- e nao "geometria pouco exacta". Um contorno tracado
    sobre mapa base esta onde se ve que esta; uma caixa construida a volta de um
    ponto documentado e reproduzivel ao metro. As duas AOI em producao sao estes
    dois casos e estao aprovadas com dados ja recolhidos: se este teste comecar
    a falhar, alguem alargou a guarda e desaprovou trabalho correcto.
    """
    site = Site(code="EUC-TUR-08", name="Turcifal 8")
    tracada = Aoi(
        site=site, code="EUC-TUR-EO8", purpose="earth_observation",
        geometry=geojson_to_wkt_element(SQUARE),
        geometry_provenance=GeometryProvenance.digitised_from_basemap,
        status=AoiStatus.approved, approved_by="site-manager",
    )
    construida = Aoi(
        site=site, code="EUC-TUR-EO9", purpose="earth_observation",
        geometry=geojson_to_wkt_element(SQUARE),
        geometry_provenance=GeometryProvenance.constructed_extent,
        status=AoiStatus.approved, approved_by="site-manager",
    )
    session.add_all([tracada, construida])
    session.commit()
    assert tracada.status == AoiStatus.approved
    assert construida.status == AoiStatus.approved


def test_approved_aoi_needs_an_approver(session):
    """Aprovada por quem? Sem nome nao ha responsavel pela aprovacao."""
    site = Site(code="EUC-TUR-05", name="Turcifal 5")
    aoi = Aoi(
        site=site, code="EUC-TUR-EO5", purpose="earth_observation",
        geometry=geojson_to_wkt_element(SQUARE),
        geometry_provenance=GeometryProvenance.documented_exact,
        status=AoiStatus.approved, approved_by=None,
    )
    session.add(aoi)
    with pytest.raises(IntegrityError) as exc:
        session.commit()
    assert "ck_aoi_approved_needs_approver" in str(exc.value)


def test_status_outside_the_enum_is_rejected(session):
    """'Approved' com maiuscula contornava as duas guardas de aprovacao, que
    comparam com o literal minusculo: uma AOI provisoria ficava aprovada por
    diferenca de caixa."""
    site = Site(code="EUC-TUR-06", name="Turcifal 6")
    aoi = Aoi(
        site=site, code="EUC-TUR-EO6", purpose="earth_observation",
        geometry=geojson_to_wkt_element(SQUARE),
        geometry_provenance=GeometryProvenance.provisional_pending_kml,
        status="Approved", approved_by="site-manager",
    )
    session.add(aoi)
    with pytest.raises(IntegrityError) as exc:
        session.commit()
    assert "ck_aoi_status_domain" in str(exc.value)


def test_geometry_provenance_outside_the_enum_is_rejected(session):
    site = Site(code="EUC-TUR-07", name="Turcifal 7")
    aoi = Aoi(
        site=site, code="EUC-TUR-EO7", purpose="earth_observation",
        geometry=geojson_to_wkt_element(SQUARE),
        geometry_provenance="desenhado_a_olho",
    )
    session.add(aoi)
    with pytest.raises(IntegrityError) as exc:
        session.commit()
    assert "ck_aoi_geometry_provenance_domain" in str(exc.value)


def test_plot_and_observation_point(session):
    site = Site(code="EUC-TUR-04", name="Turcifal 4")
    plot = Plot(site=site, code="TUR-CANOPY", name="Sob copa do limoeiro", purpose="canopy")
    point = ObservationPoint(plot=plot, code="TUR-C1", depth_cm=10)
    session.add(point)
    session.commit()
    assert point.plot.site.code == "EUC-TUR-04"
