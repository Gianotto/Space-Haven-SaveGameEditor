# Anatomia de um savegame do Space Haven

Notas levantadas medindo saves reais do jogo 1.0.4, não lendo o código dele.
Cada afirmação aqui foi verificada carregando o save alterado no jogo e olhando
o resultado na tela; onde ficou dúvida, está dito.

O que motivou o levantamento foi uma pergunta específica: dá para vários
jogadores dividirem uma galáxia, cada um rodando o próprio jogo, com um servidor
costurando as partes? A resposta acabou sendo mais interessante que a pergunta.

## Como um save é organizado

```
save/
  game               a partida inteira e o setor onde você está agora
  ships/shipNNNN     uma nave que está em outro setor, um arquivo por nave
  info               versão e data
  stats.bin, timeline.xml
```

O nome do arquivo de nave é `ship` seguido do `sid` dela. São documentos XML
soltos, com `<ship>` na raiz, sem cabeçalho, terminando em quebra de linha.

A divisão importa: **`game/ships` são as naves do setor carregado**, e `ships/`
são as que estão longe. Mover uma nave entre os dois é o que o jogo faz quando
você viaja.

## Identificadores

`masterData/@idCounter` é o contador global do save: toda entidade nova —
personagem, nave, objeto — tira o `entId` dali. Reservar um id e avançar o
contador é o que o editor faz para criar tripulante sem colidir com nada.

Os ids **dentro** de uma nave (`id`, `eid`) são locais a ela. Duas naves que
convivem no mesmo save compartilham 448 ids sem conflito nenhum, o que torna
copiar uma nave inteira uma operação barata: só o `sid` e os `entId` da
tripulação precisam ser renumerados.

Consumo observado do contador global: 55 num jogo recém-criado, 4.539 no dia 37,
62.174 no dia 124. O teto de um inteiro de 32 bits está a quatro ordens de
grandeza de distância.

`starmap/@objectIdCounter` é um contador à parte, para frotas e objetos do mapa
estelar.

## O mapa estelar e a seed

`<starmap>` guarda o tamanho da galáxia (`w`, `h`) e a lista de sistemas. Cada
sistema tem:

- `sn` e `smn`: nome longo e curto, **em hexadecimal**
- `bodies/l`: estrela, planetas, luas, asteroides, campos de asteroides. Cada
  corpo tem semente própria, tipo, `celeid`, raio de órbita (`ox`, `oy`) e de
  quem orbita (`centerId`)
- `emptySectors/l`: o resto do terreno — campos de asteroides, destroços,
  bases, minas
- `clouds`: nebulosas

**A seed digitada na criação reproduz a galáxia inteira.** Dois jogos criados
com a mesma seed e as mesmas opções deram mapas idênticos: mesmos sistemas,
mesmos corpos com as mesmas sementes, mesmos setores de terreno, mesmo ponto de
partida. Isso é a fundação de qualquer ideia de universo compartilhado, porque
significa que uma coordenada quer dizer a mesma coisa para todos os jogadores, e
que os ids de corpo celeste são vocabulário comum.

**A seed não reproduz o resto.** A tripulação inicial sai diferente (outros
nomes, outros atributos, outras perícias), o nome da nave muda, e o interior das
naves não bate: na nave inicial 338 de 630 elementos coincidem, e a nave
abandonada do setor inicial tem 414 elementos num jogo e 407 no outro.

O save **não guarda a seed** que foi digitada — o atributo `seed` da raiz veio
`0` em todas as partidas examinadas, inclusive em galáxias completamente
diferentes. Quem quiser comparar precisa anotar a seed por fora.

`tools/compare_galaxy.py` monta uma impressão digital do mundo gerado e compara
saves. Ele ignora de propósito o que muda enquanto se joga: a posição e a fase
orbital dos corpos, os setores temporários (missões, naves no mapa, ofertas de
novo lar) e o nome dos sistemas, que num save recém-criado ainda está vazio e só
aparece depois.

## Onde o jogador está

Três coisas precisam concordar:

| Onde | O quê |
|---|---|
| `<f isPlayer="true">` dentro do `<fleets>` de um corpo celeste | a frota |
| `starmap/@pa` | id do corpo onde ela está |
| `starmap/@sys` | id do sistema |

Mudar os três realoca o jogador, e o jogo aceita sem reclamar. O corpo de
destino costuma não ter `<fleets>`; é preciso criar, entre `<stuff>` e `<info>`.

Dois detalhes de apresentação, no `<info>` do corpo:

- `visited` e `isVisible` controlam o rótulo "Unvisited sector" e se o lugar
  aparece no mapa. Num jogo novo o **próprio setor inicial** vem com os dois
  desligados, e o jogo os liga em algum momento da partida.
- `isst="1"` aparece uma única vez no save, sempre num asteroide: é a origem do
  jogador. Ele e `pa` coincidem num jogo novo e divergem depois que a pessoa
  viaja, então são conceitos separados.

## Do que um setor carregado é feito

| Nó | Conteúdo | Ao mudar de setor |
|---|---|---|
| `<space>` | células de rocha, campos de minério, ordens de mineração | fica |
| `<ships>` | naves presentes | as de lá ficam, a sua vai |
| `<spaceItems>` | itens soltos flutuando | fica |
| `<crafts>` | naves pequenas atracadas, ligadas por `homeSid` | vão com você |

O `<space>` é montado a partir do `<stuff>` do corpo celeste: os minérios
listados em `<mining>/<toMine>` são exatamente os que o corpo declara.

**O jogo não regenera o setor ao carregar.** Realocar o jogador sem tocar no
`<space>` leva o cenário antigo junto; esvaziar o `<space>` deixa a pessoa no
vácuo, e o flag `visited` não muda isso. A geração de um setor só acontece
durante uma viagem feita dentro do jogo. Esvaziar dá para fazer com precisão;
preencher, não — para isso seria preciso escrever um gerador de campo de
asteroides, e o formato é conhecido mas o resultado não teria a cara do que o
jogo desenha.

## De quem é uma nave

Descoberto na marra, testando quatro hipóteses erradas antes:

**`<ship>/<settings>` tem `of` (id da facção) e `owner` (nome do lado).** É isso
que manda. Uma nave copiada da sua continua sendo sua enquanto esses dois
disserem `461` e `Player`, mesmo que a tripulação seja de outra facção e mesmo
que exista uma frota de NPC registrada apontando para ela.

Registrar a nave numa frota do mapa estelar também é necessário — um `<f>` no
corpo celeste, com `factionId`, `isPlayer="false"` e um `<createdShips><l>` cujo
`createdShipId` é o `sid` da nave e `created="true"`.

Sem dono declarado o jogo improvisa, e o improviso depende da tripulação:

- tripulação `Player`: o jogo entrega a nave inteira para você
- tripulação de outra facção: o jogo trata as pessoas como náufragos, seu ônibus
  vai buscá-las e a nave vira destroço reivindicável

Naves de NPC costumam ter três nós que a sua não tem: `<asi>` (a IA — rádio,
postura de combate), `<shipBank>` (créditos próprios e regras de preço, é com
isso que ela negocia) e `<markers>`. Uma nave sem `<shipBank>` não tem com que
comerciar; existe precedente disso no jogo.

## Quem enxerga o quê

O interior de uma nave alheia **não** é escondido pelos dados da nave. Uma nave
de NPC autêntica, transplantada de outro save com toda a sua névoa (`fg="0"` em
cada célula), `unex="1"` e `forceRoof="1"`, continuou aberta.

Quem manda é `hostmap/map/l`, a tabela de relações entre facções, por par:

| Permissão | O que governa |
|---|---|
| `accessTrade` | comerciar |
| `accessShip` | subir na nave |
| `accessVision` | ver dentro dela |
| `accessHire` | contratar a tripulação |

Num jogo novo o jogador começa **Friendly** com Civis, Mercantes e Militares, com
relação na casa dos 70, e as permissões vêm todas ligadas — por isso se enxerga
o interior das naves deles logo no primeiro dia. Com o tempo a relação decai
para Neutral e as portas fecham. Desligar `accessVision` fecha o interior na
hora.

Destroços são outro mecanismo: ficam registrados no `<stuff>` do corpo com
`derelict="true"` e só se revelam abordando, independente de facção.

## O que o jogo entrega de graça

Uma nave de outra facção parada no seu setor oferece **HAIL, TRADE e MISSIONS**
sem que nada precise ser construído, e chega a gerar missão própria. Para a
ideia de comércio entre jogadores isso é significativo: a interface já existe,
é nativa, e funciona sem os dois jogadores estarem online — a nave fica ali como
uma loja aberta.

O que uma nave dessas negocia é o estoque e os créditos **dela**, não os do
jogo. Quem monta o retrato decide o que fica exposto.

## Resumo do que dá e do que não dá

Dá, verificado no jogo:

- reproduzir a mesma galáxia em vários saves pela seed
- mover o jogador para qualquer corpo celeste, em qualquer sistema
- descarregar um setor por completo, peça por peça
- inserir a nave de outro jogador como NPC legítimo, com dono, frota, comércio e
  interior fechado
- criar tripulante, mover carga, ajustar relações entre facções

Não dá, de fora do jogo:

- gerar o cenário de um setor novo
- fazer qualquer coisa aparecer num jogo que está aberto: o jogo reescreve o
  save ao gravar, então o que vem de fora só entra entre sessões
