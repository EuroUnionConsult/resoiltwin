# Arnes de mutacao

Mede o que a suite de testes **apanha**. Muda uma linha do codigo de producao,
corre a suite inteira, e pergunta se algum teste caiu. Se nenhum caiu, o
mutante *sobreviveu*: ha comportamento que ninguem esta a defender.

Este ficheiro esta em portugues porque tudo o que o rodeia -- `docs/evidence/`,
os comentarios de codigo, as notas de ronda -- tambem esta. O README principal
do repositorio esta em ingles porque se dirige a quem le o produto; este
dirige-se a quem vai correr uma ronda.

## Correr

```sh
python tools/mutacao/arnes.py tools/mutacao/rondas/<ronda>.py
python tools/mutacao/arnes.py <ronda>.py --so a b c     # so estes mutantes
python tools/mutacao/arnes.py <ronda>.py --manter       # nao apagar a copia
python tools/mutacao/arnes.py <ronda>.py --timeout-do-mutante 120
```

Nada e escrito na arvore real: o arnes copia o repositorio para um directorio
temporario e muta la. A raiz do repositorio e derivada do `pyproject.toml`, e o
interpretador e o que estiver a correr o arnes (`sys.executable`) -- ambos
podem ser passados a mao (`--raiz`, `--python`).

Codigos de saida: `0` tudo morto, `1` ha sobreviventes ou mortes por
inspeccionar, `2` uma guarda disparou e a ronda nao chegou a medir nada.

**Estado partilhado: ja nao ha.** Ate 30/08/2026 a copia era uma arvore
separada mas a suite que la corria usava a MESMA base de dados que a suite
local -- o `conftest.py` fixava o nome `resoiltwin_test` e comecava por lhe
fazer `DROP DATABASE`. Uma ronda e um `pytest` ao lado atropelavam-se, e os
resultados que dai saissem nao valiam nada. Isto estava escrito aqui como
regra, e uma regra escrita nao e uma guarda.

Hoje cada corrida da suite cria a sua propria base, com o pid e uns digitos
aleatorios no nome, e larga-a no fim -- incluindo quando a suite falha. A ronda
e o `pytest` local deixaram de se ver um ao outro, sem que ninguem tenha de
exportar variavel nenhuma. O desenho e as duas guardas que o sustentam (a do
nome, e a que impede um `DROP` sobre uma base que a corrida nao criou) estao em
`tests/base_de_testes.py`, com os testes em `tests/test_base_de_testes.py`.

Fica na mesma uma razao para nao correr duas rondas ao mesmo tempo, mas e outra
e menos grave: cada ronda corre a suite inteira uma vez por mutante, e duas em
paralelo na mesma maquina medem sobretudo a contencao entre elas.

## O motor e permanente, a ronda e descartavel

- `arnes.py` -- o motor e as guardas. Testado em
  `tests/test_arnes_de_mutacao.py`.
- `rondas/<data>-<assunto>.py` -- a lista de mutantes de uma ronda. Serve
  aquele dia e morre com ele.

Uma ronda e um ficheiro `.py` que declara `MUTANTES` (ou um `.json` com a mesma
lista). Cada entrada tem seis campos:

```python
MUTANTES = [
    ("v2",                                       # identificador, unico na ronda
     "src/resoiltwin/weather/ingest.py",         # caminho relativo a raiz
     "    if descartadas <= 0 or escritas > 0:",  # ancora: a linha EXACTA
     "    if True:",                             # substituto (None apaga a linha)
     "_garantir_que_a_estacao_nao_mudou",        # ambito onde a linha tem de estar
     "a guarda nunca dispara"),                  # o que o mutante significa
]
```

### O que e uma ancora boa

A ancora e comparada por igualdade exacta com uma linha do ficheiro, indentacao
incluida, e **tem de aparecer uma unica vez**. Nao e uma expressao regular nem
uma pesquisa por substring: uma linha que exista duas vezes faz mutar o sitio
errado, e o "sobrevivente" que sai dai e uma leitura falsa. O arnes recusa-se a
correr nesse caso, e recusa-se tambem se a ancora ja nao existir -- o que
acontece sempre que o codigo mexe entre rondas.

O `ambito` e o nome da funcao ou classe mais interior que contem a linha, ou
`"(modulo)"` para uma linha ao nivel do modulo. E uma segunda amarra: se a
linha for unica mas estiver noutra funcao, o autor enganou-se no mutante.

### O que e um bom mutante

Um mutante devia dizer uma coisa falsa sobre o dominio ("o raio pedido pelo
chamador e ignorado", "a guarda nunca dispara"), e nao ser uma alteracao
aleatoria. A `descricao` e o que vai aparecer na tabela, e e a partir dela que
se decide se um sobrevivente e um teste em falta ou comportamento que ninguem
quer defender.

## "Morto" exige um teste caido

Um codigo de saida diferente de zero **nao** e uma morte. O arnes so declara
`morto` quando o relatorio do pytest nomeia pelo menos um teste caido
(`FAILED`, ou `ERROR` num nodeid com `::`). Um `ERROR` sobre um ficheiro
inteiro e um erro de recolha: nenhum teste correu, logo nenhum teste apanhou
nada, e o veredicto e `MORTE SUSPEITA`. Um mutante que estoire o tempo e
`TEMPO ESGOTADO`, tambem por inspeccionar -- matar por bloqueio nao e matar,
e em CI seria um build pendurado.

## As tres formas de mentir

O arnes foi a principal guarda de qualidade da Fase C: apanhou cinco testes que
nao podiam falhar e dois defeitos reais de codigo de producao. E mentiu de tres
formas diferentes **no mesmo dia**, cada uma descoberta por alguem diferente.
Quem for usar isto precisa de saber o que a ferramenta ja fez de errado.

| quando | causa | resultado |
|---|---|---|
| manha | **base vermelha** -- faltava um ficheiro na copia e um teste alheio caia sempre | **30 mutantes "mortos"** sem que nenhum teste os tivesse apanhado |
| tarde | `except Exception`, mas `pytest.fail.Exception` deriva de `BaseException` | mutantes **vivos falsos** |
| noite | mutante que **rebenta na recolha**: o pytest sai com 2 sem correr teste nenhum | **mortos falsos** outra vez |

As tres tem hoje guarda, e cada guarda tem um teste que a poe a disparar.

## As doze guardas

| # | Guarda | Nasceu de | Teste |
|---|---|---|---|
| 1 | muta numa **copia**, nunca na arvore real, com os dois lados **resolvidos** antes de comparar | um ficheiro mutado durante oito segundos e um falso alarme a espera de acontecer; e `is_relative_to` e lexical, por isso um `TMPDIR` alcancado por link simbolico (`/var` -> `/private/var`, que e o que o macOS produz por omissao) passava a guarda e punha o `copytree` a recursar a arvore real sobre si propria | `test_guarda_1_a_ronda_nao_toca_na_arvore_real`, `..._recusa_uma_arvore_de_trabalho_dentro_da_arvore_real`, `..._recusa_um_tmpdir_que_chega_a_arvore_por_link_simbolico` |
| 2 | **sabota a copia** e exige que a suite caia | um pacote instalado em modo editavel faz importar a arvore REAL, e entao todos os mutantes "sobrevivem" por uma razao que nada tem a ver com os testes | `test_guarda_2_aborta_quando_a_sentinela_nao_e_importada`, `..._prova_que_a_sabotagem_foi_mesmo_escrita`, `test_a_sentinela_deste_repositorio_e_o_pacote_e_a_suite_importa_o` |
| 3 | exige **base verde**, que recolha testes e que os corra | a mentira da manha, e as duas variantes dela pelo outro lado: uma base que nao recolhe nada, e uma base verde com tudo `skip` | `test_guarda_3_aborta_com_a_base_vermelha`, `..._quando_a_base_nao_recolhe_testes`, `..._quando_a_base_esta_verde_sem_correr_nada`, `..._quando_a_propria_base_estoira_o_tempo` |
| 4 | **ancora de linha unica** | disparou tres vezes a serio na Fase C; `job.status = JobStatus.running` passou a existir nos dois caminhos de ingestao | `test_guarda_4_recusa_uma_ancora_que_aparece_duas_vezes`, `..._que_nao_existe` |
| 5 | **`ast.parse`** do mutante | disparou duas vezes: apagar um `continue` deixava um `if` sem corpo | `test_guarda_5_recusa_um_mutante_que_nao_compila` |
| 6 | **`ast.walk`** confirma o ambito | apanhou um mutante atribuido a funcao errada | `test_guarda_6_recusa_um_ambito_declarado_errado`, `..._encontra_o_ambito_mais_interior` |
| 7 | **`timeout`** no subprocesso, com tecto proprio para o mutante | um mutante matou por bloqueio e nao por falha | `test_guarda_7_um_mutante_que_bloqueia_nao_conta_como_morto` (com o controlo negativo: sob o mesmo tecto, um mutante que nao bloqueia **nao** da `TEMPO ESGOTADO`) |
| 8 | **restauro verificado por sha256** em `finally` | uma arvore de trabalho suja torna lixo tudo o que vem a seguir | `test_guarda_8_deteta_um_restauro_falhado`, `..._o_ficheiro_mutado_volta_ao_que_era` |
| 9 | corre a **suite inteira** | quem apanha um mutante costuma viver noutro ficheiro de testes | `test_guarda_9_a_suite_inteira_apanha_o_ficheiro_de_testes_alheio` |
| 10 | **morte sem teste caido** e suspeita | a mentira da noite | `test_guarda_10_um_mutante_que_rebenta_na_recolha_nao_e_morte` |
| 11 | le o **codigo de saida de um subprocesso**, e nao uma excepcao apanhada | a mentira da tarde: nao ha `except` nenhum onde engolir um `BaseException` | `test_guarda_11_uma_falha_por_pytest_fail_conta_como_morte` |
| 12 | recusa um **mutante nulo**, comparando as **arvores** e nao o texto | um mutante que nao muda nada sobrevive sempre, e le-se como teste em falta. A igualdade literal deixava passar `LIMITE = 10 ` com um espaco a mais, ou um substituto que so mexe num comentario | `test_guarda_12_recusa_um_mutante_que_nao_muda_nada`, `..._que_so_acrescenta_um_espaco`, `..._que_so_mexe_num_comentario`, `test_um_mutante_a_serio_passa_a_guarda_12` |

Os testes montam uma **arvore de brincar** -- tres modulos e dois ficheiros de
teste -- e correm o arnes sobre ela. Nunca correm a suite real do projecto:
seriam minutos dentro da suite e uma recursao absurda. Cada guarda testa-se por
construcao, montando a arvore no estado que a faz disparar. Se um teste do
arnes demorar mais do que uns segundos, o desenho esta errado.

Duas notas sobre o alcance do que esta acima:

- os testes prendem a **mecanica** das guardas. Que
  `src/resoiltwin/__init__.py` continue a ser a sentinela certa **deste**
  repositorio esta preso a parte, por um teste proprio, porque a escolha por
  omissao e o primeiro `src/*/__init__.py` por ordem alfabetica e mudaria em
  silencio no dia em que houvesse um segundo pacote;
- o arnes normaliza os fins-de-linha para LF (`splitlines()` +
  `"\n".join(...)`). Preserva a ausencia de newline final, mas num ficheiro
  CRLF o "mutante de uma linha" reescreveria o ficheiro inteiro para LF. Sem
  efeito em Python, e este repositorio e todo LF, mas fica dito.

## O arnes sobre si proprio

`rondas/2026-08-30-arnes-sobre-si-proprio.py` desliga uma guarda de cada vez
para verificar que os testes acima nao sao vacuos. E a ronda que se volta a
correr sempre que uma guarda mudar.

Vale a pena ler a **lista de apanhados** que cada mutante imprime, e nao so a
contagem da tabela: um mutante pode morrer por dano colateral de outros testes
enquanto o teste da sua propria guarda fica de pe -- e isso e uma guarda sem
medicao, ainda que a tabela diga "morto". Foi o que aconteceu ao `g2b` na
primeira ronda.
