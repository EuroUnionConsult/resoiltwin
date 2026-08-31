# O prefixo sob o qual TODAS as rotas de dados sao servidas.
#
# Estava escrito oito vezes a mao no `main.py`, uma por `include_router`. Passou
# a ser uma constante porque deixou de ser so um detalhe de montagem: a camada
# da consola (`api/console.py`) decide o que reencaminha perguntando se o
# caminho pedido e uma rota de leitura **sob este prefixo**. Com o literal
# repetido, mudar o prefixo num sitio e nao no outro abria ou fechava a consola
# em silencio.
PREFIXO_DA_API = "/api/v1"
