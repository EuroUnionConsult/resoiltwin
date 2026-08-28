import hashlib

EVALSCRIPT_VERSION = "s2-ndvi-ndmi-ndre-v1"

# NDVI = (B08-B04)/(B08+B04)   vigor/cobertura vegetal
# NDMI = (B08-B11)/(B08+B11)   agua na folhagem, proxy de stress hidrico
# NDRE = (B8A-B05)/(B8A+B05)   red edge, vegetacao densa e clorofila
# B11 e B8A/B05 sao nativamente de 20 m; pedir 10 m reamostra, nao cria detalhe.
NDVI_NDMI_NDRE = """//VERSION=3
function setup() {
  return {
    input: [{bands: ["B04", "B05", "B08", "B8A", "B11", "dataMask"]}],
    output: [
      {id: "ndvi", bands: 1}, {id: "ndmi", bands: 1},
      {id: "ndre", bands: 1}, {id: "dataMask", bands: 1}
    ]
  };
}
function evaluatePixel(s) {
  return {
    ndvi: [(s.B08 - s.B04) / (s.B08 + s.B04)],
    ndmi: [(s.B08 - s.B11) / (s.B08 + s.B11)],
    ndre: [(s.B8A - s.B05) / (s.B8A + s.B05)],
    dataMask: [s.dataMask]
  };
}"""


def evalscript_hash() -> str:
    """Identidade do script que produziu os numeros. Mudar o script muda os valores,
    portanto o hash entra na proveniencia de cada observacao gravada."""
    return hashlib.sha256(NDVI_NDMI_NDRE.encode()).hexdigest()[:12]
