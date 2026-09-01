#!/usr/bin/env python3
"""Repoe a base de desenvolvimento a partir do zero, num so comando.

A base `resoiltwin` local ja foi apagada duas vezes por engano -- a segunda por
um `alembic downgrade base` corrido contra ela sem se ter lido para onde a
ligacao apontava. Repor a mao demora meia hora, envolve arrancar um servidor,
quatro curls e a leitura cuidadosa de quatro `status` de job. Este script faz
isso, pela mesma ordem e pelas mesmas rotas HTTP.

O que repoe:

1. os dois sitios, **pelas rotas HTTP**, e as duas AOI com as geometrias lidas
   dos GeoJSON de `resoiltwin-internal/aoi-final/` -- incluindo a proveniencia
   e a nota que vem dentro de cada ficheiro. As duas ficam aprovadas;
2. a campanha de campo de Turcifal: 2 parcelas, 1 instrumento, 27 observacoes
   de rastreio e 4 VPD derivados (`seeds/turcifal_2026_08.py`), escritos
   directamente na base -- que e como o seed funciona -- **ou**, quando o alvo
   e uma API remota, lidos da base local e escritos pelas rotas HTTP (ver
   `--api-base-url` mais abaixo);
3. quatro sincronizacoes Copernicus, tambem pelas rotas HTTP: cada AOI com e
   sem mascara SCL, o que recria as series `v1` e `v2` lado a lado;
4. a reanalise AgERA5 de cada sitio, de 1 de Julho a 29 de Agosto de 2026 --
   a janela da nota de evidencia da Fase C, escolhida por cobrir os dias da
   campanha de campo (22 a 24 de Agosto);
5. as ultimas 24 horas da estacao do IPMA mais proxima de cada sitio;
6. o balanco hidrico de cada sitio nas tres capacidades de agua utilizavel que
   a Fase D usou -- 50, 100 e 250 mm --, sobre a mesma janela da reanalise.

Os passos 4 e 6 demoram: cada sincronizacao da reanalise sao seis pedidos ao
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
E o balanco hidrico do passo 6 herda a incerteza da reanalise, porque le as
series dela: mais dias de precipitacao publicados sao mais dias de balanco.

Por isso a unica contagem EXIGIDA no fim e a das 139 linhas de campo, derivadas
e Copernicus. As tres series que dependem do dia sao impressas ao lado, com o
numero a que a reanalise converge, mas nao fazem falhar a reposicao. Exigir um
total unico obrigava a inventar um numero certo para uma coisa que muda de dia
para dia.

Uso:

    python scripts/restore_dev_data.py --yes

Sem `--yes` o script mostra para onde vai escrever e pede confirmacao; se nao
houver terminal para a pedir, recusa. Nunca escreve sem uma das duas coisas.

**Apontar para outra instalacao** (a da Azure, por exemplo):

    python scripts/restore_dev_data.py --yes \\
        --api-base-url https://<host> --api-key-env RESOILTWIN_WRITE_API_KEY

Com `--api-base-url` o script nao arranca uvicorn nenhum: fala com a API que ja
esta publicada, confirma-lhe o `/health` primeiro, e usa a chave que estiver na
variavel de ambiente indicada por `--api-key-env`. A chave nunca e escrita em
ficheiro nenhum nem impressa.

Nesse modo a base local passa a ser so a ORIGEM DE LEITURA da campanha de
campo, e o script nunca lhe escreve: o passo 2 deixa de correr o seed (que
escreve directamente na base a que a aplicacao esta ligada, e que nesse modo e
a errada) e passa a ler as parcelas e as observacoes da base local com `SELECT`
e a escreve-las pelas rotas HTTP do alvo.

⚠️ **Duas coisas nao atravessam por HTTP, e sao ditas em voz alta quando isso
acontece:** a API nao tem rota para criar instrumentos, portanto as linhas de
campo chegam ao alvo com `instrument_id` a NULL; e `ObservationCreate` nao tem
campo `derived_from`, portanto a ligacao estrutural de cada VPD as duas
leituras que o produziram nao viaja -- o que viaja e o `evidence`, que continua
a dizer os numeros de entrada. Quem precisar das duas colunas tem de as
escrever por dentro da rede, e o script diz quantas linhas ficaram assim.
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
from datetime import datetime, timedelta, timezone
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

# Os dois sitios, criados pelas rotas HTTP. O de Turcifal aparece aqui com o
# nome e a cultura que o seed lhe da: e a mesma linha, criada pelo caminho que
# funciona nos dois modos. O seed continua a saber cria-lo -- e idempotente e
# encontra o que ja existe --, mas com o alvo remoto o seed nao corre, e um
# sitio que so o seed soubesse criar nao chegaria la.
SITES = [
    {
        "code": "EUC-TUR-01",
        "name": "Turcifal - micro-site de citrinos",
        "crop_type": "citrus",
        "timezone": "Europe/Lisbon",
    },
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

# as tres capacidades de agua utilizavel do solo com que a Fase D correu, e a
# razao de serem tres esta em `schemas/water.py`: o numero nao esta medido
# nestes terrenos, e por isso nao ha uma corrida certa -- ha tres corridas
# atribuiveis, que delimitam o que o modelo diz conforme o solo que se assuma.
# Confirmadas na base pelas `processing_version` gravadas (`+awc50mm`,
# `+awc100mm`, `+awc250mm`), nao por memoria.
AWC_MM = [50.0, 100.0, 250.0]

# os dois sitios, na ordem em que a nota de evidencia os apresenta
SITIOS_METEO = ["EUC-TUR-01", "EUC-PTO-01"]

# 27 campo + 4 derivados + 54 v1 + 54 v2. So isto e exigido: e a parte que se
# reproduz byte a byte em qualquer dia, porque o seed e um ficheiro e o
# Copernicus e um arquivo fechado sobre uma janela passada.
#
# As tres series que dependem do dia -- reanalise, IPMA e o balanco hidrico que
# le a reanalise -- ficam FORA da exigencia, cada uma pela sua razao, e somar
# tudo num total unico transformava a variacao normal de qualquer uma delas num
# alarme sobre as outras.
TOTAL_REPRODUZIVEL = 139

# as tres proveniencias que dependem do dia em que o script correr
ORIGENS_QUE_DEPENDEM_DO_DIA = ("reanalysis", "weather_observed", "simulated")

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


def confirmar(database_url: str, alvo: str | None, assumir_sim: bool) -> None:
    """Diz para onde vai escrever, e so avanca com autorizacao explicita."""
    print("Reposicao dos dados de desenvolvimento do ReSoilTwin")
    if alvo is None:
        print(f"  base de destino : {url_sem_segredo(database_url)}")
        print("  API             : uvicorn temporario, arrancado por este script")
    else:
        # No modo remoto a base local NAO e o destino, e dize-lo pelo mesmo
        # rotulo era o erro que este ecra existe para impedir. O destino e a
        # API; a base local so e lida.
        print(f"  API de destino  : {alvo}")
        print(f"  base local (SO LEITURA da campanha de campo): {url_sem_segredo(database_url)}")
    print(f"  janela EO       : {DATE_FROM} a {DATE_TO}")
    print(f"  janela meteo    : {WEATHER_DATE_FROM} a {WEATHER_DATE_TO}")
    print(f"  capacidades AWC : {', '.join(f'{c:g} mm' for c in AWC_MM)}")
    print(f"  geometrias      : {AOI_DIR}")
    print()
    print("Este script ESCREVE neste destino. Confirma que e o destino certo antes de continuar.")
    if assumir_sim:
        print("  --yes dado na linha de comando: a avancar.\n")
        return
    if not sys.stdin.isatty():
        raise FalhaDaReposicao(
            "sem terminal para pedir confirmacao e sem --yes. Recuso escrever as cegas: "
            "voltar a correr com --yes depois de confirmar o destino acima."
        )
    resposta = input("Escrever neste destino? [escrever 'sim' para continuar] ").strip().lower()
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


def ler_campo_da_base_local(sessao_factory) -> tuple[list[dict], list[dict], dict]:
    """Le a campanha de campo da base LOCAL, para a escrever noutro sitio.

    **So `SELECT`.** Esta funcao existe para o modo `--api-base-url`, onde o
    seed nao pode correr: o seed escreve directamente na base a que ESTE
    processo esta ligado, que nesse modo e a local -- ou seja, correr o seed
    repunha a base de onde os dados ja estao em vez do alvo.

    Le da base e nao do modulo do seed de proposito. O que tem de chegar ao
    alvo e o que esta gravado, valor a valor, e nao o que um ficheiro diz que
    devia estar: se as duas coisas divergirem, a que se pode defender e a que
    tem historia. E o proprio seed ja ajustou um minuto de uma leitura para
    desambiguar duas linhas -- isso esta na base, com a nota que o explica.

    Devolve (parcelas, observacoes, avisos). Os avisos contam o que **nao**
    cabe no corpo de `ObservationCreate` e por isso nao viaja por HTTP.
    """
    from sqlalchemy import select

    from resoiltwin.models import Instrument, Observation, Plot, Site

    sessao = sessao_factory()
    try:
        parcelas = [
            {"site_code": site_code, "corpo": {"code": p.code, "name": p.name, "purpose": p.purpose}}
            for p, site_code in sessao.execute(
                select(Plot, Site.code).join(Site, Plot.site_id == Site.id).order_by(Plot.code)
            )
        ]

        linhas = sessao.execute(
            select(Observation, Site.code, Plot.code, Instrument.code)
            .join(Site, Observation.site_id == Site.id)
            .outerjoin(Plot, Observation.plot_id == Plot.id)
            .outerjoin(Instrument, Observation.instrument_id == Instrument.id)
            .where(Observation.source_type.in_(("observed_screening", "derived")))
            .order_by(Observation.observed_at, Observation.metric, Plot.code)
        ).all()

        observacoes = []
        instrumentos_perdidos: set[str] = set()
        derivados_sem_ligacao = 0
        for obs, site_code, plot_code, instrument_code in linhas:
            if instrument_code:
                # Nao ha `POST /instruments`. Mandar `instrument_code` daria
                # 404 e a linha nao entrava de todo -- perder a coluna e menos
                # mau do que perder a leitura, mas so se for dito.
                instrumentos_perdidos.add(instrument_code)
            if obs.derived_from:
                derivados_sem_ligacao += 1
            observacoes.append({
                "site_code": site_code,
                "plot_code": plot_code,
                "observed_at": obs.observed_at.isoformat(),
                "metric": obs.metric,
                "unit": obs.unit,
                "value_numeric": obs.value_numeric,
                "value_min": obs.value_min,
                "value_max": obs.value_max,
                "value_text": obs.value_text,
                "value_qualifier": obs.value_qualifier,
                "source_type": obs.source_type,
                "quality_flag": obs.quality_flag,
                "source_collection": obs.source_collection,
                "processing_version": obs.processing_version,
                "method": obs.method,
                "notes": obs.notes,
                "evidence": obs.evidence,
            })
        avisos = {
            "instrumentos_sem_rota": sorted(instrumentos_perdidos),
            "derivados_sem_derived_from": derivados_sem_ligacao,
        }
        return parcelas, observacoes, avisos
    finally:
        sessao.close()


def esperar_servidor(cliente: httpx.Client, processo: subprocess.Popen | None) -> None:
    """Espera pelo /health, e desiste se o uvicorn morrer entretanto.

    Sem a segunda condicao, um servidor que rebentasse no arranque (porta
    ocupada, base inacessivel) deixava o script a bater no relogio ate ao
    timeout e a reportar "nao arrancou a tempo" em vez do erro real.

    Com `processo` a None -- o modo remoto -- nao ha nada para vigiar: a mesma
    espera serve de confirmacao de que a API do outro lado responde antes de
    lhe ser pedida a primeira escrita.
    """
    limite = time.monotonic() + _ARRANQUE_TIMEOUT_S
    while time.monotonic() < limite:
        if processo is not None and processo.poll() is not None:
            raise FalhaDaReposicao(
                f"o uvicorn terminou com codigo {processo.returncode} antes de responder. "
                "Ver a saida acima: normalmente e a base inacessivel ou a porta ocupada."
            )
        try:
            resposta = cliente.get("/health", timeout=5.0)
        except httpx.TransportError:
            time.sleep(0.2)
            continue
        if resposta.status_code == 200:
            return
        time.sleep(0.2)
    onde = "o uvicorn" if processo is not None else "a API de destino"
    raise FalhaDaReposicao(f"{onde} nao respondeu ao /health em {_ARRANQUE_TIMEOUT_S:.0f}s.")


def _exigir(resposta: httpx.Response, esperado: int, o_que: str) -> dict:
    if resposta.status_code != esperado:
        raise FalhaDaReposicao(
            f"{o_que}: esperava HTTP {esperado}, veio {resposta.status_code} - {resposta.text[:400]}"
        )
    return resposta.json()


def _job_depois_da_ligacao_cair(
    cliente: httpx.Client, job_type: str, desde: datetime, o_que: str
) -> dict:
    """A ligacao caiu; o trabalho do outro lado nao parou. Vai buscar o job.

    Uma sincronizacao da reanalise sao seis pedidos ao Climate Data Store em
    serie e demora minutos. Contra um uvicorn local isso nao tem consequencia
    nenhuma, mas contra uma instalacao atras de uma entrada HTTP gerida -- a
    dos Azure Container Apps corta uma ligacao parada ao fim de 240 s -- o
    pedido perde a resposta a meio de uma execucao que continua e que acaba
    por gravar.

    Tratar isso como falha era escrever no relatorio uma falha que a base
    desmente; assumir sucesso era o erro simetrico e pior. O que se faz e o
    que o resto do script ja faz: **vai-se ler o `status` do job**, pela rota
    que existe para isso. So se le um job comecado depois do momento em que
    este pedido saiu, senao a corrida anterior do mesmo tipo respondia por esta.
    """
    limite = time.monotonic() + _METEO_TIMEOUT_S
    while time.monotonic() < limite:
        jobs = _exigir(
            cliente.get("/jobs", params={"job_type": job_type, "limit": 10}, timeout=60.0),
            200, f"{o_que}: ler a listagem de jobs depois de a ligacao cair",
        )
        recentes = [
            job for job in jobs
            if datetime.fromisoformat(job["started_at"].replace("Z", "+00:00")) >= desde
        ]
        if recentes:
            # a listagem vem do mais recente para o mais antigo
            job = recentes[0]
            if job["status"] in ("succeeded", "failed"):
                return job
        time.sleep(15)
    raise FalhaDaReposicao(
        f"{o_que}: a ligacao caiu e nao apareceu nenhum job de '{job_type}' terminado nos "
        f"{_METEO_TIMEOUT_S / 60:.0f} minutos seguintes. Nao se sabe se a execucao correu: "
        "ler `GET /jobs` antes de repetir, para nao correr por cima de uma que esteja viva."
    )


def _pedir_sync(
    cliente: httpx.Client, caminho: str, corpo: dict, timeout: float, o_que: str, job_type: str
) -> dict:
    """Pede uma sincronizacao e devolve o job, mesmo que a ligacao nao aguente.

    Um 502/503/504 aqui e a ENTRADA a desistir, nao a aplicacao: a resposta nao
    vem do servidor que esta a fazer o trabalho. E `ReadTimeout` e o mesmo do
    lado de ca. Nos dois casos a unica coisa honesta e ir perguntar a base como
    e que aquilo acabou.
    """
    desde = datetime.now(timezone.utc) - timedelta(seconds=5)
    try:
        resposta = cliente.post(caminho, json=corpo, timeout=timeout)
    except (httpx.ReadTimeout, httpx.RemoteProtocolError) as erro:
        print(f"  (ligacao caiu em '{o_que}': {type(erro).__name__}; a ler o job pela rota)")
        return _job_depois_da_ligacao_cair(cliente, job_type, desde, o_que)
    # 502 e 504 e so. O **503 fica de fora de proposito**: e o codigo com que a
    # propria aplicacao recusa tudo quando nao tem chave configurada
    # (`api/auth.py`), e trata-lo como ligacao caida punha o script a procurar
    # um job que nunca foi criado em vez de dizer que a instalacao esta sem
    # segredo.
    if resposta.status_code in (502, 504):
        print(f"  (a entrada devolveu {resposta.status_code} em '{o_que}'; a ler o job pela rota)")
        return _job_depois_da_ligacao_cair(cliente, job_type, desde, o_que)
    return _exigir(resposta, 202, o_que)


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


def publicar_campo(cliente: httpx.Client, parcelas: list[dict], observacoes: list[dict]) -> dict:
    """Escreve a campanha de campo pelas rotas HTTP, linha a linha.

    Um 409 nao e erro: e a linha ja la estar, e uma reposicao repetida nao pode
    falhar por isso. Qualquer outro codigo para tudo, com o corpo da resposta a
    vista -- uma linha recusada por um CHECK e uma linha que nao pode ser
    contornada em silencio.
    """
    for parcela in parcelas:
        resposta = cliente.post(f"/sites/{parcela['site_code']}/plots", json=parcela["corpo"])
        if resposta.status_code == 409:
            print(f"  parcela {parcela['corpo']['code']}: ja existia")
        else:
            _exigir(resposta, 201, f"criar a parcela {parcela['corpo']['code']}")
            print(f"  parcela {parcela['corpo']['code']}: criada")

    escritas = repetidas = 0
    for corpo in observacoes:
        resposta = cliente.post("/observations", json=corpo)
        if resposta.status_code == 409:
            repetidas += 1
            continue
        _exigir(
            resposta, 201,
            f"escrever {corpo['metric']} de {corpo['observed_at']} ({corpo['source_type']})",
        )
        escritas += 1
    print(f"  observacoes: {escritas} escritas, {repetidas} ja existiam")
    return {"escritas": escritas, "repetidas": repetidas}


def sincronizar(cliente: httpx.Client) -> list[dict]:
    """Corre as quatro sincronizacoes e LE o status de cada uma.

    Um 202 nao e sucesso: `sync_aoi()` nao propaga falhas de execucao, devolve
    o job com status 'failed' e o erro gravado. Um script que so olhasse para o
    codigo HTTP dava a reposicao por feita com a base a meio.
    """
    jobs = []
    for site_code, aoi_code, mascara in SYNCS:
        rotulo = "v2 (scl_mask=true)" if mascara else "v1 (scl_mask=false)"
        job = _pedir_sync(
            cliente, f"/sites/{site_code}/eo/sync",
            {
                "aoi_code": aoi_code, "date_from": DATE_FROM, "date_to": DATE_TO,
                "scl_mask": mascara,
            },
            _SYNC_TIMEOUT_S, f"sincronizar {aoi_code} {rotulo}", "eo_sync",
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
            job = _pedir_sync(
                cliente, f"/sites/{site_code}/weather/sync", corpo, _METEO_TIMEOUT_S,
                f"sincronizar {rotulo} de {site_code}",
                "reanalysis_sync" if rotulo == "reanalysis" else "ipma_sync",
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


def sincronizar_balanco_hidrico(cliente: httpx.Client) -> list[dict]:
    """Corre o balanco hidrico de cada sitio nas tres capacidades da Fase D.

    Depende do passo anterior e nao ha maneira de o contornar: o balanco le a
    precipitacao e a evapotranspiracao de referencia que a reanalise gravou. Se
    a reanalise vier curta, o balanco vem curto atras dela -- e por isso o
    numero de linhas daqui tambem esta fora da contagem exigida.

    Mesma disciplina das outras duas: um 202 nao e sucesso, le-se o `status`.
    """
    jobs = []
    for site_code in SITIOS_METEO:
        for capacidade in AWC_MM:
            job = _pedir_sync(
                cliente, f"/sites/{site_code}/water/sync",
                {
                    "date_from": WEATHER_DATE_FROM, "date_to": WEATHER_DATE_TO,
                    "available_water_capacity_mm": capacidade,
                },
                _SYNC_TIMEOUT_S, f"balanco hidrico de {site_code} com {capacidade:g} mm",
                "water_balance_sync",
            )
            print(
                f"  {site_code} awc={capacidade:g}mm: status={job['status']} "
                f"rows_written={job['rows_written']} version={job['processing_version']} "
                f"janela={job['date_from']}..{job['date_to']}"
            )
            if job["status"] != "succeeded":
                raise FalhaDaReposicao(
                    f"o balanco hidrico de {site_code} com {capacidade:g} mm veio "
                    f"'{job['status']}' e nao 'succeeded'. Erro gravado: {job['error']}."
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


def contagem_pela_api(cliente: httpx.Client) -> list[tuple]:
    """A mesma contagem, mas perguntada ao alvo em vez da base local.

    No modo remoto a base do destino nao tem endereco publico -- esta numa rede
    privada -- e contar na base local para dar a reposicao por feita seria
    verificar o registo do script contra ele proprio. Isto pergunta ao alvo.

    Agrupa por proveniencia e nao por `processing_version`: a listagem filtra
    por `source_type` e devolve o `total` que casa com o filtro sem trazer
    linha nenhuma (`limit=0`), o que da a contagem certa sem paginar milhares
    de linhas. A versao de processamento nao e um filtro desta rota, e
    inventar-lhe um percurso de paginacao so para a obter era construir uma
    segunda contagem, com a sua propria maneira de estar errada.
    """
    from resoiltwin.enums import SourceType

    por_origem: dict[str, int] = {}
    for site in SITES:
        for origem in SourceType:
            resposta = _exigir(
                cliente.get(
                    f"/sites/{site['code']}/observations",
                    params={"source_type": origem.value, "limit": 0},
                ),
                200, f"contar {origem.value} em {site['code']}",
            )
            if resposta["total"]:
                por_origem[origem.value] = por_origem.get(origem.value, 0) + resposta["total"]
    return [(origem, "(por proveniencia)", quantas) for origem, quantas in sorted(por_origem.items())]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Repoe os dados de desenvolvimento do ReSoilTwin na base configurada.",
    )
    parser.add_argument(
        "--yes", action="store_true",
        help="confirma a escrita sem perguntar. Ler primeiro o destino que o script imprime.",
    )
    parser.add_argument(
        "--port", type=int, default=None,
        help="porta do uvicorn temporario (por omissao, uma porta livre pedida ao SO).",
    )
    parser.add_argument(
        "--api-base-url", default=None,
        help=(
            "escreve por esta API em vez de arrancar um uvicorn local. Com esta opcao a "
            "base local so e LIDA, para trazer de la a campanha de campo."
        ),
    )
    parser.add_argument(
        "--api-key-env", default="WRITE_API_KEY",
        help=(
            "nome da variavel de ambiente de onde sai a chave da API de destino. A chave "
            "e lida do ambiente e nunca e escrita nem impressa."
        ),
    )
    argumentos = parser.parse_args()

    from resoiltwin.api.auth import NOME_DO_CABECALHO
    from resoiltwin.config import get_settings
    from resoiltwin.db import SessionLocal

    definicoes = get_settings()
    alvo = argumentos.api_base_url.rstrip("/") if argumentos.api_base_url else None
    remoto = alvo is not None
    try:
        confirmar(definicoes.database_url, alvo, argumentos.yes)
    except FalhaDaReposicao as erro:
        print(f"\n{erro}", file=sys.stderr)
        return 2

    # Este script trabalha pelas ROTAS HTTP, e todas elas passaram a exigir a
    # chave partilhada menos o /health (31/08/2026, decisoes 7 e 2). Sem ela o
    # uvicorn arranca na mesma -- a chave nao impede o arranque, de proposito --
    # e cada pedido responderia 503; a reposicao morreria no primeiro `_exigir`
    # com uma mensagem sobre um codigo HTTP em vez da causa. Verifica-se aqui,
    # antes de arrancar seja o que for.
    #
    # No modo remoto a chave nao e a do `.env` local: e a da instalacao de
    # destino, e vem do ambiente pelo nome que `--api-key-env` disser. Usar a
    # local contra outra instalacao dava 401 em tudo, e a mensagem falaria de
    # um ficheiro que nao tem nada a ver com o alvo.
    chave = os.environ.get(argumentos.api_key_env) if remoto else definicoes.write_api_key
    if not chave:
        if remoto:
            print(
                f"\n{argumentos.api_key_env} nao esta definida no ambiente, e e de la que "
                "sai a chave da API de destino.\nCarregar o ficheiro de segredos da "
                "instalacao antes de correr (`set -a; source ...; set +a`).",
                file=sys.stderr,
            )
        else:
            print(
                "\nWRITE_API_KEY nao esta definida, e este script escreve pelas rotas HTTP.\n"
                "Define-a no .env (ver .env.example) antes de repor os dados.",
                file=sys.stderr,
            )
        return 2

    porta = argumentos.port or porta_livre()
    processo = None
    base_url = f"{alvo}/api/v1" if remoto else f"http://127.0.0.1:{porta}/api/v1"
    try:
        if remoto:
            print(f"1/6  a falar com a API de {alvo}")
        else:
            print(f"1/6  a arrancar o uvicorn em 127.0.0.1:{porta}")
            processo = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "resoiltwin.main:app",
                 "--host", "127.0.0.1", "--port", str(porta), "--log-level", "warning"],
                cwd=str(ROOT),
                env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
            )
        with httpx.Client(
            base_url=base_url,
            timeout=60.0,
            headers={NOME_DO_CABECALHO: chave},
        ) as cliente:
            esperar_servidor(cliente, processo)
            print("  servidor a responder")

            print("\n2/6  sites e AOI, pelas rotas HTTP")
            criar_sites_e_aois(cliente)

            print("\n3/6  campanha de campo de Turcifal")
            if remoto:
                parcelas, observacoes, avisos = ler_campo_da_base_local(SessionLocal)
                print(f"  lidas da base local: {len(parcelas)} parcelas, "
                      f"{len(observacoes)} observacoes (so SELECT)")
                publicar_campo(cliente, parcelas, observacoes)
                if avisos["instrumentos_sem_rota"]:
                    print(
                        "  ⚠️  sem rota HTTP para instrumentos: "
                        f"{', '.join(avisos['instrumentos_sem_rota'])} nao viaja, e as linhas "
                        "de campo chegam com instrument_id a NULL"
                    )
                if avisos["derivados_sem_derived_from"]:
                    print(
                        f"  ⚠️  {avisos['derivados_sem_derived_from']} linhas derivadas perdem "
                        "`derived_from` (nao e campo de ObservationCreate); o `evidence` com os "
                        "numeros de entrada viaja inteiro"
                    )
            else:
                print(f"  {semear(SessionLocal)}")

            print("\n4/6  sincronizacoes Copernicus, pelas rotas HTTP")
            sincronizar(cliente)

            print("\n5/6  sincronizacoes meteorologicas, pelas rotas HTTP")
            print("  (a reanalise sao seis pedidos ao CDS por sitio; conta com minutos)")
            sincronizar_meteorologia(cliente)

            print("\n6/6  balanco hidrico, pelas rotas HTTP")
            sincronizar_balanco_hidrico(cliente)

            print("\nobservacoes no destino, por proveniencia:")
            linhas = contagem_pela_api(cliente) if remoto else contagem(SessionLocal)
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

    total = 0
    por_origem: dict[str, int] = {}
    for source_type, versao, quantas in linhas:
        print(f"  {source_type:<20} {versao:<40} {quantas}")
        total += quantas
        por_origem[str(source_type)] = por_origem.get(str(source_type), 0) + quantas
    print(f"  {'total':<61} {total}")

    da_reanalise = por_origem.get("reanalysis", 0)
    do_ipma = por_origem.get("weather_observed", 0)
    do_balanco = por_origem.get("simulated", 0)
    reproduzivel = total - sum(por_origem.get(o, 0) for o in ORIGENS_QUE_DEPENDEM_DO_DIA)

    print("\nas tres series que dependem do dia, fora da conta reproduzivel:")
    print(f"  reanalise (AgERA5)   {da_reanalise:>4} de {REANALISE_QUANDO_COMPLETA} "
          "quando o arquivo tiver a janela toda publicada")
    print(f"  estacao (IPMA)       {do_ipma:>4} sem numero esperado: a origem so publica "
          "as ultimas 24 h")
    print(f"  balanco hidrico      {do_balanco:>4} sem numero esperado: le a reanalise, "
          "e acompanha o que ela cobrir")
    if da_reanalise < REANALISE_QUANDO_COMPLETA:
        em_falta = REANALISE_QUANDO_COMPLETA - da_reanalise
        print(f"  -> faltam {em_falta} linhas de reanalise. O caso normal e o atraso de "
              "publicacao do AgERA5; cada job diz no seu `date_to` ate onde chegou.")

    if reproduzivel != TOTAL_REPRODUZIVEL:
        print(
            f"\nATENCAO: esperavam-se {TOTAL_REPRODUZIVEL} observacoes reproduziveis "
            f"(campo, derivadas e Copernicus) e o destino tem {reproduzivel}. "
            "A reposicao correu sem erro, portanto a diferenca esta nos dados devolvidos "
            "pelo Copernicus, nao no script -- comparar com a nota de evidencia antes de "
            "dar a base por reposta. As tres series que dependem do dia estao fora desta "
            "conta de proposito, e a razao esta impressa acima.",
            file=sys.stderr,
        )
        return 1

    print("\nbase reposta.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
