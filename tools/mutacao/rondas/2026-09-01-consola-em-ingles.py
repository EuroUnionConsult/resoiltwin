"""Ronda da consola em ingles (Fase F, Task 3).

Cada mutante diz uma coisa falsa sobre o dominio da lingua, e a coluna da
direita e a guarda que ela quebra. Os tres obrigatorios do plano sao o `d1` (a
lingua por omissao passa a portugues), o `e1` (a escolha deixa de ser
respeitada) e o `k1`/`k2` (uma chave desaparece de uma das linguas -- um para
cada uma das duas tabelas de chaves).

⚠️ Ler a lista de APANHADOS de cada mutante, e nao so a contagem. Um mutante
pode morrer por dano colateral enquanto o teste da sua propria guarda fica de
pe -- e isso e uma guarda sem medicao, ainda que a tabela diga "morto". Nesta
fase a contagem ja escondeu testes sem medicao tres vezes.
"""

MUTANTES = [
    # ------------------------------------------------- a lingua por omissao
    ("d1",
     "src/resoiltwin/console/textos.py",
     'LINGUA_POR_OMISSAO = "en"',
     'LINGUA_POR_OMISSAO = "pt"',
     "(modulo)",
     "a lingua por omissao passa a portugues"),

    ("d2",
     "src/resoiltwin/console/marcacao.py",
     '        f\'<!doctype html>\\n<html lang="{e(textos.etiqueta_html)}">\\n<head>\\n\'',
     '        \'<!doctype html>\\n<html lang="pt-PT">\\n<head>\\n\'',
     "pagina",
     "a pagina declara-se sempre em portugues ao navegador"),

    # ------------------------------------------------------------ a escolha
    ("e1",
     "src/resoiltwin/console/textos.py",
     '    return curta if curta in TABELAS["textos"] else LINGUA_POR_OMISSAO',
     "    return LINGUA_POR_OMISSAO",
     "lingua_pedida",
     "a escolha deixa de ser respeitada: sai sempre a lingua por omissao"),

    ("e2",
     "src/resoiltwin/console/marcacao.py",
     "    if lingua != LINGUA_POR_OMISSAO:",
     "    if False:",
     "endereco",
     "a lingua deixa de viajar nas ligacoes e perde-se ao primeiro clique"),

    ("e3",
     "src/resoiltwin/console/paginas.py",
     "        if textos.lingua != LINGUA_POR_OMISSAO",
     "        if False",
     "observacoes",
     "o formulario perde a lingua: filtrar em portugues devolve ingles"),

    ("e4",
     "src/resoiltwin/console/marcacao.py",
     "            endereco(vista, lingua, parametros),",
     "            endereco(vista, lingua),",
     "_troca_de_lingua",
     "a troca de lingua deita fora o filtro de quem estava a ler"),

    # ---------------------------------------------- uma chave que desaparece
    ("k1",
     "src/resoiltwin/console/textos.py",
     '    "painel.na_linha": "Na própria linha",',
     None,
     "(modulo)",
     "uma chave desaparece do portugues: o texto some ao mudar de lingua"),

    ("k2",
     "src/resoiltwin/console/textos.py",
     '    "distance_km": "Distância ao sítio (km)",',
     None,
     "(modulo)",
     "um rotulo da evidencia desaparece do portugues"),

    ("k3",
     "src/resoiltwin/console/textos.py",
     "            return INGLES[chave]",
     "            raise",
     "__getitem__",
     "uma chave em falta rebenta a pagina em vez de cair para o ingles"),

    ("k4",
     "src/resoiltwin/console/textos.py",
     "        return proprios.get(chave) or ROTULOS_EM_INGLES.get(chave, chave)",
     '        return proprios.get(chave, "")',
     "rotulo",
     "um campo da evidencia que ninguem nomeou passa a nascer invisivel"),

    # ------------------------------------- o que a lingua muda alem do texto
    ("n1",
     "src/resoiltwin/console/formato.py",
     "    marca = textos.marca_decimal if textos is not None else MARCA_DECIMAL[LINGUA_POR_OMISSAO]",
     '    marca = ","',
     "numero",
     "a marca decimal deixa de mudar com a lingua"),

    ("n2",
     "src/resoiltwin/console/textos.py",
     'FORMATO_DO_DIA = {"en": "%Y-%m-%d", "pt": "%d/%m/%Y"}',
     'FORMATO_DO_DIA = {"en": "%d/%m/%Y", "pt": "%d/%m/%Y"}',
     "(modulo)",
     "a data em ingles volta a ser ambigua: 09/08/2026 le-se de duas maneiras"),

    # ----------------------------------------- o que a traducao nao pode perder
    ("t1",
     "src/resoiltwin/console/textos.py",
     '    "valor.fora_da_parcela": "not measured in the parcel",',
     '    "valor.fora_da_parcela": "outside the parcel",',
     "(modulo)",
     "o ingles passa a descrever um lugar em vez de negar a medicao"),

    ("t2",
     "src/resoiltwin/console/marcacao.py",
     '        f\'<footer class="rodape"><p>{textos["ressalva"]}</p></footer>\\n\'',
     '        \'<footer class="rodape"></footer>\\n\'',
     "pagina",
     "a ressalva desaparece e a consola deixa de negar o que a tabela sugere"),

    ("t3",
     "src/resoiltwin/console/paginas.py",
     "    return textos[chave] if chave else str(atencao)",
     "    return str(atencao)",
     "_veredicto",
     "o veredicto deixa de acusar a execucao e passa a nomear um estado"),

    ("t4",
     "src/resoiltwin/api/console.py",
     '    f"({MARCA_DE_COORDENADA[\'withheld\']} {next(iter(MARCA_DE_COORDENADA))})"',
     '    "(coordenada retida)"',
     "(modulo)",
     "a marca que a camada escreve no dado volta a ser escrita a mao, e em portugues"),

    # ⭐ O defeito que esta traducao mais podia produzir: uma frase esquecida em
    # portugues dentro do codigo, numa pagina que um avaliador abre em ingles.
    ("t5",
     "src/resoiltwin/console/paginas.py",
     '        f\'<p class="nota">{e(textos["sitios.aviso_contorno"])}</p>\'',
     '        \'<p class="nota">O contorno de cada área não é servido por esta consola: '
     'os polígonos estão num repositório privado. A área em metros quadrados e a '
     'proveniência do traçado são o que há para ver aqui.</p>\'',
     "_ficha_de_sitio",
     "uma frase fica escrita a mao em portugues e sobrevive ao modo ingles"),
]

# Acrescentados depois de ler a LISTA DE APANHADOS da primeira corrida e nao a
# contagem. Cinco guardas estavam de pe sem nenhum mutante a medi-las: o
# varrimento do portugues no modo ingles, a paridade dos ajustes por lingua, a
# troca de lingua com todas as linguas, os caminhos que nao se traduzem, e a
# recusa de uma traducao que seja uma copia do ingles.
MUTANTES += [
    ("k5",
     "src/resoiltwin/console/textos.py",
     'MARCA_DECIMAL = {"en": ".", "pt": ","}',
     'MARCA_DECIMAL = {"en": "."}',
     "(modulo)",
     "uma lingua desaparece de um ajuste que a pagina le e a pagina rebenta"),

    ("k6",
     "src/resoiltwin/console/textos.py",
     "PORTUGUES = {",
     "PORTUGUES = INGLES; _NAO_USADO = {",
     "(modulo)",
     "a traducao passa a ser uma copia do ingles: as chaves batem e nao traduz nada"),

    ("e5",
     "src/resoiltwin/console/marcacao.py",
     "        for lingua in LINGUAS",
     "        for lingua in (textos.lingua,)",
     "_troca_de_lingua",
     "a troca de lingua so oferece a lingua em que ja se esta"),

    ("e6",
     "src/resoiltwin/console/marcacao.py",
     '    return vista + ("?" + urlencode(campos) if campos else "")',
     '    vista = vista if lingua == LINGUA_POR_OMISSAO else vista + "-" + lingua\n'
     '    return vista + ("?" + urlencode(campos) if campos else "")',
     "endereco",
     "o caminho da vista passa a mudar com a lingua: duas paginas para a mesma vista"),

    ("e7",
     "src/resoiltwin/console/textos.py",
     '        self.lingua = lingua if lingua in TABELAS["textos"] else LINGUA_POR_OMISSAO',
     "        self.lingua = lingua",
     "__init__",
     "uma lingua que nao existe deixa de cair para o ingles e rebenta"),
]

# As tres regras que a Task 2 decidiu, remutadas contra os testes REESCRITOS
# desta ronda. Os testes deixaram de afirmar cadeias portuguesas e passaram a
# afirmar a propriedade nas duas linguas; estes tres provam que continuam a
# apanhar exactamente o que apanhavam antes.
MUTANTES += [
    ("r1",
     "src/resoiltwin/console/formato.py",
     '            f"{numero(minimo, casas, textos)}{separador}{numero(maximo, casas, textos)}",',
     "            numero((minimo + maximo) / 2, casas, textos),",
     "apresentar_valor",
     "o intervalo volta a mostrar-se como um numero: o meio dele"),

    ("r2",
     "src/resoiltwin/console/formato.py",
     '            f"{MAIOR_OU_IGUAL}{ESPACO_DE_MILHARES}"',
     '            ""',
     "apresentar_valor",
     "a leitura saturada perde o >= e volta a ler-se como uma medida"),

    ("r3",
     "src/resoiltwin/console/paginas.py",
     "    if conteudo.estruturada:",
     "    if True:",
     "_painel",
     "uma linha sem proveniencia estruturada volta a mostrar um painel vazio"),
]
