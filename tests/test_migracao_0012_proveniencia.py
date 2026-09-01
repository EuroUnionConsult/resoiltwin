"""A migracao 0012 corrigiu duas linhas gravadas. Este ficheiro mede-o.

Nasceu de um sobrevivente. Na ronda de mutacao de 01/09/2026, tirar a guarda
`AND geometry_provenance = :de` do UPDATE da migracao nao fez cair teste nenhum,
e a razao era estrutural: a base que a suite constroi nasce vazia, portanto a
0012 corria sobre zero linhas de `aois` e o seu UPDATE era um nao-acontecimento
com ou sem guarda. Uma correccao de dados que so foi ensaiada a mao e uma
correccao por defender.

Este teste constroi uma base propria -- pelas mesmas guardas que a suite usa,
em `tests/base_de_testes.py` --, para-a na 0011, poe-lhe linhas dentro e so
depois a leva a 0012. E a unica forma de ver o UPDATE a acontecer: na base da
suite ele ja correu, sobre o vazio, antes de qualquer teste comecar.

Nao ha aqui coordenada nenhuma: os poligonos sao um quadrado de brincar e o que
se afirma e sobre a coluna `geometry_provenance`, nao sobre geometria.
"""

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from resoiltwin.config import get_settings
from tests.base_de_testes import BaseDeTestes

# um quadrado de brincar. A migracao nao olha para a geometria.
_QUADRADO = "POLYGON((0 0, 0 1, 1 1, 1 0, 0 0))"

# a terceira AOI existe para o controlo negativo: se ela mudar, a correccao nao
# esta a nomear as duas linhas, esta a varrer a tabela.
_ALHEIA = "EUC-TST-EO9"


def _configuracao(url: str, raiz) -> Config:
    cfg = Config(str(raiz / "alembic.ini"))
    cfg.set_main_option("script_location", str(raiz / "migrations"))
    cfg.attributes["sqlalchemy_url"] = url
    return cfg


def _semear(motor, linhas: dict[str, str]) -> None:
    """Um sitio e uma AOI por entrada, com a proveniencia pedida."""
    with motor.begin() as ligacao:
        ligacao.execute(text(
            "INSERT INTO sites (id, code, name, timezone, created_at)"
            " VALUES (gen_random_uuid(), 'EUC-TST-01', 'sitio de teste', 'Europe/Lisbon', now())"
        ))
        sitio = ligacao.execute(text("SELECT id FROM sites WHERE code = 'EUC-TST-01'")).scalar()
        for codigo, proveniencia in linhas.items():
            ligacao.execute(
                text(
                    "INSERT INTO aois (id, site_id, code, purpose, geometry,"
                    " geometry_provenance, status, approved_by, approved_at, created_at)"
                    " VALUES (gen_random_uuid(), :sitio, :codigo, 'earth_observation',"
                    " ST_GeomFromText(:quadrado, 4326), :proveniencia, 'approved',"
                    " 'site-manager', now(), now())"
                ),
                {"sitio": sitio, "codigo": codigo, "proveniencia": proveniencia,
                 "quadrado": _QUADRADO},
            )


def _proveniencias(motor) -> dict[str, str]:
    with motor.connect() as ligacao:
        return dict(ligacao.execute(text(
            "SELECT code, geometry_provenance FROM aois ORDER BY code"
        )).all())


def _repor(motor, linhas: dict[str, str]) -> None:
    with motor.begin() as ligacao:
        for codigo, proveniencia in linhas.items():
            ligacao.execute(
                text("UPDATE aois SET geometry_provenance = :p WHERE code = :c"),
                {"p": proveniencia, "c": codigo},
            )


@pytest.fixture
def base_parada_na_0011(request):
    """Uma base descartavel levada ate a 0011 e ali deixada.

    Propria e nao a da suite: a da suite ja esta em `head`, e nao ha maneira de
    ver uma migracao a correr numa base onde ela ja correu.
    """
    base = BaseDeTestes(get_settings().database_url)
    with base:
        cfg = _configuracao(base.url, request.config.rootpath)
        command.upgrade(cfg, "0011")
        motor = create_engine(base.url)
        try:
            yield motor, cfg
        finally:
            motor.dispose()


def test_a_0012_corrige_as_duas_linhas_e_so_essas(base_parada_na_0011):
    """As duas passagens cobrem os dois codigos nos dois papeis.

    Primeira: a AOI de Turcifal esta em `surveyed` e tem de passar a
    `constructed_extent`; a do Porto ja foi corrigida a mao para outra coisa e
    NAO pode ser tocada. Segunda: os papeis trocam, e e a do Porto que tem de
    passar a `digitised_from_basemap`.

    Sem a segunda passagem, o valor que a AOI do Porto recebe ficava sem teste:
    trocar as duas entradas do mapa de correccoes passava despercebido.
    """
    motor, cfg = base_parada_na_0011
    _semear(motor, {
        "EUC-TUR-EO1": "surveyed",
        "EUC-PTO-EO1": "documented_exact",
        _ALHEIA: "surveyed",
    })

    command.upgrade(cfg, "head")
    assert _proveniencias(motor) == {
        "EUC-TUR-EO1": "constructed_extent",
        "EUC-PTO-EO1": "documented_exact",
        _ALHEIA: "surveyed",
    }

    command.downgrade(cfg, "0011")
    _repor(motor, {"EUC-TUR-EO1": "documented_exact", "EUC-PTO-EO1": "surveyed"})
    command.upgrade(cfg, "head")
    assert _proveniencias(motor) == {
        "EUC-TUR-EO1": "documented_exact",
        "EUC-PTO-EO1": "digitised_from_basemap",
        _ALHEIA: "surveyed",
    }


def test_a_0012_nao_cria_nem_apaga_linhas(base_parada_na_0011):
    """A afirmacao de contagem que a propria migracao faz, verificada.

    A correccao de 01/09/2026 correu contra uma base com 1121 observacoes e 25
    jobs e nao devia mexer em nenhuma. Aqui as tabelas sao pequenas; o que se
    prende e a forma da afirmacao, nao os numeros daquele dia.
    """
    motor, cfg = base_parada_na_0011
    _semear(motor, {"EUC-TUR-EO1": "surveyed", "EUC-PTO-EO1": "surveyed", _ALHEIA: "surveyed"})

    def contar() -> dict[str, int]:
        with motor.connect() as ligacao:
            return {
                tabela: ligacao.execute(text(f"SELECT count(*) FROM {tabela}")).scalar()
                for tabela in ("aois", "sites", "observations", "ingestion_jobs")
            }

    antes = contar()
    command.upgrade(cfg, "head")
    assert contar() == antes


def test_o_downgrade_recusa_se_outra_linha_usar_um_valor_novo(base_parada_na_0011):
    """O downgrade repoe `surveyed` nas duas linhas nomeadas e mais nada.

    Uma terceira AOI que entretanto use um dos valores novos nao tem para onde
    voltar: o dominio antigo nao a aceita. O PostgreSQL recusa recriar a
    constraint, e e isso que se quer -- reduzir uma area tracada a "levantada em
    campo" em silencio seria pior do que nao reverter.
    """
    motor, cfg = base_parada_na_0011
    _semear(motor, {"EUC-TUR-EO1": "surveyed", "EUC-PTO-EO1": "surveyed", _ALHEIA: "surveyed"})
    command.upgrade(cfg, "head")
    _repor(motor, {_ALHEIA: "digitised_from_basemap"})

    with pytest.raises(Exception) as excepcao:
        command.downgrade(cfg, "0011")
    assert "ck_aoi_geometry_provenance_domain" in str(excepcao.value)
