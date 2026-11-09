// Settings, bookmarks and recent searches, kept in localStorage.
// Every access is wrapped: in private mode or with storage blocked the app
// still works, it just forgets things between visits.

const KEY = 'apte.';

function read(name, fallback) {
  try {
    const v = localStorage.getItem(KEY + name);
    return v ? JSON.parse(v) : fallback;
  } catch {
    return fallback;
  }
}

function write(name, value) {
  try {
    localStorage.setItem(KEY + name, JSON.stringify(value));
  } catch { /* storage full or unavailable */ }
}

export const DEFAULT_SETTINGS = {
  theme: 'system',      // system | light | dark
  fontScale: 1,         // 0.85 … 1.6
  scheme: 'auto',       // auto | iast | hk | itrans | slp1 | wx
  showRoman: true,      // IAST reading aid under headwords
  showCategories: true, // जाति / उपाधि … lines in entries
};

export const settings = {
  get() { return { ...DEFAULT_SETTINGS, ...read('settings', {}) }; },
  set(patch) { const s = { ...this.get(), ...patch }; write('settings', s); return s; },
};

export const bookmarks = {
  all() { return read('bookmarks', []); },
  has(id) { return this.all().some((b) => b.id === id); },
  /** Add or remove; returns true if the entry is now bookmarked. */
  toggle(entry) {
    const list = this.all();
    const i = list.findIndex((b) => b.id === entry.id);
    if (i >= 0) list.splice(i, 1);
    else list.unshift({ id: entry.id, headword: entry.headword, grammar: entry.grammar, gloss: entry.gloss, t: Date.now() });
    write('bookmarks', list);
    return i < 0;
  },
  clear() { write('bookmarks', []); },
};

const MAX_RECENT = 25;
export const recent = {
  searches() { return read('recentSearches', []); },
  addSearch(q, mode) {
    q = q.trim();
    if (!q) return;
    const list = this.searches().filter((r) => !(r.q === q && r.mode === mode));
    list.unshift({ q, mode });
    write('recentSearches', list.slice(0, MAX_RECENT));
  },
  entries() { return read('recentEntries', []); },
  addEntry(e) {
    const list = this.entries().filter((r) => r.id !== e.id);
    list.unshift({ id: e.id, headword: e.headword });
    write('recentEntries', list.slice(0, MAX_RECENT));
  },
  clear() { write('recentSearches', []); write('recentEntries', []); },
};
