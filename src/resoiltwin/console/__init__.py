"""A consola: tres vistas de leitura sobre o que esta na base.

    navegador  ->  paginas (aqui)  ->  camada que guarda a chave  ->  API

Este pacote **desenha**; nao le a base e nao fala com a API. Os dados chegam-lhe
pela camada da Task 1 (`resoiltwin.api.console.ler`), que e o unico sitio deste
repositorio onde a chave e apresentada e o unico onde as geometrias e as
coordenadas sao cortadas. Uma pagina que fosse buscar dados por outro caminho
perdia as duas garantias de uma vez, e por isso nao ha aqui nem uma sessao de
base de dados nem um cliente HTTP.

**Desenhada no servidor, e sem uma linha de JavaScript.** Nao e nostalgia: o que
o navegador recebe e o HTML final, e o HTML final ja passou pelo filtro. Sem
script nao ha nada no navegador que possa ir buscar mais do que lhe foi dado, e
o unico pedido que a pagina faz e o da propria folha de estilo -- que e servida
por nos. O contentor pode nao ter saida para a internet, e nao precisa de ter.

As regras de desenho estao em `paleta.py` (a cor), `formato.py` (a forma de um
valor) e `estilo.py` (a folha). Nenhuma delas e uma preferencia:

- **solido = medido na parcela, tramado = nao.** Vale em toda a interface, e a
  trama e um canal independente da cor, porque cerca de 8% dos homens tem
  dificuldade com vermelho/verde;
- **um intervalo desenha-se como intervalo**, nunca como o meio dele;
- **uma leitura saturada mostra-se como um limite**, nunca como um valor;
- **a moldura e neutra e fria; a cor esta so nos dados**, e vem do dominio:
  matiz 10YR para a proveniencia, castanho para verde na vegetacao, seco para
  humido na agua. Nunca arco-iris.
"""
