"""A folha de estilo da consola, escrita a partir da paleta.

**Porque e que isto e um modulo de Python e nao um ficheiro `.css`.** A imagem
de producao instala o pacote com `pip install .`, e o `setuptools` leva os
`.py` e mais nada: um `.css` ao lado do codigo ficava de fora da imagem sem
ninguem dar por isso, e a consola chegava ao contentor sem estilo nenhum. Um
ficheiro de dados exige declara-lo no `pyproject.toml`, exige resolve-lo em
tempo de execucao e exige um teste que corra sobre a imagem construida para
provar que la esta. Escrito assim, a folha vai onde o codigo vai, por
construcao. Custo: perde-se o realce de sintaxe do editor.

**E as cores vem da paleta, e nao estao escritas aqui.** Um valor hexadecimal
repetido nos dois sitios diverge, e a divergencia numa cor de dados e uma
mentira silenciosa -- a mancha deixa de querer dizer o que a escala diz.
"""

from resoiltwin.console import paleta

_ORDEM_DAS_ORIGENS = tuple(origem.value for origem in paleta.ORDEM_DA_PROVENIENCIA)

# ⭐ A trama, num sitio so. E ela que diz "isto nao foi medido nesta parcela", e
# aparece em dois lados -- no quadrado da origem e na barra do valor. Escrita
# duas vezes, um dia uma delas mudava e a mesma afirmacao passava a ter dois
# aspectos. Repare-se que e GEOMETRIA e nao cor: sobrevive a qualquer
# daltonismo, a uma impressao a preto e branco e a um ecra mal calibrado.
TRAMA = (
    "repeating-linear-gradient(45deg, transparent 0 var(--trama-passo), "
    "var(--superficie) var(--trama-passo) calc(var(--trama-passo) + var(--trama-largura)))"
)


def _tokens_do_tema(moldura: dict[str, str], proveniencia: dict) -> str:
    linhas = [f"  --{nome}: {cor};" for nome, cor in moldura.items()]
    linhas += [
        f"  --prov-{origem.value}: {proveniencia[origem]};"
        for origem in paleta.ORDEM_DA_PROVENIENCIA
    ]
    return "\n".join(linhas)


def _tokens_sem_tema() -> str:
    linhas = [f"  --vegetacao-{i}: {cor};" for i, cor in enumerate(paleta.VEGETACAO)]
    linhas += [f"  --agua-{i}: {cor};" for i, cor in enumerate(paleta.AGUA)]
    linhas += [
        "  --duracao: 180ms;",
        "  --curva: cubic-bezier(0.22, 0.61, 0.36, 1);",
        "  --trama-passo: 2px;",
        "  --trama-largura: 1.4px;",
    ]
    return "\n".join(linhas)


FOLHA_DE_ESTILO = f"""/* A consola do ReSoilTwin. Moldura neutra e fria; a cor esta so nos dados. */

:root {{
{_tokens_do_tema(paleta.MOLDURA_CLARA, paleta.PROVENIENCIA_CLARA)}
{_tokens_sem_tema()}
}}

/* O tema escuro nao e um acessorio: uma consola que so existe num dos dois nao
   e seria. A matiz dos dados nao muda; o valor deles muda, porque a escala de
   proveniencia le-se pelo contraste contra o fundo. */
@media (prefers-color-scheme: dark) {{
  :root {{
{_tokens_do_tema(paleta.MOLDURA_ESCURA, paleta.PROVENIENCIA_ESCURA)}
  }}
}}

*, *::before, *::after {{ box-sizing: border-box; }}

html {{ -webkit-text-size-adjust: 100%; }}

body {{
  margin: 0;
  padding: 0;
  background: var(--fundo);
  color: var(--tinta);
  font-family: ui-sans-serif, system-ui, "Segoe UI", "Helvetica Neue", sans-serif;
  font-size: 13.5px;
  line-height: 1.5;
}}

/* Numeros em tabela: largura fixa por digito, senao as colunas dancam. */
.numero, .valor, td.quando, .contagem {{
  font-family: ui-monospace, "SFMono-Regular", "JetBrains Mono", Menlo, Consolas, monospace;
  font-variant-numeric: tabular-nums;
}}

a {{ color: var(--tinta); text-decoration-color: var(--fio-forte); text-underline-offset: 3px; }}
a:hover {{ text-decoration-color: var(--tinta); }}
a:focus-visible, summary:focus-visible, select:focus-visible, button:focus-visible {{
  outline: 2px solid var(--tinta);
  outline-offset: 2px;
}}

/* ---------------------------------------------------------------- cimo */

.cimo {{
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 0 1.75rem;
  padding: 0.9rem 1.5rem;
  border-bottom: 1px solid var(--fio);
  background: var(--superficie);
}}

.cimo .produto {{
  margin: 0;
  font-size: 0.78rem;
  font-weight: 600;
  letter-spacing: 0.09em;
  text-transform: uppercase;
  color: var(--tinta-media);
}}

.cimo nav {{ display: flex; gap: 1.25rem; }}
.cimo nav a {{ text-decoration: none; color: var(--tinta-media); }}
.cimo nav a[aria-current="page"] {{
  color: var(--tinta);
  font-weight: 600;
  box-shadow: 0 1px 0 0 var(--tinta);
}}

.cimo .ambiente {{ margin: 0 0 0 auto; font-size: 0.75rem; color: var(--tinta-fraca); }}

/* A escolha da lingua. Fica ao lado do ambiente e nao no meio da navegacao das
   vistas: nao e uma quarta vista, e uma propriedade desta. E le-se em texto
   ("English", "Português") e nao numa bandeira -- uma bandeira e um pais, e
   nenhuma das duas linguas desta consola pertence a um so. */
.cimo nav.lingua {{ gap: 0.75rem; font-size: 0.75rem; }}
.cimo nav.lingua a {{ color: var(--tinta-fraca); }}
.cimo nav.lingua a[aria-current="page"] {{
  color: var(--tinta);
  font-weight: 600;
  box-shadow: none;
}}

/* ---------------------------------------------------------------- corpo */

main {{ padding: 1.5rem; max-width: 96rem; margin: 0 auto; }}

h1 {{ margin: 0 0 0.15rem; font-size: 1.28rem; font-weight: 600; letter-spacing: -0.01em; }}
h2 {{ margin: 2rem 0 0.5rem; font-size: 0.95rem; font-weight: 600; }}
h3 {{ margin: 0 0 0.3rem; font-size: 0.85rem; font-weight: 600; }}

.subtitulo {{ margin: 0 0 1.1rem; color: var(--tinta-media); max-width: 62ch; }}

/* Uma leitura que nao respondeu. Marcada por um fio e por peso, e nunca por
   cor: a cor desta consola pertence aos dados, e uma falha de leitura nao e uma
   medicao de coisa nenhuma. */
.falha {{
  margin: 0 0 1.25rem;
  padding: 0.85rem 1rem;
  border: 1px solid var(--fio-forte);
  border-left: 3px solid var(--tinta);
  border-radius: 6px;
  background: var(--fundo-fraco);
  max-width: 78ch;
}}
.falha p {{ margin: 0.35rem 0; color: var(--tinta-media); }}
.falha ul {{ margin: 0.35rem 0 0; padding-left: 1.1rem; font-size: 0.82rem; color: var(--tinta-media); }}

/* ---------------------------------------------------------------- filtros */

form.filtros {{
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: 0.85rem;
  padding: 0.85rem 1rem;
  margin-bottom: 1rem;
  border: 1px solid var(--fio);
  border-radius: 6px;
  background: var(--fundo-fraco);
}}

form.filtros label {{ display: flex; flex-direction: column; gap: 0.25rem; }}
form.filtros span {{ font-size: 0.72rem; letter-spacing: 0.06em; text-transform: uppercase; color: var(--tinta-fraca); }}

select {{
  min-width: 11rem;
  padding: 0.35rem 0.5rem;
  border: 1px solid var(--fio-forte);
  border-radius: 4px;
  background: var(--superficie);
  color: var(--tinta);
  font: inherit;
}}

button {{
  padding: 0.4rem 0.95rem;
  border: 1px solid var(--tinta);
  border-radius: 4px;
  background: var(--tinta);
  color: var(--superficie);
  font: inherit;
  font-weight: 600;
  cursor: pointer;
}}

button:active {{ transform: translateY(1px); }}

.limpar {{ font-size: 0.8rem; color: var(--tinta-media); }}

/* ---------------------------------------------------------------- legenda */

.legenda {{
  display: flex;
  flex-wrap: wrap;
  gap: 1.25rem;
  margin: 0 0 0.75rem;
  padding: 0;
  list-style: none;
  font-size: 0.78rem;
  color: var(--tinta-media);
}}

.legenda li {{ display: flex; align-items: center; gap: 0.4rem; }}

/* --------------------------------------------------------------- a marca */

/* Solido = medido na parcela. A cor diz QUAO directa e a medicao, na matiz
   10YR das cartas de solo; e uma escala ordinal e nao oito etiquetas. */
.marca {{
  display: inline-block;
  width: 0.8rem;
  height: 0.8rem;
  flex: none;
  border-radius: 2px;
  background-color: var(--prov, var(--tinta-fraca));
  box-shadow: inset 0 0 0 1px rgb(128 128 128 / 0.35);
}}

/* Tramado = nao medido na parcela. A trama e GEOMETRIA e nao cor: sobrevive a
   qualquer daltonismo, a uma impressao a preto e branco e a um ecra mal
   calibrado. Cerca de 8% dos homens tem dificuldade com vermelho/verde, e esta
   e a distincao que nao pode depender disso. */
[data-parcela="nao"] .marca {{ background-image: {TRAMA}; }}

/* ---------------------------------------------------------------- tabela */

/* A tabela tem a sua propria altura e o seu proprio deslocamento: e assim que
   o cabecalho pode ficar colado ao topo enquanto se percorrem cem linhas. Sem
   um contentor com altura, `position: sticky` nao tem a que se colar. */
.tabela {{
  max-height: min(70vh, 46rem);
  overflow: auto;
  border: 1px solid var(--fio);
  border-radius: 6px;
  background: var(--superficie);
}}

table {{ width: 100%; border-collapse: collapse; }}

thead th {{
  position: sticky;
  top: 0;
  z-index: 1;
  padding: 0.5rem 0.75rem;
  text-align: left;
  font-size: 0.7rem;
  font-weight: 600;
  letter-spacing: 0.07em;
  text-transform: uppercase;
  color: var(--tinta-fraca);
  background: var(--fundo-fraco);
  border-bottom: 1px solid var(--fio-forte);
  white-space: nowrap;
}}

tbody td {{ padding: 0.45rem 0.75rem; border-bottom: 1px solid var(--fio); vertical-align: top; }}
tbody tr:last-child td {{ border-bottom: 0; }}
tr.linha:hover td {{ background: var(--realce); }}
tr.linha[data-seleccionada="sim"] td {{ background: var(--realce); box-shadow: inset 2px 0 0 0 var(--tinta); }}

td.quando {{ white-space: nowrap; color: var(--tinta-media); }}
td.metrica {{ font-weight: 500; }}
td.valor {{ white-space: nowrap; }}
td.valor .unidade {{ margin-left: 0.35rem; font-size: 0.78rem; color: var(--tinta-fraca); }}
td.versao {{ font-size: 0.75rem; color: var(--tinta-fraca); word-break: break-all; }}

.origem .par {{ display: inline-flex; align-items: center; gap: 0.45rem; }}
.origem .nome {{ white-space: nowrap; }}
.lugar {{ display: block; font-size: 0.72rem; color: var(--tinta-fraca); }}

/* --------------------------------------------------------------- a barra */

/* Uma barra por linha, e so onde o dominio NAO e inventado. Um intervalo
   desenha-se como a banda inteira, que e a unica maneira de o desenhar sem
   escolher um ponto dentro dele. */
.barra {{
  display: block;
  position: relative;
  height: 3px;
  margin-top: 4px;
  border-radius: 2px;
  background: var(--fio);
}}
.barra i {{ position: absolute; top: 0; bottom: 0; border-radius: 2px; }}
.barra i[data-parcela-barra="nao"] {{ background-image: {TRAMA}; }}
.barra[data-aberta="sim"]::after {{
  content: "";
  position: absolute;
  right: -1px;
  top: -2px;
  border: 3.5px solid transparent;
  border-left-color: var(--tinta-media);
}}

/* --------------------------------------------------- observacoes e painel */

.duas-colunas {{ display: grid; grid-template-columns: minmax(0, 1fr) 21rem; gap: 1.25rem; align-items: start; }}

aside.proveniencia {{
  position: sticky;
  top: 1rem;
  padding: 0.35rem;
  border: 1px solid var(--fio);
  border-radius: 6px;
  background: var(--fundo-fraco);
}}

aside.proveniencia .interior {{
  padding: 0.85rem 0.95rem;
  border: 1px solid var(--fio);
  border-radius: 4px;
  background: var(--superficie);
}}

aside.proveniencia dl {{ margin: 0.4rem 0 0; }}
aside.proveniencia dt {{ font-size: 0.72rem; letter-spacing: 0.04em; color: var(--tinta-fraca); }}
aside.proveniencia dd {{ margin: 0 0 0.5rem; word-break: break-word; }}
aside.proveniencia dd.retido {{ color: var(--tinta-fraca); font-style: italic; }}
aside.proveniencia dl dl {{ margin-left: 0.75rem; padding-left: 0.6rem; border-left: 1px solid var(--fio); }}
.em-falta {{ margin: 0.4rem 0 0.8rem; color: var(--tinta-media); }}
.em-falta strong {{ display: block; color: var(--tinta); }}

/* -------------------------------------------------------- sincronizacoes */

/* Uma execucao que precisa de um humano marca-se com um fio e com uma palavra,
   e nunca com cor: a cor desta consola pertence aos dados, e o estado de uma
   execucao nao e uma medicao de coisa nenhuma. */
tr.linha[data-atencao="sim"] td:first-child {{ box-shadow: inset 3px 0 0 0 var(--tinta); }}
tr.linha[data-atencao="sim"] .veredicto {{ font-weight: 600; }}
.janela {{ display: block; white-space: nowrap; font-size: 0.78rem; }}
.janela b {{ font-weight: 500; color: var(--tinta-fraca); }}
td.erro {{ color: var(--tinta-media); max-width: 26rem; }}

/* ---------------------------------------------------------------- sitios */

.ficha {{ padding: 0.35rem; margin-bottom: 1.25rem; border: 1px solid var(--fio); border-radius: 6px; background: var(--fundo-fraco); }}
.ficha .interior {{ padding: 1rem 1.1rem; border: 1px solid var(--fio); border-radius: 4px; background: var(--superficie); }}
.pares {{ display: flex; flex-wrap: wrap; gap: 0.35rem 1.75rem; margin: 0 0 0.5rem; padding: 0; list-style: none; font-size: 0.82rem; }}
.pares b {{ font-weight: 500; color: var(--tinta-fraca); }}
.nota {{ margin: 0.35rem 0 0; color: var(--tinta-media); max-width: 78ch; font-size: 0.82rem; }}

/* ---------------------------------------------------------------- rodape */

.rodape {{ padding: 1.25rem 1.5rem 2.5rem; border-top: 1px solid var(--fio); color: var(--tinta-fraca); }}
.rodape p {{ margin: 0 0 0.4rem; max-width: 82ch; font-size: 0.8rem; }}

.contagem {{ color: var(--tinta-media); }}

/* ------------------------------------------------------------ estreitos */

@media (max-width: 60rem) {{
  main {{ padding: 1rem; }}
  .duas-colunas {{ grid-template-columns: minmax(0, 1fr); }}
  /* O painel sobe para cima da tabela: quem carrega em "proveniencia" tem de
     ver a resposta sem ir a procura dela no fim da pagina. */
  aside.proveniencia {{ position: static; order: -1; }}
  .cimo {{ padding: 0.75rem 1rem; }}
  .cimo .ambiente {{ margin-left: 0; width: 100%; }}
  /* Num ecra estreito a tabela deixa de ter altura propria: dois deslocamentos
     encaixados num telemovel sao uma armadilha, e a pagina inteira ja rola. */
  .tabela {{ max-height: none; }}
}}

/* -------------------------------------------------------------- movimento */

/* Toda a animacao desta consola vive dentro desta guarda, e e pouca de
   proposito. Numa ferramenta de trabalho, a animacao boa e a que EXPLICA -- o
   painel entra por baixo da linha de onde saiu, e diz de onde veio. A
   decorativa cansa ao terceiro uso e faz o produto parecer menos serio. */
@media (prefers-reduced-motion: no-preference) {{
  aside.proveniencia {{ animation: entra-o-painel var(--duracao) var(--curva) both; }}
  tr.linha td {{ transition: background-color 110ms var(--curva); }}
  a, button, select {{ transition: color 110ms var(--curva), border-color 110ms var(--curva); }}

  @keyframes entra-o-painel {{
    from {{ opacity: 0; transform: translateY(6px); }}
    to {{ opacity: 1; transform: none; }}
  }}
}}
"""

# Os oito nomes de origem, pela ordem da escala, para quem quiser desenhar a
# legenda a partir da mesma fonte que desenha as cores.
ORDEM_DAS_ORIGENS = _ORDEM_DAS_ORIGENS
