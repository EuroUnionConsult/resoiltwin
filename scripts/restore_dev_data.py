#!/usr/bin/env python3
"""Repoe a base de desenvolvimento a partir do zero, num so comando.

A base `resoiltwin` local ja foi apagada duas vezes por engano -- a segunda por
um `alembic downgrade base` corrido contra ela sem se ter lido para onde a
ligacao apontava. Repor a mao demora meia hora, envolve arrancar um servidor,
quatro curls e a leitura cuidadosa de quatro `status` de job. Este script faz
isso, pela mesma ordem e pelas mesmas rotas HTTP.

O que repoe:

1. a campanha de campo de Turcifal (`seeds/turcifal_2026_08.py`): site
   EUC-TUR-01, 2 parcelas, 1 instrumento, 27 observacoes de rastreio e 4 VPD
   derivados. Escrito directamente na base, que e como o seed funciona;
2. o site do Porto e as duas AOI, **pelas rotas HTTP**, com as geometrias lidas
   dos GeoJSON de `resoiltwin-internal/aoi-final/` -- incluindo a proveniencia
   e a nota que vem dentro de cada ficheiro. As duas ficam aprovadas;
3. quatro sincronizacoes Copernicus, tambem pelas rotas HTTP: cada AOI com e
   sem mascara SCL, o que recria as series `v1` e `v2` lado a lado;
4. a reanalise AgERA5 de cada sitio, de 1 de Julho a 29 de Agosto de 2026 --
   a janela da nota de evidencia da Fase C, escolhida por cobrir os dias da
   campanha de campo (22 a 24 de Agosto);
5. as ultimas 24 horas da estacao do IPMA mais proxima de cada sitio.

Os passos 4 e 5 demoram: cada sincronizacao da reanalise sao seis pedidos ao
Climate Data Store (tres variaveis x dois meses), e cada pedido demora dezenas
de segundos a minutos. Quatro a cinco minutos por sitio e normal.

O que NAO repoe, e nao ha maneira de repor: os UUID dos jobs e das AOI, e os
`created_at`/`started_at` da execucao original. Esses identificadores sao
gerados a cada execucao. Os valores dos indices sao que sao reproduziveis --
vem do Copernicus, nao da base.

**E as duas series meteorologicas nao se reproduzem, cada uma pela sua razao.**
A do IPMA porque a origem nao tem arquivo -- publica as ultimas 24 horas e mais
nada -- portanto o que o passo 5 escreve depende do dia e da hora a que este
script correr, e as horas que ele nao apanhar nao se recuperam. A da reanalise
porque o AgERA5 tem atraso de publicacao: a 29/08/2026 uma janela pedida ate
29/08 vinha ate 22/08, e a mesma janela pedida daqui a uma semana vem inteira.

Por isso a unica contagem EXIGIDA no fim e a das 139 linhas de campo, derivadas
e Copernicus. As duas series meteorologicas sao impressas ao lado, com o numero
a que a reanalise converge, mas nao fazem falhar a reposicao. Exigir um total
unico obrigava a inventar um numero certo para uma coisa que muda de dia para
dia.

Uso:

    python scripts/restore_dev_data.py --yes

Sem `--yes` o script mostra para onde vai escrever e pede confirmacao; se nao
houver terminal para a pedir, recusa. Nunca escreve sem uma das duas coisas.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

AOI_DIR = Path.home() / "Cods" / "resoiltwin-internal" / "aoi-final"

# a janela da nota de 29/08: um dia a frente do fim da Fase B, de proposito.
DATE_FROM = "2026-08-01"
DATE_TO = "2026-08-29"

APPROVED_BY = "Talys Cordeiro"

# O site de Turcifal vem do seed, com o nome e a cultura que o seed declara.
# O do Porto so existia pelas rotas HTTP, por isso e aqui que fica escrito.
SITES = [
    {
        "code": "EUC-PTO-01",
        "name": "Porto - Parque de Requesende",
        "crop_type": "vine",
        "timezone": "Europe/Lisbon",
        "notes": (
            "Area verde urbana de referencia, com vinha em pergola. Serve de controlo "
            "ao micro-site de Turcifal: geometria irregular, sem campanha de campo."
        ),
    },
]

# (codigo da AOI, site a que pertence, ficheiro GeoJSON)
AOIS = [
    ("EUC-TUR-EO1", "EUC-TUR-01", "EUC-TUR-EO1.geojson"),
    ("EUC-PTO-EO1", "EUC-PTO-01", "EUC-PTO-EO1.geojson"),
]

# a ordem importa para a leitura de quem acompanha: primeiro as duas series v1
# (sem mascara), depois as duas v2. E a ordem em que a nota de evidencia as
# apresenta.
SYNCS = [
    ("EUC-TUR-01", "EUC-TUR-EO1", False),
    ("EUC-PTO-01", "EUC-PTO-EO1", False),
    ("EUC-TUR-01", "EUC-TUR-EO1", True),
    ("EUC-PTO-01", "EUC-PTO-EO1", True),
]

# a janela da reanalise: a mesma da nota de evidencia da Fase C. Comeca um mes
# antes da janela EO porque o balanco hidrico da Fase D precisa de historico de
# precipitacao antes do primeiro dia que quer explicar, e vai ate 29/08 porque
# tem de conter a campanha de campo de 22 a 24 de Agosto.
WEATHER_DATE_FROM = "2026-07-01"
WEATHER_DATE_TO = "2026-08-29"

# os dois sitios, na ordem em que a nota de evidencia os apresenta
SITIOS_METEO = ["EUC-TUR-01", "EUC-PTO-01"]

# 27 campo + 4 derivados + 54 v1 + 54 v2. So isto e exigido: e a parte que se
# reproduz byte a byte em qualquer dia, porque o seed e um ficheiro e o
# Copernicus e um arquivo fechado sobre uma janela passada.
#
# As duas series meteorologicas ficam FORA da exigencia, cada uma pela sua
# razao, e somar as tres num total unico transformava a variacao normal de
# qualquer uma delas num alarme sobre as outras.
TOTAL_REPRODUZIVEL = 139

# 60 dias x 3 metricas x 2 sitios, se o AgERA5 ja tiver publicado a janela
# toda. Nao e uma exigencia, e um alvo: o AgERA5 tem atraso de publicacao e a
# 29/08/2026 um pedido ate 29/08 devolvia ate 22/08 -- 53 dias, 318 linhas.
# O numero sobe sozinho a medida que o arquivo apanha os dias em falta, e
# volta a bater certo quando os apanhar todos.
REANALISE_QUANDO_COMPLETA = 360

_ARRANQUE_TIMEOUT_S = 30.0
_SYNC_TIMEOUT_S = 300.0

# muito maior do que o do satelite, e nao por precaucao: uma sincronizacao da
# reanalise sao seis pedidos ao CDS em serie, cada um com o seu proprio tecto
# de 900 s dentro do cliente. Um timeout de cliente mais curto do que a soma
# desses tectos cortava a ligacao com o trabalho ja feito do lado do CDS e a
# reposicao acabava sem saber se o job tinha corrido.
_METEO_TIMEOUT_S = 5700.0


class FalhaDaReposicao(RuntimeError):
    """Erro que o script sabe explicar. Sai com mensagem, sem traceback."""


def url_sem_segredo(url: str) -> str:
    """Esconde a palavra-passe da URL antes de a imprimir.

    O ponto do script e dizer para onde vai escrever, e isso precisa do host,
    da porta e do nome da base -- nao da credencial. Imprimir a URL em bruto
    punha uma palavra-passe em qualquer log ou captura de ecra de quem corresse
    a reposicao.
    """
    return re.sub(r"://([^:/@]+):[^@]*@", r"://\1:***@", url)


def porta_livre() -> int:
    """Pede uma porta ao SO em vez de escolher um numero.

    Uma porta fixa colide com o uvicorn que o programador ja tenha a correr --
    e o pior caso nao e o erro de arranque, e o script falar com o servidor
    errado, possivelmente ligado a outra base.
    """
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def confirmar(database_url: str, assumir_sim: bool) -> None:
    """Diz para onde vai escrever, e so avanca com autorizacao explicita."""
    print("Reposicao dos dados de desenvolvimento do ReSoilTwin")
    print(f"  base de destino : {url_sem_segredo(database_url)}")
    print(f"  janela EO       : {DATE_FROM} a {DATE_TO}")
    print(f"  geometrias      : {AOI_DIR}")
    print()
    print("Este script ESCREVE nesta base. Confirma que e a base certa antes de continuar.")
    if assumir_sim:
        print("  --yes dado na linha de comando: a avancar.\n")
        return
    if not sys.stdin.isatty():
        raise FalhaDaReposicao(
            "sem terminal para pedir confirmacao e sem --yes. Recuso escrever as cegas: "
            "voltar a correr com --yes depois de confirmar a base acima."
        )
    resposta = input("Escrever nesta base? [escrever 'sim' para continuar] ").strip().lower()
    if resposta != "sim":
        raise FalhaDaReposicao("cancelado a pedido do utilizador; nada foi escrito.")
    print()


def carregar_aoi(ficheiro: Path, codigo: str) -> dict:
    """Corpo do POST da AOI, construido a partir do GeoJSON tal como esta.

    A proveniencia e a nota de origem vivem dentro do proprio ficheiro e sao
    lidas de la: reescreve-las aqui era criar uma segunda opiniao sobre a
    origem de um poligono, que e exactamente o que a coluna
    `geometry_provenance` existe para impedir.
    """
    if not ficheiro.exists():
        raise FalhaDaReposicao(
            f"falta o GeoJSON {ficheiro}. As geometrias vivem fora deste repositorio, em "
            "resoiltwin-internal/aoi-final/; sem elas nao ha AOI para repor e inventar "
            "um poligono produzia numeros que nao se podem defender."
        )
    dados = json.loads(ficheiro.read_text())
    feicoes = dados.get("features") or []
    if len(feicoes) != 1:
        raise FalhaDaReposicao(
            f"{ficheiro.name} tem {len(feicoes)} feicoes e esperava-se exactamente uma. "
            "Escolher uma ao acaso mudava a area da AOI em silencio."
        )
    propriedades = feicoes[0].get("properties") or {}
    declarado = propriedades.get("site_id")
    if declarado != codigo:
        raise FalhaDaReposicao(
            f"{ficheiro.name} declara '{declarado}' e este script esperava '{codigo}'. "
            "Carregar o poligono errado com o codigo certo e indetectavel depois."
        )
    proveniencia = propriedades.get("geometry_provenance")
    if not proveniencia:
        raise FalhaDaReposicao(
            f"{ficheiro.name} nao declara geometry_provenance. Uma AOI sem proveniencia "
            "declarada nao pode ser aprovada."
        )
    return {
        "code": codigo,
        "purpose": "earth_observation",
        "geometry": feicoes[0]["geometry"],
        "geometry_provenance": proveniencia,
        "geometry_source_note": propriedades.get("note"),
    }


def semear(sessao_factory) -> dict:
    from seeds.turcifal_2026_08 import seed_turcifal

    sessao = sessao_factory()
    try:
        return seed_turcifal(sessao)
    finally:
        sessao.close()


def esperar_servidor(cliente: httpx.Client, processo: subprocess.Popen) -> None:
    """Espera pelo /health, e desiste se o uvicorn morrer entretanto.

    Sem a segunda condicao, um servidor que rebentasse no arranque (porta
    ocupada, base inacessivel) deixava o script a bater no relogio ate ao
    timeout e a reportar "nao arrancou a tempo" em vez do erro real.
    """
    limite = time.monotonic() + _ARRANQUE_TIMEOUT_S
    while time.monotonic() < limite:
        if processo.poll() is not None:
            raise FalhaDaReposicao(
                f"o uvicorn terminou com codigo {processo.returncode} antes de responder. "
                "Ver a saida acima: normalmente e a base inacessivel ou a porta ocupada."
            )
        try:
            resposta = cliente.get("/health", timeout=2.0)
        except httpx.TransportError:
            time.sleep(0.2)
            continue
        if resposta.status_code == 200:
            return
        time.sleep(0.2)
    raise FalhaDaReposicao(f"o uvicorn nao respondeu ao /health em {_ARRANQUE_TIMEOUT_S:.0f}s.")


def _exigir(resposta: httpx.Response, esperado: int, o_que: str) -> dict:
    if resposta.status_code != esperado:
        raise FalhaDaReposicao(
            f"{o_que}: esperava HTTP {esperado}, veio {resposta.status_code} - {resposta.text[:400]}"
        )
    return resposta.json()


def criar_sites_e_aois(cliente: httpx.Client) -> None:
    for site in SITES:
        resposta = cliente.post("/sites", json=site)
        if resposta.status_code == 409:
            print(f"  site {site['code']}: ja existia")
        else:
            _exigir(resposta, 201, f"criar o site {site['code']}")
            print(f"  site {site['code']}: criado")

    for codigo, site_code, ficheiro in AOIS:
        corpo = carregar_aoi(AOI_DIR / ficheiro, codigo)
        resposta = cliente.post(f"/sites/{site_code}/aois", json=corpo)
        if resposta.status_code == 409:
            print(f"  AOI {codigo}: ja existia")
        else:
            aoi = _exigir(resposta, 201, f"criar a AOI {codigo}")
            print(f"  AOI {codigo}: criada, {aoi['area_m2']:,.2f} m2, {aoi['geometry_provenance']}")

        aprovada = _exigir(
            cliente.post(f"/aois/{codigo}/approve", json={"approved_by": APPROVED_BY}),
            200, f"aprovar a AOI {codigo}",
        )
        print(f"  AOI {codigo}: {aprovada['status']} por {aprovada['approved_by']}")


def sincronizar(cliente: httpx.Client) -> list[dict]:
    """Corre as quatro sincronizacoes e LE o status de cada uma.

    Um 202 nao e sucesso: `sync_aoi()` nao propaga falhas de execucao, devolve
    o job com status 'failed' e o erro gravado. Um script que so olhasse para o
    codigo HTTP dava a reposicao por feita com a base a meio.
    """
    jobs = []
    for site_code, aoi_code, mascara in SYNCS:
        rotulo = "v2 (scl_mask=true)" if mascara else "v1 (scl_mask=false)"
        job = _exigir(
            cliente.post(
                f"/sites/{site_code}/eo/sync",
                json={
                    "aoi_code": aoi_code, "date_from": DATE_FROM, "date_to": DATE_TO,
                    "scl_mask": mascara,
                },
                timeout=_SYNC_TIMEOUT_S,
            ),
            202, f"sincronizar {aoi_code} {rotulo}",
        )
        print(
            f"  {aoi_code} {rotulo}: status={job['status']} "
            f"rows_written={job['rows_written']} version={job['processing_version']}"
        )
        if job["status"] != "succeeded":
            raise FalhaDaReposicao(
                f"o job de {aoi_code} {rotulo} veio '{job['status']}' e nao 'succeeded'. "
                f"Erro gravado: {job['error']}. A reposicao para aqui: continuar deixaria a "
                "base com uma serie parcial que se apresenta como completa."
            )
        jobs.append(job)
    return jobs


def sincronizar_meteorologia(cliente: httpx.Client) -> list[dict]:
    """Corre a reanalise e o IPMA para cada sitio, e LE o status de cada job.

    Mesma disciplina do `sincronizar()` do satelite -- um 202 nao e sucesso --
    e a mesma paragem imediata quando um job vem `failed`. O que muda e o que
    se pode exigir DEPOIS: nenhuma das duas series tem um numero de linhas para
    exigir.

    A do IPMA porque a origem so publica as ultimas 24 horas: numa base acabada
    de repor entram 24 por metrica, numa reposicao repetida no mesmo dia podem
    entrar zero, e zero e a resposta certa. A da reanalise porque o AgERA5
    atrasa a publicacao e a janela pedida pode vir curta -- o `date_to` de cada
    job impresso acima diz ate onde chegou.

    Quem defende as duas metades e o `status` de cada job, e nao uma contagem:
    o sincronizador do IPMA ja falha quando a execucao nao escreve nada e havia
    leituras de outra estacao a colidir com ela, e o da reanalise falha quando a
    origem falha.
    """
    jobs = []
    for site_code in SITIOS_METEO:
        for corpo in (
            {"source": "reanalysis",
             "date_from": WEATHER_DATE_FROM, "date_to": WEATHER_DATE_TO},
            # sem janela: o feed do IPMA nao tem parametro de data nenhum, e
            # o pedido recusa-a com 422 em vez de a ignorar em silencio
            {"source": "ipma"},
        ):
            rotulo = corpo["source"]
            job = _exigir(
                cliente.post(f"/sites/{site_code}/weather/sync", json=corpo,
                             timeout=_METEO_TIMEOUT_S),
                202, f"sincronizar {rotulo} de {site_code}",
            )
            print(
                f"  {site_code} {rotulo}: status={job['status']} "
                f"rows_written={job['rows_written']} version={job['processing_version']} "
                f"janela={job['date_from']}..{job['date_to']}"
            )
            if job["status"] != "succeeded":
                raise FalhaDaReposicao(
                    f"o job de {rotulo} de {site_code} veio '{job['status']}' e nao "
                    f"'succeeded'. Erro gravado: {job['error']}. A reposicao para aqui: "
                    "continuar deixaria a base com uma serie parcial que se apresenta "
                    "como completa."
                )
            jobs.append(job)
    return jobs


def contagem(sessao_factory) -> list[tuple]:
    from sqlalchemy import func, select

    from resoiltwin.models import Observation

    sessao = sessao_factory()
    try:
        return sessao.execute(
            select(
                Observation.source_type, Observation.processing_version, func.count()
            ).group_by(Observation.source_type, Observation.processing_version)
            .order_by(Observation.source_type, Observation.processing_version)
        ).all()
    finally:
        sessao.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Repoe os dados de desenvolvimento do ReSoilTwin na base configurada.",
    )
    parser.add_argument(
        "--yes", action="store_true",
        help="confirma a escrita sem perguntar. Ler primeiro a base que o script imprime.",
    )
    parser.add_argument(
        "--port", type=int, default=None,
        help="porta do uvicorn temporario (por omissao, uma porta livre pedida ao SO).",
    )
    argumentos = parser.parse_args()

    from resoiltwin.api.auth import NOME_DO_CABECALHO
    from resoiltwin.config import get_settings
    from resoiltwin.db import SessionLocal

    definicoes = get_settings()
    try:
        confirmar(definicoes.database_url, argumentos.yes)
    except FalhaDaReposicao as erro:
        print(f"\n{erro}", file=sys.stderr)
        return 2

    # Este script escreve pelas ROTAS HTTP, e as rotas que escrevem passaram a
    # exigir a chave partilhada (31/08/2026, decisao 7). Sem ela o uvicorn
    # arranca na mesma -- a chave nao impede o arranque, de proposito -- e cada
    # POST responderia 503; a reposicao morreria no primeiro `_exigir` com uma
    # mensagem sobre um codigo HTTP em vez da causa. Verifica-se aqui, antes de
    # arrancar seja o que for.
    if not definicoes.write_api_key:
        print(
            "\nWRITE_API_KEY nao esta definida, e este script escreve pelas rotas HTTP.\n"
            "Define-a no .env (ver .env.example) antes de repor os dados.",
            file=sys.stderr,
        )
        return 2

    porta = argumentos.port or porta_livre()
    processo = None
    try:
        print("1/5  campanha de campo de Turcifal (seed directo)")
        resumo = semear(SessionLocal)
        print(f"  {resumo}")

        print(f"\n2/5  a arrancar o uvicorn em 127.0.0.1:{porta}")
        processo = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "resoiltwin.main:app",
             "--host", "127.0.0.1", "--port", str(porta), "--log-level", "warning"],
            cwd=str(ROOT),
            env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        )
        with httpx.Client(
            base_url=f"http://127.0.0.1:{porta}/api/v1",
            timeout=60.0,
            headers={NOME_DO_CABECALHO: definicoes.write_api_key},
        ) as cliente:
            esperar_servidor(cliente, processo)
            print("  servidor a responder")

            print("\n3/5  sites e AOI, pelas rotas HTTP")
            criar_sites_e_aois(cliente)

            print("\n4/5  sincronizacoes Copernicus, pelas rotas HTTP")
            sincronizar(cliente)

            print("\n5/5  sincronizacoes meteorologicas, pelas rotas HTTP")
            print("  (a reanalise sao seis pedidos ao CDS por sitio; conta com minutos)")
            sincronizar_meteorologia(cliente)
    except FalhaDaReposicao as erro:
        print(f"\nreposicao interrompida: {erro}", file=sys.stderr)
        return 1
    finally:
        if processo is not None and processo.poll() is None:
            processo.terminate()
            try:
                processo.wait(timeout=10)
            except subprocess.TimeoutExpired:
                processo.kill()

    print("\nobservacoes na base, por proveniencia:")
    linhas = contagem(SessionLocal)
    total = 0
    por_origem: dict[str, int] = {}
    for source_type, versao, quantas in linhas:
        print(f"  {source_type:<20} {versao:<40} {quantas}")
        total += quantas
        por_origem[str(source_type)] = por_origem.get(str(source_type), 0) + quantas
    print(f"  {'total':<61} {total}")

    da_reanalise = por_origem.get("reanalysis", 0)
    do_ipma = por_origem.get("weather_observed", 0)
    reproduzivel = total - da_reanalise - do_ipma

    print("\nas duas series meteorologicas, fora da conta reproduzivel:")
    print(f"  reanalise (AgERA5)   {da_reanalise:>4} de {REANALISE_QUANDO_COMPLETA} "
          "quando o arquivo tiver a janela toda publicada")
    print(f"  estacao (IPMA)       {do_ipma:>4} sem numero esperado: a origem so publica "
          "as ultimas 24 h")
    if da_reanalise < REANALISE_QUANDO_COMPLETA:
        em_falta = REANALISE_QUANDO_COMPLETA - da_reanalise
        print(f"  -> faltam {em_falta} linhas de reanalise. O caso normal e o atraso de "
              "publicacao do AgERA5; cada job diz no seu `date_to` ate onde chegou.")

    if reproduzivel != TOTAL_REPRODUZIVEL:
        print(
            f"\nATENCAO: esperavam-se {TOTAL_REPRODUZIVEL} observacoes reproduziveis "
            f"(campo, derivadas e Copernicus) e a base tem {reproduzivel}. "
            "A reposicao correu sem erro, portanto a diferenca esta nos dados devolvidos "
            "pelo Copernicus, nao no script -- comparar com a nota de evidencia antes de "
            "dar a base por reposta. As duas series meteorologicas estao fora desta conta "
            "de proposito, e a razao esta impressa acima.",
            file=sys.stderr,
        )
        return 1

    print("\nbase reposta.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
