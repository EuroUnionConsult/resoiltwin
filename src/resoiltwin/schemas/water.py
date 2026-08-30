"""O corpo do pedido de sincronizacao do balanco hidrico.

Tres campos, todos obrigatorios, e o terceiro e o que este ficheiro existe
sobretudo para defender.

**A capacidade de agua utilizavel do solo nao tem valor por omissao, e nao pode
vir a ter.** Nao ha analise de solo destes terrenos neste projecto: o numero
nao esta medido, e e ele que DOMINA o resultado do balanco. Um valor por
omissao aqui seria um numero inventado a decidir em silencio o que sai de todas
as corridas de quem nao o escrever -- e o `evidence` da linha continuaria a
declarar uma capacidade, dando-lhe o ar de escolha deliberada que ela nao teve.
Obrigar quem chama a escreve-la nao a torna verdadeira; torna-a **atribuivel**,
que e tudo o que se pode fazer enquanto ninguem a medir.

A regra do que e uma capacidade admissivel **nao esta aqui**. E a do modelo
(`water.balance.Solo`), chamada a partir daqui. Reescrever `gt=0` neste
ficheiro criava uma segunda fronteira sobre o mesmo numero, e duas fronteiras
divergem no dia em que uma delas mudar -- exactamente a razao por que
`water.ingest` tambem nao a reescreve. O que este validador acrescenta nao e a
regra: e o MOMENTO em que ela corre. Uma capacidade impossivel e uma
propriedade do corpo do pedido, decidivel sem tocar na base, e por isso sai
como 422 como a janela invertida, em vez de descer ate ao sincronizador e sair
como um 409 que diria que o problema estava no estado do sitio.
"""

from datetime import date

from pydantic import BaseModel, model_validator

from resoiltwin.water.balance import Solo


class WaterSyncRequest(BaseModel):
    date_from: date
    date_to: date
    # sem omissao, de proposito -- ver o docstring do modulo. O nome e o mesmo
    # com que o valor viaja no `evidence` de cada linha gravada
    # (`available_water_capacity_mm`), para que quem le a linha e quem faz o
    # pedido usem a mesma palavra para a mesma coisa.
    available_water_capacity_mm: float

    @model_validator(mode="after")
    def _o_pedido_tem_de_ser_corrivel(self):
        # mesma regra e mesma razao das outras duas rotas de sincronizacao:
        # recusar aqui com 422 e mais barato do que criar um job so para ele
        # falhar por uma janela invertida, e deixa a base sem um `failed` de
        # uma execucao que nunca devia ter comecado.
        if self.date_from > self.date_to:
            raise ValueError("date_from must not be after date_to")
        # a guarda do MODELO, chamada aqui, e nao uma copia dela. O valor
        # construido e deitado fora: o que interessa e a excepcao que ele
        # levanta, e o sincronizador volta a construir o seu a partir do mesmo
        # numero. Uma segunda instancia custa nada; uma segunda REGRA custava
        # a coerencia entre o que a API recusa e o que o modelo aceita.
        Solo(capacidade_utilizavel_mm=self.available_water_capacity_mm)
        return self
