"""A consola nas duas linguas: ingles por omissao, portugues a pedido.

O projecto e europeu e toda a interaccao com o consorcio e com quem avalia e em
ingles. Estes testes prendem quatro coisas, e cada uma delas ja falhou noutro
sitio deste repositorio de uma forma parecida:

1. **sem escolha nenhuma sai o ingles.** Nao "sai o que estiver configurado",
   nao "sai o que o navegador pedir": sai o ingles;
2. **a escolha e respeitada**, e sobrevive a navegar, a filtrar e a trocar de
   lingua a meio;
3. **as duas linguas tem as mesmas chaves.** Uma chave so numa lingua e uma
   frase que desaparece quando se muda de lingua, e sem este teste ninguem
   daria por isso -- o acesso cai para o ingles em silencio de proposito, para
   que a consola nao fique em branco em producao;
4. **nao sobra portugues no modo ingles.** E a guarda contra a cadeia escrita a
   mao dentro do codigo, que e o defeito que esta traducao mais podia produzir.

⚠️ Os textos esperados sao lidos da MESMA tabela que a pagina usa, e nunca
escritos a mao aqui. Um teste que afirme uma cadeia exacta parte-se a cada
retoque de redaccao; o que estes afirmam e que a distincao esta visivel, que as
duas linguas se distinguem uma da outra, e que nenhuma delas tem buracos.
"""

import re
from datetime import datetime, timedelta, timezone

import pytest

from resoiltwin.console import formato, marcacao, textos
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

SITIO = "EUC-LIN-01"

# ⛔ Um quadrado inventado, e nao o de nenhuma parcela. Estes testes precisam de
# uma geometria valida e de mais nada -- o que medem e texto --, e a coordenada
# de uma parcela nao se escreve num sitio onde nao faz falta nenhuma.
QUADRADO = {
    "type": "Polygon",
    "coordinates": [[
        [0.0001, 0.0001], [0.0003, 0.0001],
        [0.0003, 0.0003], [0.0001, 0.0003], [0.0001, 0.0001],
    ]],
}

AS_VISTAS = ("/console/observacoes", "/console/sincronizacoes", "/console/sitios")


def _momento(dias: int) -> datetime:
    return datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc) + timedelta(days=dias)


def _end(caminho: str, lingua: str) -> str:
    """O mesmo caminho pedido numa lingua. Sem parametro nenhum sai o ingles."""
    if lingua == textos.LINGUA_POR_OMISSAO:
        return caminho
    junta = "&" if "?" in caminho else "?"
    return f"{caminho}{junta}{textos.PARAMETRO_DA_LINGUA}={lingua}"


def _texto(html: str) -> str:
    return re.sub(r"<[^>]+>", " ", html)


@pytest.fixture
def dados(session):
    """Um sitio com material para as tres vistas escreverem tudo o que tem.

    Cada linha existe para pos uma parte do texto no ecra: a que nao tem
    evidencia acende o "sem proveniencia estruturada", a de reanalise acende o
    "fora da parcela" e os rotulos da evidencia, e a execucao com janela pedida
    acende as duas janelas e o veredicto.
    """
    sitio = Site(
        code=SITIO, name="Sitio da lingua", crop_type="citrus",
        timezone="Europe/Lisbon", notes="Nota do sitio.",
    )
    aoi = Aoi(
        site=sitio, code="EUC-LIN-EO1", purpose="earth_observation",
        geometry=geojson_to_wkt_element(QUADRADO),
        geometry_provenance=GeometryProvenance.surveyed,
        geometry_source_note="Contorno levantado no terreno.",
        status=AoiStatus.approved, approved_by="Talys Cordeiro",
    )
    parcela = Plot(site=sitio, code="LIN-GRASS", name="Relvado", purpose="open_grass")
    session.add_all([sitio, aoi, parcela])
    session.flush()

    linhas = [
        Observation(
            site_id=sitio.id, observed_at=_momento(0), metric="ph_screening", unit="pH",
            value_min=7.0, value_max=8.0, value_qualifier=ValueQualifier.range,
            source_type=SourceType.observed_screening, quality_flag=QualityFlag.range_value,
            processing_version="manual-v1", method="manual_screening", evidence=None,
        ),
        Observation(
            site_id=sitio.id, observed_at=_momento(1), metric="air_temperature", unit="degC",
            value_numeric=22.7647338867, value_qualifier=ValueQualifier.exact,
            source_type=SourceType.reanalysis, quality_flag=QualityFlag.valid,
            processing_version="agera5-v2_0",
            source_collection="sis-agrometeorological-indicators",
            evidence={
                "aoi_code": "EUC-LIN-EO1",
                "variable": "2m_temperature",
                "distance_km": 5.3412,
                "cell_size_km_ns": 11.11950802335329,
                "measured_at_site": False,
                "determined": True,
                "window_end": None,
                "campo_que_ninguem_nomeou": 3,
            },
        ),
    ]
    session.add_all(linhas)
    session.add_all([
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
    ])
    session.commit()
    return {"linhas": {linha.metric: linha for linha in linhas}}


def _paginas(client, lingua: str, dados) -> dict[str, str]:
    """As tres vistas nessa lingua, mais o painel de uma linha escolhida."""
    caminhos = list(AS_VISTAS) + [
        f"/console/observacoes?sitio={SITIO}&linha={dados['linhas']['air_temperature'].id}",
        f"/console/observacoes?sitio={SITIO}&linha={dados['linhas']['ph_screening'].id}",
    ]
    corpos = {}
    for caminho in caminhos:
        resposta = client.get(_end(caminho, lingua))
        assert resposta.status_code == 200, (caminho, lingua, resposta.status_code)
        corpos[caminho] = resposta.text
    return corpos


# ---------------------------------------------------------------------------
# 1. Sem escolha nenhuma, a consola responde em ingles
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("caminho", AS_VISTAS)
def test_sem_escolha_nenhuma_a_consola_responde_em_ingles(client, dados, caminho):
    """⭐ Ingles por omissao. Sem `?lang=`, sem cabecalho, sem nada.

    Mede-se pelos dois canais de uma vez: o `lang` do `<html>`, que e o que o
    navegador le, e os nomes das tres vistas, que sao o que a pessoa le. Um
    deles sozinho passava com o outro errado.
    """
    html = client.get(caminho).text
    assert 'lang="en-GB"' in html
    for chave in ("nav.observacoes", "nav.sincronizacoes", "nav.sitios"):
        assert textos.INGLES[chave] in html, chave
        assert textos.PORTUGUES[chave] not in html, chave


def test_a_lingua_por_omissao_e_o_ingles():
    """O piso. Sem isto, os testes acima passavam com a omissao a ser portugues.

    ⚠️ Este teste e o unico sitio de toda a suite onde a lingua por omissao e
    afirmada e nao derivada. Todos os outros leem `LINGUA_POR_OMISSAO`, e por
    isso passariam alegremente com ela trocada.
    """
    assert textos.LINGUA_POR_OMISSAO == "en"
    assert textos.lingua_pedida(None) == "en"
    assert textos.lingua_pedida("") == "en"
    assert textos.de(None).lingua == "en"


# ---------------------------------------------------------------------------
# 2. A escolha
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("caminho", AS_VISTAS)
def test_a_escolha_da_lingua_e_respeitada(client, dados, caminho):
    """`?lang=pt` traz a pagina em portugues, e nao um pedaco dela."""
    html = client.get(_end(caminho, "pt")).text
    assert 'lang="pt-PT"' in html
    for chave in ("nav.observacoes", "nav.sincronizacoes", "nav.sitios"):
        assert textos.PORTUGUES[chave] in html, chave


def test_uma_lingua_que_nao_existe_cai_para_o_ingles(client, dados):
    """Um endereco escrito a mao nao pode derrubar a pagina nem inventar lingua."""
    for pedida in ("de", "xx", "pt-BR-nonsense-", "  "):
        resposta = client.get(f"/console/observacoes?lang={pedida}")
        assert resposta.status_code == 200, pedida
    resposta = client.get("/console/observacoes?lang=de")
    assert 'lang="en-GB"' in resposta.text


def test_a_classe_dos_textos_tambem_recusa_uma_lingua_que_nao_existe():
    """A mesma guarda um degrau abaixo, e ela precisa de ser medida a parte.

    ⚠️ `de()` ja normaliza antes de construir, e por isso nenhuma rota chega
    aqui com uma lingua estranha. Mas `Textos` e exportada, e quem a construir
    directamente amanha tem de ter a mesma rede. Sem este teste a guarda nao
    estava medida por nada -- apagava-se e nenhum teste caia --, e foi assim que
    ela apareceu como sobrevivente na primeira corrida da ronda.
    """
    estranha = textos.Textos("de")
    assert estranha.lingua == textos.LINGUA_POR_OMISSAO
    assert estranha["obs.titulo"] == textos.INGLES["obs.titulo"]
    assert estranha.etiqueta_html == textos.ETIQUETA_HTML[textos.LINGUA_POR_OMISSAO]
    assert estranha.rotulo("distance_km") == textos.ROTULOS_EM_INGLES["distance_km"]


def test_a_lingua_aceita_se_escrita_de_varias_maneiras():
    """`pt-PT`, `PT`, `pt_PT`: o que se escreve a mao raramente tem a forma exacta."""
    for escrita in ("pt", "PT", "pt-PT", "pt_pt", " pt "):
        assert textos.lingua_pedida(escrita) == "pt", escrita
    for escrita in ("en", "EN", "en-GB", "en_US"):
        assert textos.lingua_pedida(escrita) == "en", escrita


def test_a_lingua_viaja_em_todas_as_ligacoes_internas(client, dados):
    """⭐ Nao ha maneira de voltar ao ingles sem querer.

    Uma ligacao interna sem a lingua devolvia quem escolheu portugues ao ingles
    ao primeiro clique -- e a escolha existiria sem funcionar.
    """
    caminho = f"/console/observacoes?sitio={SITIO}"
    html = client.get(_end(caminho, "pt")).text
    # A troca de lingua e a unica excepcao, e tem de ser: e ela que serve para
    # SAIR do portugues, e por isso a ligacao dela nao pode levar `lang=pt`.
    sem_a_troca = re.sub(r'<nav class="lingua".*?</nav>', "", html, flags=re.S)
    ligacoes = [
        destino for destino in re.findall(r'href="([^"]*)"', sem_a_troca)
        if destino.startswith("/console") and not destino.endswith(".css")
    ]
    assert len(ligacoes) >= 4, ligacoes
    sem_lingua = [
        destino for destino in ligacoes
        if f"{textos.PARAMETRO_DA_LINGUA}=pt" not in destino
    ]
    assert not sem_lingua, sem_lingua


def test_o_formulario_dos_filtros_leva_a_lingua(client, dados):
    """⚠️ O formulario e um `GET`, e um `GET` manda os campos que tem.

    Sem um campo para a lingua, carregar em «Filtrar» em portugues devolvia
    uma pagina em ingles -- e a escolha perdia-se no gesto mais comum da vista.
    """
    html = client.get(_end(f"/console/observacoes?sitio={SITIO}", "pt")).text
    formulario = re.search(r"<form class=\"filtros\".*?</form>", html, re.S)
    assert formulario, "a vista das observacoes nao tem formulario"
    assert f'name="{textos.PARAMETRO_DA_LINGUA}" value="pt"' in formulario.group(0)
    # e em ingles nao ha campo nenhum: a lingua por omissao nao se escreve.
    em_ingles = client.get(f"/console/observacoes?sitio={SITIO}").text
    assert f'name="{textos.PARAMETRO_DA_LINGUA}"' not in em_ingles


def test_filtrar_em_portugues_devolve_uma_pagina_em_portugues(client, dados):
    """O caminho que o campo escondido do formulario existe para servir."""
    html = client.get(
        f"/console/observacoes?sitio={SITIO}&metrica=ph_screening"
        f"&{textos.PARAMETRO_DA_LINGUA}=pt"
    ).text
    assert 'lang="pt-PT"' in html
    assert textos.PORTUGUES["obs.titulo"] in html


def test_trocar_de_lingua_nao_deita_fora_o_filtro(client, dados):
    """⭐ Quem esta a ler uma tabela filtrada quer a MESMA tabela na outra lingua.

    Uma troca que perdesse o filtro obrigava a refazer a escolha toda -- e a
    comparar duas tabelas diferentes a pensar que eram a mesma.
    """
    html = client.get(f"/console/observacoes?sitio={SITIO}&metrica=ph_screening").text
    troca = re.search(r'<nav class="lingua".*?</nav>', html, re.S)
    assert troca, "a pagina nao tem a troca de lingua"
    destinos = re.findall(r'href="([^"]*)"', troca.group(0))
    para_portugues = [d for d in destinos if f"{textos.PARAMETRO_DA_LINGUA}=pt" in d]
    assert para_portugues, destinos
    assert "metrica=ph_screening" in para_portugues[0], para_portugues[0]
    assert f"sitio={SITIO}" in para_portugues[0], para_portugues[0]


def test_a_troca_de_lingua_oferece_todas_as_linguas(client, dados):
    """Piso: uma troca com uma so entrada nao e uma troca."""
    html = client.get("/console/observacoes").text
    troca = re.search(r'<nav class="lingua".*?</nav>', html, re.S).group(0)
    for lingua in textos.LINGUAS:
        assert textos.NOME_DA_LINGUA[lingua] in troca, lingua
    assert len(textos.LINGUAS) >= 2


# ---------------------------------------------------------------------------
# 3. As duas linguas tem as mesmas chaves
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("nome", sorted(textos.TABELAS))
def test_as_duas_linguas_tem_as_mesmas_chaves(nome):
    """⭐ Uma chave so numa lingua e um texto que desaparece ao mudar de lingua.

    E desaparece em SILENCIO: o acesso cai para o ingles de proposito, para que
    a consola nao fique em branco em producao por faltar uma frase. Este teste
    e a unica coisa que impede que essa rede de seguranca chegue a ser usada.
    """
    tabela = textos.TABELAS[nome]
    assert set(tabela) == set(textos.LINGUAS), nome
    referencia = set(tabela[textos.LINGUA_POR_OMISSAO])
    assert referencia, f"{nome} esta vazia"
    for lingua, valores in tabela.items():
        assert set(valores) == referencia, sorted(
            referencia.symmetric_difference(valores)
        )


@pytest.mark.parametrize("nome", sorted(textos.AJUSTES_POR_LINGUA))
def test_todas_as_linguas_tem_os_ajustes_que_a_pagina_le(nome):
    """A marca decimal, os formatos de data, a etiqueta e o nome da lingua.

    Nao sao textos, sao as outras coisas que mudam com a lingua. Uma lingua que
    faltasse a qualquer uma delas dava um `KeyError` a desenhar a pagina -- e
    isso e uma pagina de erro em vez de uma consola.
    """
    assert set(textos.AJUSTES_POR_LINGUA[nome]) == set(textos.LINGUAS), nome


def test_o_piso_das_tabelas_por_lingua():
    """Um inventario vazio faria os testes acima passarem sem medir nada."""
    assert len(textos.TABELAS) == 2
    assert len(textos.AJUSTES_POR_LINGUA) >= 5
    assert len(textos.TABELAS["textos"][textos.LINGUA_POR_OMISSAO]) >= 60
    assert len(textos.TABELAS["rotulos"][textos.LINGUA_POR_OMISSAO]) >= 40


def test_as_duas_linguas_dizem_coisas_diferentes():
    """O controlo negativo da paridade.

    Sem ele, uma "traducao" que copiasse o ingles para o portugues tinha as
    mesmas chaves, passava o teste de cima, e nao traduzia nada.
    """
    iguais = [
        chave for chave, valor in textos.INGLES.items()
        if textos.PORTUGUES[chave] == valor
    ]
    # ha coincidencias legitimas (um "{total}" isolado nao existe, mas um
    # rotulo curto pode calhar); nao podem ser a regra.
    assert len(iguais) < len(textos.INGLES) / 4, iguais


def test_uma_chave_em_falta_numa_lingua_cai_para_o_ingles(monkeypatch, caplog):
    """A rede de seguranca, posta a disparar de proposito.

    ⚠️ Isto NAO e a guarda -- a guarda e a paridade acima. Isto e o que
    acontece se ela alguma vez falhar: a frase inglesa, que e degradada mas
    verdadeira, e um erro no registo. Uma consola que existe para ser honesta
    nao pode ficar em branco por faltar uma frase.
    """
    sem_uma = dict(textos.PORTUGUES)
    del sem_uma["obs.titulo"]
    monkeypatch.setitem(textos.TABELAS["textos"], "pt", sem_uma)
    portugues = textos.de("pt")
    assert portugues["obs.titulo"] == textos.INGLES["obs.titulo"]
    assert any("obs.titulo" in registo.getMessage() for registo in caplog.records)
    # e o resto da lingua continua a ser portugues.
    assert portugues["obs.vazio"] == textos.PORTUGUES["obs.vazio"]


def test_um_rotulo_de_evidencia_que_ninguem_nomeou_aparece_pelo_nome_cru(client, dados):
    """Um campo novo tem de ser visivel antes de ser bonito.

    ⚠️ Isto vale nas duas linguas e e diferente do texto das paginas: ali uma
    chave em falta e um defeito; aqui e um campo da base que ainda ninguem
    nomeou, e escondê-lo fazia nascer campos invisiveis.
    """
    identificador = dados["linhas"]["air_temperature"].id
    for lingua in textos.LINGUAS:
        html = client.get(
            _end(f"/console/observacoes?sitio={SITIO}&linha={identificador}", lingua)
        ).text
        assert "campo_que_ninguem_nomeou" in html, lingua
        assert textos.de(lingua).rotulo("campo_que_ninguem_nomeou") == "campo_que_ninguem_nomeou"


# ---------------------------------------------------------------------------
# 4. Nao sobra portugues no modo ingles
# ---------------------------------------------------------------------------

# So as frases: acima de doze caracteres nao ha coincidencia possivel com um
# rotulo curto (" a ", "sim", "estado") nem com o que vem da base de dados. Os
# rotulos curtos estao cobertos pelo teste da navegacao e pelo das chaves
# visiveis, mais abaixo.
COMPRIMENTO_DE_UMA_FRASE = 12


def _frases(tabela: dict[str, str], excepto: dict[str, str]) -> set[str]:
    outros = " ".join(excepto.values())
    return {
        valor for valor in tabela.values()
        if len(valor) >= COMPRIMENTO_DE_UMA_FRASE and "{" not in valor and valor not in outros
    }


def test_no_modo_ingles_nao_sobra_uma_frase_portuguesa(client, dados):
    """⭐ A guarda contra a cadeia escrita a mao dentro do codigo.

    E o defeito que esta traducao mais podia produzir: uma frase esquecida em
    portugues numa pagina que um avaliador abre em ingles. Varre as tres vistas
    e os dois paineis, e nao ha excepcao nenhuma.
    """
    portuguesas = _frases(textos.PORTUGUES, textos.INGLES)
    portuguesas |= _frases(textos.ROTULOS_EM_PORTUGUES, textos.ROTULOS_EM_INGLES)
    assert len(portuguesas) >= 20, "o varrimento nao esta a procurar quase nada"
    for caminho, html in _paginas(client, "en", dados).items():
        for frase in portuguesas:
            assert frase not in html, (caminho, frase)


def test_no_modo_portugues_nao_sobra_uma_frase_inglesa(client, dados):
    """O controlo negativo do teste acima.

    Sem ele, uma consola que ficasse em ingles nos dois modos passava la.
    """
    inglesas = _frases(textos.INGLES, textos.PORTUGUES)
    inglesas |= _frases(textos.ROTULOS_EM_INGLES, textos.ROTULOS_EM_PORTUGUES)
    assert len(inglesas) >= 20
    for caminho, html in _paginas(client, "pt", dados).items():
        for frase in inglesas:
            assert frase not in html, (caminho, frase)


# Uma frase longa nao aparece por acaso dentro de outra coisa. E o comprimento a
# partir do qual "esta chave apareceu na pagina" e uma medicao e nao uma
# coincidencia.
COMPRIMENTO_DE_UMA_CHAVE_MEDIVEL = 20

# ⚠️ A medibilidade tem de ser a MESMA nas duas linguas, e por isso exige-se o
# comprimento nas duas. Uma chave medivel so numa delas -- "geometry provenance"
# tem 19 caracteres e "proveniência da geometria" tem 25 -- produzia uma
# diferenca que nao e um defeito nenhum, so o comprimento das palavras.
CHAVES_MEDIVEIS = frozenset(
    chave for chave in textos.INGLES
    if all(
        len(textos.TABELAS["textos"][lingua][chave]) >= COMPRIMENTO_DE_UMA_CHAVE_MEDIVEL
        and "{" not in textos.TABELAS["textos"][lingua][chave]
        for lingua in textos.LINGUAS
    )
)


def _chaves_visiveis(html: str, lingua: str) -> set[str]:
    tabela = textos.TABELAS["textos"][lingua]
    return {chave for chave in CHAVES_MEDIVEIS if tabela[chave] in html}


@pytest.mark.parametrize("caminho", AS_VISTAS)
def test_a_mesma_pagina_usa_as_mesmas_chaves_nas_duas_linguas(client, dados, caminho):
    """⭐ A propriedade que sobrevive a qualquer reduccao.

    Nao afirma que texto esta la: afirma que o CONJUNTO de chaves que a pagina
    usa e o mesmo nas duas linguas. Uma chave que deixe de ser usada numa
    delas -- por um literal escrito a mao, ou por uma frase apagada -- faz este
    teste cair sem que ninguem tenha de olhar para as palavras.
    """
    em_ingles = _chaves_visiveis(client.get(_end(caminho, "en")).text, "en")
    em_portugues = _chaves_visiveis(client.get(_end(caminho, "pt")).text, "pt")
    assert len(CHAVES_MEDIVEIS) >= 15, "quase nada e medivel: o teste nao mede nada"
    assert em_ingles, f"{caminho} nao usa chave nenhuma medivel"
    assert em_ingles == em_portugues, sorted(em_ingles.symmetric_difference(em_portugues))


# ---------------------------------------------------------------------------
# O que a lingua muda para alem das palavras
# ---------------------------------------------------------------------------

def test_a_data_em_ingles_e_inequivoca(client, dados):
    """⚠️ `09/08/2026` le-se de duas maneiras conforme quem le.

    Esta consola e uma janela sobre uma base cujas datas viajam em ISO, e uma
    data ambigua num painel de proveniencia e exactamente a classe de erro que
    o resto do produto existe para nao cometer.
    """
    ingles, portugues = textos.de("en"), textos.de("pt")
    assert marcacao.dia("2026-09-29", ingles) == "2026-09-29"
    assert marcacao.dia("2026-09-29", portugues) == "29/09/2026"
    assert marcacao.momento("2026-09-29T14:05:00+00:00", ingles) == "2026-09-29 14:05"
    html = client.get("/console/sincronizacoes").text
    assert "2026-09-29" in html
    assert "29/09/2026" not in html


def test_o_valor_diz_o_lugar_da_medicao_nas_duas_linguas(client, dados):
    """⭐ A frase inglesa NEGA a medicao, e nao descreve um lugar.

    "not measured in the parcel" e nao "outside the parcel": a literal deixaria
    quem le a pensar que o numero e desta parcela e foi lido ao lado. E a
    distincao que este produto inteiro existe para nao apagar.
    """
    for lingua in textos.LINGUAS:
        da_lingua = textos.de(lingua)
        fora = formato.lugar_da_medicao(
            {"source_type": "reanalysis", "evidence": None}, da_lingua
        )
        dentro = formato.lugar_da_medicao(
            {"source_type": "observed_screening", "evidence": None}, da_lingua
        )
        assert fora != dentro, lingua
        assert fora == da_lingua["valor.fora_da_parcela"]
        assert dentro == da_lingua["valor.na_parcela"]
    # e em ingles a negacao esta la, e nao so uma referencia a um sitio.
    assert "not" in textos.INGLES["valor.fora_da_parcela"].split()
    assert "measured" in textos.INGLES["valor.fora_da_parcela"]


def test_os_veredictos_acusam_a_execucao_nas_duas_linguas(client, dados):
    """Um veredicto que descrevesse um estado deixava de ser um veredicto.

    Mede-se pela distincao: os tres tem de ser diferentes uns dos outros nas
    duas linguas, e o da execucao que falhou tem de aparecer na linha dela.
    """
    for lingua in textos.LINGUAS:
        da_lingua = textos.de(lingua)
        veredictos = {
            da_lingua[chave] for chave in (
                "veredicto.failed", "veredicto.never_finished",
                "veredicto.succeeded_without_writing",
            )
        }
        assert len(veredictos) == 3, lingua
        html = client.get(_end("/console/sincronizacoes", lingua)).text
        linha = re.search(r'<tr class="linha"[^>]*data-execucao="eo_sync".*?</tr>', html, re.S)
        assert linha, lingua
        assert da_lingua["veredicto.failed"] in _texto(linha.group(0)), lingua


def test_a_ressalva_do_rodape_aparece_nas_duas_linguas(client, dados):
    """⭐ E a unica coisa nesta consola que impede tres leituras erradas.

    Se ela se perdesse numa das linguas, a consola dessa lingua passava a
    afirmar por omissao o que a portuguesa nega por escrito. Mede-se pelas
    tres afirmacoes que ela carrega, e nao pela frase inteira.
    """
    for lingua in textos.LINGUAS:
        html = client.get(_end("/console/observacoes", lingua)).text
        rodape = re.search(r'<footer class="rodape".*?</footer>', html, re.S)
        assert rodape, lingua
        assert textos.TABELAS["textos"][lingua]["ressalva"] in rodape.group(0), lingua
        # a parte a negrito e a que nao pode cair: e ela que diz que nada aqui
        # foi validado agronomicamente.
        assert "<b>" in rodape.group(0), lingua


def test_a_marca_que_a_camada_escreve_no_dado_nao_muda_com_a_lingua(client, dados):
    """⚠️ O que a camada corta e substituido DENTRO do dado, e nao na pagina.

    O mesmo corpo em JSON e servido a quem le a camada directamente. Uma marca
    traduzida por pedido dava a mesma nota de uma area de interesse com dois
    conteudos conforme quem a leu, e nenhum deles corresponderia ao que esta
    gravado. Usa a palavra fixada no README e nas rotas -- `withheld` --, e nao
    um sinonimo: e derivada da marca estruturada em vez de escrita ao lado dela.
    """
    from resoiltwin.api import console as camada

    (chave, razao), = camada.MARCA_DE_COORDENADA.items()
    assert chave in camada.TEXTO_DE_COORDENADA_RETIDA
    assert razao in camada.TEXTO_DE_COORDENADA_RETIDA
    assert chave in camada.MARCA_DE_RETIDO

    # e, ponta a ponta: a mesma nota lida nas duas linguas traz a mesma marca.
    notas = {
        lingua: client.get(
            _end(f"/console/api/v1/sites/{SITIO}/aois", lingua)
        ).json()[0]["geometry_source_note"]
        for lingua in textos.LINGUAS
    }
    assert len(set(notas.values())) == 1, notas


def test_os_caminhos_das_vistas_nao_mudam_com_a_lingua(client, dados):
    """⚠️ Um endereco e uma identidade, e nao um texto.

    Traduzi-lo dava duas paginas para quem le um registo, dois favoritos para a
    mesma vista, e uma ligacao partilhada que abria noutro sitio.

    ⚠️ Compara-se o CONJUNTO exacto de caminhos, e nao "o caminho aparece la".
    A primeira escrita deste teste procurava `href="/console/observacoes` como
    prefixo, e um mutante que servisse `/console/observacoes-pt` sobrevivia-lhe
    inteiro: o prefixo continuava a casar.
    """
    esperados = {destino for _, destino in marcacao.VISTAS} | {"/console/estilo.css"}
    for lingua in textos.LINGUAS:
        html = client.get(_end("/console/observacoes", lingua)).text
        caminhos = {
            destino.split("?")[0].split("#")[0]
            for destino in re.findall(r'href="([^"]*)"', html)
            if destino.startswith("/console")
        }
        assert caminhos == esperados, (lingua, sorted(caminhos))
