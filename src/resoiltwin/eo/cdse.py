import time

import httpx

TOKEN_URL = ("https://identity.dataspace.copernicus.eu/auth/realms/CDSE"
             "/protocol/openid-connect/token")
BASE_URL = "https://sh.dataspace.copernicus.eu"
CATALOG_PATH = "/api/v1/catalog/1.0.0/search"
STATS_PATH = "/api/v1/statistics"

_MARGEM_EXPIRACAO_S = 60


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
            corpo = r.json() if r.text else {}
            raise RuntimeError(
                f"CDSE recusou as credenciais: {corpo.get('error', r.status_code)} "
                f"- {corpo.get('error_description', r.text[:200])}"
            )
        d = r.json()
        self._token = d["access_token"]
        self._expires_at = time.monotonic() + d.get("expires_in", 600) - _MARGEM_EXPIRACAO_S
        return self._token

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token()}", "Content-Type": "application/json"}

    def search_scenes(self, geometry_4326: dict, date_from: str, date_to: str,
                      collection: str = "sentinel-2-l2a", max_cloud: int = 30,
                      limit: int = 100) -> list[dict]:
        """Descobre que aquisicoes existem antes de processar seja o que for."""
        body = {
            "collections": [collection],
            "intersects": geometry_4326,
            "datetime": f"{date_from}T00:00:00Z/{date_to}T23:59:59Z",
            "limit": limit,
            "filter": {"op": "<=", "args": [{"property": "eo:cloud_cover"}, max_cloud]},
        }
        r = self._client.post(BASE_URL + CATALOG_PATH, json=body, headers=self._headers())
        r.raise_for_status()
        return r.json().get("features", [])

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
