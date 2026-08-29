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


EVALSCRIPT_VERSION_SCL = "s2-ndvi-ndmi-ndre-scl-v2"

# Scene Classification Layer do Sentinel-2 L2A. Excluimos nuvem, sombra, cirros,
# saturacao, neve e ausencia de dado. Mantemos vegetacao (4), solo nu (5),
# agua (6) e nao classificado (7) -- sao superficie real da AOI, nao artefacto.
SCL_CLASSES_EXCLUIDAS = frozenset({0, 1, 2, 3, 8, 9, 10, 11})

NDVI_NDMI_NDRE_SCL = """//VERSION=3
function setup() {
  return {
    input: [{bands: ["B04", "B05", "B08", "B8A", "B11", "SCL", "dataMask"]}],
    output: [
      {id: "ndvi", bands: 1}, {id: "ndmi", bands: 1},
      {id: "ndre", bands: 1}, {id: "dataMask", bands: 1}
    ]
  };
}
function pixelValido(s) {
  // Espelha SCL_CLASSES_EXCLUIDAS: 0 sem dados, 1 saturado/defeituoso,
  // 2 sombra projectada, 3 sombra de nuvem, 8 nuvem media, 9 nuvem alta,
  // 10 cirros finos, 11 neve/gelo. Fica vegetacao(4), solo nu(5), agua(6)
  // e nao classificado(7).
  var excluidas = [__EXCLUIDAS__];
  return excluidas.indexOf(s.SCL) === -1 ? 1 : 0;
}
function evaluatePixel(s) {
  var valido = pixelValido(s) * s.dataMask;
  return {
    ndvi: [(s.B08 - s.B04) / (s.B08 + s.B04)],
    ndmi: [(s.B08 - s.B11) / (s.B08 + s.B11)],
    ndre: [(s.B8A - s.B05) / (s.B8A + s.B05)],
    dataMask: [valido]
  };
}""".replace("__EXCLUIDAS__", ", ".join(str(classe) for classe in sorted(SCL_CLASSES_EXCLUIDAS)))
# O array JS acima e derivado de SCL_CLASSES_EXCLUIDAS, nao duplicado a mao:
# um so lugar define quais classes ficam de fora, script e constante nao podem divergir.


def evalscript_hash(evalscript: str) -> str:
    """Identidade do script que produziu os numeros. Mudar o script muda os valores,
    portanto o hash entra na proveniencia de cada observacao gravada.

    Sem valor por omissao de proposito: statistics() aceita qualquer evalscript
    por argumento, e hashear sempre a constante do modulo gravaria uma
    proveniencia que nao corresponde ao script que realmente correu assim que
    alguem passar um script diferente. Sem default fica impossivel esquecer-se
    de passar o script certo.
    """
    return hashlib.sha256(evalscript.encode()).hexdigest()[:12]
