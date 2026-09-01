"""A consola: as tres vistas, e as guardas de desenho que as decidem.

Os quatro testes que decidiram o desenho -- e que foram escritos antes de
existir uma linha da consola -- sao:

1. uma linha de **intervalo** mostra-se como intervalo, e nunca como um numero.
   O meio de um intervalo e um numero que ninguem mediu;
2. uma leitura **saturada** mostra-se como `>= valor`, e nunca como o valor.
   2000 numa escala que satura a 2000 nao e uma medida, e um limite inferior;
3. uma linha **sem proveniencia estruturada** di-lo, em vez de mostrar um
   painel vazio. Um painel vazio le-se como "nao ha nada a dizer sobre isto",
   quando o que se passa e o contrario -- ha, e nao foi gravado;
4. a origem **tramada** distingue-se da solida por outra coisa alem da cor.
   Cerca de 8% dos homens tem dificuldade com vermelho/verde, e a distincao
   entre "medido na parcela" e "nao medido na parcela" e a distincao que este
   produto inteiro existe para nao apagar.

O resto do ficheiro prende o que a consola nao pode deixar escapar (a chave, as
coordenadas), o encaminhamento (a pagina tem de ganhar ao apanha-tudo da camada)
e as regras de cor e de movimento, que sao vinculativas e nao sugestoes.
"""

import re
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from resoiltwin.api import console
from resoiltwin.config import get_settings
from resoiltwin.console import formato, marcacao, paleta, textos
from resoiltwin.console.estilo import FOLHA_DE_ESTILO
from resoiltwin.enums import (
    AoiStatus,
    GeometryProvenance,
    JobStatus,
    QualityFlag,
    SourceType,
    ValueQualifier,
)
from resoiltwin.geo import geojson_to_wkt_element
from resoiltwin.models import Aoi, IngestionJob, Observation, Plot, Site
from tests.conftest import CHAVE_DE_ESCRITA_DOS_TESTES

# ---------------------------------------------------------------------------
# Os dados de que estes testes precisam, e cada linha esta ca por uma razao.
# ---------------------------------------------------------------------------

SITIO = "EUC-CON-01"

# Uma coordenada com sete casas decimais, do genero das que estao mesmo na base
# (o `site_lat` das linhas de reanalise, e o par que aparece dentro da nota de
# uma AOI). Nenhum destes numeros pode chegar ao navegador.
LATITUDE = 39.0373170
LONGITUDE = -9.2402470

QUADRADO = {
    "type": "Polygon",
    "coordinates": [[
        [-9.24034, 39.03725], [-9.24016, 39.03725],
        [-9.24016, 39.03739], [-9.24034, 39.03739], [-9.24034, 39.03725],
    ]],
}

# O mesmo par escrito com menos casas. Esta ca porque as duas regras que cortam
# coordenadas de dentro de um texto -- o par de decimais e o decimal solto com
# muitas casas -- se sobrepoem no par de cima: sem um par curto, desligar a
# regra do par nao mudava nada de visivel, e nenhum mutante conseguia medi-la.
PAR_CURTO = "39.0385, -9.2255"

NOTA_DA_AOI = (
    f"Caixa de 2,5 x 2,5 km centrada no micro-site {SITIO} ({LATITUDE}, {LONGITUDE}), "
    f"escolhida a 28/08/2026 a partir do vértice de referência ({PAR_CURTO})."
)


def _momento(dias: int) -> datetime:
    return datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc) + timedelta(days=dias)


@pytest.fixture
def dados(session):
    """Um sitio com uma linha de cada forma que a consola tem de saber mostrar."""
    sitio = Site(code=SITIO, name="Sitio da consola", crop_type="citrus")
    aoi = Aoi(
        site=sitio, code="EUC-CON-EO1", purpose="earth_observation",
        geometry=geojson_to_wkt_element(QUADRADO),
        geometry_provenance=GeometryProvenance.surveyed,
        geometry_source_note=NOTA_DA_AOI,
        status=AoiStatus.approved, approved_by="Talys Cordeiro",
    )
    parcela = Plot(site=sitio, code="CON-GRASS", name="Relvado", purpose="open_grass")
    session.add_all([sitio, aoi, parcela])
    session.flush()

    evidencia_de_reanalise = {
        "aoi_code": "EUC-CON-EO1",
        "variable": "2m_temperature",
        "site_lat": LATITUDE,
        "site_lon": LONGITUDE,
        "cell_lat": 39.0000000000029,
        "cell_lon": -9.200000000009709,
        "area_aoi": [39.048545, -9.254703, 39.026088, -9.225790],
        "distance_km": 5.3412,
        "cell_size_km_ns": 11.11950802335329,
        "cell_size_km_ew": 8.366483616356287,
        "measured_at_site": False,
    }

    linhas = [
        # 1. o intervalo. O meio de 7,0 e 8,0 e 7,5, e 7,5 e um numero que
        #    ninguem leu -- aparece de proposito dentro das replicas, para que o
        #    teste do intervalo tenha de olhar para a celula e nao para a pagina.
        Observation(
            site_id=sitio.id, observed_at=_momento(0), metric="ph_screening", unit="pH",
            value_min=7.0, value_max=8.0, value_qualifier=ValueQualifier.range,
            source_type=SourceType.observed_screening, quality_flag=QualityFlag.range_value,
            processing_version="manual-v1", method="manual_screening", evidence=None,
        ),
        # 2. a leitura saturada: o instrumento parou no topo da escala.
        Observation(
            site_id=sitio.id, observed_at=_momento(1), metric="light_screening",
            unit="instrument_scale", value_numeric=2000.0,
            value_qualifier=ValueQualifier.censored_high,
            source_type=SourceType.observed_screening, quality_flag=QualityFlag.saturated_high,
            processing_version="manual-v1", method="manual_screening", evidence=None,
        ),
        # 3. a linha com proveniencia estruturada, medida na parcela.
        Observation(
            site_id=sitio.id, plot_id=parcela.id, observed_at=_momento(2),
            metric="soil_moisture_screening", unit="instrument_scale_0_10",
            value_numeric=7.3, value_qualifier=ValueQualifier.mean_of_replicates,
            source_type=SourceType.observed_screening, quality_flag=QualityFlag.repeated,
            processing_version="manual-v1", method="manual_screening",
            evidence={"replicates": [7, 7.5, 8], "window_end": "2026-08-22T16:26+01:00"},
        ),
        # 4. a celula de reanalise: nao e uma medicao no sitio, e a evidencia
        #    dela traz coordenadas que nao podem sair.
        Observation(
            site_id=sitio.id, observed_at=_momento(3), metric="air_temperature", unit="degC",
            value_numeric=22.7647338867, value_qualifier=ValueQualifier.exact,
            source_type=SourceType.reanalysis, quality_flag=QualityFlag.valid,
            processing_version="agera5-v2_0", source_collection="sis-agrometeorological-indicators",
            evidence=evidencia_de_reanalise,
        ),
        # 5. o balanco hidrico: um intervalo que vai de 0 a quase toda a
        #    capacidade, que e a forma honesta de dizer "ainda nao sei".
        Observation(
            site_id=sitio.id, observed_at=_momento(4), metric="soil_available_water", unit="mm",
            value_min=0.0, value_max=93.121741771698, value_qualifier=ValueQualifier.range,
            source_type=SourceType.simulated, quality_flag=QualityFlag.range_value,
            processing_version="water-balance-v1",
            evidence={"available_water_capacity_mm": 100.0, "measured_at_site": False,
                      "determined": False, "model_version": "water-balance-v1"},
        ),
        # 6. o indice do satelite: medido sobre a propria area de interesse.
        Observation(
            site_id=sitio.id, observed_at=_momento(5), metric="ndvi", unit="index",
            value_numeric=0.4852038715, value_qualifier=ValueQualifier.exact,
            source_type=SourceType.satellite_observed, quality_flag=QualityFlag.unchecked,
            processing_version="s2-ndvi-v2",
            evidence={"aoi_code": "EUC-CON-EO1", "sampled_pixels": 2501, "resolution_m": 10},
        ),
    ]
    session.add_all(linhas)

    execucoes = [
        IngestionJob(
            aoi_id=aoi.id, job_type="reanalysis_sync", status=JobStatus.succeeded,
            date_from=_momento(0).date(), date_to=_momento(1).date(),
            requested_date_from=_momento(0).date(), requested_date_to=_momento(59).date(),
            request_hash="a" * 64, processing_version="agera5-v2_0",
            started_at=_momento(6), finished_at=_momento(6), rows_written=6,
        ),
        IngestionJob(
            aoi_id=aoi.id, job_type="eo_sync", status=JobStatus.failed,
            date_from=_momento(0).date(), date_to=_momento(1).date(),
            request_hash="b" * 64, started_at=_momento(7), finished_at=_momento(7),
            rows_written=0, error="A colheita do Copernicus devolveu 401.",
        ),
    ]
    session.add_all(execucoes)
    session.commit()
    return {"sitio": sitio, "aoi": aoi, "linhas": {linha.metric: linha for linha in linhas}}


def _pagina(cliente, caminho: str) -> str:
    resposta = cliente.get(caminho)
    assert resposta.status_code == 200, f"{caminho} respondeu {resposta.status_code}"
    assert resposta.headers["content-type"].startswith("text/html")
    return resposta.text


def _linha(html: str, identificador) -> str:
    """O troco de HTML de uma linha da tabela, e so dele.

    Um teste que procure um numero na pagina inteira nao mede nada: o meio de um
    intervalo aparece legitimamente noutros sitios (dentro das replicas, por
    exemplo). O que tem de ser verdade e sobre a CELULA.
    """
    encontrado = re.search(
        rf'<tr class="linha"[^>]*data-linha="{identificador}".*?</tr>', html, re.S
    )
    assert encontrado, f"a linha {identificador} nao esta na pagina"
    return encontrado.group(0)


def _celula(html: str, identificador, classe: str) -> str:
    troco = _linha(html, identificador)
    encontrado = re.search(rf'<td class="{classe}"[^>]*>(.*?)</td>', troco, re.S)
    assert encontrado, f"a linha {identificador} nao tem celula {classe}"
    return encontrado.group(1)


def _texto(html: str) -> str:
    """O texto visivel, sem etiquetas: e o que uma pessoa le."""
    return re.sub(r"<[^>]+>", " ", html)


# ---------------------------------------------------------------------------
# As duas linguas
# ---------------------------------------------------------------------------

# ⚠️ Os testes desta suite correm nas DUAS linguas onde a lingua pode mudar o
# que eles medem, e leem o texto esperado da mesma tabela que a pagina usa. Uma
# cadeia portuguesa escrita a mao dentro de um teste parte-se ao primeiro
# retoque de reduccao e nao defende propriedade nenhuma: o que tem de ser
# verdade e que a DISTINCAO esta visivel, e nao que ela esta escrita com estas
# palavras.
AS_DUAS_LINGUAS = ("en", "pt")


def _end(caminho: str, lingua: str) -> str:
    """O mesmo caminho, pedido numa lingua. Sem parametro nenhum sai ingles."""
    if lingua == textos.LINGUA_POR_OMISSAO:
        return caminho
    junta = "&" if "?" in caminho else "?"
    return f"{caminho}{junta}{textos.PARAMETRO_DA_LINGUA}={lingua}"


def _numero(valor, casas, lingua):
    """O numero como a consola o escreve nessa lingua."""
    return formato.numero(valor, casas, textos.de(lingua))


# ---------------------------------------------------------------------------
# 1. Um intervalo desenha-se como intervalo, e nunca como um numero
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("lingua", AS_DUAS_LINGUAS)
def test_uma_linha_de_intervalo_mostra_se_como_intervalo(client, dados, lingua):
    """Os dois extremos, e a relacao entre eles -- nas duas linguas.

    Os numeros esperados sao pedidos ao mesmo formatador que a pagina usa, e
    nao escritos a mao: o que tem de ser verdade e que os DOIS extremos estao
    la com uma palavra pelo meio, e nao que essa palavra e « a ».
    """
    html = _pagina(client, _end(f"/console/observacoes?sitio={SITIO}", lingua))
    celula = _celula(html, dados["linhas"]["ph_screening"].id, "valor")
    assert 'data-forma="intervalo"' in _linha(html, dados["linhas"]["ph_screening"].id)
    visivel = _texto(celula)
    assert _numero(7.0, 1, lingua) in visivel
    assert _numero(8.0, 1, lingua) in visivel
    separador = textos.de(lingua)[formato.CHAVE_DO_SEPARADOR]
    assert separador.strip() in visivel
    # e o separador esta ENTRE os dois, e nao em qualquer sitio da celula.
    assert re.search(
        rf"{re.escape(_numero(7.0, 2, lingua))}\s*{re.escape(separador.strip())}\s*"
        rf"{re.escape(_numero(8.0, 2, lingua))}",
        visivel,
    ), visivel


def test_um_intervalo_nunca_se_mostra_como_o_meio_dele(client, dados):
    """7,5 e o meio de 7,0 a 8,0, e o meio de um intervalo nao foi medido.

    O 7,5 esta de proposito nas replicas desta base de teste: se este teste
    olhasse para a pagina inteira em vez de para a celula, passava por engano no
    dia em que a celula passasse a mostrar a media.
    """
    for lingua in AS_DUAS_LINGUAS:
        html = _pagina(client, _end(f"/console/observacoes?sitio={SITIO}", lingua))
        celula = _texto(_celula(html, dados["linhas"]["ph_screening"].id, "valor"))
        assert _numero(7.5, 1, lingua) not in celula, lingua
        # e nem sequer um numero unico: a celula tem de trazer os dois extremos.
        numeros = re.findall(r"\d+[,.]\d+", celula)
        assert len(numeros) >= 2, f"a celula do intervalo tem {numeros}"


def test_o_balanco_hidrico_tambem_e_um_intervalo_e_nao_o_meio(client, dados):
    """A regra vale para o balanco hidrico, que e onde ela custa mais.

    0 a 93,12 mm tem por meio 46,56 -- um numero que se le como "quase metade do
    reservatorio" quando o que a base diz e "esta algures entre vazio e cheio".
    """
    for lingua in AS_DUAS_LINGUAS:
        html = _pagina(client, _end(f"/console/observacoes?sitio={SITIO}", lingua))
        celula = _texto(_celula(html, dados["linhas"]["soil_available_water"].id, "valor"))
        assert _numero(46.56, 2, lingua)[:3] not in celula, lingua
        assert _numero(93.121741771698, 2, lingua) in celula, lingua


def test_a_banda_de_um_intervalo_desenha_o_intervalo_inteiro(client, dados):
    """A barra e o segundo sitio onde a regra do intervalo pode ser quebrada.

    Uma barra que fosse do zero ate ao meio do intervalo dizia, em geometria,
    exactamente a coisa que o texto tem proibido dizer. O balanco hidrico desta
    linha vai de 0 a 93,12 mm num reservatorio de 100 mm: a banda tem de cobrir
    a distancia toda, e nao parar nos 46,6% do meio.
    """
    html = _pagina(client, f"/console/observacoes?sitio={SITIO}")
    celula = _celula(html, dados["linhas"]["soil_available_water"].id, "valor")
    banda = re.search(r'<i [^>]*style="left: ([\d.]+)%; width: ([\d.]+)%', celula)
    assert banda, "a linha de intervalo nao tem banda nenhuma"
    inicio, largura = float(banda.group(1)), float(banda.group(2))
    assert inicio == pytest.approx(0.0, abs=0.5)
    assert largura == pytest.approx(93.1, abs=0.5)


def test_uma_metrica_sem_dominio_nao_ganha_barra_nenhuma(client, dados):
    """Uma barra desenha um eixo, e um eixo e uma afirmacao.

    Nada neste projecto diz onde fica o "meio" de uma temperatura do ar, e por
    isso nao ha barra nenhuma nessa linha. E o controlo negativo do teste
    acima: sem ele, uma barra desenhada em tudo passava por lá.
    """
    html = _pagina(client, f"/console/observacoes?sitio={SITIO}")
    celula = _celula(html, dados["linhas"]["air_temperature"].id, "valor")
    assert "barra" not in celula


@pytest.mark.parametrize("lingua", AS_DUAS_LINGUAS)
def test_o_formatador_recusa_se_a_devolver_um_escalar_para_um_intervalo(lingua):
    """A guarda, na unidade: nao ha caminho por onde um `range` saia um numero."""
    da_lingua = textos.de(lingua)
    apresentado = formato.apresentar_valor({
        "value_numeric": None, "value_min": 7.0, "value_max": 8.0,
        "value_qualifier": "range", "value_text": None, "unit": "pH",
    }, da_lingua)
    assert apresentado.forma == "intervalo"
    assert apresentado.texto == (
        f"{_numero(7.0, 2, lingua)}{da_lingua[formato.CHAVE_DO_SEPARADOR]}"
        f"{_numero(8.0, 2, lingua)}"
    )
    # ⚠️ A `forma` NAO se traduz: e ela que a folha de estilo le.
    assert apresentado.forma == formato.apresentar_valor({
        "value_numeric": None, "value_min": 7.0, "value_max": 8.0,
        "value_qualifier": "range", "value_text": None, "unit": "pH",
    }, textos.de("en")).forma


# ---------------------------------------------------------------------------
# 2. Uma leitura saturada mostra-se como >= valor, nunca como o valor
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("lingua", AS_DUAS_LINGUAS)
def test_uma_leitura_saturada_mostra_se_como_maior_ou_igual(client, dados, lingua):
    html = _pagina(client, _end(f"/console/observacoes?sitio={SITIO}", lingua))
    celula = _texto(_celula(html, dados["linhas"]["light_screening"].id, "valor"))
    assert formato.MAIOR_OU_IGUAL in celula
    assert _numero(2000.0, 2, lingua) in celula


def test_uma_leitura_saturada_nunca_se_mostra_como_o_valor(client, dados):
    """O numero sozinho seria uma medida, e nao e: e um limite inferior.

    Mede-se pelo que fica na celula depois de tirar o simbolo -- se o `>=` cair,
    o que sobra e exactamente o numero cru, e e isso que este teste recusa.
    """
    for lingua in AS_DUAS_LINGUAS:
        html = _pagina(client, _end(f"/console/observacoes?sitio={SITIO}", lingua))
        celula = _texto(_celula(html, dados["linhas"]["light_screening"].id, "valor"))
        numero = re.search(re.escape(_numero(2000.0, 0, lingua)), celula)
        assert numero, f"o valor desapareceu da celula em {lingua}"
        antes = celula[: numero.start()]
        assert formato.MAIOR_OU_IGUAL in antes, "o numero aparece sem o simbolo a frente"


@pytest.mark.parametrize("lingua", AS_DUAS_LINGUAS)
def test_o_formatador_censura_nos_dois_sentidos(lingua):
    da_lingua = textos.de(lingua)
    alto = formato.apresentar_valor({
        "value_numeric": 2000.0, "value_min": None, "value_max": None,
        "value_qualifier": "censored_high", "value_text": None, "unit": "instrument_scale",
    }, da_lingua)
    baixo = formato.apresentar_valor({
        "value_numeric": 5.0, "value_min": None, "value_max": None,
        "value_qualifier": "censored_low", "value_text": None, "unit": "instrument_scale",
    }, da_lingua)
    assert alto.texto.startswith(formato.MAIOR_OU_IGUAL)
    assert baixo.texto.startswith(formato.MENOR_OU_IGUAL)
    assert alto.forma == "censurado_alto"


# ---------------------------------------------------------------------------
# 3. Uma linha sem proveniencia estruturada di-lo
# ---------------------------------------------------------------------------

def test_uma_linha_sem_proveniencia_estruturada_di_lo(client, dados):
    """As leituras de campo foram gravadas antes de o campo existir.

    Um painel vazio le-se como "nao ha nada a dizer", que e o contrario da
    verdade. Tem de dizer que falta, e porque falta.
    """
    identificador = dados["linhas"]["ph_screening"].id
    for lingua in AS_DUAS_LINGUAS:
        da_lingua = textos.de(lingua)
        html = _pagina(
            client, _end(f"/console/observacoes?sitio={SITIO}&linha={identificador}", lingua)
        )
        painel = re.search(r'<aside class="proveniencia".*?</aside>', html, re.S)
        assert painel, "a pagina nao trouxe o painel de proveniencia"
        texto = _texto(painel.group(0))
        assert da_lingua["prov.sem_proveniencia"] in texto, lingua
        # e nao e um painel vazio: diz PORQUE falta, e mostra o que a linha tem.
        assert da_lingua["prov.porque_falta"] in texto, lingua
        assert "manual_screening" in texto, lingua


def test_uma_linha_com_proveniencia_estruturada_mostra_a(client, dados):
    """O controlo negativo do teste anterior.

    Sem ele, um painel que dissesse "sem proveniencia estruturada" a TODAS as
    linhas passava no teste de cima.
    """
    identificador = dados["linhas"]["soil_moisture_screening"].id
    for lingua in AS_DUAS_LINGUAS:
        da_lingua = textos.de(lingua)
        html = _pagina(
            client, _end(f"/console/observacoes?sitio={SITIO}&linha={identificador}", lingua)
        )
        painel = re.search(r'<aside class="proveniencia".*?</aside>', html, re.S)
        texto = _texto(painel.group(0))
        assert da_lingua["prov.sem_proveniencia"] not in texto, lingua
        assert da_lingua["prov.porque_falta"] not in texto, lingua
        assert _numero(7.5, 2, lingua) in texto, "as replicas nao aparecem"


def test_o_painel_de_reanalise_traz_a_distancia_e_o_tamanho_da_celula(client, dados):
    """Distancias e o tamanho da celula podem aparecer -- e sao o que interessa."""
    identificador = dados["linhas"]["air_temperature"].id
    for lingua in AS_DUAS_LINGUAS:
        html = _pagina(
            client, _end(f"/console/observacoes?sitio={SITIO}&linha={identificador}", lingua)
        )
        texto = _texto(re.search(r'<aside class="proveniencia".*?</aside>', html, re.S).group(0))
        assert _numero(5.3412, 2, lingua) in texto, lingua
        assert _numero(11.11950802335329, 2, lingua) in texto, lingua


# ---------------------------------------------------------------------------
# 4. A origem tramada distingue-se da solida por outra coisa alem da cor
# ---------------------------------------------------------------------------

def test_a_origem_tramada_diz_se_por_escrito(client, dados):
    """Primeiro canal: palavras. Le-se sem cor nenhuma, e ate sem folha de estilo."""
    for lingua in AS_DUAS_LINGUAS:
        da_lingua = textos.de(lingua)
        html = _pagina(client, _end(f"/console/observacoes?sitio={SITIO}", lingua))
        fora = _texto(_celula(html, dados["linhas"]["air_temperature"].id, "origem"))
        dentro = _texto(_celula(html, dados["linhas"]["soil_moisture_screening"].id, "origem"))
        # A propriedade e a DISTINCAO: as duas celulas nao podem dizer o mesmo,
        # e a que nao foi medida aqui tem de o negar.
        assert da_lingua["valor.fora_da_parcela"] in fora, lingua
        assert da_lingua["valor.na_parcela"] in dentro, lingua
        assert da_lingua["valor.fora_da_parcela"] not in dentro, lingua
        assert fora.strip() != dentro.strip(), lingua


def test_a_origem_tramada_marca_se_na_propria_linha(client, dados):
    """Segundo canal: um atributo na linha, que a folha de estilo usa para a trama."""
    html = _pagina(client, f"/console/observacoes?sitio={SITIO}")
    assert 'data-parcela="nao"' in _linha(html, dados["linhas"]["air_temperature"].id)
    assert 'data-parcela="sim"' in _linha(html, dados["linhas"]["soil_moisture_screening"].id)


def test_a_trama_e_um_padrao_e_nao_uma_cor():
    """Terceiro canal, e o que decide: a folha de estilo desenha uma trama.

    A prova nao e "existe uma regra diferente" -- duas regras podem diferir so
    na cor. E que, **tirando todas as declaracoes de cor das duas**, elas
    continuam a ser diferentes. O que sobra e geometria.
    """
    solida = _regra(FOLHA_DE_ESTILO, r"^\.marca$")
    tramada = _regra(FOLHA_DE_ESTILO, r'^\[data-parcela="nao"\] \.marca$')
    assert "repeating-linear-gradient" in tramada
    assert "repeating-linear-gradient" not in solida
    assert _sem_cor(tramada) != _sem_cor(solida)
    assert _sem_cor(tramada) != "", "a trama vive so na cor"


def _regra(folha: str, padrao: str) -> str:
    """O corpo da primeira regra CSS cujo selector case com `padrao`.

    O selector e a ultima linha do que vem antes da chaveta: o que a apanha
    antes disso sao comentarios e linhas em branco da regra anterior.
    """
    for selector, corpo in re.findall(r"([^{}]+)\{([^{}]*)\}", folha):
        limpo = selector.strip().splitlines()[-1].strip()
        if re.search(padrao, limpo):
            return corpo
    raise AssertionError(f"nenhuma regra casa com {padrao}")


def _sem_cor(corpo: str) -> str:
    """O corpo da regra sem uma unica declaracao de cor."""
    sobra = []
    for declaracao in corpo.split(";"):
        if not declaracao.strip():
            continue
        propriedade = declaracao.split(":", 1)[0].strip()
        if propriedade in {"color", "background", "background-color", "border-color", "fill"}:
            continue
        sobra.append(re.sub(r"(var\(--[\w-]+\)|#[0-9a-fA-F]{3,8}|rgba?\([^)]*\))", "", declaracao))
    return ";".join(parte.strip() for parte in sobra if parte.strip())


# ---------------------------------------------------------------------------
# A chave, e as coordenadas
# ---------------------------------------------------------------------------

CAMINHOS_DA_CONSOLA = [
    "/console",
    "/console/observacoes",
    "/console/sincronizacoes",
    "/console/sitios",
    "/console/estilo.css",
]


@pytest.mark.parametrize("caminho", CAMINHOS_DA_CONSOLA)
def test_a_chave_nao_aparece_em_nada_do_que_o_navegador_recebe(cliente_sem_chave, dados, caminho):
    resposta = cliente_sem_chave.get(caminho)
    assert resposta.status_code == 200, caminho
    assert CHAVE_DE_ESCRITA_DOS_TESTES not in resposta.text
    for nome, valor in resposta.headers.items():
        assert CHAVE_DE_ESCRITA_DOS_TESTES not in valor, nome


@pytest.mark.parametrize("caminho", CAMINHOS_DA_CONSOLA)
def test_nenhuma_pagina_da_consola_pede_a_chave_da_api(cliente_sem_chave, dados, caminho):
    """Quem passa a porta da consola nao precisa da chave DA API.

    ⚠️ O nome deste teste mudou a 31/08 a noite, e a mudanca nao e cosmetica.
    Chamava-se «nao pede credencial» e isso deixou de ser verdade: a consola
    passou a ter uma senha a porta (`api/console_auth.py`), e o
    `cliente_sem_chave` apresenta-a. O que continua verdade -- e e o que este
    teste mede -- e que o navegador nao tem de apresentar a chave da API, que e
    a razao de a camada existir. A porta esta medida em
    `tests/test_console_auth.py`.
    """
    assert cliente_sem_chave.get(caminho).status_code == 200


def test_o_piso_dos_caminhos_da_consola():
    """Um inventario vazio faria os dois testes acima passarem sem correr nada."""
    assert len(CAMINHOS_DA_CONSOLA) == 5


def test_a_consola_nao_serve_coordenadas_de_parcela(cliente_sem_chave, dados):
    """⛔ Os poligonos estao num repositorio privado desde 31/08.

    Distancias e o tamanho da celula podem; centroides e geometrias nao.
    """
    proibidos = [
        str(LATITUDE), str(LONGITUDE), "39.0373", "-9.2402", "39.048545",
        "39.0385", "-9.2255",
    ]
    for caminho in CAMINHOS_DA_CONSOLA:
        corpo = cliente_sem_chave.get(caminho).text
        for numero in proibidos:
            assert numero not in corpo, f"{numero} saiu em {caminho}"
    identificador = dados["linhas"]["air_temperature"].id
    corpo = cliente_sem_chave.get(f"/console/observacoes?sitio={SITIO}&linha={identificador}").text
    for numero in proibidos:
        assert numero not in corpo, f"{numero} saiu no painel de proveniencia"


def test_a_camada_retem_as_coordenadas_de_dentro_da_evidencia(cliente_sem_chave, dados):
    """A camada corta, e por isso a consola nunca chega a ve-las.

    O corte esta na camada e nao na pagina de proposito: e a camada que esta
    entre o navegador e a API, e o apanha-tudo dela serve esta mesma rota.
    """
    corpo = cliente_sem_chave.get(f"/console/api/v1/sites/{SITIO}/observations").json()
    linha = next(r for r in corpo["rows"] if r["source_type"] == "reanalysis")
    assert linha["evidence"]["site_lat"] == console.MARCA_DE_COORDENADA
    assert linha["evidence"]["cell_lon"] == console.MARCA_DE_COORDENADA
    assert linha["evidence"]["area_aoi"] == console.MARCA_DE_COORDENADA
    # e o que nao e coordenada continua a passar, que e metade do ponto.
    assert linha["evidence"]["distance_km"] == pytest.approx(5.3412)
    assert linha["evidence"]["cell_size_km_ns"] == pytest.approx(11.11950802335329)


def test_a_camada_retem_uma_coordenada_escrita_dentro_de_um_texto(cliente_sem_chave, dados):
    """A nota de uma AOI traz o centroide escrito no meio de uma frase.

    Nao tem forma de GeoJSON nenhum, e por isso o corte da Task 1 nao lhe tocava.
    """
    corpo = cliente_sem_chave.get(f"/console/api/v1/sites/{SITIO}/aois").json()
    nota = corpo[0]["geometry_source_note"]
    assert str(LATITUDE) not in nota
    # e o par escrito com menos casas tambem nao, que e a metade da regra que a
    # outra metade tapava.
    assert PAR_CURTO not in nota
    assert console.TEXTO_DE_COORDENADA_RETIDA in nota
    # o resto da frase fica: e ela que diz de onde veio o contorno.
    assert "2,5 x 2,5 km" in nota


def test_controlo_a_api_devolve_mesmo_as_coordenadas(client, dados):
    """O controlo negativo dos dois testes acima.

    Sem ele, os dois passavam no dia em que a API deixasse de gravar `site_lat`
    -- e passavam por a fonte da fuga ter desaparecido, nao por a camada cortar.
    """
    corpo = client.get(f"/api/v1/sites/{SITIO}/observations").json()
    linha = next(r for r in corpo["rows"] if r["source_type"] == "reanalysis")
    assert linha["evidence"]["site_lat"] == pytest.approx(LATITUDE)
    nota = client.get(f"/api/v1/sites/{SITIO}/aois").json()[0]["geometry_source_note"]
    assert str(LATITUDE) in nota


# ---------------------------------------------------------------------------
# Encaminhamento: a pagina tem de ganhar ao apanha-tudo da camada
# ---------------------------------------------------------------------------

def test_a_pagina_da_consola_ganha_ao_apanha_tudo(cliente_sem_chave, dados):
    """⚠️ `/console/{caminho:path}` apanha tudo o que esteja sob `/console`.

    Registado antes das paginas, ele responde-lhes 404 em JSON. E a preocupacao
    4 do relatorio da Task 1, e e aqui que uma troca de ordem no `main.py` cai.
    """
    resposta = cliente_sem_chave.get("/console/observacoes")
    assert resposta.headers["content-type"].startswith("text/html")
    assert console.RECUSA_DE_ROTA not in resposta.text


def test_o_apanha_tudo_continua_a_servir_as_leituras(cliente_sem_chave, dados):
    """O outro lado: registar as paginas antes nao pode tapar a camada."""
    resposta = cliente_sem_chave.get("/console/api/v1/sites")
    assert resposta.status_code == 200
    assert resposta.headers["content-type"].startswith("application/json")
    assert any(sitio["code"] == SITIO for sitio in resposta.json())


def test_a_consola_nao_corre_javascript(cliente_sem_chave, dados):
    """Nao ha script nenhum, e por isso nao ha script que possa ir buscar a chave.

    E tambem a razao de a consola ser desenhada no servidor: o que o navegador
    recebe e o que se ve, e o que se ve foi filtrado antes de sair.
    """
    for caminho in CAMINHOS_DA_CONSOLA:
        corpo = cliente_sem_chave.get(caminho).text
        assert "<script" not in corpo.lower(), caminho
        assert "javascript:" not in corpo.lower(), caminho


def test_a_consola_nao_carrega_nada_de_fora(cliente_sem_chave, dados):
    """O contentor pode nao ter saida para a internet, e nao precisa de ter.

    Mede-se sobre as REFERENCIAS a recursos, e nao sobre o texto: o painel de
    proveniencia mostra legitimamente o endereco de onde o IPMA foi lido, como
    texto que ninguem vai buscar.
    """
    for caminho in CAMINHOS_DA_CONSOLA:
        corpo = cliente_sem_chave.get(caminho).text
        for referencia in re.findall(r'(?:src|href)="([^"]*)"', corpo):
            assert not referencia.startswith(("http://", "https://", "//")), \
                f"{caminho} vai buscar {referencia}"
        assert "@import" not in corpo, caminho
        for alvo in re.findall(r"url\(([^)]*)\)", corpo):
            assert not alvo.strip("\"' ").startswith(("http", "//")), f"{caminho}: {alvo}"


# ---------------------------------------------------------------------------
# As tres vistas
# ---------------------------------------------------------------------------

def test_a_vista_das_observacoes_filtra_por_sitio_metrica_e_origem(client, dados):
    todas = _pagina(client, f"/console/observacoes?sitio={SITIO}")
    assert 'data-linha="' in todas
    so_reanalise = _pagina(client, f"/console/observacoes?sitio={SITIO}&origem=reanalysis")
    assert str(dados["linhas"]["air_temperature"].id) in so_reanalise
    assert str(dados["linhas"]["ndvi"].id) not in so_reanalise
    so_ndvi = _pagina(client, f"/console/observacoes?sitio={SITIO}&metrica=ndvi")
    assert str(dados["linhas"]["ndvi"].id) in so_ndvi
    assert str(dados["linhas"]["air_temperature"].id) not in so_ndvi


def test_os_filtros_vem_da_api_e_nao_de_uma_lista_dentro_da_pagina(client, dados):
    """As opcoes sao as metricas que este sitio tem, e nao uma lista escrita a mao.

    O sitio desta suite tem metricas que a base de producao nao tem; se as
    opcoes viessem de uma constante, este teste caia.
    """
    html = _pagina(client, f"/console/observacoes?sitio={SITIO}")
    opcoes = set(re.findall(r'<option value="([^"]*)"', html))
    assert {"ph_screening", "light_screening", "ndvi", "soil_available_water"} <= opcoes


def test_o_inventario_de_metricas_nao_encolhe_com_o_filtro(client, dados):
    """Filtrar por uma metrica nao pode fazer as outras desaparecerem do filtro.

    Um filtro que se apague a si proprio deixa quem o usa preso na escolha que
    fez -- e nao ha caminho de volta sem editar o endereco a mao.
    """
    html = _pagina(client, f"/console/observacoes?sitio={SITIO}&metrica=ndvi")
    opcoes = set(re.findall(r'<option value="([^"]*)"', html))
    assert "ph_screening" in opcoes


def test_a_vista_das_sincronizacoes_mostra_o_que_falhou_e_porque(client, dados):
    html = _pagina(client, "/console/sincronizacoes")
    texto = _texto(html)
    assert "A colheita do Copernicus devolveu 401." in texto
    assert "failed" in texto


def test_a_vista_das_sincronizacoes_separa_a_janela_pedida_da_coberta(client, dados):
    """Duas janelas, e nunca uma so.

    Sem o par, a execucao tem sempre razao: os dois lados da comparacao saem
    dela propria. Foi assim que dois jobs `succeeded` esconderam a perda de 96%
    da serie a 29/08.
    """
    for lingua in AS_DUAS_LINGUAS:
        da_lingua = textos.de(lingua)
        html = _pagina(client, _end("/console/sincronizacoes", lingua))
        linha = re.search(
            r'<tr class="linha"[^>]*data-execucao="reanalysis_sync".*?</tr>', html, re.S
        )
        assert linha, "a execucao de reanalise nao esta na pagina"
        texto = _texto(linha.group(0))
        assert da_lingua["sinc.janela.pedida"] in texto, lingua
        assert da_lingua["sinc.janela.coberta"] in texto, lingua
        # ⭐ E as duas datas de fim sao DIFERENTES. E o que o par existe para
        # mostrar: sem ele, a execucao tem sempre razao porque os dois lados da
        # comparacao saem dela propria.
        pedido = marcacao.dia("2026-09-29", da_lingua)
        coberto = marcacao.dia("2026-08-02", da_lingua)
        assert pedido != coberto
        assert pedido in texto, "a janela pedida nao aparece"
        assert coberto in texto, "a janela coberta nao aparece"


def test_a_vista_das_sincronizacoes_conta_os_dias_por_cobrir_sem_os_julgar(client, dados):
    """A contagem e um numero, e nao um veredicto -- o limiar e de quem le."""
    html = _pagina(client, "/console/sincronizacoes")
    linha = re.search(r'<tr class="linha"[^>]*data-execucao="reanalysis_sync".*?</tr>', html, re.S)
    assert "58" in _texto(linha.group(0))


def test_a_vista_dos_sitios_mostra_as_areas_de_interesse_e_o_que_cada_uma_tem(client, dados):
    html = _pagina(client, "/console/sitios")
    texto = _texto(html)
    assert SITIO in texto
    assert "EUC-CON-EO1" in texto
    assert "surveyed" in texto
    assert "approved" in texto
    assert "CON-GRASS" in texto
    # o inventario do sitio: que metricas tem, e de que origens.
    assert "ph_screening" in texto
    assert "soil_available_water" in texto


def test_a_vista_dos_sitios_mostra_a_area_mas_nunca_o_contorno(client, dados):
    html = _pagina(client, "/console/sitios")
    assert "m²" in html
    assert "coordinates" not in html
    assert "Polygon" not in html


# ---------------------------------------------------------------------------
# As regras de cor, de tema e de movimento
# ---------------------------------------------------------------------------

def _canal(cor: str) -> tuple[int, int, int]:
    cor = cor.lstrip("#")
    return tuple(int(cor[i:i + 2], 16) for i in (0, 2, 4))


def _croma(cor: str) -> int:
    """A distancia entre o canal mais alto e o mais baixo, em 0-255.

    Usa-se isto e nao a saturacao HSL de proposito: a saturacao HSL de um
    cinzento quase branco dispara para valores altos por causa do denominador,
    e um teste que a usasse recusava a moldura inteira sem nenhuma cor existir.
    """
    canais = _canal(cor)
    return max(canais) - min(canais)


def _matiz(cor: str) -> float:
    vermelho, verde, azul = (canal / 255 for canal in _canal(cor))
    alto, baixo = max(vermelho, verde, azul), min(vermelho, verde, azul)
    if alto == baixo:
        return 0.0
    amplitude = alto - baixo
    if alto == vermelho:
        return (60 * ((verde - azul) / amplitude)) % 360
    if alto == verde:
        return 60 * (2 + (azul - vermelho) / amplitude)
    return 60 * (4 + (vermelho - verde) / amplitude)


def test_a_moldura_e_neutra_e_fria():
    """A cor esta so nos dados. A moldura nao tem saturacao nenhuma."""
    for nome, cor in paleta.MOLDURA_CLARA.items():
        assert _croma(cor) <= paleta.CROMA_MAXIMO_DA_MOLDURA, f"{nome} tem cor a mais: {cor}"
    for nome, cor in paleta.MOLDURA_ESCURA.items():
        assert _croma(cor) <= paleta.CROMA_MAXIMO_DA_MOLDURA, f"{nome} tem cor a mais: {cor}"


def test_a_proveniencia_esta_na_matiz_10yr_nos_dois_temas():
    """O hue que a pedologia usa para descrever solo, e ele nao muda com o tema.

    O que muda e o valor (a claridade), porque a leitura depende do contraste
    com o fundo -- e num fundo escuro a ordem tem de ser lida ao contrario.
    """
    for rampa in (paleta.PROVENIENCIA_CLARA, paleta.PROVENIENCIA_ESCURA):
        assert set(rampa) == set(SourceType), "falta uma origem na rampa"
        for origem, cor in rampa.items():
            assert paleta.MATIZ_10YR[0] <= _matiz(cor) <= paleta.MATIZ_10YR[1], f"{origem}: {cor}"


def test_a_proveniencia_ordena_se_por_contraste_nos_dois_temas():
    """Quanto mais directa a medicao, mais contraste tem contra o fundo."""
    for rampa, fundo in (
        (paleta.PROVENIENCIA_CLARA, paleta.MOLDURA_CLARA["superficie"]),
        (paleta.PROVENIENCIA_ESCURA, paleta.MOLDURA_ESCURA["superficie"]),
    ):
        claridade_do_fundo = sum(_canal(fundo)) / 3
        distancias = [
            abs(sum(_canal(rampa[origem])) / 3 - claridade_do_fundo)
            for origem in paleta.ORDEM_DA_PROVENIENCIA
        ]
        assert distancias == sorted(distancias, reverse=True), distancias


def test_nenhuma_rampa_e_um_arco_iris():
    """⛔ Nunca arco-iris.

    Um arco-iris percorre a roda das cores toda e inverte o sentido pelo
    caminho; uma rampa honesta anda numa direccao so, entre dois ancoradouros.
    """
    for nome, rampa in paleta.RAMPAS_DE_VALOR.items():
        matizes = [_matiz(cor) for cor in rampa]
        assert matizes == sorted(matizes) or matizes == sorted(matizes, reverse=True), \
            f"{nome} inverte o sentido: {matizes}"
        assert abs(matizes[-1] - matizes[0]) < paleta.PERCURSO_MAXIMO_DE_MATIZ, \
            f"{nome} percorre {abs(matizes[-1] - matizes[0]):.0f} graus"


def test_o_tema_escuro_redefine_todos_os_tokens_do_claro():
    """Uma consola que so existe em escuro (ou em claro) nao e seria."""
    claros = set(re.findall(r"(--[\w-]+)\s*:", _regra(FOLHA_DE_ESTILO, r"^:root$")))
    escuros = set(re.findall(r"(--[\w-]+)\s*:", _bloco(FOLHA_DE_ESTILO, "prefers-color-scheme: dark")))
    assert claros, "nao ha tokens nenhuns"
    assert len(claros) > len(paleta.TOKENS_SEM_TEMA), "so ha tokens isentos"
    assert claros - paleta.TOKENS_SEM_TEMA <= escuros, sorted(claros - paleta.TOKENS_SEM_TEMA - escuros)


def _bloco(folha: str, marcador: str) -> str:
    """O bloco `@media` que contem `marcador`, com as chavetas equilibradas."""
    inicio = folha.index(marcador)
    abertura = folha.index("{", inicio)
    profundidade = 0
    for posicao in range(abertura, len(folha)):
        if folha[posicao] == "{":
            profundidade += 1
        elif folha[posicao] == "}":
            profundidade -= 1
            if profundidade == 0:
                return folha[inicio:posicao + 1]
    raise AssertionError(f"o bloco de {marcador} nao fecha")


def test_toda_a_animacao_respeita_quem_pediu_menos_movimento():
    """Regra da casa: animacao sem esta guarda e um defeito de acessibilidade."""
    guarda = "prefers-reduced-motion: no-preference"
    fora_da_guarda = FOLHA_DE_ESTILO.replace(_bloco(FOLHA_DE_ESTILO, guarda), "")
    assert "transition:" not in fora_da_guarda
    assert "animation:" not in fora_da_guarda
    assert "@keyframes" not in fora_da_guarda
    # e o controlo: dentro da guarda ha mesmo movimento, senao o teste era vazio.
    assert "transition:" in FOLHA_DE_ESTILO
    assert "animation:" in FOLHA_DE_ESTILO


# ---------------------------------------------------------------------------
# Numeros em portugues de Portugal
# ---------------------------------------------------------------------------

def test_os_numeros_escrevem_se_em_portugues_de_portugal():
    """Virgula decimal, e espaco insecavel nos milhares."""
    portugues = textos.de("pt")
    assert formato.numero(1234.5, 1, portugues) == "1\u00a0234,5"
    assert formato.numero(7.0, 1, portugues) == "7,0"
    assert formato.numero(2000.0, 0, portugues) == "2\u00a0000"
    assert "." not in formato.numero(1234567.25, 2, portugues)
    # o separador e insecavel: um numero partido por uma mudanca de linha deixa
    # de ser um numero.
    assert "\u00a0" in formato.numero(1234.5, 1, portugues)


def test_os_numeros_em_ingles_levam_ponto_decimal():
    """A marca decimal muda com a lingua; o separador de milhares nao.

    O ponto nos milhares nao e usado em lingua nenhuma desta consola: `1.234`
    le-se como mil duzentos de um lado e como um virgula dois do outro, e o
    espaco insecavel e o que a escrita cientifica recomenda para os dois.
    """
    ingles = textos.de("en")
    assert formato.numero(1234.5, 1, ingles) == "1\u00a0234.5"
    assert formato.numero(2000.0, 2, ingles) == "2\u00a0000.00"
    assert "," not in formato.numero(1234567.25, 2, ingles)
    assert "\u00a0" in formato.numero(1234.5, 1, ingles)


def test_sem_lingua_nenhuma_o_numero_sai_na_lingua_por_omissao():
    """O piso: `numero()` sem `textos` nao pode cair no portugues por acidente."""
    assert formato.numero(1234.5, 1) == formato.numero(
        1234.5, 1, textos.de(textos.LINGUA_POR_OMISSAO)
    )
    assert formato.numero(1234.5, 1) == "1\u00a0234.5"


def test_a_ordem_das_origens_cobre_o_enum_inteiro():
    """Piso: uma ordem parcial faria os testes da rampa medirem meia rampa."""
    assert set(paleta.ORDEM_DA_PROVENIENCIA) == set(SourceType)
    assert len(paleta.ORDEM_DA_PROVENIENCIA) == len(SourceType)


def test_medido_na_parcela_le_se_da_evidencia_antes_de_se_deduzir():
    """A linha diz de si propria; a deducao pela origem e so o que resta.

    `measured_at_site` existe exactamente para isto -- para nao ser preciso
    interpretar distancias -- e por isso ganha a qualquer regra sobre origens.
    """
    assert formato.medido_na_parcela({
        "source_type": "observed_screening", "evidence": {"measured_at_site": False},
    }) is False
    assert formato.medido_na_parcela({"source_type": "observed_screening", "evidence": None}) is True
    assert formato.medido_na_parcela({"source_type": "reanalysis", "evidence": None}) is False


def test_uma_evidencia_retida_nao_se_le_como_um_valor(client, dados):
    """O que a camada reteve aparece como retido, e nao como um campo em falta."""
    identificador = dados["linhas"]["air_temperature"].id
    for lingua in AS_DUAS_LINGUAS:
        da_lingua = textos.de(lingua)
        html = _pagina(
            client, _end(f"/console/observacoes?sitio={SITIO}&linha={identificador}", lingua)
        )
        painel = _texto(re.search(r'<aside class="proveniencia".*?</aside>', html, re.S).group(0))
        assert da_lingua["prov.retido.coordinate"] in painel, lingua
        # e nao se le como um campo em falta: as duas frases sao diferentes.
        assert da_lingua["prov.retido.coordinate"] != da_lingua["prov.nao_registado"]


@pytest.fixture
def sem_segredo(monkeypatch):
    """A instalação a que o segredo nunca chegou: a API responde 503 a tudo.

    É a falha de operação mais provável desta arquitectura -- o segredo não
    chega ao contentor -- e a que a consola tem de saber dizer.
    """
    monkeypatch.setenv("WRITE_API_KEY", "")
    get_settings.cache_clear()
    yield
    monkeypatch.undo()
    get_settings.cache_clear()


@pytest.mark.parametrize("caminho", [c for c in CAMINHOS_DA_CONSOLA if not c.endswith(".css")])
def test_uma_leitura_que_falha_di_lo_em_vez_de_parecer_vazia(cliente_sem_chave, dados, sem_segredo, caminho):
    """⚠️ Vazio e ilegível são duas coisas, e confundi-las é mentir.

    Sem esta guarda, uma API a responder 503 produzia uma tabela vazia com a
    legenda «nenhuma observação corresponde a este filtro»: a página afirmava
    que a base está vazia quando o que se passa é que ninguém conseguiu ler.
    """
    for lingua in AS_DUAS_LINGUAS:
        resposta = cliente_sem_chave.get(_end(caminho, lingua))
        assert resposta.status_code == 200
        assert textos.de(lingua)["falha.titulo"] in resposta.text, (caminho, lingua)
        assert "503" in resposta.text


def test_o_controlo_a_pagina_que_leu_tudo_nao_grita(client, dados):
    """O controlo negativo do teste acima.

    Sem ele, um aviso posto em todas as páginas passava lá.
    """
    for caminho in ("/console/observacoes", "/console/sincronizacoes", "/console/sitios"):
        for lingua in AS_DUAS_LINGUAS:
            pagina = _pagina(client, _end(caminho, lingua))
            assert textos.de(lingua)["falha.titulo"] not in pagina, (caminho, lingua)


def test_uma_metrica_ou_um_sitio_que_nao_existem_nao_rebentam(client, dados):
    """O endereco e escrito a mao com facilidade, e um 500 nao explica nada."""
    resposta = client.get("/console/observacoes?sitio=NAO-EXISTE")
    assert resposta.status_code == 200
    resposta = client.get(f"/console/observacoes?sitio={SITIO}&linha={uuid.uuid4()}")
    assert resposta.status_code == 200
