// Romanisation <-> Devanagari for IAST, Harvard-Kyoto, ITRANS, SLP1 and WX.
//
// Each scheme is a small table of vowels, consonants and marks. Conversion is
// a greedy longest-match scan: a consonant followed by another consonant gets
// a virama, a consonant followed by a vowel gets that vowel's sign (matra),
// and "a" after a consonant is the inherent vowel (nothing is written).

const V = '्'; // virama

// vowel: [independent letter, dependent sign]
const VOWELS = {
  a: ['अ', ''], aa: ['आ', 'ा'], i: ['इ', 'ि'], ii: ['ई', 'ी'], u: ['उ', 'ु'], uu: ['ऊ', 'ू'],
  r: ['ऋ', 'ृ'], rr: ['ॠ', 'ॄ'], l: ['ऌ', 'ॢ'], ll: ['ॡ', 'ॣ'],
  e: ['ए', 'े'], ai: ['ऐ', 'ै'], o: ['ओ', 'ो'], au: ['औ', 'ौ'],
};

// Every scheme lists, for each sound, the spellings it accepts; the first
// spelling is the one used when converting *to* that scheme.
const SCHEMES = {
  iast: {
    label: 'IAST', caseless: true,
    vowels: {
      a: ['a'], aa: ['ā'], i: ['i'], ii: ['ī'], u: ['u'], uu: ['ū'],
      r: ['ṛ', 'r̥'], rr: ['ṝ', 'r̥̄'], l: ['ḷ', 'l̥'], ll: ['ḹ', 'l̥̄'],
      e: ['e', 'ē'], ai: ['ai'], o: ['o', 'ō'], au: ['au'],
    },
    consonants: {
      'क': ['k'], 'ख': ['kh'], 'ग': ['g'], 'घ': ['gh'], 'ङ': ['ṅ'],
      'च': ['c'], 'छ': ['ch'], 'ज': ['j'], 'झ': ['jh'], 'ञ': ['ñ'],
      'ट': ['ṭ'], 'ठ': ['ṭh'], 'ड': ['ḍ'], 'ढ': ['ḍh'], 'ण': ['ṇ'],
      'त': ['t'], 'थ': ['th'], 'द': ['d'], 'ध': ['dh'], 'न': ['n'],
      'प': ['p'], 'फ': ['ph'], 'ब': ['b'], 'भ': ['bh'], 'म': ['m'],
      'य': ['y'], 'र': ['r'], 'ल': ['l'], 'व': ['v'], 'श': ['ś'], 'ष': ['ṣ'],
      'स': ['s'], 'ह': ['h'], 'ळ': ['ḻ'],
    },
    marks: { 'ं': ['ṃ', 'ṁ'], 'ः': ['ḥ'], 'ँ': ['m̐'], 'ऽ': ["'", '’'] },
  },
  hk: {
    label: 'Harvard-Kyoto',
    vowels: {
      a: ['a'], aa: ['A'], i: ['i'], ii: ['I'], u: ['u'], uu: ['U'],
      r: ['R'], rr: ['RR'], l: ['lR'], ll: ['lRR'], e: ['e'], ai: ['ai'], o: ['o'], au: ['au'],
    },
    consonants: {
      'क': ['k'], 'ख': ['kh'], 'ग': ['g'], 'घ': ['gh'], 'ङ': ['G'],
      'च': ['c'], 'छ': ['ch'], 'ज': ['j'], 'झ': ['jh'], 'ञ': ['J'],
      'ट': ['T'], 'ठ': ['Th'], 'ड': ['D'], 'ढ': ['Dh'], 'ण': ['N'],
      'त': ['t'], 'थ': ['th'], 'द': ['d'], 'ध': ['dh'], 'न': ['n'],
      'प': ['p'], 'फ': ['ph'], 'ब': ['b'], 'भ': ['bh'], 'म': ['m'],
      'य': ['y'], 'र': ['r'], 'ल': ['l'], 'व': ['v'], 'श': ['z'], 'ष': ['S'],
      'स': ['s'], 'ह': ['h'],
    },
    marks: { 'ं': ['M'], 'ः': ['H'], 'ँ': ['~'], 'ऽ': ["'"] },
  },
  itrans: {
    label: 'ITRANS',
    vowels: {
      a: ['a'], aa: ['A', 'aa'], i: ['i'], ii: ['I', 'ii'], u: ['u'], uu: ['U', 'uu'],
      r: ['RRi', 'R^i', 'Ri'], rr: ['RRI', 'R^I', 'RI'], l: ['LLi', 'L^i'], ll: ['LLI', 'L^I'],
      e: ['e'], ai: ['ai'], o: ['o'], au: ['au'],
    },
    consonants: {
      'क': ['k'], 'ख': ['kh'], 'ग': ['g'], 'घ': ['gh'], 'ङ': ['~N', 'N^'],
      'च': ['ch', 'c'], 'छ': ['Ch', 'chh'], 'ज': ['j'], 'झ': ['jh'], 'ञ': ['~n', 'JN'],
      'ट': ['T'], 'ठ': ['Th'], 'ड': ['D'], 'ढ': ['Dh'], 'ण': ['N'],
      'त': ['t'], 'थ': ['th'], 'द': ['d'], 'ध': ['dh'], 'न': ['n'],
      'प': ['p'], 'फ': ['ph'], 'ब': ['b'], 'भ': ['bh'], 'म': ['m'],
      'य': ['y'], 'र': ['r'], 'ल': ['l'], 'व': ['v', 'w'], 'श': ['sh'], 'ष': ['Sh', 'shh'],
      'स': ['s'], 'ह': ['h'], 'ळ': ['L', 'ld'],
      ['क' + V + 'ष']: ['kSh', 'x', 'kS'], ['ज' + V + 'ञ']: ['GY', 'j~n', 'dny'],
    },
    marks: { 'ं': ['M', '.m', '.n'], 'ः': ['H'], 'ँ': ['.N'], 'ऽ': ['.a'] },
  },
  slp1: {
    label: 'SLP1',
    vowels: {
      a: ['a'], aa: ['A'], i: ['i'], ii: ['I'], u: ['u'], uu: ['U'],
      r: ['f'], rr: ['F'], l: ['x'], ll: ['X'], e: ['e'], ai: ['E'], o: ['o'], au: ['O'],
    },
    consonants: {
      'क': ['k'], 'ख': ['K'], 'ग': ['g'], 'घ': ['G'], 'ङ': ['N'],
      'च': ['c'], 'छ': ['C'], 'ज': ['j'], 'झ': ['J'], 'ञ': ['Y'],
      'ट': ['w'], 'ठ': ['W'], 'ड': ['q'], 'ढ': ['Q'], 'ण': ['R'],
      'त': ['t'], 'थ': ['T'], 'द': ['d'], 'ध': ['D'], 'न': ['n'],
      'प': ['p'], 'फ': ['P'], 'ब': ['b'], 'भ': ['B'], 'म': ['m'],
      'य': ['y'], 'र': ['r'], 'ल': ['l'], 'व': ['v'], 'श': ['S'], 'ष': ['z'],
      'स': ['s'], 'ह': ['h'], 'ळ': ['L'],
    },
    marks: { 'ं': ['M'], 'ः': ['H'], 'ँ': ['~'], 'ऽ': ["'"] },
  },
  wx: {
    label: 'WX',
    vowels: {
      a: ['a'], aa: ['A'], i: ['i'], ii: ['I'], u: ['u'], uu: ['U'],
      r: ['q'], rr: ['Q'], l: ['L'], e: ['e'], ai: ['E'], o: ['o'], au: ['O'],
    },
    consonants: {
      'क': ['k'], 'ख': ['K'], 'ग': ['g'], 'घ': ['G'], 'ङ': ['f'],
      'च': ['c'], 'छ': ['C'], 'ज': ['j'], 'झ': ['J'], 'ञ': ['F'],
      'ट': ['t'], 'ठ': ['T'], 'ड': ['d'], 'ढ': ['D'], 'ण': ['N'],
      'त': ['w'], 'थ': ['W'], 'द': ['x'], 'ध': ['X'], 'न': ['n'],
      'प': ['p'], 'फ': ['P'], 'ब': ['b'], 'भ': ['B'], 'म': ['m'],
      'य': ['y'], 'र': ['r'], 'ल': ['l'], 'व': ['v'], 'श': ['S'], 'ष': ['R'],
      'स': ['s'], 'ह': ['h'],
    },
    marks: { 'ं': ['M'], 'ः': ['H'], 'ँ': ['z'], 'ऽ': ["'"] },
  },
};

export const SCHEME_NAMES = Object.keys(SCHEMES);
export const schemeLabel = (name) => SCHEMES[name]?.label ?? name;

// Build, per scheme, a token list sorted longest-first for greedy matching.
const TOKENS = {};
for (const [name, sc] of Object.entries(SCHEMES)) {
  const list = [];
  for (const [v, spellings] of Object.entries(sc.vowels)) {
    for (const sp of spellings) list.push({ sp: sp.normalize('NFC'), type: 'v', dev: VOWELS[v] });
  }
  for (const [dev, spellings] of Object.entries(sc.consonants)) {
    for (const sp of spellings) list.push({ sp: sp.normalize('NFC'), type: 'c', dev });
  }
  for (const [dev, spellings] of Object.entries(sc.marks)) {
    for (const sp of spellings) list.push({ sp: sp.normalize('NFC'), type: 'm', dev });
  }
  list.sort((a, b) => b.sp.length - a.sp.length);
  TOKENS[name] = list;
}

/** Convert romanised text in `scheme` to Devanagari. Characters the scheme
 *  does not know (spaces, digits, Devanagari) pass through unchanged. */
export function toDevanagari(text, scheme) {
  const sc = SCHEMES[scheme];
  if (!sc) throw new Error(`unknown scheme ${scheme}`);
  let s = text.normalize('NFC');
  if (sc.caseless) s = s.toLowerCase();
  const tokens = TOKENS[scheme];
  let out = '';
  let pending = false; // last output was a consonant still awaiting its vowel
  let i = 0;
  while (i < s.length) {
    const tok = tokens.find((t) => s.startsWith(t.sp, i));
    if (!tok) {
      if (pending) out += V;
      pending = false;
      out += s[i++];
      continue;
    }
    i += tok.sp.length;
    if (tok.type === 'c') {
      if (pending) out += V;
      out += tok.dev;
      pending = true;
    } else if (tok.type === 'v') {
      out += pending ? tok.dev[1] : tok.dev[0];
      pending = false;
    } else {
      out += tok.dev; // a mark after a consonant implies the inherent vowel
      pending = false;
    }
  }
  if (pending) out += V;
  return out;
}

// Reverse tables for Devanagari -> romanisation (first spelling wins).
const MATRA_TO_VOWEL = {};
const LETTER_TO_VOWEL = {};
for (const [v, [ind, sign]] of Object.entries(VOWELS)) {
  LETTER_TO_VOWEL[ind] = v;
  if (sign) MATRA_TO_VOWEL[sign] = v;
}

/** Convert Devanagari to romanisation (IAST by default). Used to show a
 *  reading aid under headwords and in tests. */
export function fromDevanagari(text, scheme = 'iast') {
  const sc = SCHEMES[scheme];
  const cons = {};
  for (const [dev, sp] of Object.entries(sc.consonants)) if ([...dev].length === 1) cons[dev] = sp[0];
  const marks = {};
  for (const [dev, sp] of Object.entries(sc.marks)) marks[dev] = sp[0];
  const vowel = (v) => (sc.vowels[v] ? sc.vowels[v][0] : '');
  const chars = [...text.normalize('NFC').normalize('NFD').replaceAll('़', '').normalize('NFC')];
  let out = '';
  for (let i = 0; i < chars.length; i++) {
    const ch = chars[i];
    if (cons[ch] !== undefined) {
      out += cons[ch];
      const next = chars[i + 1];
      if (next === V) { i++; continue; }
      if (MATRA_TO_VOWEL[next]) { out += vowel(MATRA_TO_VOWEL[next]); i++; continue; }
      out += vowel('a');
    } else if (LETTER_TO_VOWEL[ch]) {
      out += vowel(LETTER_TO_VOWEL[ch]);
    } else if (marks[ch] !== undefined) {
      out += marks[ch];
    } else {
      out += ch;
    }
  }
  return out;
}

const DEVANAGARI = /[ऀ-ॿ]/;
const IAST_MARKS = /[āīūṛṝḷḹṅñṭḍṇśṣṃṁḥēọ̥̄̄̐]/i;

/**
 * Interpret a query typed in any supported way.
 * Returns a list of { scheme, text } readings, most likely first:
 *  - Devanagari input is used as is;
 *  - a specific scheme converts with that scheme only;
 *  - 'auto' uses IAST if the text has IAST diacritics, otherwise tries every
 *    ASCII scheme (HK, ITRANS, SLP1, WX) and keeps the distinct readings.
 */
export function readings(query, scheme = 'auto') {
  const q = query.trim();
  if (!q) return [];
  if (DEVANAGARI.test(q)) return [{ scheme: 'deva', text: q }];
  if (scheme !== 'auto') return [{ scheme, text: toDevanagari(q, scheme) }];
  const order = IAST_MARKS.test(q) ? ['iast'] : ['hk', 'itrans', 'slp1', 'wx'];
  const seen = new Map();
  for (const s of order) {
    const text = toDevanagari(q, s);
    // Skip readings that left Latin letters unconverted (not this scheme).
    if (/[a-z]/i.test(text)) continue;
    if (!seen.has(text)) seen.set(text, { scheme: s, text });
  }
  return [...seen.values()];
}
