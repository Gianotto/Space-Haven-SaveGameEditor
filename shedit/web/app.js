'use strict';

/* Interface do editor. Toda alteracao vira uma operacao {path, attr, valor}
   enviada ao processo Python, que mantem a arvore do save em memoria. O botao
   "Gravar" e o unico que escreve no disco. */

const $ = (sel, root = document) => root.querySelector(sel);
const state = {
  status: null,
  tab: null,
  data: null,
  sel: {},          // selecao corrente por aba (tripulante, nave, no do XML)
  filter: {},       // texto dos filtros por aba
  lang: 'pt',
  strings: {},      // catalogo do idioma corrente, vindo de /api/i18n
};

/* ------------------------------------------------------------- idioma -- */

/** Texto da interface. As chaves vêm do mesmo catálogo que o backend usa,
    então um rótulo montado no Python e um escrito aqui falam a mesma língua. */
function T(key, fmt) {
  let text = state.strings[key];
  if (text === undefined) return key;
  if (fmt) for (const [k, v] of Object.entries(fmt)) text = text.split(`{${k}}`).join(v);
  return text;
}

const LANG_TAGS = { pt: 'pt-BR', en: 'en' };

async function loadLanguage(lang) {
  const res = await api('/api/i18n?lang=' + encodeURIComponent(lang));
  state.lang = res.lang;
  state.strings = res.strings;
  state.languages = res.languages;
  try { localStorage.setItem('shedit.lang', res.lang); } catch { /* modo privado */ }
  document.documentElement.lang = LANG_TAGS[res.lang] || res.lang;
  applyStaticStrings();
}

/** Traduz o HTML estático (cabeçalho e diálogo) a partir dos data-i18n. */
function applyStaticStrings() {
  for (const el of document.querySelectorAll('[data-i18n]')) el.textContent = T(el.dataset.i18n);
  for (const el of document.querySelectorAll('[data-i18n-title]')) el.title = T(el.dataset.i18nTitle);
  for (const el of document.querySelectorAll('[data-i18n-placeholder]'))
    el.placeholder = T(el.dataset.i18nPlaceholder);
}

/** Acrescenta ?lang= às chamadas que devolvem texto traduzido. */
function withLang(url) {
  return url + (url.includes('?') ? '&' : '?') + 'lang=' + encodeURIComponent(state.lang);
}

/* --------------------------------------------------------------- utils -- */

function h(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === 'class') node.className = v;
    else if (k === 'html') node.innerHTML = v;
    else if (k.startsWith('on')) node.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k === 'value') node.value = v;
    else node.setAttribute(k, v === true ? '' : v);
  }
  for (const c of children.flat(3)) {
    if (c === null || c === undefined || c === false) continue;
    node.append(c.nodeType ? c : document.createTextNode(String(c)));
  }
  return node;
}

let toastTimer;
function toast(message, kind = '') {
  const el = $('#toast');
  el.textContent = message;
  el.className = 'show ' + kind;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.className = kind; }, 3200);
}

async function api(path, options) {
  const res = await fetch(path, options);
  let payload;
  try { payload = await res.json(); } catch { payload = { error: T('toast.badResponse', { status: res.status }) }; }
  if (!res.ok || payload.error) throw new Error(payload.error || T('toast.httpError', { status: res.status }));
  return payload;
}

const post = (path, body) => api(path, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body || {}),
});

/* ------------------------------------------------------------- patches -- */

async function patch(ops, opts = {}) {
  try {
    const res = await post('/api/patch', { ops });
    markDirty(res.dirty);
    if (opts.refresh) await loadTab(state.tab, { keepScroll: true });
    return res;
  } catch (err) {
    toast(err.message, 'bad');
    throw err;
  }
}

async function action(name, params, opts = {}) {
  try {
    const res = await post('/api/action', { name, params });
    markDirty(res.dirty);
    if (res.changed === 0) toast(T('toast.nothing'));
    else toast(res.changed === 1 ? T('toast.changedOne')
                                 : T('toast.changedMany', { n: res.changed }), 'ok');
    if (opts.refresh !== false) await loadTab(state.tab, { keepScroll: true });
    return res;
  } catch (err) {
    toast(err.message, 'bad');
  }
}

function markDirty(dirty) {
  if (state.status) state.status.dirty = dirty;
  const el = $('#status');
  el.textContent = dirty ? T('app.dirty') : T('app.clean');
  el.className = 'status ' + (dirty ? 'dirty' : 'saved');
}

/* -------------------------------------------------------------- campos -- */

/** Renderiza um campo editavel descrito pelo backend.
    `opts.bare` omite o rotulo — usado dentro de tabelas, onde o cabecalho
    da coluna ja diz o que o campo e. */
function fieldInput(f, onChanged, opts = {}) {
  const commit = (value) => {
    patch([{ op: 'set', path: f.path, attrs: { [f.attr]: value } }])
      .then(() => { if (onChanged) onChanged(value); });
  };

  if (f.type === 'bool') {
    const input = h('input', { type: 'checkbox' });
    input.checked = String(f.value) === 'true';
    input.addEventListener('change', () => commit(input.checked ? 'true' : 'false'));
    return h('label', { class: 'check' }, input, opts.bare ? null : f.label);
  }

  let input;
  if (f.type === 'select') {
    input = h('select');
    const options = f.options || [];
    if (!options.some(o => String(o.value) === String(f.value)) && f.value != null)
      input.append(h('option', { value: f.value }, f.value));
    for (const o of options) input.append(h('option', { value: o.value }, o.label));
    input.value = f.value ?? '';
    input.addEventListener('change', () => { input.classList.add('changed'); commit(input.value); });
  } else {
    const numeric = f.type === 'int' || f.type === 'float';
    input = h('input', {
      type: numeric ? 'number' : 'text',
      value: f.value ?? '',
      step: f.type === 'float' ? 'any' : (numeric ? '1' : null),
      min: f.min !== undefined ? f.min : null,
      max: f.max !== undefined ? f.max : null,
    });
    input.addEventListener('change', () => { input.classList.add('changed'); commit(input.value); });
  }

  if (opts.bare) return input;
  return h('label', { class: 'field' },
    h('span', {}, f.label, f.hint ? h('em', { class: 'mono' }, f.hint) : null),
    input);
}

const bareInput = (f) => fieldInput(f, null, { bare: true });

const fieldGrid = (fields, onChanged) =>
  h('div', { class: 'grid' }, fields.map(f => fieldInput(f, onChanged)));

/* ---------------------------------------------------------------- abas -- */

const RENDER = {};

RENDER.game = (d) => h('div', {},
  d.groups.map(g => h('section', { class: 'card' },
    h('h2', {}, g.title),
    g.hint ? h('p', { class: 'hint' }, g.hint) : null,
    fieldGrid(g.fields))));

/* ------------------------------------------------------------ tripulação */

RENDER.crew = (d) => {
  if (!d.ships.length) return h('div', { class: 'empty' }, T('crew.empty'));

  // Nave em foco: a do jogador por padrão.
  if (!d.ships.some(s => s.path === state.sel.crewShip)) {
    state.sel.crewShip = (d.ships.find(s => s.isPlayer) || d.ships[0]).path;
  }
  const ship = d.ships.find(s => s.path === state.sel.crewShip);

  // Visitantes de outras facções ficam no mesmo <characters> da nave; por
  // padrão a lista mostra só quem é da nave.
  const showVisitors = state.filter.crewVisitors === true;
  const shown = ship.characters.filter(c => showVisitors || c.side === ship.mainSide);
  if (!shown.length) return h('div', { class: 'empty' }, T('crew.emptyShip'));

  if (!shown.some(c => c.path === state.sel.crew)) state.sel.crew = shown[0].path;
  const current = shown.find(c => c.path === state.sel.crew);

  const list = h('div', { class: 'list pinned' },
    h('div', { class: 'group' }, ship.ship,
      ship.isPlayer ? h('span', { class: 'pill accent', style: 'margin-left:6px' }, T('crew.player')) : null,
      ship.inSector ? null : h('span', { class: 'pill', style: 'margin-left:6px' }, T('crew.outOfSector'))),
    shown.map(c => h('button', {
      class: 'item' + (c.path === state.sel.crew ? ' active' : ''),
      onclick: () => { state.sel.crew = c.path; render(); },
    }, `${c.name} ${c.lname}`.trim() || `#${c.cid}`,
       h('small', {}, [c.side, c.task].filter(Boolean).join(' · ')),
       c.where ? h('small', { style: 'color:var(--accent)' }, T('crew.in', { where: c.where })) : null)));

  setToolbar(crewToolbar(d, ship));

  return h('div', { class: 'split' }, list, current ? crewDetail(current, d) : h('div'));
};

function crewToolbar(d, ship) {
  const showVisitors = state.filter.crewVisitors === true;

  const shipPicker = h('select', {
    onchange: (e) => { state.sel.crewShip = e.target.value; render(); },
  }, d.ships.map(s => h('option', { value: s.path, selected: s.path === state.sel.crewShip },
    `${s.ship} (${s.ownCount}${s.visitorCount ? ' + ' + T('crew.visitorsCount', { n: s.visitorCount }) : ''})`
      + (s.isPlayer ? T('crew.playerSuffix') : '')
      + (s.inSector ? '' : T('crew.outOfSectorSuffix')))));

  const visitors = h('label', { class: 'check' },
    h('input', {
      type: 'checkbox', checked: showVisitors,
      onchange: (e) => { state.filter.crewVisitors = e.target.checked; render(); },
    }),
    T('crew.visitorsShow') + (ship.visitorCount ? ` (${ship.visitorCount})` : ''));

  // As ações em lote seguem o filtro por padrão; a alternativa explícita evita
  // a surpresa de mexer em naves que não estão à vista.
  const scope = h('select', {
    onchange: (e) => { state.filter.crewScope = e.target.value; renderInPlace(); },
  },
    h('option', { value: 'ship', selected: state.filter.crewScope !== 'all' }, T('crew.scopeShip')),
    h('option', { value: 'all', selected: state.filter.crewScope === 'all' }, T('crew.scopeAll')));

  // Numa nave, a ação vale para quem é dela — visitantes só entram se estiverem
  // sendo exibidos. No escopo global, sempre só a tripulação do jogador.
  const target = () => state.filter.crewScope === 'all'
    ? {}
    : { shipPath: ship.path, ...(showVisitors ? {} : { side: ship.mainSide }) };

  return h('div', { class: 'inner' },
    h('div', { class: 'row' },
      h('strong', {}, T('crew.ship')), shipPicker, visitors,
      h('span', { class: 'spacer' }),
      h('strong', {}, T('crew.bulk')), scope),
    h('div', { class: 'row' },
      h('button', { class: 'btn', onclick: () => action('crew.restore', target()) }, T('crew.restore')),
      h('button', { class: 'btn', onclick: () => action('crew.clearConditions', target()) }, T('crew.clearConditions')),
      h('button', { class: 'btn', onclick: () => action('crew.raiseSkillCaps', { ...target(), cap: 8 }) }, T('crew.skillCaps')),
      h('button', { class: 'btn', onclick: () => action('crew.maxSkills', { ...target(), level: 8, onlyWithinMax: false }) }, T('crew.maxSkills')),
      h('button', { class: 'btn', onclick: () => action('crew.maxAttributes', { ...target(), points: 10 }) }, T('crew.maxAttributes'))));
}

function crewDetail(c, d) {
  const box = h('div');
  const only = { path: c.path };

  box.append(h('section', { class: 'card' },
    h('h2', {}, `${c.name} ${c.lname}`.trim(),
      ' ', h('span', { class: 'pill accent' }, c.faction),
      c.side !== 'Player' ? h('span', { class: 'pill' }, c.side) : null,
      c.where ? h('span', { class: 'pill accent', style: 'margin-left:6px' }, c.where) : null),
    fieldGrid(c.identity, () => loadTab('crew', { keepScroll: true }))));

  if (c.needs.length) box.append(h('section', { class: 'card' },
    h('h2', {}, T('crew.needs')),
    d.needsHint ? h('p', { class: 'hint' }, d.needsHint) : null,
    h('div', { class: 'row', style: 'margin-bottom:10px' },
      h('button', { class: 'btn small', onclick: () => action('crew.restore', only) }, T('crew.restoreAll'))),
    fieldGrid(c.needs)));

  if (c.attributes.length) box.append(h('section', { class: 'card' },
    h('h2', {}, T('crew.attributes')),
    h('div', { class: 'row', style: 'margin-bottom:10px' },
      h('button', { class: 'btn small', onclick: () => action('crew.maxAttributes', { ...only, points: 10 }) }, T('crew.allTen'))),
    fieldGrid(c.attributes)));

  if (c.skills.length) {
    const rows = c.skills.filter(s => !s.hidden).map(s => h('tr', {},
      h('td', {}, s.label),
      h('td', { class: 'num' }, bareInput(s.level)),
      h('td', { class: 'num' }, bareInput(s.max)),
      h('td', { class: 'num' }, bareInput(s.exp))));
    box.append(h('section', { class: 'card' },
      h('h2', {}, T('crew.skills')),
      h('p', { class: 'hint' }, T('crew.skillsHint')),
      h('div', { class: 'row', style: 'margin-bottom:10px' },
        h('button', { class: 'btn small', onclick: () => action('crew.raiseSkillCaps', { ...only, cap: 8 }) }, T('crew.capEight')),
        h('button', { class: 'btn small', onclick: () => action('crew.maxSkills', { ...only, level: 8, onlyWithinMax: false }) }, T('crew.levelEight'))),
      h('table', {},
        h('thead', {}, h('tr', {}, h('th', {}, T('crew.skill')), h('th', { class: 'num' }, T('crew.level')),
          h('th', { class: 'num' }, T('crew.max')), h('th', { class: 'num' }, T('crew.exp')))),
        h('tbody', {}, rows))));
  }

  const traitPicker = h('select');
  traitPicker.append(h('option', { value: '' }, T('crew.addTrait')));
  for (const t of d.traitCatalog) traitPicker.append(h('option', { value: t.id, title: t.desc }, t.label));
  traitPicker.addEventListener('change', () => {
    if (traitPicker.value) action('crew.addTrait', { ...only, traitId: traitPicker.value });
  });
  box.append(h('section', { class: 'card' },
    h('h2', {}, T('crew.traits')),
    h('div', { class: 'tags' }, c.traits.length ? c.traits.map(t => h('span', { class: 'tag', title: t.desc },
      t.label,
      h('button', { title: T('crew.remove'), onclick: () => patch([{ op: 'remove', path: t.path }], { refresh: true }) }, '×')))
      : h('span', { class: 'hint' }, T('crew.noTraits'))),
    traitPicker));

  box.append(h('section', { class: 'card' },
    h('h2', {}, T('crew.conditions')),
    h('div', { class: 'row', style: 'margin-bottom:10px' },
      h('button', { class: 'btn small danger', onclick: () => action('crew.clearConditions', only) }, T('crew.removeAll'))),
    h('div', { class: 'tags' }, c.conditions.length ? c.conditions.map(cond =>
      h('span', { class: 'tag', title: cond.desc }, `${cond.label} (${cond.level.value})`,
        h('button', { title: T('crew.remove'), onclick: () => patch([{ op: 'remove', path: cond.path }], { refresh: true }) }, '×')))
      : h('span', { class: 'hint' }, T('crew.noConditions')))));

  if (c.jobs.length) {
    const bulkPriority = h('select');
    bulkPriority.append(h('option', { value: '' }, T('crew.setAllJobs')));
    for (const o of d.priorityOptions) bulkPriority.append(h('option', { value: o.value }, o.label));
    bulkPriority.addEventListener('change', () => {
      if (bulkPriority.value) action('crew.setAllJobs', { ...only, priority: bulkPriority.value });
    });
    box.append(h('section', { class: 'card' },
      h('h2', {}, T('crew.jobs')),
      h('div', { class: 'row', style: 'margin-bottom:10px' }, bulkPriority),
      fieldGrid(c.jobs)));
  }

  return box;
}

/* --------------------------------------------------------- armazenamento */

RENDER.storage = (d) => {
  if (!d.ships.length) return h('div', { class: 'empty' }, T('storage.empty'));
  if (!d.ships.some(s => s.sid === state.sel.storage)) state.sel.storage = d.ships[0].sid;
  const ship = d.ships.find(s => s.sid === state.sel.storage);

  const picker = h('select', {
    onchange: (e) => { state.sel.storage = e.target.value; render(); },
  }, d.ships.map(s => h('option', { value: s.sid, selected: s.sid === state.sel.storage },
    s.inSector ? s.ship : `${s.ship} (${T('crew.outOfSector')})`)));

  const fillInput = h('input', { type: 'number', value: '50', min: '0', style: 'width:90px' });
  const header = h('section', { class: 'card' },
    h('h2', {}, T('storage.title')),
    h('p', { class: 'hint' }, T('storage.hint')),
    h('div', { class: 'row' }, T('crew.ship'), picker, h('span', { class: 'spacer' }),
      T('storage.fillWith'), fillInput,
      h('button', {
        class: 'btn',
        onclick: () => action('storage.fillAll', { sid: ship.sid, amount: Number(fillInput.value) }),
      }, T('storage.apply'))));

  const summary = h('section', { class: 'card' },
    h('h2', {}, T('storage.totals')),
    h('table', {},
      h('thead', {}, h('tr', {}, h('th', {}, T('storage.resource')), h('th', { class: 'num' }, T('storage.racks')),
        h('th', { class: 'num' }, T('storage.buffers')), h('th', { class: 'num' }, T('storage.total')),
        h('th', { class: 'num' }, T('storage.stacksHeader')),
        h('th', {}, T('storage.setEach')))),
      h('tbody', {}, ship.summary.map(r => {
        // Pre-preenchido com a media por pilha de armazem (o que a ação
        // altera): aplicar sem mexer no numero mantem o total quase igual.
        const perStack = r.rackStacks ? Math.round(r.rack / r.rackStacks) : 0;
        const value = h('input', {
          type: 'number', min: '0', value: perStack, style: 'width:90px',
          disabled: !r.rackStacks,
        });
        return h('tr', {},
          h('td', {}, r.name, ' ', h('span', { class: 'pill' }, r.id)),
          h('td', { class: 'num' }, r.rack),
          h('td', { class: 'num' }, r.machine),
          h('td', { class: 'num' }, r.total),
          h('td', { class: 'num' }, `${r.rackStacks}/${r.stacks}`),
          h('td', {}, h('div', { class: 'row' }, value, h('button', {
            class: 'btn small',
            disabled: !r.rackStacks,
            onclick: () => action('storage.setStacks', {
              sid: ship.sid, elementaryId: r.id, amount: Number(value.value),
            }),
          }, T('storage.ok')))));
      }))));

  const showMachines = state.filter.storageMachines === true;
  const stacks = ship.stacks.filter(s => showMachines || s.kind === 'rack');
  const detail = h('section', { class: 'card' },
    h('h2', {}, T('storage.stacks')),
    h('label', { class: 'check', style: 'margin-bottom:10px' },
      h('input', {
        type: 'checkbox', checked: showMachines,
        onchange: (e) => { state.filter.storageMachines = e.target.checked; render(); },
      }), T('storage.showBuffers')),
    h('table', {},
      h('thead', {}, h('tr', {}, h('th', {}, T('storage.resource')), h('th', {}, T('storage.where')),
        h('th', {}, T('storage.kind')), h('th', { class: 'num' }, T('storage.amount')), h('th', {}, ''))),
      h('tbody', {}, stacks.map(s => h('tr', {},
        h('td', {}, s.name),
        h('td', { class: 'mono' }, s.where),
        h('td', {}, h('span', { class: 'pill' + (s.kind === 'rack' ? ' accent' : '') },
          s.kind === 'rack' ? T('storage.rack') : s.holder)),
        h('td', { class: 'num' }, bareInput(s.amountField)),
        h('td', {}, h('button', {
          class: 'btn small danger',
          onclick: () => patch([{ op: 'remove', path: s.path }], { refresh: true }),
        }, T('crew.remove'))))))));

  return h('div', {}, header, summary, detail,
    addStackCard(ship, d), oneOfEachCard(ship, d));
};

/** Um <option> por armazém da nave, sem repetir o mesmo inventário. */
function rackOptions(ship) {
  const racks = [...new Map(ship.stacks.filter(s => s.kind === 'rack')
    .map(s => [s.invPath, s])).values()];
  return racks.map(s => h('option', { value: s.invPath }, `${s.where} — ${s.name}`));
}

function addStackCard(ship, d) {
  const racks = rackOptions(ship);
  if (!racks.length) return null;

  const where = h('select', {}, racks);
  const what = h('select', {}, d.catalog.map(c => h('option', { value: c.id }, c.label)));
  const amount = h('input', { type: 'number', value: '20', min: '1', style: 'width:90px' });

  return h('section', { class: 'card' },
    h('h2', {}, T('storage.addTitle')),
    h('p', { class: 'hint' }, T('storage.addHint')),
    h('div', { class: 'row' },
      what, T('storage.in'), where, T('storage.quantity'), amount,
      h('button', {
        class: 'btn primary',
        onclick: () => action('storage.addStack', {
          invPath: where.value, elementaryId: what.value, amount: Number(amount.value),
        }),
      }, T('storage.add'))));
}

/** Cria uma pilha de cada recurso conhecido num armazém, todas com a mesma
    quantidade. Fica por último porque é a ação mais destrutiva da aba. */
function oneOfEachCard(ship, d) {
  const racks = rackOptions(ship);
  if (!racks.length) return null;

  const counts = d.catalog.reduce((acc, c) => {
    acc[c.table] = (acc[c.table] || 0) + 1;
    return acc;
  }, {});
  const total = d.catalog.length;

  const where = h('select', {}, racks);
  const scope = h('select', {},
    h('option', { value: 'all' }, T('storage.eachScopeAll', { n: total })),
    h('option', { value: 'products' }, T('storage.eachScopeProducts', { n: counts.products || 0 })),
    h('option', { value: 'items' }, T('storage.eachScopeItems', { n: counts.items || 0 })));
  const amount = h('input', { type: 'number', value: '50', min: '0', style: 'width:90px' });

  return h('section', { class: 'card' },
    h('h2', {}, T('storage.eachTitle')),
    h('p', { class: 'hint' }, T('storage.eachHint')),
    h('div', { class: 'row' },
      scope, T('storage.in'), where, T('storage.quantity'), amount,
      h('button', {
        class: 'btn primary',
        onclick: async () => {
          const res = await action('storage.addOneOfEach', {
            invPath: where.value, amount: Number(amount.value), scope: scope.value,
          }, { refresh: false });
          if (res) {
            toast(T('storage.eachResult', { added: res.added, updated: res.updated }), 'ok');
            await loadTab(state.tab, { keepScroll: true });
          }
        },
      }, T('storage.eachButton'))));
}

/* -------------------------------------------------------------- pesquisa */

RENDER.research = (d) => {
  if (!d.techs.length) return h('div', { class: 'empty' }, T('research.empty'));

  const query = (state.filter.research || '').toLowerCase();
  const visible = d.techs.filter(t => !query || t.label.toLowerCase().includes(query));
  const doneCount = d.techs.filter(t => t.complete).length;

  const search = h('input', {
    placeholder: T('research.filter'), value: state.filter.research || '', style: 'flex:1;max-width:320px',
    oninput: (e) => { state.filter.research = e.target.value; renderInPlace(); },
  });

  const head = h('section', { class: 'card' },
    h('h2', {}, T('research.title') + ' ',
      h('span', { class: 'pill ok' }, T('research.done', { done: doneCount, total: d.techs.length }))),
    h('div', { class: 'row' }, search, h('span', { class: 'spacer' }),
      h('button', {
        class: 'btn primary',
        onclick: () => confirmThen(T('research.confirmAll'),
          () => action('research.complete', {})),
      }, T('research.completeAll')),
      h('button', {
        class: 'btn danger',
        onclick: () => confirmThen(T('research.confirmReset'),
          () => action('research.reset', {})),
      }, T('research.resetAll'))));

  const table = h('section', { class: 'card' },
    h('table', {},
      h('thead', {}, h('tr', {}, h('th', {}, T('research.tech')), h('th', {}, T('research.state')),
        h('th', {}, T('research.stages')), h('th', {}, ''))),
      h('tbody', {}, visible.map(t => h('tr', { title: t.desc },
        h('td', {}, t.label),
        h('td', {}, t.complete
          ? h('span', { class: 'pill ok' }, T('research.complete'))
          : t.inSave ? h('span', { class: 'pill accent' }, T('research.inProgress'))
            : h('span', { class: 'pill' }, T('research.notStarted'))),
        h('td', { class: 'mono' }, t.stages.length
          ? t.stages.map(s => s.done ? '■' : '□').join(' ')
          : (t.cost || []).map(() => '□').join(' ')),
        h('td', {}, h('div', { class: 'row end' },
          !t.complete ? h('button', {
            class: 'btn small',
            onclick: () => action('research.complete', { techIds: [t.id] }),
          }, T('research.completeOne')) : null,
          t.inSave ? h('button', {
            class: 'btn small danger',
            onclick: () => action('research.reset', { techIds: [t.id] }),
          }, T('research.resetOne')) : null)))))));

  return h('div', {}, head, table);
};

/* ----------------------------------------------------------------- naves */

RENDER.ships = (d) => h('div', {},
  d.ships.map(s => h('section', { class: 'card' },
    h('h2', {}, s.name || `nave ${s.sid}`,
      ' ', s.isStation ? h('span', { class: 'pill accent' }, T('ships.station')) : null,
      ' ', s.inSector ? null : h('span', { class: 'pill' }, T('crew.outOfSector')),
      ' ', h('span', { class: 'pill' }, T('ships.crewCount', { n: s.crew })),
      ' ', h('span', { class: 'pill' }, T('ships.sizeTiles', { size: s.size, tiles: s.tiles }))),
    fieldGrid(s.fields, () => loadTab('ships', { keepScroll: true })))));

/* -------------------------------------------------------------- facções */

RENDER.factions = (d) => {
  if (!d.rows.length) return h('div', { class: 'empty' }, T('factions.empty'));
  const query = (state.filter.factions || '').toLowerCase();
  const rows = d.rows.filter(r => !query ||
    `${r.s1} ${r.s2}`.toLowerCase().includes(query));

  return h('div', {},
    h('section', { class: 'card' },
      h('h2', {}, T('factions.title')),
      h('p', { class: 'hint' }, T('factions.hint')),
      h('input', {
        placeholder: T('factions.filter'), value: state.filter.factions || '', style: 'max-width:320px',
        oninput: (e) => { state.filter.factions = e.target.value; renderInPlace(); },
      })),
    rows.map(r => h('section', { class: 'card' },
      h('h2', {}, `${r.s1} → ${r.s2}`),
      fieldGrid(r.fields))));
};

/* ------------------------------------------------------------------ XML */

RENDER.raw = (d) => {
  const crumbs = h('div', { class: 'crumbs' },
    d.breadcrumb.map((b, i) => [i ? h('span', {}, '/') : null,
      h('button', { onclick: () => openRaw(b.path) }, `<${b.tag}>`)]));

  const docPicker = h('select', {
    onchange: (e) => openRaw(e.target.value),
  }, d.documents.map(doc => h('option', {
    value: doc.path, selected: doc.key === d.doc,
  }, doc.label)));

  const searchBox = h('input', {
    placeholder: T('raw.searchPlaceholder'), style: 'flex:1',
    onkeydown: (e) => { if (e.key === 'Enter') runSearch(e.target.value); },
  });

  const body = h('div', {},
    h('section', { class: 'card' },
      h('h2', {}, T('raw.title')),
      h('p', { class: 'hint' }, T('raw.hint')),
      h('div', { class: 'row' }, searchBox,
        h('button', { class: 'btn', onclick: () => runSearch(searchBox.value) }, T('raw.search'))),
      h('div', { class: 'row', style: 'margin:10px 0' }, T('raw.file'), docPicker),
      crumbs),
    d.attrs.length ? h('section', { class: 'card' },
      h('h2', {}, T('raw.attrsOf', { tag: d.tag })),
      fieldGrid(d.attrs)) : null,
    h('section', { class: 'card' },
      h('h2', {}, T('raw.children', { n: d.total })),
      d.children.length ? h('table', {},
        h('thead', {}, h('tr', {}, h('th', {}, T('raw.tag')), h('th', {}, T('raw.summary')),
          h('th', { class: 'num' }, T('raw.childCount')), h('th', {}, T('raw.attrs')), h('th', {}, ''))),
        h('tbody', {}, d.children.map(c => h('tr', {},
          h('td', { class: 'mono' }, `<${c.tag}>`),
          h('td', {}, c.summary),
          h('td', { class: 'num' }, c.childCount || ''),
          h('td', { class: 'mono', style: 'max-width:420px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap' },
            Object.entries(c.attrs).map(([k, v]) => `${k}="${v}"`).join(' ')),
          h('td', {}, h('div', { class: 'row end' },
            h('button', { class: 'btn small', onclick: () => openRaw(c.path) }, T('raw.open')),
            h('button', {
              class: 'btn small danger',
              onclick: () => confirmThen(T('raw.confirmRemove', { tag: c.tag }),
                () => patch([{ op: 'remove', path: c.path }], { refresh: true })),
            }, T('raw.remove')))))))
      ) : h('p', { class: 'hint' }, T('raw.noChildren'))));

  return body;
};

function openRaw(path) {
  state.sel.raw = path;
  loadTab('raw');
}

async function runSearch(query) {
  if (!query.trim()) return;
  try {
    const res = await api(withLang('/api/search?q=' + encodeURIComponent(query)));
    showSearch(res);
  } catch (err) { toast(err.message, 'bad'); }
}

function showSearch(res) {
  const dialog = h('dialog', {},
    h('div', { class: 'head' }, T('raw.results',
      { query: res.query, n: res.hits.length + (res.truncated ? '+' : '') })),
    h('div', { class: 'body' },
      res.hits.length ? h('table', {},
        h('tbody', {}, res.hits.map(hit => h('tr', {},
          h('td', { class: 'mono' }, `<${hit.tag}>`),
          h('td', {}, hit.doc !== 'game' ? h('span', { class: 'pill' }, hit.doc) : null),
          h('td', {}, hit.summary),
          h('td', { class: 'mono' }, hit.match),
          h('td', {}, h('button', {
            class: 'btn small',
            onclick: () => { dialog.close(); dialog.remove(); openRaw(hit.path); },
          }, T('raw.open'))))))) : h('p', { class: 'hint' }, T('raw.nothingFound'))),
    h('div', { class: 'foot' },
      h('button', { class: 'btn', onclick: () => { dialog.close(); dialog.remove(); } }, T('dialog.close'))));
  document.body.append(dialog);
  dialog.showModal();
}

function confirmThen(message, fn) {
  if (window.confirm(message)) fn();
}

/* ------------------------------------------------------------ orquestração */

function renderInPlace() {
  const main = $('main');
  const top = main.scrollTop;
  render();
  main.scrollTop = top;
}

/** Preenche a barra fixa da aba. Cada render() começa esvaziando-a, então só
    as abas que chamam isto exibem a barra. */
function setToolbar(node) {
  const bar = $('#toolbar');
  bar.textContent = '';
  if (node) bar.append(node);
  bar.hidden = !node;
  measureChrome();
}

/** Altura do que fica fora da área que rola. A lista fixa usa esta medida
    para não passar do fim da tela, já que a barra da aba muda de altura. */
function measureChrome() {
  const bar = $('#toolbar');
  const px = $('header').offsetHeight + $('nav').offsetHeight
    + (bar.hidden ? 0 : bar.offsetHeight);
  document.documentElement.style.setProperty('--chrome', px + 'px');
}

window.addEventListener('resize', measureChrome);

function render() {
  const view = $('#view');
  view.textContent = '';
  setToolbar(null);
  if (!state.status?.loaded) {
    view.append(h('div', { class: 'empty' },
      state.status?.error || T('app.emptyState'),
      h('div', { style: 'margin-top:14px' },
        h('button', { class: 'btn primary', onclick: openFileDialog }, T('app.openButton')))));
    return;
  }
  if (!state.data) { view.append(h('div', { class: 'empty' }, T('app.loading'))); return; }
  const renderer = RENDER[state.tab];
  view.append(renderer ? renderer(state.data) : h('div', { class: 'empty' }, T('app.tabUnavailable')));
}

async function loadTab(tab, opts = {}) {
  state.tab = tab;
  for (const btn of $('#tabs').children) btn.classList.toggle('active', btn.dataset.id === tab);
  syncHash();
  const main = $('main');
  const top = opts.keepScroll ? main.scrollTop : 0;
  try {
    let url = '/api/tab?id=' + encodeURIComponent(tab);
    if (tab === 'raw') url += '&path=' + encodeURIComponent(state.sel.raw || '');
    state.data = await api(withLang(url));
    render();
    main.scrollTop = top;
  } catch (err) {
    state.data = null;
    toast(err.message, 'bad');
    render();
  }
}

/* A aba (e o no aberto no navegador de XML) ficam na URL, para poder
   recarregar a pagina ou compartilhar um link direto. */

let ignoreHashChange = false;

function syncHash() {
  // O path de um no contem '#' (documento#indices), por isso vai codificado.
  const want = state.tab === 'raw' && state.sel.raw
    ? `#raw/${encodeURIComponent(state.sel.raw)}` : `#${state.tab || 'game'}`;
  if (location.hash === want) return;
  ignoreHashChange = true;
  location.hash = want;
  setTimeout(() => { ignoreHashChange = false; }, 0);
}

function readHash() {
  const raw = location.hash.replace(/^#/, '');
  if (!raw) return null;
  const slash = raw.indexOf('/');
  if (slash === -1) return { tab: raw, path: null };
  return { tab: raw.slice(0, slash), path: decodeURIComponent(raw.slice(slash + 1)) };
}

window.addEventListener('hashchange', () => {
  if (ignoreHashChange) return;
  const target = readHash();
  if (!target || !state.status?.loaded) return;
  if (target.tab === 'raw') state.sel.raw = target.path || '';
  loadTab(target.tab);
});

async function refreshStatus() {
  state.status = await api(withLang('/api/state'));
  $('#filePath').textContent = state.status.path || T('app.noSave');
  $('#filePath').title = state.status.path || '';
  markDirty(state.status.dirty);

  // Sem save carregado não há o que recarregar nem gravar.
  $('#btnReload').disabled = $('#btnSave').disabled = !state.status.loaded;

  // Os rótulos das abas vêm traduzidos do backend, então são refeitos a cada
  // troca de idioma.
  const tabs = $('#tabs');
  tabs.textContent = '';
  for (const tab of state.status.tabs) {
    tabs.append(h('button', {
      'data-id': tab.id,
      class: tab.id === state.tab ? 'active' : null,
      onclick: () => loadTab(tab.id),
    }, tab.label));
  }
  if (!state.status.gamedata) toast(T('toast.noGamedata'), 'bad');
}

function buildLanguagePicker() {
  const picker = $('#langPicker');
  picker.textContent = '';
  for (const l of (state.languages || [])) {
    picker.append(h('option', { value: l.code, selected: l.code === state.lang }, l.label));
  }
  picker.onchange = async (e) => {
    await loadLanguage(e.target.value);
    buildLanguagePicker();
    await refreshStatus();
    if (state.status.loaded) await loadTab(state.tab, { keepScroll: true });
    else render();
  };
}

/* ------------------------------------------------------ seletor de arquivo */

async function openFileDialog(startPath) {
  const dialog = $('#fileDialog');
  await browseTo(startPath);
  if (!dialog.open) dialog.showModal();
}

async function browseTo(path) {
  let res;
  try {
    res = await api('/api/browse' + (path ? '?path=' + encodeURIComponent(path) : ''));
  } catch (err) { return toast(err.message, 'bad'); }

  $('#fileInput').value = res.path;
  const crumb = $('#fileCrumb');
  crumb.textContent = '';
  crumb.append(h('button', { onclick: () => browseTo(res.parent) }, T('dialog.up')),
    h('span', {}, res.path));
  // No Windows não existe uma raiz única: cada unidade é um ponto de partida.
  if (res.drives && res.drives.length > 1) {
    crumb.append(h('span', {}, T('dialog.drives')),
      ...res.drives.map(d => h('button', { onclick: () => browseTo(d) }, d)));
  }

  const list = $('#fileList');
  list.textContent = '';
  if (!res.entries.length) list.append(h('div', { class: 'hint', style: 'padding:12px' }, T('dialog.emptyFolder')));
  for (const e of res.entries) {
    // Pastas de partida contêm o save atual e os autosaves: dá para abrir
    // direto e também entrar para escolher outro.
    const row = h('div', { class: 'item', style: 'display:flex;align-items:center;gap:8px' },
      h('button', {
        class: 'btn small', style: 'flex:1;text-align:left;border:none;background:none',
        onclick: () => e.dir ? browseTo(e.path) : chooseSave(e.path),
      }, e.dir ? (e.save ? '💾 ' : '📁 ') : '📄 ', e.name),
      e.save || !e.dir ? h('button', {
        class: 'btn small primary', onclick: () => chooseSave(e.path),
      }, T('dialog.openEntry')) : null);
    list.append(row);
  }
}

async function chooseSave(path) {
  try {
    await post('/api/open', { path });
    $('#fileDialog').close();
    await refreshStatus();
    await loadTab(state.tab || 'game');
    toast(T('toast.loaded'), 'ok');
  } catch (err) { toast(err.message, 'bad'); }
}

/* ------------------------------------------------------------------ boot */

$('#btnOpen').addEventListener('click', () => openFileDialog(state.status?.path));
$('#fileCancel').addEventListener('click', () => $('#fileDialog').close());
$('#fileGo').addEventListener('click', () => browseTo($('#fileInput').value));
$('#fileInput').addEventListener('keydown', (e) => {
  if (e.key === 'Enter') browseTo(e.target.value);
});

$('#btnReload').addEventListener('click', async () => {
  if (state.status?.dirty && !window.confirm(T('confirm.discard'))) return;
  try {
    await post('/api/reload');
    await refreshStatus();
    await loadTab(state.tab);
    toast(T('toast.reloaded'), 'ok');
  } catch (err) { toast(err.message, 'bad'); }
});

$('#btnSave').addEventListener('click', async () => {
  try {
    const res = await post('/api/save', { backup: true });
    markDirty(false);
    const names = (res.files || []).map(f => f.path.split('/').pop());
    toast(T('toast.savedFiles', { files: names.join(', ') }), 'ok');
  } catch (err) { toast(err.message, 'bad'); }
});

window.addEventListener('beforeunload', (e) => {
  if (state.status?.dirty) { e.preventDefault(); e.returnValue = ''; }
});

(async function boot() {
  let saved = null;
  try { saved = localStorage.getItem('shedit.lang'); } catch { /* modo privado */ }
  await loadLanguage(saved || navigator.language || 'pt');
  buildLanguagePicker();
  await refreshStatus();
  const target = readHash();
  if (target && target.tab === 'raw') state.sel.raw = target.path || '';
  if (state.status.loaded) await loadTab(target?.tab || 'game');
  else { render(); openFileDialog(); }
})();
