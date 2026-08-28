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
        r.raise_for_status()
        return _normalizar(r.json().get("data", []))


def _erro_resposta(r: httpx.Response, prefixo: str) -> RuntimeError:
    """Formata um erro do CDSE com o corpo da resposta, nao so o codigo HTTP.

    O endpoint de token usa error/error_description; o Catalog usa code/description
    (confirmado contra a API real). Um raise_for_status() seco perderia esta
    informacao e voltaria a dar o diagnostico ambiguo que este helper evita.
    """
    corpo = r.json() if r.text else {}
    codigo = corpo.get("error", corpo.get("code", r.status_code))
    descricao = corpo.get("error_description", corpo.get("description", r.text[:200]))
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
    """Coordenadas UTM andam nas centenas de milhar; graus nunca passam de 180."""
    for anel in geometry["coordinates"]:
        for x, y in anel:
            if abs(x) <= 180 and abs(y) <= 90:
                raise ValueError(
                    "A geometria parece estar em graus (EPSG:4326). A Statistical API "
                    "exige UTM 29N (EPSG:32629), senao interpreta a resolucao em graus "
                    "por pixel. Reprojectar com resoiltwin.geo antes de chamar."
                )


def _normalizar(dados: list[dict]) -> list[dict]:
    """Uma linha por aquisicao valida. Intervalos sem outputs sao dias sem cena util."""
    linhas = []
    for item in dados:
        saidas = item.get("outputs") or {}
        if not saidas:
            continue

        def stat(nome):
            return saidas[nome]["bands"]["B0"]["stats"]

        ndvi = stat("ndvi")
        if not ndvi.get("sampleCount") or ndvi.get("mean") is None:
            continue
        linhas.append({
            "date": item["interval"]["from"][:10],
            "ndvi": ndvi["mean"],
            "ndmi": stat("ndmi")["mean"],
            "ndre": stat("ndre")["mean"],
            "valid_pixels": ndvi["sampleCount"],
            "no_data_pixels": ndvi.get("noDataCount", 0),
        })
    return linhas
