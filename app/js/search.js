// In-memory headword index: exact, prefix, loose and typo-tolerant lookup.
//
// The ~64k (key, entry) pairs from the search_keys table are loaded once.
// Lookups then run in plain JS, which keeps typo tolerance simple (SQLite has
// no fuzzy matching) and fast enough to run on every keystroke.

import { normalize, loose } from './normalize.js';

// Score bands: lower is better. Within a band, shorter keys rank first.
const EXACT = 0;
const PREFIX = 1;
const LOOSE_EXACT = 2;
const LOOSE_PREFIX = 3;
const FUZZY = 4;

const MAX_PREFIX_KEYS = 400; // cap per band, so one-letter queries stay fast

/** Index of the first element of sorted `arr` that is >= `x`. */
function lowerBound(arr, x) {
  let lo = 0;
  let hi = arr.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (arr[mid] < x) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

/**
 * Edit distance between `a` and `b` (insertions, deletions, substitutions
 * and adjacent transpositions), giving up once it must exceed `max`.
 * With `prefix` set, `a` is compared to the best-matching *prefix* of `b`,
 * which lets a half-typed word with a typo still find its headword.
 */
export function editDistance(a, b, max, prefix = false) {
  const n = a.length;
  const m = b.length;
  if (!prefix && Math.abs(n - m) > max) return max + 1;
  let prev2 = null;
  let prev = Array.from({ length: m + 1 }, (_, j) => j);
  for (let i = 1; i <= n; i++) {
    const cur = [i];
    let rowMin = i;
    for (let j = 1; j <= m; j++) {
      const cost = a[i - 1] === b[j - 1] ? 0 : 1;
      let v = Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost);
      if (prev2 && i > 1 && j > 1 && a[i - 1] === b[j - 2] && a[i - 2] === b[j - 1]) {
        v = Math.min(v, prev2[j - 2] + 1);
      }
      cur.push(v);
      if (v < rowMin) rowMin = v;
    }
    if (rowMin > max) return max + 1;
    prev2 = prev;
    prev = cur;
  }
  return prefix ? Math.min(...prev) : prev[m];
}

export class HeadwordIndex {
  /** @param rows [key, entryId] pairs, in any order. */
  constructor(rows) {
    const byKey = new Map();
    for (const [key, id] of rows) {
      if (!byKey.has(key)) byKey.set(key, []);
      byKey.get(key).push(id);
    }
    this.keys = [...byKey.keys()].sort();
    this.ids = this.keys.map((k) => byKey.get(k));
    // Loose keys -> indices into this.keys.
    const byLoose = new Map();
    this.keys.forEach((k, i) => {
      const l = loose(k);
      if (!byLoose.has(l)) byLoose.set(l, []);
      byLoose.get(l).push(i);
    });
    this.looseKeys = [...byLoose.keys()].sort();
    this.looseIdx = this.looseKeys.map((l) => byLoose.get(l));
  }

  /**
   * Find entries for one Devanagari query.
   * @returns Map entryId -> { score, key }
   */
  find(devanagari, { fuzzy = true } = {}) {
    const found = new Map();
    const add = (keyIndex, score) => {
      const key = this.keys[keyIndex];
      for (const id of this.ids[keyIndex]) {
        const prev = found.get(id);
        if (!prev || score < prev.score) found.set(id, { score, key });
      }
    };
    const n = normalize(devanagari);
    if (!n) return found;
    // While typing a conjunct the query briefly ends in a virama (क् on the
    // way to क्ष); for prefix matching, the bare consonant is what is meant.
    const stem = n.endsWith('्') ? n.slice(0, -1) : n;

    for (const q of new Set([n, stem])) {
      const i = lowerBound(this.keys, q);
      if (this.keys[i] === q) add(i, EXACT);
    }
    this.#prefixScan(this.keys, stem, (i, extra) => add(i, PREFIX + extra));

    const l = loose(stem);
    const looseHit = (li, score) => this.looseIdx[li].forEach((i) => add(i, score));
    const li = lowerBound(this.looseKeys, l);
    if (this.looseKeys[li] === l) looseHit(li, LOOSE_EXACT);
    if (l.length >= 2) this.#prefixScan(this.looseKeys, l, (j, extra) => looseHit(j, LOOSE_PREFIX + extra));

    // Typo tolerance: only when the cheaper bands found little.
    if (fuzzy && found.size < 10 && l.length >= 3) {
      const max = l.length <= 4 ? 1 : 2;
      for (let j = 0; j < this.looseKeys.length; j++) {
        const k = this.looseKeys[j];
        if (k.length < l.length - max) continue;
        const whole = editDistance(l, k, max);
        if (whole <= max) { looseHit(j, FUZZY + whole + k.length / 1000); continue; }
        const part = editDistance(l, k, max, true);
        if (part <= max) looseHit(j, FUZZY + 0.5 + part + k.length / 1000);
      }
    }
    return found;
  }

  // Call fn(index, tieBreak) for keys starting with `prefix` (excluding an
  // exact match), shortest first, up to MAX_PREFIX_KEYS of them.
  #prefixScan(arr, prefix, fn) {
    const start = lowerBound(arr, prefix);
    const hits = [];
    for (let i = start; i < arr.length && arr[i].startsWith(prefix); i++) {
      if (arr[i] !== prefix) hits.push(i);
      if (hits.length > MAX_PREFIX_KEYS * 4) break;
    }
    hits.sort((a, b) => arr[a].length - arr[b].length);
    for (const i of hits.slice(0, MAX_PREFIX_KEYS)) fn(i, Math.min((arr[i].length - prefix.length) / 100, 0.9));
  }
}
