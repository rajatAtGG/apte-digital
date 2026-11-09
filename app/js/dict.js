// Dictionary queries over the SQLite database built by pipeline/build.py.
// It takes an open @sqlite.org/sqlite-wasm `oo1.DB`, so the same code runs
// in the browser and in the Node tests.

import { HeadwordIndex } from './search.js';
import { readings } from './translit.js';
import { normalizeWords } from './normalize.js';

const SENSE_STRIDE = 1000; // must match pipeline/build.py

/** Plain text of a run list (see pipeline/apte_parser.py), optionally
 *  leaving out some tags such as citations. */
export function runsText(runs, skip = []) {
  if (!runs) return '';
  let s = '';
  for (const r of runs) {
    if (typeof r === 'string') s += r;
    else if (!skip.includes(r[0])) s += ` ${runsText(r.slice(1), skip)} `;
  }
  return s.replace(/\s+/g, ' ').trim();
}

const glossOf = (json, max = 110) => {
  const t = runsText(json ? JSON.parse(json) : [], ['citation']);
  return t.length > max ? `${t.slice(0, max - 1).trimEnd()}…` : t;
};

export class Dictionary {
  constructor(db) {
    this.db = db;
    this.meta = Object.fromEntries(this.#rows('SELECT key, value FROM meta'));
    this.index = new HeadwordIndex(this.#rows('SELECT key, entry_id FROM search_keys'));
  }

  #rows(sql, bind) {
    return this.db.exec({ sql, bind, returnValue: 'resultRows' });
  }

  #objects(sql, bind) {
    return this.db.exec({ sql, bind, returnValue: 'resultRows', rowMode: 'object' });
  }

  /** Summary rows (for result lists) for the given entry ids, keyed by id. */
  summaries(ids) {
    const out = new Map();
    for (let i = 0; i < ids.length; i += 500) {
      const chunk = ids.slice(i, i + 500);
      const rows = this.#objects(
        `SELECT e.id, e.kind, e.headword, e.grammar, e.sort_key, e.main_id,
                m.headword AS main_headword,
                json_extract(e.body, '$.senses[0].runs') AS sense0
           FROM entries e JOIN entries m ON m.id = e.main_id
          WHERE e.id IN (${chunk.map(() => '?').join(',')})`, chunk);
      for (const r of rows) {
        r.gloss = glossOf(r.sense0);
        delete r.sense0;
        out.set(r.id, r);
      }
    }
    return out;
  }

  /**
   * Headword search. `query` may be Devanagari or any romanisation;
   * `scheme` is 'auto' or one of the scheme names in translit.js.
   * Returns { readings, results: [{ ...summary, score, reading }] }.
   */
  search(query, scheme = 'auto', limit = 60) {
    const rs = readings(query, scheme);
    const best = new Map();
    rs.forEach((r, ri) => {
      for (const [id, hit] of this.index.find(r.text)) {
        // Small penalty for less likely readings breaks ties between schemes.
        const score = hit.score + ri * 0.001;
        const prev = best.get(id);
        if (!prev || score < prev.score) best.set(id, { score, reading: r });
      }
    });
    // Prefer main entries over sub-entries at equal scores.
    const ranked = [...best.entries()].sort((a, b) => a[1].score - b[1].score).slice(0, limit * 3);
    const info = this.summaries(ranked.map(([id]) => id));
    const results = ranked
      .map(([id, hit]) => ({ ...info.get(id), ...hit }))
      .sort((a, b) => Math.floor(a.score) - Math.floor(b.score)
        || (a.kind !== 'main') - (b.kind !== 'main')
        || a.score - b.score
        || (a.sort_key < b.sort_key ? -1 : 1))
      .slice(0, limit);
    return { readings: rs, results };
  }

  /**
   * Reverse search: entries whose (Hindi) senses contain all the words of
   * `query`. Whole-word matches come first, then words that merely start
   * with the query words. Returns [{ ...summary, senses: [index] }].
   */
  reverse(query, scheme = 'auto', limit = 150) {
    const r = readings(query, scheme)[0];
    const words = r ? normalizeWords(r.text) : [];
    if (!words.length) return { words, reading: r, results: [], total: 0 };
    const quoted = words.map((w) => `"${w.replaceAll('"', '')}"`);
    const hits = new Map(); // entryId -> sense indices, in rank order
    let total = 0;
    for (const match of [quoted.join(' '), quoted.map((w) => `${w}*`).join(' ')]) {
      total = Math.max(total, this.#rows(
        'SELECT count(*) FROM senses_fts WHERE senses_fts MATCH ?', [match])[0][0]);
      const rows = this.#rows(
        'SELECT rowid FROM senses_fts WHERE senses_fts MATCH ? ORDER BY rank LIMIT 1000', [match]);
      for (const [rowid] of rows) {
        const id = Math.floor(rowid / SENSE_STRIDE);
        if (!hits.has(id)) {
          if (hits.size >= limit) continue;
          hits.set(id, []);
        }
        const list = hits.get(id);
        const sense = rowid % SENSE_STRIDE;
        if (!list.includes(sense)) list.push(sense);
      }
    }
    const info = this.summaries([...hits.keys()]);
    const bodies = new Map(this.#rows(
      `SELECT id, json_extract(body, '$.senses') FROM entries WHERE id IN (${[...hits.keys()].map(() => '?').join(',') || 'NULL'})`,
      [...hits.keys()]));
    const results = [...hits].map(([id, senses]) => {
      const all = JSON.parse(bodies.get(id) || '[]');
      return {
        ...info.get(id),
        senses: senses.map((i) => ({ n: all[i]?.n, text: runsText(all[i]?.runs, ['citation']) })),
      };
    });
    return { words, reading: r, results, total };
  }

  /** A main entry with all its sub-entries, as a tree. `id` may be the id
   *  of a sub-entry; the whole main entry is returned either way. */
  entry(id) {
    const rows = this.#objects(
      `SELECT * FROM entries WHERE main_id = (SELECT main_id FROM entries WHERE id = ?) ORDER BY id`, [id]);
    if (!rows.length) return null;
    const byId = new Map();
    for (const r of rows) {
      // The plain-text grammar column becomes grammar_text; `grammar` is the
      // structured run list from the body.
      r.grammar_text = r.grammar;
      delete r.grammar;
      Object.assign(r, JSON.parse(r.body));
      delete r.body;
      r.children = [];
      byId.set(r.id, r);
      if (r.parent_id) byId.get(r.parent_id).children.push(r);
    }
    return rows[0];
  }

  /** Main entries just before and after `entry` in dictionary order. */
  neighbours(entry) {
    const q = (op, dir) => this.#objects(
      `SELECT id, headword FROM entries WHERE kind = 'main' AND (sort_key, id) ${op} (?, ?)
        ORDER BY sort_key ${dir}, id ${dir} LIMIT 1`, [entry.sort_key, entry.id])[0] || null;
    return { prev: q('<', 'DESC'), next: q('>', 'ASC') };
  }

  /** Number of main entries per initial letter. */
  letterCounts() {
    return new Map(this.#rows(
      "SELECT letter, count(*) FROM entries WHERE kind = 'main' GROUP BY letter"));
  }

  /** A page of main entries for one letter, in varnamala order. */
  browse(letter, offset = 0, limit = 200) {
    return this.#objects(
      `SELECT id, headword, grammar, json_extract(body, '$.senses[0].runs') AS sense0
         FROM entries WHERE kind = 'main' AND letter = ?
        ORDER BY sort_key, id LIMIT ? OFFSET ?`, [letter, limit, offset])
      .map((r) => ({ id: r.id, headword: r.headword, grammar: r.grammar, gloss: glossOf(r.sense0) }));
  }
}

/** Open a database image (Uint8Array) read-only in memory. */
export function openDatabase(sqlite3, bytes) {
  const p = sqlite3.wasm.allocFromTypedArray(bytes);
  const db = new sqlite3.oo1.DB();
  const { capi } = sqlite3;
  const rc = capi.sqlite3_deserialize(db.pointer, 'main', p, bytes.byteLength, bytes.byteLength,
    capi.SQLITE_DESERIALIZE_FREEONCLOSE | capi.SQLITE_DESERIALIZE_READONLY);
  db.checkRc(rc);
  return db;
}
