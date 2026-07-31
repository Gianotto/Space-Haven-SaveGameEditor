# Galáxia Compartilhada — projeto do servidor

Documento de projeto para um servidor que permite a vários jogadores de Space
Haven dividirem a mesma galáxia, cada um rodando o próprio jogo, sem que uma
linha do código do jogo seja alterada.

Escrito para ser lido sozinho, por quem for implementar o servidor num
repositório separado. Tudo que está aqui como fato foi medido carregando saves
alterados no jogo 1.0.4 e olhando o resultado; o que é suposição está marcado
como tal.

Projeto de origem, onde as ferramentas de leitura e escrita de save já existem:
<https://github.com/Gianotto/Space-Haven-SaveGameEditor>

---

# Parte 1 — O que o jogo permite

## 1.1 O que não dá para fazer, e por quê

Antes do desenho, os três limites que o moldam. Nenhum deles se contorna de
fora do jogo.

**A simulação não roda sem o cliente.** Não existe modo headless. As classes de
simulação do jogo (mundo, coisas, IA, mapa estelar) referenciam a biblioteca
gráfica em 36% a 48% dos casos e chamam direto o pacote de interface em 10% a
23%. Não há costura para cortar. Um servidor autoritativo que simule o mundo
está fora de alcance.

**A simulação não é determinística.** Das classes de simulação que sorteiam,
312 criam gerador sem semente. Duas máquinas partindo do mesmo estado divergem
de imediato, então lockstep — a técnica padrão de multiplayer para jogos desse
gênero — não é viável.

**O jogo é dono do arquivo enquanto está aberto.** Ele reescreve o save ao
gravar. Qualquer coisa que o servidor queira colocar dentro do jogo de alguém
tem que chegar com o jogo fechado.

Existe código de rede no jar (`fi.bugbyte.shared.matchmaking`, 21 classes com
socket UDP), mas **nenhuma classe do Space Haven o referencia** — é biblioteca
compartilhada dos outros jogos da Bugbyte, carona morta.

## 1.2 Anatomia de um save

```
save/
  game               a partida inteira e o setor onde o jogador está agora
  ships/shipNNNN     uma nave que está em outro setor, um arquivo por nave
  info               versão e data
  stats.bin, timeline.xml
```

O nome do arquivo de nave é `ship` + o `sid` dela. São documentos XML soltos,
raiz `<ship>`, sem cabeçalho XML, terminando em `</ship>` e quebra de linha.

A distinção central: **`game/ships` são as naves do setor carregado**; `ships/`
são as que estão longe. Mover uma nave entre os dois é o que o jogo faz quando
o jogador viaja.

Tamanho típico: o `game` de uma partida de 124 dias tem 4,5 MB; um save
recém-criado tem 390 KB.

## 1.3 Identificadores

`masterData/@idCounter` é o contador global do save. Toda entidade nova —
personagem, nave, objeto — tira o `entId` dali. **Para criar qualquer coisa num
save, reserve o valor atual e incremente o contador.**

Ids **dentro** de uma nave (`id`, `eid`) são locais a ela: duas naves que
convivem no mesmo save compartilham 448 ids sem conflito. Copiar uma nave
inteira exige renumerar apenas o `sid` e os `entId` da tripulação.

`starmap/@objectIdCounter` é um contador à parte, para frotas e objetos do mapa
estelar.

Consumo observado: 55 num save novo, 4.539 no dia 37, 62.174 no dia 124. Teto de
inteiro de 32 bits está a quatro ordens de grandeza. **Não há limite prático de
jogadores por sala vindo daqui**, porque cada save tem o próprio contador e eles
nunca se encontram — só é preciso renumerar o que for injetado.

## 1.4 A seed reproduz a galáxia

Verificado com dois jogos criados com a seed `1654267488` e as mesmas opções:

**Reproduz:** os sistemas (64), os corpos celestes (123) com semente própria,
tipo, raio de órbita e de quem orbitam, os setores de terreno (99), o tamanho da
galáxia e **o ponto de partida** (x=75724, y=235080).

**Não reproduz:** a tripulação inicial (outros nomes, atributos e perícias), o
nome da nave do jogador, e o interior das naves — 338 de 630 elementos
coincidem na nave inicial, e a nave abandonada do setor inicial tem 414
elementos num jogo e 407 no outro.

Isso é a fundação do projeto: **uma coordenada e um id de corpo celeste
significam a mesma coisa para todos os jogadores da sala**, sem o servidor
precisar distribuir mapa nenhum. E cada jogador ganha tripulação própria de
graça.

**O save não guarda a seed digitada** — o atributo `seed` da raiz vem `0` em
todas as partidas, inclusive em galáxias completamente diferentes. Quem precisa
saber a seed de uma sala é o servidor.

Ferramenta pronta para conferir se duas galáxias são iguais:
`tools/compare_galaxy.py` no repositório do editor.

## 1.5 Onde o jogador está

Três coisas precisam concordar:

| Onde | O quê |
|---|---|
| `<f isPlayer="true">` dentro do `<fleets>` de um corpo celeste | a frota |
| `starmap/@pa` | id do corpo onde ela está |
| `starmap/@sys` | id do sistema |

Mudar os três realoca o jogador e o jogo aceita. O corpo de destino em geral não
tem `<fleets>`; é preciso criar, entre `<stuff>` e `<info>`.

No `<info>` do corpo:

- `visited` e `isVisible` controlam o rótulo "Unvisited sector" e a aparição no
  mapa. Num jogo novo **o próprio setor inicial vem com os dois desligados** — é
  comportamento de fábrica, não defeito.
- `isst="1"` aparece uma vez só no save, sempre num asteroide: é a origem do
  jogador. Coincide com `pa` num jogo novo e diverge depois que a pessoa viaja.

## 1.6 Do que um setor carregado é feito

| Nó da raiz | Conteúdo | Ao mudar de setor |
|---|---|---|
| `<space>` | células de rocha, campos de minério, ordens de mineração | fica |
| `<ships>` | naves presentes | as de lá ficam, a do jogador vai |
| `<spaceItems>` | itens soltos flutuando | fica |
| `<crafts>` | naves pequenas atracadas, ligadas por `homeSid` | vão com o jogador |

O `<space>` é montado a partir do `<stuff>` do corpo celeste: os minérios em
`<mining>/<toMine>` são exatamente os que o corpo declara.

**O jogo não regenera o setor ao carregar.** Realocar sem tocar no `<space>`
leva o cenário antigo junto; esvaziar deixa o jogador no vácuo, e o flag
`visited` não muda isso. A geração de um setor só acontece durante uma viagem
feita dentro do jogo.

**Consequência de projeto:** o servidor não coloca jogador novo em lugar
nenhum. Todos nascem em casa e conquistam território voando — o que é melhor de
jogo, além de mais barato.

## 1.7 De quem é uma nave

**`<ship>/<settings>` tem `of` (id da facção) e `owner` (nome do lado). É isso
que manda.** Uma nave copiada continua sendo do jogador enquanto esses dois
disserem `461` e `Player`, mesmo com tripulação de outra facção e mesmo com
frota de NPC registrada apontando para ela.

Também é necessário registrar a nave numa frota do mapa estelar: um `<f>` no
`<fleets>` do corpo celeste, com `factionId`, `isPlayer="false"` e:

```xml
<createdShips>
  <l seed="..." createdShipId="SID" created="true" station="false"
     shipDamagedNoFTL="false" crew="N" cryoCrew="0" monsters="0" bigMonsters="0"
     hives="0" infesters="0" flybots="0" walkers="0" roboBase="0"
     derelict="false" addLoot="false" inHyper="false" sx="LARGURA" sy="ALTURA"/>
</createdShips>
```

Sem dono declarado o jogo improvisa, e o improviso depende da tripulação:

- tripulação `Player` → o jogo entrega a nave inteira ao jogador
- tripulação de outra facção → o jogo trata as pessoas como náufragos, o ônibus
  do jogador vai buscá-las e a nave vira destroço reivindicável

Naves de NPC costumam ter três nós que a do jogador não tem:

- `<asi>` — a IA da nave: rádio, cooldowns de saudação, postura de combate
- `<shipBank>` — créditos próprios e regras de preço. **É com isso que ela
  negocia.** Sem esse nó a nave não tem como comerciar
- `<markers>` — pontos de atracagem

Exemplo real de `<shipBank>`:

```xml
<shipBank s="Civilian" ca="12309" cr="0" slp="10066" blp="9891" spmd="2">
  <markup>
    <n element="2053" howMuch="1" consumeEvery="1"/>
  </markup>
  <discount/>
</shipBank>
```

## 1.8 Quem enxerga o quê

O interior de uma nave alheia **não** é escondido pelos dados da nave. Uma nave
de NPC autêntica, transplantada de outro save com `fg="0"` em cada célula,
`unex="1"` e `forceRoof="1"`, continuou aberta.

Quem manda é `hostmap/map/l`, a tabela de relações entre facções, por par:

| Permissão | O que governa |
|---|---|
| `accessTrade` | comerciar |
| `accessShip` | subir na nave |
| `accessVision` | ver dentro dela |
| `accessHire` | contratar a tripulação |

Num jogo novo o jogador começa **Friendly** com Civis, Mercantes e Militares,
relação na casa dos 70, e as permissões vêm todas ligadas — por isso se enxerga
o interior das naves deles no primeiro dia. Com o tempo a relação decai para
Neutral e as portas fecham.

**Essa tabela é o painel de controle do servidor** sobre o que um jogador pode
fazer com o retrato do outro.

Destroços são outro mecanismo: registrados no `<stuff>` do corpo com
`derelict="true"`, só se revelam abordando, independente de facção.

## 1.9 O que o jogo entrega de graça

Uma nave de outra facção parada no setor do jogador oferece **HAIL, TRADE e
MISSIONS** sem que nada seja construído, e chega a gerar missão própria.
Verificado: dá para comerciar sem nunca ter tido contato com a tripulação.

Para o projeto isso é decisivo: **a interface de comércio entre jogadores não
precisa ser inventada.** Ela é nativa, e funciona sem os dois estarem online.

O que uma nave dessas negocia é o estoque e os créditos **dela**, não os do
jogo. Quem monta o retrato decide o que fica exposto.

## 1.10 Não existe identidade de jogador no save

Procurado e não encontrado: `steam`, `account`, `userId`, `playerId`, prefixo de
SteamID64 — zero ocorrências. O que existe é `settings/@f = 461` (a facção do
jogador, igual em todo save do mundo), a frota `id=0` e o `playerBank`.

O jogo tem integração com Steam no jar, inclusive tickets de autenticação, mas
nada disso chega ao savegame.

**A identidade tem que ser do servidor.** Vantagens: funciona para cópias fora
da Steam, não depende de API nenhuma, e dentro do próprio save "eu" é sempre a
facção 461, sem ambiguidade.

Como o jogo tem um conjunto fixo de facções, dois vizinhos podem cair na mesma.
**Quem distingue um jogador do outro na tela é o nome da nave** (`sname`), que é
texto livre.

---

# Parte 2 — Projeto do servidor

## 2.1 Princípios

**O servidor é dono da verdade.** Ele guarda o save de cada jogador, empresta a
cada sessão e recebe de volta. O jogador não tem cópia canônica.

**Cooperativo, não competitivo.** Cada um roda o jogo na própria máquina, em
arquivos que consegue abrir. Um desenho onde se vence derrotando os outros pede
exatamente o comportamento que não dá para policiar. Um desenho onde se
sobrevive porque os vizinhos abastecem torna a trapaça sem graça.

**Sai contínuo, entra entre sessões.** O autosave alimenta o servidor enquanto
se joga; o que vem de volta chega na próxima abertura.

## 2.2 Identidade e salas

Conta criada no servidor, token guardado no cliente. Sem Steam.

Uma **sala** é:

| Campo | Descrição |
|---|---|
| `id` | identificador curto |
| `seed` | a seed de criação, que define a galáxia |
| `options` | as opções exatas de criação (dificuldade e os 21 parâmetros de cenário) |
| `password` | opcional |
| `roster` | jogadores, com o save canônico de cada um |
| `world` | estado compartilhado: quem está onde, consignações, eventos |

A listagem mostra nome, número de jogadores, e se tem senha. O cliente pede a
senha só na hora de entrar.

Por enquanto: um servidor, uma sala, uma seed. A estrutura já nasce por sala
para não precisar refazer.

**As opções de criação importam tanto quanto a seed.** Dois jogos com a mesma
seed e opções diferentes não dão a mesma galáxia. A sala precisa publicar as
opções e o cliente precisa conferi-las no save que receber.

## 2.3 Entrada de um jogador novo

É o único momento que exige o jogador, por causa de 1.6 — o servidor não
consegue gerar uma colônia inicial.

1. o cliente mostra a seed da sala e as opções exatas
2. o jogador cria a partida no jogo, normalmente
3. o cliente sobe o save recém-criado
4. o servidor confere que a galáxia bate com a da sala (impressão digital, ver
   `tools/compare_galaxy.py`) e adota o save como canônico daquele jogador

Uma vez só. Depois disso o servidor é dono.

Se a impressão digital não bater, o save é recusado com a explicação — quase
sempre é opção de criação diferente.

## 2.4 Ciclo de uma sessão

```
retirada  → o servidor monta o save do jogador, com vizinhos e entregas
            pendentes já dentro, e entrega ao cliente
jogo      → o cliente grava numa pasta dedicada da sala e o jogador joga
batimento → o cliente observa os autosaves e manda o estado ao servidor
devolução → o cliente sobe o save final; o servidor concilia e guarda
```

**Prazo de retirada.** Quem não devolve volta ao estado de quando pegou. Isso
tapa o buraco de "só devolvo a sessão que foi boa" e resolve cliente travado.

**Recuperação de queda.** O jogo pode fechar sozinho. O cliente precisa
conseguir devolver o último autosave, e o servidor valida igual.

**O último batimento é o que fica.** Depois que o jogador desconecta, é esse
estado que os outros veem.

## 2.5 O que o servidor injeta na retirada

Para cada vizinho da sala cuja frota esteja no mesmo corpo celeste:

1. a nave dele em `game/ships`, com `sid` novo tirado do `masterData/@idCounter`
   do save de destino
2. `entId` novo para cada tripulante, do mesmo contador
3. `<ship>/<settings>` com `of` e `owner` da facção escolhida para representá-lo
4. `<asi>` copiado de uma nave de NPC, para a IA existir
5. `<shipBank>` contendo **apenas o que aquele jogador consignou**, com `ca`
   limitando quanto ela consegue comprar
6. `fg="0"` em cada célula, `unex="1"`, `forceRoof="1"`
7. uma frota `<f>` no corpo celeste, com `createdShipId` apontando para o `sid`
8. no `hostmap`, as permissões daquela facção: `accessTrade` conforme a relação,
   `accessVision` e `accessShip` desligados

O nome da nave (`sname`) carrega a identidade do jogador dono.

Entregas pendentes (compras fechadas, presentes) entram direto no porão da nave
do jogador, como pilhas em um `<inv>` de armazém.

## 2.6 Consignação e conciliação

O medo legítimo é: "alguém compra todo o meu estoque e eu abro o jogo sem nada".

O desenho que resolve: **banca de feira, não porão.**

- o jogador consigna o que quer vender; **só isso entra no retrato**
- o resto do estoque não existe naquela cópia, então ninguém pode comprar
- os créditos do `ca` limitam quanto aquela nave consegue comprar
- na conciliação o servidor desconta do consignado e credita o vendedor
- o porão real nunca fica exposto

Segunda trava: as permissões por facção. Um vizinho pode negociar sem enxergar o
porão; um desafeto não negocia nem se aproxima.

## 2.7 Postura sobre trapaça

O jogo roda na máquina do jogador, em arquivos que ele consegue editar. Isso não
tem solução, e o documento não finge que tem.

O que dá para fazer, e é bastante:

- **fim do save scumming.** Existe uma cópia só e o servidor sabe qual é.
  Recarregar um save antigo não é aceito
- **fim da duplicação por sessão paralela**
- **conferência, não adivinhação.** O servidor montou o arquivo que entregou,
  então na devolução ele compara os dois e pergunta: quanto tempo passou e
  quanto os módulos produziriam nele? de onde vieram esses créditos? essa carga
  cabia na nave que a transportou? esse tripulante estava a bordo na saída? essa
  pesquisa tinha pontos?

Divergência não precisa virar punição automática. Pode virar sinalização, e num
mundo cooperativo isso costuma bastar.

## 2.8 Responsabilidades do cliente

O cliente é a evolução do editor de savegame, que já lê e grava um save byte a
byte sem perturbar nada que não foi pedido.

- autenticar, listar salas, entrar
- gerenciar uma pasta de savegame por sala
- **nunca escrever com o jogo aberto** — detectar o processo e recusar. É a
  regra que evita destruir a partida de alguém
- observar os autosaves e mandar batimento
- subir o save final ao detectar que o jogo fechou
- mostrar o mapa da sala entre sessões

## 2.9 Como o cliente conversa com o jogo

**Princípio que não se negocia: a simulação é da Bugbyte e não se toca nela.**
Tudo que este projeto faz é ler e gravar savegame — o mesmo que jogadores fazem
na mão há anos. O servidor é uma camada ao lado do jogo, nunca dentro dele.

### O launcher é configurável

O executável `spacehaven` não é o jogo: é um launcher nativo de 86 KB que lê
`config.json`, cria uma JVM e carrega a classe principal.

```json
{
  "classPath": ["spacehaven.jar"],
  "mainClass": "fi.bugbyte.spacehaven.steam.SpacehavenSteam",
  "vmArgs": ["-Xmx4G"]
}
```

Nas strings do binário aparecem `Error: no 'mainClass' element found in config!`
e a assinatura de `URLClassLoader`. Classpath e classe principal são
configuráveis por arquivo de texto, e as classes do jogo não estão ofuscadas.

### Existe um template de mod da comunidade

<https://github.com/Spacehaven-modding-tools/SpaceHavenModTemplate> — **da
comunidade, não da Bugbyte.** Não há API oficial nem hooks providos pelo jogo.

Ele usa AspectJ com weaving em tempo de carga: você declara pointcuts que
envolvem métodos do jogo, coloca seu jar em `mods/` e acrescenta a entrada no
`classPath` do `config.json`. Exige `aspectj-1.9.19` e `aspectjweaver` na pasta
do jogo, e Java 17+. Pointcuts do tipo `around` envolvem um método e decidem se
o original chega a rodar.

### O que um mod desbloquearia

Envolver as rotinas de gravação e carregamento dá **limites de sessão exatos**,
em vez de vigiar arquivos de autosave e inferir. Indo além, dá para manipular
objetos vivos do jogo em vez de editar arquivo, o que abriria a porta para
colocar a nave de um vizinho no setor sem fechar a partida.

### O que ele não muda

A simulação continua local e não determinística. Dois jogadores se vendo mover
ao vivo exigiria uma camada de rede nossa lutando contra as premissas do jogo.

E o custo é real: o jogador precisa instalar AspectJ, editar o `config.json` e
ter Java 17. Cada atualização do jogo pode quebrar os pointcuts, porque eles
apontam para assinaturas de método que ninguém prometeu manter.

### A decisão

**O cliente lança o jogo ele mesmo.** Executa o binário e espera o processo
terminar. Não toca em código nem em configuração, é só gerenciamento de
processo, e resolve a regra mais importante do cliente: como ele é quem inicia e
quem espera o fim, sabe com certeza quando o jogo está aberto e nunca escreve
por cima.

**O mod é opcional e não bloqueia fase nenhuma.** Um mod mínimo, que só envolva
salvar e carregar sem tocar em lógica de jogo, melhora a precisão dos limites de
sessão. Quem instalar ganha isso; quem não instalar continua funcionando com a
vigilância de arquivos. Fazer dele um requisito multiplicaria a fricção de
instalação antes de existir qualquer coisa para aproveitar — e o objetivo das
primeiras fases é justamente descobrir se alguém quer isso.

**Injeção ao vivo fica para depois de existirem jogadores.** É a evolução
natural e agora se sabe que é possível.

## 2.10 Fases

| Fase | Entrega | O que prova |
|---|---|---|
| **0** | conta, salas, sobe e desce save | a custódia funciona, sem multiplayer nenhum |
| **1** | batimento por autosave, mapa web da sala | a sala fica viva entre sessões |
| **2** | injeção de vizinho, sem comércio | você abre o jogo e a nave de alguém está lá |
| **3** | consignação e conciliação | comércio de verdade entre jogadores |

Fora da fila, sem bloquear nada: o **mod mínimo** de 2.9, que dá limites de
sessão exatos a quem quiser instalá-lo, e a **injeção ao vivo**, que só faz
sentido depois que houver gente jogando.

A fase 0 já é um produto sozinha: save na nuvem, com histórico e sem save
scumming. E é a que mais ensina, porque expõe cedo o que é chato de verdade —
sessão abandonada, cliente travado, jogo que fecha sozinho.

Escopo do primeiro corte: **só comércio e as missões que o próprio jogo gera.**
Transferir tripulação e naves inteiras é possível (verificado), mas cada uma
traz regra de jogo própria e pode esperar.

## 2.11 Confiança e adoção

A barreira real deste projeto não é técnica. É que a comunidade — com razão —
não instala aplicativo desconhecido, e ainda menos um que sobe arquivos para
algum servidor. Se isso não for resolvido de propósito, o resto não importa.

### A sequência importa mais que o argumento

Cada degrau pede um pouco mais de confiança que o anterior e entrega algo antes
de pedir o próximo:

1. **O editor de savegame**, que serve sozinho e não manda nada para lugar
   nenhum. Ganha uma base de gente que já usa e já confia.
2. **O mapa da sala como página web.** Nada para instalar: a pessoa vê o mundo
   compartilhado vivo e decide se quer entrar. Dá para permitir participação sem
   instalação nenhuma, com a pessoa escolhendo a pasta do save no navegador,
   clique a clique.
3. **O cliente**, que vira comodidade em vez de porta de entrada — e chega como
   *uma aba a mais numa ferramenta que a pessoa já tem*, não como app novo.

A diferença de conversão entre "instale este app desconhecido para jogar com
estranhos" e "aquele editor que você já usa agora conecta numa sala" é enorme.

### Verificável em vez de confiável

- **Rodar do código é a opção principal.** O editor é biblioteca padrão do
  Python; o cliente deve manter essa propriedade enquanto for possível.
- **Build público a partir de fonte público.** O binário é montado pelo GitHub
  Actions a partir do commit da tag, e o log fica público. A afirmação
  checável é: *este binário saiu deste commit, e aqui está o registro*.
  Linkar a execução nas notas da release.
- **Checksums em toda release**, e link de análise antivírus pública.
- **Assinatura de código** custa dinheiro e pode esperar; não substitui nada
  acima.

### O servidor precisa ser auto-hospedável

É a alavanca que mais muda a conversa numa comunidade de modding. Com o servidor
aberto e fácil de subir, ninguém precisa confiar em ninguém: um grupo de amigos
levanta a própria sala. O autor deixa de ser um serviço a quem entregar dados e
passa a ser autor de uma ferramenta. E vai acontecer de qualquer jeito — sempre
aparece quem quer a sala privada.

### Política de dados, escrita antes de existir

O editor promete hoje que nada sai do computador. **O cliente quebra essa
promessa**, e fingir que não seria o pior erro possível. Então, em linguagem
clara e onde a pessoa lê antes de instalar:

- o que sobe: o arquivo de save, inteiro
- para onde
- quem enxerga: o servidor e, em forma de retrato, os outros jogadores da sala
- por quanto tempo fica guardado
- como apagar tudo e sair

E dentro do cliente:

- **registro visível** de tudo que foi enviado e de todo arquivo escrito
- **modo de ensaio**: mostrar o que seria alterado sem alterar
- nunca encostar na instalação do jogo. Se o mod opcional de 2.9 existir um dia,
  vem separado, com aviso, e nunca embutido

### Franqueza sobre o que não dá para impedir

Dizer abertamente que o jogo roda na máquina do jogador, que dá para editar o
save, e que por isso o desenho é cooperativo e o servidor confere em vez de
adivinhar. Comunidade de modding respeita isso e desconfia do contrário — quem
promete segurança absoluta é quem não pensou no assunto.

## 2.12 Suposições ainda não testadas

Marcadas para quem for implementar não tomar como fato:

- **injeção mútua.** Testamos injetar uma nave num save. Não testamos dois
  jogadores se vendo ao mesmo tempo, cada um no seu save
- **comércio conciliável.** Vimos o TRADE aparecer e funcionar. Não medimos como
  a transação fica registrada no save, nem se dá para reconstruí-la na
  devolução. **É o próximo experimento a fazer**, e ele decide a fase 3
- **estabilidade com muitos vizinhos.** Testamos uma nave injetada. Dez podem
  pesar, ou confundir a IA
- **atualização do jogo.** Se a Bugbyte mudar o formato, tudo aqui precisa ser
  reconferido. O `compare_galaxy.py` detecta mudança de geração; o resto é na
  mão
- **missões geradas em nave injetada.** O jogo criou uma. Não sabemos se ela se
  resolve bem, nem o que acontece se a nave sumir no meio

## 2.13 Aviso legal

Space Haven é um jogo da Bugbyte Ltd. Este é um projeto independente, feito por
fã, sem vínculo com ela. Nada aqui altera o código do jogo: tudo é leitura e
escrita de savegame, que jogadores fazem na mão há anos.

O que **não** pode ser redistribuído é conteúdo do jogo. O editor de origem
extrai a tabela de nomes do `spacehaven.jar` da instalação do próprio usuário,
justamente para não redistribuir. O servidor deve seguir a mesma regra.

Se o projeto encontrar público, vale mostrar à Bugbyte — não como pedido de
permissão, que não é necessário, mas como demonstração de que a demanda existe.
