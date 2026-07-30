# Editor de savegame — Space Haven

Editor local para os savegames do Space Haven. Lê o save, mostra os parâmetros
em abas (com os nomes reais do jogo) e grava as alterações de volta no arquivo.

Interface em **português e inglês**, com o seletor no canto superior direito.

Só precisa de **Python 3.10+**. Sem dependências, sem instalação.

```bash
python3 run.py                    # abre o seletor de saves no navegador
python3 run.py caminho/do/save    # abre um save direto
```

A interface roda no navegador (`http://127.0.0.1:8713`), mas quem lê e grava os
arquivos é o processo Python, na sua máquina. Nada sai do computador.

## Aviso legal

**Space Haven** é um jogo da [Bugbyte Ltd.](https://bugbyte.fi/) Este editor é
um projeto independente feito por fãs: não é oficial, não é endossado pela
Bugbyte e não tem qualquer vínculo com ela.

O arquivo `shedit/data/gamedata.json` contém nomes e descrições extraídos dos
arquivos do jogo. **Esse conteúdo é propriedade da Bugbyte Ltd.**, e está aqui
apenas para o editor mostrar nomes legíveis no lugar dos IDs numéricos do save.
Nenhum outro material do jogo é redistribuído. A pedido da Bugbyte, o arquivo
será removido — o editor continua funcionando com
`tools/extract_gamedata.py`, que gera a tabela a partir da sua própria cópia do
jogo.

> **Disclaimer** — *Space Haven* is a game by Bugbyte Ltd. This editor is an
> unofficial, fan-made project with no affiliation to or endorsement from
> Bugbyte. The file `shedit/data/gamedata.json` contains names and descriptions
> extracted from the game's data files; **that content belongs to Bugbyte Ltd.**
> and is included solely so the editor can display readable names instead of the
> numeric IDs stored in savegames. It will be removed on request by Bugbyte;
> `tools/extract_gamedata.py` regenerates the table from your own copy of the
> game.

## Abas

| Aba | O que dá para mudar |
|---|---|
| **Jogo** | relógio (dias/horas/turnos), créditos, seed, facção do jogador, dificuldade e as regras do cenário (monstros, robôs, erupções solares, asteroides…) |
| **Tripulação** | nome, necessidades (saúde, comida, energia, conforto, humor…), atributos, perícias com nível/teto/exp, traços, condições e prioridades de trabalho. A lista mostra uma nave por vez — a do jogador por padrão — e fica fixa ao rolar. Inclui quem está pilotando um minerador, construtor ou caça; visitantes de outras facções ficam escondidos até você pedir |
| **Armazenamento** | totais por recurso e por nave, quantidade de cada pilha, adicionar um recurso novo a um armazém, ou criar um de cada de uma vez |
| **Pesquisa** | estado de cada tecnologia; concluir ou zerar uma ou todas |
| **Naves** | nome, ID, névoa de guerra |
| **Facções** | postura, relação, paciência e permissões (comércio, acesso, contratação) entre cada par de facções |
| **XML** | navegador da árvore completa: qualquer atributo de qualquer nó, com busca em todo o save |

As abas Tripulação, Armazenamento e Pesquisa têm ações em lote (restaurar toda
a tripulação, encher os armazéns, concluir toda a pesquisa) para o que seria
tedioso campo a campo. Na Tripulação elas ficam numa barra fixa acima da área
que rola, e por padrão valem só para a nave em foco — o seletor ao lado troca
para toda a tripulação do jogador.

## Como funciona

Um save do Space Haven é uma pasta com vários XML:

```
save/
  game               partida, pesquisa, banco, facções e as naves do setor atual
  ships/shipNNNN     uma nave fora do setor atual, por arquivo
  info, stats.bin, timeline.xml    (o editor não toca)
```

O editor carrega o `game` **e** todas as naves em `ships/` — inclusive a
tripulação delas. Ao gravar, só os arquivos que realmente mudaram são
reescritos, cada um com um backup `.bak-AAAAMMDD-HHMMSS` ao lado.

A serialização reproduz o estilo do jogo byte a byte: carregar e gravar sem
alterar nada devolve arquivos idênticos aos originais, e uma edição de um
atributo muda exatamente aquela linha.

### Idiomas

A interface tem PT-BR e EN, trocáveis a qualquer momento pelo seletor na barra
superior — sem recarregar a página. Na primeira visita segue o idioma do
navegador; depois disso a escolha fica no `localStorage`.

Os textos da interface ficam num catálogo só, `shedit/data/i18n.json`, usado
tanto pelo Python (rótulos montados no backend) quanto pelo navegador (o
resto), que o recebe por `/api/i18n`. Para acertar uma tradução ou acrescentar
um idioma, mexa nesse arquivo e em `LANGS` de `shedit/i18n.py`.

Os nomes do próprio jogo — recursos, tecnologias, traços, perícias — não estão
nesse catálogo: vêm de `gamedata.json`, que já traz EN e PT-BR extraídos do
jogo. Por isso "Hipério" vira "Hyperium" e "Coragem" vira "Bravery" junto com o
resto da interface.

As mensagens de erro do backend (arquivo não encontrado, save inválido)
continuam só em português.

### Nomes em vez de IDs

O save guarda tudo como ID numérico (`elementaryId="1873"`, `techId="2532"`,
`sk="16"`). Os nomes legíveis vêm de `shedit/data/gamedata.json`, extraído do
`spacehaven.jar` da sua instalação:

```bash
python3 tools/extract_gamedata.py                        # procura o jar sozinho
python3 tools/extract_gamedata.py /caminho/spacehaven.jar
```

Rode de novo depois de atualizar o jogo. Sem esse arquivo o editor funciona
igual, só mostra os IDs crus.

O extrator lê os textos e as definições de `library/texts` e `library/haven`, e
os enums internos (perícias, profissões, prioridades) por reflexão, usando o
`jjs` do JRE que vem junto com o jogo — assim as tabelas são as do jogo, não
uma lista mantida à mão.

O conteúdo dessa tabela (887 nomes e 811 descrições, em EN e PT-BR) é do jogo e
pertence à Bugbyte Ltd. — veja o [aviso legal](#aviso-legal).

## Onde ficam os saves

O seletor já abre na pasta certa quando encontra a instalação. Nos caminhos
padrão do Steam:

- Linux: `~/.steam/steam/steamapps/common/SpaceHaven/savegames`
  (ou `~/snap/steam/common/.local/share/Steam/...` no Steam via snap)
- Windows: `C:\Program Files (x86)\Steam\steamapps\common\SpaceHaven\savegames`
- macOS: `~/Library/Application Support/Steam/steamapps/common/SpaceHaven/savegames`

Dentro de cada partida há `save/` (o save atual) e `autosave1..4`.

### Sobre as necessidades da tripulação

Em saúde, comida, energia e conforto **maior é melhor** — isso vem dos gatilhos
das condições no próprio jogo (comida < 20 "com fome", < 10 "desnutrição",
> 120 "comeu demais"; energia < 15 "exausto", < −5 "inconsciente"). Nos gases
inalados é o contrário: 0 é ar limpo.

Cada necessidade tem o valor do momento e o de longo prazo — os mesmos que as
condições consultam como `whenPresent` e `whenLongTerm`. Em comida, conforto,
oxigênio e temperatura o valor do momento gravado no save é uma constante que o
jogo recalcula ao carregar, então o editor mostra apenas o que de fato persiste
(a saciedade de longo prazo, e no oxigênio a reserva do traje).

A energia é a que o jogo chama de ENERGY e vale `80 + Pique × 15`, menos a
penalidade por tempo acordado e a por trabalho. São essas duas penalidades que
esvaziam a barra, e é nelas que "Restaurar necessidades" mexe — zerá-las
equivale a um turno de sono. Bônus de aumentos e penalidades vindas de
condições (fadiga pós-cirúrgica, por exemplo) entram por fora: para tirar essas
últimas, use "Remover condições".

A barra de comida é o conteúdo do estômago — o mesmo que o tooltip do jogo
mostra como "Estômago". Restaurar enche com uma ração de Comida espacial
(P15 C20 F10 V10), que é o que o jogo dá a uma refeição completa. Os campos do
estômago também são editáveis um a um.

### Tripulantes que não estão a bordo

Quem está pilotando um minerador, construtor ou caça não fica no `<characters>`
da nave: fica dentro de `<crafts>`, com o vínculo `homeSid` apontando para a
nave-mãe. O editor junta os dois, marcando onde a pessoa está.

Naves também recebem visitas — mercadores usando as camas médicas aparecem no
mesmo `<characters>` da sua estação. Eles ficam escondidos por padrão e fora das
ações em lote; o seletor mostra a contagem separada ("15 + 8 visitantes").

## Antes de editar

- **Feche o jogo.** Ele reescreve o save ao gravar e sobrescreve suas mudanças.
- O editor faz backup a cada gravação, mas um save inteiro copiado à parte não
  custa nada.
- A aba XML não valida nada: dá para editar qualquer atributo, inclusive os que
  quebram a partida. As outras abas só oferecem campos com faixas conhecidas.

## Opções

```
python3 run.py [save] [--port 8713] [--host 127.0.0.1] [--no-browser]
```

## Executável pronto (Windows e Linux)

Cada tag `v*` publica os binários numa release: baixe o do seu sistema e execute.
Não precisa de Python nem de instalação.

- **Windows** — `SpaceHavenEditor-windows.exe`. Na primeira vez o SmartScreen
  avisa que o programa é desconhecido: *Mais informações → Executar assim mesmo*.
- **Linux** — `SpaceHavenEditor-linux`; dê `chmod +x` antes de rodar.

A janela de console que abre junto é onde aparece o endereço do editor, e
fechá-la (ou Ctrl+C) encerra o servidor.

### Empacotando você mesmo

```bash
pip install pyinstaller
pyinstaller --clean --noconfirm SpaceHavenEditor.spec
python3 tools/smoke_test.py dist/SpaceHavenEditor      # dist/SpaceHavenEditor.exe no Windows
```

O binário sai em `dist/`. O `.spec` embute `shedit/data/*.json` e `shedit/web/`;
como os caminhos ali são relativos, o mesmo arquivo serve nos dois sistemas.

O PyInstaller **não** faz cross-compile: o executável do Windows precisa ser
gerado no Windows. É o que `.github/workflows/build.yml` faz, com uma matriz de
`ubuntu-latest` e `windows-latest`.

O teste de fumaça sobe o binário de verdade e confere que a API responde e que
os dados foram embutidos — sem ele, um empacotamento sem os JSON passaria e a
interface só apareceria quebrada para quem baixasse.

## Estrutura

```
run.py                       entrada: sobe o servidor e abre o navegador
shedit/
  savefile.py                leitura, edição por path e gravação byte a byte
  views.py                   monta o conteúdo de cada aba
  actions.py                 ações em lote
  gamedata.py                IDs -> nomes
  i18n.py                    textos da interface (PT-BR / EN)
  resources.py               localiza os dados (empacotado ou não)
  server.py                  servidor HTTP local (só stdlib)
  data/gamedata.json         tabela extraída do jogo
  data/i18n.json             catálogo de textos da interface
  web/                       interface (HTML/CSS/JS, sem dependências)
tools/extract_gamedata.py    regera data/gamedata.json a partir do jar
tools/smoke_test.py          confere que o executável empacotado funciona
SpaceHavenEditor.spec        receita do PyInstaller
.github/workflows/build.yml  build de Windows e Linux + release por tag
```
