// Devanagari search against the real database (skipped if not built).
import { test, before } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import sqlite3InitModule from '@sqlite.org/sqlite-wasm';
import { Dictionary, openDatabase } from '../../app/js/dict.js';
import { HeadwordIndex, editDistance } from '../../app/js/search.js';

const DB = new URL('../../build/apte.sqlite', import.meta.url);
const haveDb = existsSync(DB);
let dict;

before(async () => {
  if (!haveDb) return;
  const sqlite3 = await sqlite3InitModule({ print: () => {}, printErr: () => {} });
  dict = new Dictionary(openDatabase(sqlite3, new Uint8Array(readFileSync(DB))));
});

const top = (q, n = 5) => dict.search(q).slice(0, n).map((r) => r.headword);

test('edit distance', () => {
  assert.equal(editDistance('कमल', 'कमल', 2), 0);
  assert.equal(editDistance('कमल', 'कलम', 2), 1);   // transposition
  assert.equal(editDistance('कमल', 'कमलम', 2), 1);
  assert.equal(editDistance('कम', 'कमलाकर', 1, true), 0); // prefix mode
  assert.equal(editDistance('abcdef', 'uvwxyz', 2), 3); // gives up past max
});

test('HeadwordIndex bands: exact < prefix < loose < fuzzy', () => {
  const idx = new HeadwordIndex([['राम', 1], ['रामायण', 2], ['रम', 3], ['रामचंद्र', 4], ['कमल', 5]]);
  const hits = idx.find('राम');
  assert.equal(hits.get(1).score, 0);
  assert.ok(hits.get(2).score >= 1 && hits.get(2).score < 2);
  assert.ok(hits.get(3).score >= 2 && hits.get(3).score < 3); // loose: vowel length
  assert.ok(!hits.has(5));
  assert.ok(idx.find('कमक').has(5)); // one typo
});

const opts = { skip: !haveDb && 'build/apte.sqlite not built (run make build)' };

test('stems match nominative headwords: कमल -> कमलम्', opts, () => {
  assert.ok(top('कमल').includes('कमलम्'), top('कमल'));
});

test('visarga is optional: राम finds राम and रामः', opts, () => {
  assert.deepEqual(top('राम', 2).sort(), ['राम', 'रामः'].sort());
  assert.ok(top('रामः').includes('राम'));
});

test('anusvara and nasal-cluster spellings meet: शंकर / शङ्कर', opts, () => {
  assert.ok(top('शंकर').some((h) => h.startsWith('शङ्कर') || h.startsWith('शंकर')), top('शंकर'));
});

test('prefix match while typing, including a half-typed conjunct', opts, () => {
  const hw = dict.search('कमला', 200).map((r) => r.headword);
  assert.ok(hw.includes('कमलाकरः'), hw.slice(0, 10));
  // क्  (on the way to क्ष) still lists words beginning with क.
  assert.ok(dict.search('क्').length > 0);
});

test('typo tolerance in Devanagari', opts, () => {
  assert.ok(top('क्रिश्न').some((h) => h.startsWith('कृष्ण')), top('क्रिश्न'));  // ri for ṛ, श for ष
  assert.ok(top('दर्म').some((h) => h.startsWith('धर्म')), top('दर्म'));         // missing aspiration
  assert.ok(top('संसकृत').some((h) => h.startsWith('संस्कृत')), top('संसकृत'));   // missing virama
});

test('non-matching input returns nothing rather than throwing', opts, () => {
  assert.deepEqual(dict.search('kamala'), []);
  assert.deepEqual(dict.search(''), []);
});

test('star headwords are found without the star', opts, () => {
  assert.ok(top('कृत्वस्').includes('*कृत्वस्'), top('कृत्वस्'));
});

test('homonyms are both returned', opts, () => {
  assert.ok(top('कंसः', 10).filter((h) => h === 'कंसः').length >= 2);
});

test('reverse search: Hindi word -> Sanskrit headwords', opts, () => {
  const { results } = dict.reverse('प्याला');
  const hw = results.map((r) => r.headword);
  assert.ok(hw.includes('चषकः') && hw.includes('कंसः'), hw);
  assert.ok(results[0].senses[0].text.includes('प्याला'));
  // Candrabindu/anusvara variants meet: काँसा finds senses written कांसा too.
  assert.ok(dict.reverse('काँसा').results.length > 0);
});

test('entry tree and neighbours', opts, () => {
  const id = dict.search('अंश्').find((r) => r.headword === 'अंश्').id;
  const e = dict.entry(id);
  assert.equal(e.kind, 'main');
  assert.equal(e.children[0].headword, 'व्यंश्');
  assert.equal(e.grammar_text, 'चुरा* उभ* अंशयति,अंशते');
  assert.ok(Array.isArray(e.grammar));
  const { prev, next } = dict.neighbours(e);
  assert.ok(next && next.id !== e.id && (prev === null || prev.id !== e.id));
});

test('browse is in varnamala order', opts, () => {
  const counts = dict.letterCounts();
  assert.equal([...counts.values()].reduce((a, b) => a + b, 0), 27699);
  const kh = dict.browse('ख', 0, 5).map((r) => r.headword);
  assert.deepEqual(kh.slice(0, 2), ['खः', 'खम्']);
});

test('search is fast enough to run per keystroke', opts, () => {
  const t = performance.now();
  for (const q of ['क', 'कम', 'कमल', 'कमला', 'क्रिश्न', 'ज़ज़ज़ज़']) dict.search(q);
  assert.ok(performance.now() - t < 1500, `${performance.now() - t} ms`);
});
