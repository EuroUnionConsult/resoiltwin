"""O corpo do pedido de sincronizacao meteorologica.

As duas fontes nao pedem a mesma coisa, e e essa assimetria que este ficheiro
existe para tornar visivel. A reanalise tem arquivo e aceita uma janela; as
estacoes do IPMA nao tem -- o feed e um URL fixo que devolve sempre as ultimas
24 horas e nao leva parametro de data nenhum.
"""

from datetime import date
from enum import StrEnum

from pydantic import BaseModel, model_validator


class WeatherSource(StrEnum):
    """Qual das duas ingestoes correr.

    Nao e o `SourceType` da base, apesar de `reanalysis` coincidir. Este enum
    escolhe uma EXECUCAO (que cliente, que janela, que versao de
    processamento); o `SourceType` classifica um VALOR ja gravado, e o valor
    que vem do IPMA fica como `weather_observed`, nao como `ipma`. Colar os
    dois vocabularios obrigava um deles a mentir.
    """

    reanalysis = "reanalysis"
    ipma = "ipma"


class WeatherSyncRequest(BaseModel):
    source: WeatherSource
    # anulaveis os dois, e nao obrigatorios como no pedido de satelite: a
    # obrigatoriedade depende da fonte e e o validador abaixo que a aplica.
    date_from: date | None = None
    date_to: date | None = None

    @model_validator(mode="after")
    def _a_janela_tem_de_servir_a_fonte(self):
        if self.source is WeatherSource.ipma:
            # Recusar, e nao ignorar em silencio. Aceitar
            # `date_from`/`date_to` aqui e devolver 202 dizia ao cliente que a
            # janela dele foi atendida; o job que ele receberia declara a
            # janela das ultimas 24 horas, que nao e a que ele pediu, e o
            # arquivo que ele julga ter pedido nao existe em lado nenhum. Uma
            # recusa custa-lhe um pedido; o silencio custa-lhe a confianca em
            # todas as series que ele julga ter arquivadas.
            dados = [nome for nome, valor in
                     (("date_from", self.date_from), ("date_to", self.date_to))
                     if valor is not None]
            if dados:
                raise ValueError(
                    f"source 'ipma' does not take a window ({', '.join(dados)} given). The IPMA "
                    "open-data feed has no date parameter: it always publishes the last 24 hours. "
                    "Accepting a window here would promise an archive that does not exist."
                )
            return self

        em_falta = [nome for nome, valor in
                    (("date_from", self.date_from), ("date_to", self.date_to)) if valor is None]
        if em_falta:
            raise ValueError(
                f"source 'reanalysis' requires a window: {', '.join(em_falta)} missing. "
                "The Climate Data Store request is built from the window; without one there is "
                "no series to ask for."
            )
        # mesma regra do pedido de satelite, e pela mesma razao: recusar aqui
        # com 422 e mais barato do que criar um job so para ele falhar por uma
        # janela invertida, e deixa a base sem um `failed` de uma execucao que
        # nunca devia ter comecado.
        if self.date_from > self.date_to:
            raise ValueError("date_from must not be after date_to")
        return self
