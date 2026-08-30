import time

import httpx

TOKEN_URL = ("https://identity.dataspace.copernicus.eu/auth/realms/CDSE"
             "/protocol/openid-connect/token")
BASE_URL = "https://sh.dataspace.copernicus.eu"
CATALOG_PATH = "/api/v1/catalog/1.0.0/search"
STATS_PATH = "/api/v1/statistics"

_MARGEM_EXPIRACAO_S = 60
_TECTO_PAGINAS_CATALOGO = 20


class CDSEClient:
    """Cliente do Copernicus Data Space. So fala HTTP: nao sabe nada da base de dados.

    O token e reutilizado ate 60 segundos antes de expirar. Pedir um token novo a
    cada chamada e desperdicio e a spec do projecto proibe-o explicitamente.
    """

    def __init__(self, client_id: str, client_secret: str, transport=None, timeout: float = 180.0):
        self._id = client_id
        self._secret = client_secret
        self._client = httpx.Client(transport=transport, timeout=timeout)
        self._token: str | None = None
        self._expires_at: float = 0.0

    def token(self) -> str:
        if self._token and time.monotonic() < self._expires_at:
            return self._token
        r = self._client.post(TOKEN_URL, data={
            "grant_type": "client_credentials",
            "client_id": self._id,
            "client_secret": self._secret,
        })
        if r.status_code != 200:
            raise _erro_resposta(r, "CDSE recusou as credenciais")
        d = r.json()
        self._token = d["access_token"]
        self._expires_at = time.monotonic() + d.get("expires_in", 600) - _MARGEM_EXPIRACAO_S
        return self._token

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token()}", "Content-Type": "application/json"}

    def search_scenes(self, geometry_4326: dict, date_from: str, date_to: str,
                      collection: str = "sentinel-2-l2a", max_cloud: int = 30,
                      limit: int = 100) -> list[dict]:
        """Descobre que aquisicoes existem antes de processar seja o que for.

        ⚠️ **Nao tem chamador em `src/`, `scripts/`, `seeds/` nem `tools/` a
        30/08/2026**, e isto esta escrito aqui para deixar de ser uma surpresa.
        O `sync_aoi` so chama o `statistics()`, que nao tem paginacao nem
        verificacao de completude nenhuma -- portanto a guarda cuidadosa que
        vem a seguir NAO esta no caminho de ingestao, apesar de o docstring
        dela dar essa impressao. Foi usado a mao, e o produto dele -- a
        nebulosidade por cena -- esta na tabela de `docs/evidence/
        2026-08-29-mascara-scl.md`, que e a nota que demonstrou que essa
        nebulosidade NAO decide se a AOI esta contaminada.

        Fica, e nao e por indecisao. Apagar isto nao fecha buraco nenhum e
        deita fora a unica chamada que responde a pergunta que a ingestao ainda
        nao sabe responder: separar "o satelite nao passou" de "passou e nos
        descartamos". Liga-lo agora ao `sync_aoi` tambem nao se faz aqui --
        custa um pedido por sincronizacao e uma politica sobre o que fazer com
        a diferenca, e nenhuma das duas coisas se decide sem correr contra a
        API a serio. O que estava errado era so o silencio: um metodo com uma
        guarda de completude, testado, e sem nada a dizer que a ingestao nao
        passa por ele.

        Segue a paginacao do Catalog (links rel=next) ate esgotar, ate um tecto
        defensivo de seguranca. Uma AOI grande numa janela de meses passa
        facilmente do limit; devolver so a primeira pagina em silencio daria uma
        serie incompleta que se apresenta como completa, o que numa tese de
        proveniencia auditavel e pior do que um erro.

        O filtro de nuvens vai em CQL2-JSON: sem declarar filter-lang, o CDSE
        recusa o pedido com 400 (confirmado contra a API real em 28/08/2026).
        """
        body = {
            "collections": [collection],
            "intersects": geometry_4326,
            "datetime": f"{date_from}T00:00:00Z/{date_to}T23:59:59Z",
            "limit": limit,
            "filter-lang": "cql2-json",
            "filter": {"op": "<=", "args": [{"property": "eo:cloud_cover"}, max_cloud]},
        }
        cenas: list[dict] = []
        paginas = 0
        while True:
            r = self._client.post(BASE_URL + CATALOG_PATH, json=body, headers=self._headers())
            if r.status_code >= 400:
                raise _erro_resposta(r, "CDSE recusou o pedido ao Catalog")
            d = r.json()
            cenas.extend(d.get("features", []))
            paginas += 1
            proxima = _proxima_pagina(d)
            if proxima is None:
                break
            if paginas >= _TECTO_PAGINAS_CATALOGO:
                raise RuntimeError(
                    f"Catalog CDSE: tecto de {_TECTO_PAGINAS_CATALOGO} paginas atingido com "
                    f"{len(cenas)} cenas recolhidas e a paginacao ainda nao esgotou (ha mais "
                    "'next' por seguir). Nao devolvo uma serie parcial como se fosse completa; "
                    "reduzir a janela de datas ou a AOI, ou rever o tecto, antes de repetir."
                )
            corpo_proximo = proxima.get("body", {})
            body = {**body, **corpo_proximo} if proxima.get("merge", True) else corpo_proximo
        return cenas

    def statistics(self, geometry_utm: dict, date_from: str, date_to: str,
                   evalscript: str, resolution_m: int = 10, max_cloud: int = 30,
                   collection: str = "sentinel-2-l2a") -> list[dict]:
        """Series agregadas por poligono. A geometria TEM de vir em UTM 29N.

        Com coordenadas em graus o Copernicus interpreta resx/resy como graus por
        pixel: devolve um unico pixel, ou recusa o pedido. Verificamos aqui em vez
        de deixar o erro aparecer como uma serie de um pixel que parece plausivel.
        """
        _garantir_metros(geometry_utm)
        body = {
            "input": {
                "bounds": {"geometry": geometry_utm, "properties": {
                    "crs": "http://www.opengis.net/def/crs/EPSG/0/32629"}},
                "data": [{"type": collection, "dataFilter": {"maxCloudCoverage": max_cloud}}],
            },
            "aggregation": {
                "timeRange": {"from": f"{date_from}T00:00:00Z", "to": f"{date_to}T23:59:59Z"},
                "aggregationInterval": {"of": "P1D"},
                "resx": resolution_m, "resy": resolution_m,
                "evalscript": evalscript,
            },
            "calculations": {"default": {}},
        }
        r = self._client.post(BASE_URL + STATS_PATH, json=body, headers=self._headers())
        if r.status_code >= 400:
            # o mesmo helper do token() e do search_scenes(): um raise_for_status()
            # seco deixava o corpo da resposta pelo caminho, e e o corpo que diz
            # o que o Copernicus recusou. Aqui pesa mais do que nos outros dois --
            # o erro deste metodo e o que vai parar ao `error` do job de ingestao,
            # que na fase seguinte corre agendado e e o unico rasto que fica.
            raise _erro_resposta(r, "CDSE recusou o pedido a Statistical API")
        return _normalizar(r.json().get("data", []))


def _erro_resposta(r: httpx.Response, prefixo: str) -> RuntimeError:
    """Formata um erro do CDSE com o corpo da resposta, nao so o codigo HTTP.

    O endpoint de token usa error/error_description; o Catalog usa code/description
    (confirmado contra a API real). Um raise_for_status() seco perderia esta
    informacao e voltaria a dar o diagnostico ambiguo que este helper evita.

    O corpo nem sempre e JSON valido: um proxy ou WAF pelo meio de um 5xx pode
    devolver uma pagina HTML em vez do formato do Copernicus. Nesse caso nao
    deixamos o JSONDecodeError rebentar por cima do erro original, degradamos
    para o texto em bruto, truncado, mantendo sempre o codigo de estado.
    """
    corpo = {}
    if r.text:
        try:
            corpo = r.json()
        except ValueError:
            corpo = {}
    codigo = corpo.get("error", corpo.get("code", r.status_code))
    descricao = corpo.get("error_description", corpo.get("description"))
    if descricao is None:
        descricao = r.text[:200] if r.text else "(corpo vazio)"
    return RuntimeError(f"{prefixo}: {codigo} - {descricao}")


def _proxima_pagina(resposta: dict) -> dict | None:
    """Le o link rel=next do STAC Catalog do CDSE, se existir.

    Confirmado contra a API real: a proxima pagina e um POST cujo corpo se
    mescla (merge=true) no pedido original, contendo um token de continuacao.
    """
    for link in resposta.get("links", []):
        if link.get("rel") == "next":
            return link
    return None


def _garantir_metros(geometry: dict) -> None:
    """Coordenadas UTM andam nas centenas de milhar; graus nunca passam de 180.

    Suporta Polygon e MultiPolygon: a Fase A declara a coluna da AOI como
    GEOMETRY generica, portanto um MultiPolygon e entrada plausivel. Sem este
    nivel extra o `for x, y in anel` assumia sempre Polygon e um MultiPolygon
    rebentava com "too many values to unpack" antes de chegar a verificacao
    de UTM, UTM ou graus tanto fazia.
    """
    aneis = (geometry["coordinates"] if geometry["type"] == "Polygon" else
             [anel for poligono in geometry["coordinates"] for anel in poligono])
    for anel in aneis:
        for x, y in anel:
            if abs(x) <= 180 and abs(y) <= 90:
                raise ValueError(
                    "A geometria parece estar em graus (EPSG:4326). A Statistical API "
                    "exige UTM 29N (EPSG:32629), senao interpreta a resolucao em graus "
                    "por pixel. Reprojectar com resoiltwin.geo antes de chamar."
                )


_INDICES = ("ndvi", "ndmi", "ndre")


def _normalizar(dados: list[dict]) -> list[dict]:
    """Uma linha por aquisicao valida.

    Intervalos sem outputs sao dias sem cena util. Intervalos com outputs
    parciais (falta algum dos tres indices) sao tratados da mesma forma: o
    evalscript pede sempre os tres juntos, por isso um output incompleto e
    sinal de aquisicao malformada, nao motivo para um KeyError que aborta a
    serie inteira por causa de uma unica data.
    """
    linhas = []
    for item in dados:
        saidas = item.get("outputs") or {}
        if not all(indice in saidas for indice in _INDICES):
            continue

        def stat(nome, saidas=saidas):
            return saidas[nome]["bands"]["B0"]["stats"]

        stats = {indice: stat(indice) for indice in _INDICES}
        ndvi = stats["ndvi"]
        if not ndvi.get("sampleCount") or ndvi.get("mean") is None:
            continue
        # As tres contagens sao o MINIMO/MAXIMO comum aos tres indices, e nao
        # so as do ndvi: um pixel invalido apenas em ndmi ou ndre nao pode
        # desaparecer atras da contagem do ndvi.
        #
        # `sampled_pixels` chamou-se `valid_pixels` ate 30/08/2026 e o nome era
        # falso: `sampleCount` conta os pixeis AMOSTRADOS, mascara incluida.
        # Na aquisicao de 24/08/2026 sobre Campo Real dizia 62 750 quando os
        # que contribuiram foram 5 318, e era identico com e sem mascara nas 18
        # aquisicoes -- um valor descrito por um rotulo que e verdadeiro de
        # outra coisa, a mesma classe de defeito do `cell_size_km` unico.
        #
        # `contributing_pixels` e a subtraccao POR INDICE antes do minimo, e
        # nao `min(sampleCount) - max(noDataCount)`. As duas formas dao numeros
        # diferentes quando o indice de menor amostra nao e o de maior
        # descarte, e a segunda nao e sequer uma contagem: mistura bandas
        # diferentes e o que sai nao e o numero de pixeis de nenhuma delas.
        # Esta e o pior caso REAL entre os tres indices, que e o que se quer
        # afirmar sobre uma media que so se defende se as tres a suportarem.
        linhas.append({
            "date": item["interval"]["from"][:10],
            "ndvi": ndvi["mean"],
            "ndmi": stats["ndmi"]["mean"],
            "ndre": stats["ndre"]["mean"],
            "sampled_pixels": min(s.get("sampleCount", 0) for s in stats.values()),
            "contributing_pixels": min(s.get("sampleCount", 0) - s.get("noDataCount", 0)
                                       for s in stats.values()),
            "no_data_pixels": max(s.get("noDataCount", 0) for s in stats.values()),
        })
    return linhas
