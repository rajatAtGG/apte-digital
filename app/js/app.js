// App controller: loads the database, routes between views, wires up input.
//
// Routes (hash-based, so the app works from any sub-path such as GitHub Pages):
//   #/?q=…&m=sa|hi   search (Sanskrit headwords, or Hindi reverse search)
//   #/e/<id>          an entry (a sub-entry id opens its main entry at it)
//   #/browse[/<letter>], #/saved, #/settings, #/about

import sqlite3InitModule from '../vendor/sqlite3/index.mjs';
import { DB_URL, DB_GZ_BYTES, APP_VERSION } from './config.js';
import { Dictionary, openDatabase, runsText } from './dict.js';
import { SCHEME_NAMES, schemeLabel, toDevanagari } from './translit.js';
import { settings, bookmarks, recent } from './store.js';
import { esc, article, resultRow, highlight } from './render.js';

const $ = (sel, root = document) => root.querySelector(sel);
const views = ['search', 'entry', 'browse', 'saved', 'settings', 'about'];

let dict = null;
let opts = settings.get();
const state = { q: '', mode: 'sa', navCount: 0 };

// ------------------------------------------------------------ database load

async function fetchDatabase(onProgress) {
  const res = await fetch(DB_URL);
  if (!res.ok) throw new Error(`Could not download the dictionary (HTTP ${res.status}).`);
  const total = Number(res.headers.get('content-length')) || DB_GZ_BYTES;
  const reader = res.body.getReader();
  const chunks = [];
  let loaded = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    chunks.push(value);
    loaded += value.length;
    onProgress(Math.min(loaded / total, 1));
  }
  let bytes = new Uint8Array(await new Blob(chunks).arrayBuffer());
  // Decompress unless the server already did (gzip magic number 1f 8b).
  if (bytes[0] === 0x1f && bytes[1] === 0x8b) {
    if (typeof DecompressionStream === 'undefined') {
      throw new Error('This browser is too old to unpack the dictionary. Please update it.');
    }
    const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'));
    bytes = new Uint8Array(await new Response(stream).arrayBuffer());
  }
  return bytes;
}

async function boot() {
  applySettings();
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('sw.js').catch((e) => console.warn('service worker:', e));
  }
  navigator.storage?.persist?.().catch(() => {});
  const msg = $('#loading-msg');
  const bar = $('#bar-fill');
  try {
    const [sqlite3, bytes] = await Promise.all([
      sqlite3InitModule({ print: () => {}, printErr: () => {} }),
      fetchDatabase((f) => {
        bar.style.width = `${Math.round(f * 100)}%`;
        msg.textContent = `Downloading the dictionary… ${Math.round(f * 100)}%`;
      }),
    ]);
    msg.textContent = 'Opening…';
    dict = new Dictionary(openDatabase(sqlite3, bytes));
  } catch (e) {
    console.error(e);
    msg.textContent = `${e.message || e} Check your connection and reload.`;
    bar.parentElement.hidden = true;
    return;
  }
  $('#loading').hidden = true;
  wireInput();
  window.addEventListener('hashchange', () => { state.navCount++; route(); });
  route();
}

// ---------------------------------------------------------------- settings

function applySettings() {
  const root = document.documentElement;
  if (opts.theme === 'system') delete root.dataset.theme;
  else root.dataset.theme = opts.theme;
  root.style.setProperty('--scale', opts.fontScale);
  $('#scheme').textContent = opts.scheme === 'auto' ? 'Auto' : schemeLabel(opts.scheme).replace('Harvard-Kyoto', 'HK');
}

function updateSettings(patch) {
  opts = settings.set(patch);
  applySettings();
}

// ------------------------------------------------------------------ router

function show(name) {
  for (const v of views) $(`#view-${v}`).hidden = v !== name;
  const tab = name === 'entry' ? null : name === 'about' ? 'settings' : name;
  document.querySelectorAll('.tabbar a').forEach((a) => a.classList.toggle('on', a.dataset.tab === tab));
  $('#readings').hidden = name !== 'search';
}

function route() {
  const hash = location.hash.slice(1) || '/';
  const [path, query = ''] = hash.split('?');
  const parts = path.split('/').filter(Boolean).map(decodeURIComponent);
  if (parts[0] === 'e' && parts[1]) return showEntry(Number(parts[1]));
  if (parts[0] === 'browse') return parts[1] ? showLetter(parts[1]) : showBrowse();
  if (parts[0] === 'saved') return showSaved();
  if (parts[0] === 'settings') return showSettings();
  if (parts[0] === 'about') return showAbout();
  const params = new URLSearchParams(query);
  const q = params.get('q') ?? '';
  const mode = params.get('m') === 'hi' ? 'hi' : 'sa';
  if ($('#q').value !== q) $('#q').value = q;
  setMode(mode, false);
  state.q = q;
  show('search');
  renderSearch();
}

// ------------------------------------------------------------------ search

function wireInput() {
  const input = $('#q');
  let timer = 0;
  input.addEventListener('input', () => {
    clearTimeout(timer);
    timer = setTimeout(() => {
      state.q = input.value;
      // replaceState: typing should not create a history entry per keystroke.
      const hash = `#/?${new URLSearchParams({ q: state.q, m: state.mode })}`;
      if (location.hash !== hash) history.replaceState(null, '', hash);
      show('search');
      renderSearch();
    }, 90);
  });
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { recent.addSearch(input.value, state.mode); input.blur(); }
  });
  input.addEventListener('focus', () => { if (!$('#view-search').hidden) return; location.hash = `#/?${new URLSearchParams({ q: input.value, m: state.mode })}`; });
  $('#mode').addEventListener('click', () => {
    setMode(state.mode === 'sa' ? 'hi' : 'sa', true);
    history.replaceState(null, '', `#/?${new URLSearchParams({ q: state.q, m: state.mode })}`);
    show('search');
    renderSearch();
    input.focus();
  });
  $('#scheme').addEventListener('click', openSchemeDialog);
  // Remember the query when a result is opened.
  $('#view-search').addEventListener('click', (e) => {
    if (e.target.closest('.list a')) recent.addSearch(state.q, state.mode);
  });
}

function setMode(mode, user) {
  state.mode = mode;
  $('#mode').textContent = mode === 'sa' ? 'सं→हि' : 'हि→सं';
  $('#q').placeholder = mode === 'sa'
    ? 'संस्कृत शब्द · kamala, kṛṣṇa, धर्म'
    : 'हिन्दी अर्थ से खोजें · प्याला, पानी';
  if (user) $('#q').select?.();
}

function renderReadings(readings) {
  const el = $('#readings');
  const shown = readings.filter((r) => r.scheme !== 'deva');
  el.innerHTML = shown.map((r) =>
    `<b>${esc(r.text)}</b> <span class="sch">${esc(r.scheme === 'hk' ? 'HK' : schemeLabel(r.scheme))}</span>`).join('');
}

function renderSearch() {
  const view = $('#view-search');
  const q = state.q.trim();
  if (!q) {
    renderReadings([]);
    view.innerHTML = searchHome();
    return;
  }
  if (state.mode === 'hi') {
    const { words, reading, results, total } = dict.reverse(q, opts.scheme);
    renderReadings(reading ? [reading] : []);
    if (!results.length) {
      view.innerHTML = `<p class="empty">“${esc(q)}” किसी अर्थ में नहीं मिला।<br><small>No sense contains this word.</small></p>`;
      return;
    }
    const rows = results.map((r) => resultRow(r, opts,
      r.senses.slice(0, 3).map((s) => `<span class="snip"><span class="n">${esc(s.n ?? '')}</span>${highlight(s.text, words)}</span>`).join('')));
    view.innerHTML = `<p class="note">${total} अर्थों में मिला${total > results.length ? ` · showing ${results.length} entries` : ''}</p><ul class="list">${rows.join('')}</ul>`;
    return;
  }
  const { readings, results } = dict.search(q, opts.scheme);
  renderReadings(readings);
  if (!results.length) {
    view.innerHTML = `<p class="empty">कोई शब्द नहीं मिला।<br><small>No headword matches. Try another input method, or
      <a href="#/?${esc(new URLSearchParams({ q, m: 'hi' }))}">search Hindi meanings</a>.</small></p>`;
    return;
  }
  const fuzzy = results[0].score >= 4; // typo band only (see search.js)
  view.innerHTML = (fuzzy ? '<p class="note">निकटतम शब्द · closest matches</p>' : '')
    + `<ul class="list">${results.map((r) => resultRow(r, opts)).join('')}</ul>`;
}

function searchHome() {
  const searches = recent.searches();
  const seen = recent.entries();
  let h = '';
  if (searches.length) {
    h += '<h2 class="section">हाल की खोजें · Recent searches</h2><div class="chips">'
      + searches.slice(0, 12).map((r) => `<a class="chip" href="#/?${esc(new URLSearchParams({ q: r.q, m: r.mode }))}">${esc(r.q)}${r.mode === 'hi' ? ' <small class="muted">हि</small>' : ''}</a>`).join('')
      + '</div>';
  }
  if (seen.length) {
    h += '<h2 class="section">हाल में देखे · Recently viewed</h2><div class="chips">'
      + seen.slice(0, 12).map((r) => `<a class="chip" href="#/e/${r.id}">${esc(r.headword)}</a>`).join('') + '</div>';
  }
  h += `<h2 class="section">खोजने के तरीके · How to search</h2>
    <div class="prose small muted">
      <p>Type in Devanagari or in any romanisation. With <b>Auto</b> every scheme is tried:
      <code>kṛṣṇa</code> (IAST), <code>kRSNa</code> (Harvard-Kyoto), <code>kRiShNa</code> (ITRANS),
      <code>kfzRa</code> (SLP1), <code>kqRNa</code> (WX). Plain spellings like <code>krishna</code> also work.</p>
      <p>Tap <b>सं→हि</b> to switch to <b>हि→सं</b> and find Sanskrit words by their Hindi meaning.</p>
    </div>`;
  return h;
}

function openSchemeDialog() {
  const dlg = $('#scheme-dialog');
  const sample = 'कृष्ण';
  const examples = { iast: 'kṛṣṇa', hk: 'kRSNa', itrans: 'kRiShNa', slp1: 'kfzRa', wx: 'kqRNa' };
  $('#scheme-options').innerHTML = [['auto', 'Auto', 'tries every scheme; Devanagari always works']]
    .concat(SCHEME_NAMES.map((s) => [s, schemeLabel(s), `${examples[s]} → ${toDevanagari(examples[s], s) === sample ? sample : ''}`]))
    .map(([v, label, hint]) => `<label><input type="radio" name="scheme" value="${v}" ${opts.scheme === v ? 'checked' : ''}>
      <span>${esc(label)} <small>${esc(hint)}</small></span></label>`).join('');
  dlg.onchange = (e) => {
    updateSettings({ scheme: e.target.value });
    if (!$('#view-search').hidden) renderSearch();
  };
  dlg.showModal();
}

// ------------------------------------------------------------------- entry

function showEntry(id) {
  const e = dict.entry(id);
  const view = $('#view-entry');
  show('entry');
  if (!e) {
    view.innerHTML = '<p class="empty">Entry not found.</p>';
    return;
  }
  const gloss = runsText(e.senses?.[0]?.runs, ['citation']).slice(0, 110);
  const marked = bookmarks.has(e.id);
  const { prev, next } = dict.neighbours(e);
  view.innerHTML = `
    <div class="entry-bar">
      <button class="icon-btn" type="button" data-act="back" aria-label="Back">←</button>
      <span class="spacer"></span>
      <button class="icon-btn" type="button" data-act="star" aria-pressed="${marked}"
              aria-label="Bookmark">${marked ? '★' : '☆'}</button>
    </div>
    ${article(e, opts, id)}
    <nav class="pager">
      ${prev ? `<a class="btn" href="#/e/${prev.id}">← ${esc(prev.headword)}</a>` : '<span></span>'}
      ${next ? `<a class="btn" href="#/e/${next.id}">${esc(next.headword)} →</a>` : '<span></span>'}
    </nav>
    <p class="note small">${esc(e.src_file)} · lexhead ${esc(e.lexhead_no)}</p>`;
  view.onclick = (ev) => {
    const act = ev.target.closest('[data-act]')?.dataset.act;
    if (act === 'back') {
      if (state.navCount > 0) history.back();
      else location.hash = '#/';
    } else if (act === 'star') {
      const on = bookmarks.toggle({ id: e.id, headword: e.headword, grammar: e.grammar_text, gloss });
      ev.target.setAttribute('aria-pressed', on);
      ev.target.textContent = on ? '★' : '☆';
    } else if (act === 'expand') {
      const all = view.querySelectorAll('details.sub');
      const open = [...all].some((d) => !d.open);
      all.forEach((d) => { d.open = open; });
      ev.target.textContent = open ? 'सब बंद करें' : 'सब खोलें';
    }
  };
  recent.addEntry(e);
  if (id !== e.id) {
    const target = document.getElementById(`e${id}`);
    if (target) {
      target.classList.add('flash');
      requestAnimationFrame(() => target.scrollIntoView({ block: 'center' }));
    }
  } else {
    window.scrollTo(0, 0);
  }
}

// ------------------------------------------------------------------ browse

const LETTER_GROUPS = [
  ['स्वर', 'अ आ इ ई उ ऊ ऋ ॠ ऌ ए ऐ ओ औ'],
  ['कवर्ग', 'क ख ग घ ङ'], ['चवर्ग', 'च छ ज झ ञ'], ['टवर्ग', 'ट ठ ड ढ ण'],
  ['तवर्ग', 'त थ द ध न'], ['पवर्ग', 'प फ ब भ म'], ['अन्तःस्थ', 'य र ल व'], ['ऊष्म', 'श ष स ह'],
];

function showBrowse() {
  show('browse');
  const counts = dict.letterCounts();
  $('#view-browse').innerHTML = '<h2 class="section">वर्णमाला · Browse by letter</h2>'
    + LETTER_GROUPS.map(([label, letters]) => `<div class="group-label">${label}</div><div class="letters">${
      letters.split(' ').map((l) => {
        const n = counts.get(l) || 0;
        return `<a href="#/browse/${encodeURIComponent(l)}" class="${n ? '' : 'none'}">${l}<small>${n}</small></a>`;
      }).join('')}</div>`).join('');
}

function showLetter(letter) {
  show('browse');
  const view = $('#view-browse');
  const total = dict.letterCounts().get(letter) || 0;
  view.innerHTML = `<div class="entry-bar"><a class="icon-btn btn" href="#/browse" aria-label="All letters">←</a>
    <h2 class="section" style="margin:0">${esc(letter)} · ${total} शब्द</h2></div><ul class="list" id="letter-list"></ul>
    <button class="btn more" type="button" id="more">और · more</button>`;
  const list = $('#letter-list');
  const more = $('#more');
  let offset = 0;
  const page = () => {
    const rows = dict.browse(letter, offset, 200);
    offset += rows.length;
    list.insertAdjacentHTML('beforeend', rows.map((r) => resultRow(r, opts)).join(''));
    more.hidden = offset >= total;
  };
  more.onclick = page;
  page();
  // Load further pages automatically as the button scrolls into view.
  const io = new IntersectionObserver((es) => { if (es[0].isIntersecting && !more.hidden) page(); }, { rootMargin: '600px' });
  io.observe(more);
  window.scrollTo(0, 0);
}

// ------------------------------------------------------------------- saved

function showSaved() {
  show('saved');
  const marks = bookmarks.all();
  const seen = recent.entries();
  const view = $('#view-saved');
  view.innerHTML = '<h2 class="section">बुकमार्क · Bookmarks</h2>'
    + (marks.length
      ? `<ul class="list">${marks.map((b) => resultRow(b, opts)).join('')}</ul>`
      : '<p class="empty">No bookmarks yet. Tap ☆ on an entry to save it here.</p>')
    + (seen.length ? `<h2 class="section">हाल में देखे · Recently viewed</h2><div class="chips">${
      seen.map((r) => `<a class="chip" href="#/e/${r.id}">${esc(r.headword)}</a>`).join('')}</div>` : '')
    + `<p style="margin-top:24px">${marks.length ? '<button class="btn" data-act="clear-marks">Clear bookmarks</button> ' : ''}
       ${seen.length || recent.searches().length ? '<button class="btn" data-act="clear-recent">Clear history</button>' : ''}</p>`;
  view.onclick = (e) => {
    const act = e.target.dataset.act;
    if (act === 'clear-marks' && confirm('Remove all bookmarks?')) { bookmarks.clear(); showSaved(); }
    if (act === 'clear-recent' && confirm('Clear recent searches and viewed entries?')) { recent.clear(); showSaved(); }
  };
}

// ---------------------------------------------------------------- settings

async function showSettings() {
  show('settings');
  const view = $('#view-settings');
  const seg = (name, value, choices) => `<div class="seg-ctl" data-name="${name}">${choices.map(([v, l]) =>
    `<button type="button" data-value="${v}" aria-pressed="${String(value) === String(v)}">${l}</button>`).join('')}</div>`;
  view.innerHTML = `
    <h2 class="section">सेटिंग · Settings</h2>
    <div class="setting"><label class="t">Theme</label>
      ${seg('theme', opts.theme, [['system', 'System'], ['light', 'Light'], ['dark', 'Dark']])}</div>
    <div class="setting"><label class="t" for="font">Text size · <span id="font-val">${Math.round(opts.fontScale * 100)}%</span></label>
      <input id="font" type="range" min="0.85" max="1.6" step="0.05" value="${opts.fontScale}">
      <p class="small" style="margin:6px 0 0"><b>धर्मः</b> <span class="g">पुं०</span> कर्तव्य, नैतिक गुण</p></div>
    <div class="setting"><label class="t">Input method</label>
      ${seg('scheme', opts.scheme, [['auto', 'Auto'], ...SCHEME_NAMES.map((s) => [s, s === 'hk' ? 'HK' : schemeLabel(s)])])}</div>
    <div class="setting switch"><label for="rom">Show IAST under headwords</label>
      <input id="rom" type="checkbox" ${opts.showRoman ? 'checked' : ''}></div>
    <div class="setting switch"><label for="cats">Show semantic categories (जाति, उपाधि…)</label>
      <input id="cats" type="checkbox" ${opts.showCategories ? 'checked' : ''}></div>
    <div class="setting"><label class="t">Offline</label><span id="offline" class="small muted">Checking…</span></div>
    <p><a class="btn" href="#/about">About & credits</a></p>`;
  view.onclick = (e) => {
    const b = e.target.closest('.seg-ctl button');
    if (!b) return;
    updateSettings({ [b.parentElement.dataset.name]: b.dataset.value });
    b.parentElement.querySelectorAll('button').forEach((x) => x.setAttribute('aria-pressed', x === b));
  };
  $('#font').oninput = (e) => {
    updateSettings({ fontScale: Number(e.target.value) });
    $('#font-val').textContent = `${Math.round(opts.fontScale * 100)}%`;
  };
  $('#rom').onchange = (e) => updateSettings({ showRoman: e.target.checked });
  $('#cats').onchange = (e) => updateSettings({ showCategories: e.target.checked });
  let offline = 'Service workers are unavailable here, so the dictionary needs a connection.';
  if ('caches' in window && navigator.serviceWorker?.controller) {
    offline = (await caches.match(DB_URL))
      ? '✓ The whole dictionary is stored on this device and works without internet.'
      : 'Saving for offline use…';
  } else if ('serviceWorker' in navigator) {
    offline = 'Will be available offline after the next reload.';
  }
  const el = $('#offline');
  if (el) el.textContent = offline;
}

// ------------------------------------------------------------------- about

function showAbout() {
  show('about');
  const m = dict.meta;
  let counts = {};
  try { counts = JSON.parse(m.counts); } catch { /* old database */ }
  const commit = m.source_commit || '';
  $('#view-about').innerHTML = `<div class="prose">
    <h1>आप्टे संस्कृत-हिन्दी कोश</h1>
    <p>An offline edition of <b>Vaman Shivram Apte’s Sanskrit-Hindi Kosh</b>, the Hindi version of
    <i>The Practical Sanskrit-English Dictionary</i>.</p>
    <h2>Credits</h2>
    <ul>
      <li><b>V. S. Apte</b> (1858–1892), author of the dictionary.</li>
      <li>The digital text comes from the <b>Samsaadhanii</b> project, Department of Sanskrit Studies,
        <b>University of Hyderabad</b>:
        <a href="https://github.com/samsaadhanii/scl" rel="noopener">github.com/samsaadhanii/scl</a>
        (<code>MT/data/hi/Apte_dict</code>${commit ? `, commit <code>${esc(commit.slice(0, 10))}</code>` : ''}).</li>
      <li>Typeface: <b>Noto Serif Devanagari</b> by the Noto Project, SIL Open Font License 1.1.</li>
      <li>Database engine: <b>SQLite</b> (public domain), compiled to WebAssembly by the SQLite project.</li>
    </ul>
    <h2>Licence</h2>
    <p>The Samsaadhanii repository, and so the dictionary data, is distributed under the
    <b>GNU General Public License, version 2</b>. This app passes the data on under the same terms.
    The full text of the licence is at <a href="https://www.gnu.org/licenses/old-licenses/gpl-2.0.html" rel="noopener">gnu.org</a>.</p>
    <h2>About this edition</h2>
    <p>${(counts.lexhead || 27699).toLocaleString('en-IN')} main entries, ${(counts.dentry || 54463).toLocaleString('en-IN')} headwords
    including sub-entries and compounds, ${(counts.sense || 98634).toLocaleString('en-IN')} senses and
    ${(counts.citation || 27649).toLocaleString('en-IN')} citations. Abbreviations marked <code>*</code> in the
    source are shown as <code>०</code> (पुं०, नपुं०). Headwords are shown exactly as in the source. Errors in the
    text belong to the digital source; please report them to the Samsaadhanii project.</p>
    <p class="small muted">Built ${esc(m.built_at || '')} · app ${esc(APP_VERSION)}</p>
    <p><a class="btn" href="#/settings">← Settings</a></p>
  </div>`;
  window.scrollTo(0, 0);
}

boot();
