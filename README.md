# Space Haven Savegame Editor

*[Leia em português](README.pt-BR.md)*

A local editor for Space Haven savegames. It reads the save, shows every
parameter in tabs (using the game's own names) and writes the changes back.

Interface in **English and Brazilian Portuguese**, switchable in the top-right
corner.

**Windows and Linux builds** are ready to download — no Python, no install.
See [Ready-made executable](#ready-made-executable).

<!-- Screenshots: drop the images in docs/ and uncomment.
![Crew tab](docs/screenshot-crew.png)
![Storage tab](docs/screenshot-storage.png)
-->

## Why another save editor

Other editors exist and are good. This one exists for the cases they don't
cover:

- **Linux is a first-class target** — a native binary, not a workaround.
- **Full Brazilian Portuguese**, including the game's own names for resources,
  technologies, traits and skills. They come from your copy of the game, not
  from a hand-written translation.
- **Byte-identical writes.** Loading a save and writing it back without
  changing anything produces files identical to the originals; editing one
  attribute changes exactly that one line. Nothing else in the file is
  rewritten, reordered or reformatted.
- **A raw XML tab** with search across the whole save, for everything the
  purpose-built tabs don't expose.
- **No dependencies.** Pure Python standard library, so you can read the whole
  thing and run it from source instead of trusting a binary.

## Running it

Needs **Python 3.10+** only.

```bash
python3 run.py                    # opens the save picker in your browser
python3 run.py path/to/save       # opens a save directly
```

The interface runs in the browser (`http://127.0.0.1:8713`), but the process
reading and writing your files is the local Python one. Nothing leaves your
machine.

## Disclaimer

**Space Haven** is a game by [Bugbyte Ltd.](https://bugbyte.fi/) This editor is
an independent, fan-made project: it is not official, not endorsed by Bugbyte,
and has no affiliation with them.

The file `shedit/data/gamedata.json` contains names and descriptions extracted
from the game's data files. **That content belongs to Bugbyte Ltd.**, and is
included only so the editor can show readable names instead of the numeric IDs
stored in savegames. No other game material is redistributed.

## Tabs

| Tab | What you can change |
|---|---|
| **Game** | clock (days/hours/turns), credits, seed, player faction, difficulty and the scenario rules (monsters, robots, solar flares, asteroids…) |
| **Crew** | name, needs (health, food, energy, comfort, mood…), attributes, skills with level/cap/exp, traits, conditions and work priorities, plus creating a new crew member on the selected ship. The list shows one ship at a time — the player's by default — and stays pinned while you scroll. It includes crew piloting a miner, builder or fighter; visitors from other factions stay hidden until you ask for them |
| **Storage** | totals per resource and per ship, quantity of each stack, adding a new resource to a rack, or creating one of each at once |
| **Research** | state of every technology; complete or reset one or all |
| **Ships** | name, ID, fog of war |
| **Factions** | stance, relation, patience and permissions (trade, access, hiring) between each pair of factions |
| **XML** | browser for the whole tree: any attribute of any node, with search across the entire save |

The Crew, Storage and Research tabs have bulk actions (restore the whole crew,
fill the racks, complete all research) for what would be tedious field by
field. In Crew they sit in a bar pinned above the scrolling area, and by
default apply only to the ship in focus — the selector next to them switches
to the player's entire crew.

## How it works

A Space Haven save is a folder of XML files:

```
save/
  game               the run, research, bank, factions and the ships in the current sector
  ships/shipNNNN     one ship outside the current sector, per file
  info, stats.bin, timeline.xml    (the editor doesn't touch these)
```

The editor loads `game` **and** every ship in `ships/` — including their crew.
When saving, only the files that actually changed are rewritten, each with a
`.bak-YYYYMMDD-HHMMSS` backup next to it.

Serialization reproduces the game's own style byte for byte, which is what
makes a no-op round trip a no-op on disk.

### Languages

The interface has English and PT-BR, switchable at any time from the top bar —
no page reload. On the first visit it follows the browser's language; after
that the choice lives in `localStorage`.

Interface text lives in a single catalog, `shedit/data/i18n.json`, used both by
Python (labels built on the backend) and by the browser (everything else),
which receives it from `/api/i18n`. To fix a translation or add a language,
edit that file and `LANGS` in `shedit/i18n.py`.

The game's own names — resources, technologies, traits, skills — are not in
that catalog: they come from `gamedata.json`, which already carries EN and
PT-BR extracted from the game. That is why "Hyperium" becomes "Hipério" and
"Bravery" becomes "Coragem" along with the rest of the interface.

Backend error messages (file not found, invalid save) are still Portuguese
only.

### Names instead of IDs

The save stores everything as numeric IDs (`elementaryId="1873"`,
`techId="2532"`, `sk="16"`). The readable names come from
`shedit/data/gamedata.json`, extracted from the `spacehaven.jar` in your own
installation:

```bash
python3 tools/extract_gamedata.py                        # finds the jar by itself
python3 tools/extract_gamedata.py /path/to/spacehaven.jar
```

Run it again after the game updates. Without that file the editor works the
same, it just shows the raw IDs.

The extractor reads the texts and definitions from `library/texts` and
`library/haven`, and the internal enums (skills, professions, priorities) by
reflection, using the `jjs` from the JRE that ships with the game — so the
tables are the game's own, not a hand-maintained list.

The contents of that table (887 names and 811 descriptions, in EN and PT-BR)
belong to Bugbyte Ltd. — see the [disclaimer](#disclaimer).

## Where the saves are

The picker opens in the right folder when it finds the installation. Default
Steam paths:

- Linux: `~/.steam/steam/steamapps/common/SpaceHaven/savegames`
  (or `~/snap/steam/common/.local/share/Steam/...` for Steam via snap)
- Windows: `C:\Program Files (x86)\Steam\steamapps\common\SpaceHaven\savegames`
- macOS: `~/Library/Application Support/Steam/steamapps/common/SpaceHaven/savegames`

Inside each run there is `save/` (the current save) and `autosave1..4`.

### About crew needs

For health, food, energy and comfort **higher is better** — this comes from the
condition triggers in the game itself (food < 20 "a little hungry", < 10
"starvation", > 120 "ate too much"; energy < 15 "extremely fatigued", < −5
"unconscious"). For inhaled gases it is the opposite: 0 is clean air.

Each need has a current value and a long-term one — the same ones the
conditions read as `whenPresent` and `whenLongTerm`. For food, comfort, oxygen
and temperature the current value stored in the save is a constant the game
recalculates on load, so the editor only exposes what actually persists (the
long-term satiety, and for oxygen the suit reserve).

Energy is what the game calls ENERGY and equals `80 + Zest × 15`, minus the
awake-time penalty and the work penalty. Those two penalties are what drain the
bar, and they are what "Restore needs" touches — zeroing them is equivalent to
a turn of sleep. Augmentation bonuses and penalties coming from conditions
(post-surgery fatigue, for instance) are applied on top; to clear those, use
"Remove conditions".

The food bar is the stomach contents — the same thing the game's tooltip shows
as "Stomach". Restoring fills it with one ration of Space Food (P15 C20 F10
V10), which is what the game gives for a full meal. The stomach fields are also
editable one by one.

### Crew who aren't aboard

Anyone piloting a miner, builder or fighter isn't in the ship's `<characters>`:
they sit inside `<crafts>`, with a `homeSid` link pointing back to the mother
ship. The editor merges the two, marking where each person is.

Ships also get visitors — merchants using your medical beds show up in your
station's own `<characters>`. They are hidden by default and left out of bulk
actions; the selector shows the count separately ("15 + 8 visitors").

### Creating a crew member

"+ New crew member" in the Crew tab adds someone to the ship in focus. You give
a first and last name (leave them blank for a random one drawn from the names
already in your save), a value for the four attributes and a starting skill
level.

The new sheet is a copy of someone already aboard, with everything individual
replaced. That is deliberate: a character node has eleven required sub-trees,
and one missing piece surfaces only as a save the game refuses to load. Copying
from the same ship is also what guarantees a usable position — the coordinates
belong to that ship's grid, and someone placed outside it would be stuck.

What gets replaced: a fresh `entId` reserved from `masterData/@idCounter`, the
same counter the game allocates from; new name and appearance; no traits, no
conditions, no relationships, no equipment and no augmentations (gear carries
its own entity ids, and cloning it would duplicate them); work priorities all
at Normal; needs full. Health goes to 100 and suit oxygen to 0 rather than
following the template, since the newcomer has neither the implants nor the
suit that earned those numbers.

Because the copy comes from the crew aboard, this only works on ships that
already have someone on them.

## Before you edit

- **Close the game.** It rewrites the save when it saves, overwriting your
  changes.
- The editor backs up on every write, but a copy of the whole save kept aside
  costs nothing.
- The XML tab validates nothing: you can edit any attribute, including the ones
  that break the run. The other tabs only offer fields with known ranges.

## Options

```
python3 run.py [save] [--port 8713] [--host 127.0.0.1] [--no-browser]
```

## Ready-made executable

Every `v*` tag publishes the binaries in a release: download the one for your
system and run it. No Python, no install.

- **Windows** — `SpaceHavenEditor-windows.exe`. The first time, SmartScreen
  warns that the program is unknown: *More info → Run anyway*.
- **Linux** — `SpaceHavenEditor-linux`; `chmod +x` it before running.

The binaries are not code-signed, so Windows and some antivirus tools will flag
them — normal for PyInstaller output. Every release ships a `SHA256SUMS` file
so you can check what you downloaded:

```bash
sha256sum -c SHA256SUMS            # Linux
certutil -hashfile SpaceHavenEditor-windows.exe SHA256    # Windows
```

If you'd rather not run a binary from a stranger, the whole thing is Python
standard library — read it and run `python3 run.py` from source.

The console window that opens alongside is where the editor's address appears;
closing it (or Ctrl+C) shuts the server down.

### Packaging it yourself

```bash
pip install pyinstaller
pyinstaller --clean --noconfirm SpaceHavenEditor.spec
python3 tools/smoke_test.py dist/SpaceHavenEditor      # dist/SpaceHavenEditor.exe on Windows
```

The binary lands in `dist/`. The `.spec` embeds `shedit/data/*.json` and
`shedit/web/`; the paths in it are relative, so the same file works on both
systems.

PyInstaller does **not** cross-compile: the Windows executable has to be built
on Windows. That is what `.github/workflows/build.yml` does, with a matrix of
`ubuntu-latest` and `windows-latest`.

The smoke test launches the real binary and checks that the API answers and the
data was embedded — without it, a build missing the JSON files would pass and
only look broken to whoever downloaded it.

## Layout

```
run.py                       entry point: starts the server and opens the browser
shedit/
  savefile.py                reading, editing by path and byte-exact writing
  views.py                   builds the contents of each tab
  actions.py                 bulk actions
  gamedata.py                IDs -> names
  i18n.py                    interface text (EN / PT-BR)
  resources.py               locates the data (packaged or not)
  server.py                  local HTTP server (stdlib only)
  data/gamedata.json         table extracted from the game
  data/i18n.json             interface text catalog
  web/                       interface (HTML/CSS/JS, no dependencies)
tools/extract_gamedata.py    regenerates data/gamedata.json from the jar
tools/smoke_test.py          checks that the packaged executable works
SpaceHavenEditor.spec        PyInstaller recipe
.github/workflows/build.yml  Windows and Linux builds + release on tag
```

## License

[MIT](LICENSE) for the editor's source code. The game data in
`shedit/data/gamedata.json` belongs to Bugbyte Ltd. and is not covered by it —
see [NOTICE](NOTICE) and the [disclaimer](#disclaimer).
