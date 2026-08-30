"""Ronda da Task 4 da Fase D: a rota do balanco hidrico.

Onze mutantes sobre a porta de fora, e sobre os dois sitios de onde ela pode
mentir sem que nada rebente:

- **o 202 que esconde uma falha** (`h2`). E o defeito que esta rota existe para
  nao ter: um pedido aceite e processado responde 202 mesmo quando o resultado
  e mau, e o `status` no corpo e a unica coisa que separa "a serie ficou
  gravada" de "nao ficou nada". Um cliente que leia so o codigo HTTP perde uma
  ingestao inteira -- ja aconteceu neste projecto.
- **a capacidade que ninguem mediu** (`c1`--`c4`). Ela chega pelo corpo do
  pedido, entra na identidade da linha e viaja no `evidence`. Uma rota que a
  ignorasse, que lhe desse omissao, ou que corrigisse em silencio um valor
  impossivel, decidia as escuras o numero que DOMINA o resultado.

Os tres ultimos (`j1`, `j2`) nao mudam ficheiros desta tarefa: mudam
`water/ingest.py`. Nao e engano. A rota afirma pela porta de fora duas coisas
que sao implementadas la dentro -- a janela que o job declara, e o dia
indeterminado que sai como intervalo -- e um teste meu que nenhum mutante mate
e um teste por medir, mesmo que outra ronda ja tenha medido a mesma linha.
"""

MUTANTES = [
    # --- a porta existe mesmo -------------------------------------------------
    ("m1",
     "src/resoiltwin/main.py",
     '    app.include_router(water.router, prefix="/api/v1")',
     None,
     "create_app",
     "o balanco fica sem porta de fora: a rota existe mas nao esta montada"),

    # --- o contrato do 202 ----------------------------------------------------
    ("h1",
     "src/resoiltwin/api/water.py",
     "    status_code=status.HTTP_202_ACCEPTED,",
     "    status_code=status.HTTP_200_OK,",
     "(modulo)",
     "correr um balanco passa a responder 200, como se fosse uma leitura"),
    ("h2",
     "src/resoiltwin/api/water.py",
     "    return job",
     '    job.status = job.status.__class__("succeeded"); return job',
     "sync_water",
     "o 202 esconde o job falhado e devolve-o a dizer sucesso"),

    # --- as duas recusas antes do job nao se confundem ------------------------
    ("a1",
     "src/resoiltwin/api/water.py",
     "    _garantir_que_o_sitio_existe(session, code)",
     None,
     "sync_water",
     "um sitio inexistente deixa de ser 404 e passa por sitio mal configurado"),
    ("a2",
     "src/resoiltwin/api/water.py",
     "        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc",
     "        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc",
     "sync_water",
     "um sitio sem AOI aprovada passa por sitio inexistente"),

    # --- a capacidade utilizavel: chega do corpo, e ninguem a mediu -----------
    ("c1",
     "src/resoiltwin/api/water.py",
     "            payload.available_water_capacity_mm,",
     "            100.0,",
     "sync_water",
     "a capacidade do corpo do pedido e ignorada e a rota usa um numero seu"),
    ("c2",
     "src/resoiltwin/schemas/water.py",
     "    available_water_capacity_mm: float",
     "    available_water_capacity_mm: float = 100.0",
     "WaterSyncRequest",
     "a capacidade ganha valor por omissao: quem nao a escrever fica com um "
     "numero inventado a dominar o resultado"),
    ("c3",
     "src/resoiltwin/schemas/water.py",
     "        Solo(capacidade_utilizavel_mm=self.available_water_capacity_mm)",
     None,
     "_o_pedido_tem_de_ser_corrivel",
     "a capacidade impossivel deixa de ser recusada no corpo e desce ate ao "
     "sincronizador, saindo como 409 em vez de 422"),
    ("c4",
     "src/resoiltwin/schemas/water.py",
     "        Solo(capacidade_utilizavel_mm=self.available_water_capacity_mm)",
     "        Solo(capacidade_utilizavel_mm=abs(self.available_water_capacity_mm) or 1.0)",
     "_o_pedido_tem_de_ser_corrivel",
     "uma capacidade impossivel e corrigida em silencio em vez de recusada"),

    # --- a janela ------------------------------------------------------------
    ("w1",
     "src/resoiltwin/schemas/water.py",
     "        if self.date_from > self.date_to:",
     "        if False:",
     "_o_pedido_tem_de_ser_corrivel",
     "a janela invertida deixa de ser recusada no corpo do pedido"),

    # --- o que a rota afirma e `water/ingest.py` implementa -------------------
    ("j1",
     "src/resoiltwin/water/ingest.py",
     "        job.date_from, job.date_to = dias[0], dias[-1]",
     None,
     "sync_water_balance",
     "o job devolvido declara a janela PEDIDA em vez da que balancou"),
    ("j2",
     "src/resoiltwin/water/ingest.py",
     "    determinado = dia.determinado",
     "    determinado = True",
     "_observacao_de_agua",
     "o dia indeterminado sai pela rota como valor exacto com o minimo do "
     "intervalo: o estado inicial do reservatorio reinventado pela porta de tras"),
]
