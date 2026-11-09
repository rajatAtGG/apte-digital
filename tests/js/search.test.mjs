// Transliteration search against the real database (skipped if not built).
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

const top = (q, scheme = 'auto', n = 5) => dict.search(q, scheme).results.slice(0, n).map((r) => r.headword);

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

test('the same word in every input method finds कृष्ण', opts, () => {
  for (const [q, scheme] of [['कृष्ण', 'auto'], ['kṛṣṇa', 'auto'], ['kRSNa', 'hk'],
    ['kRiShNa', 'itrans'], ['kfzRa', 'slp1'], ['kqRNa', 'wx'], ['kRSNa', 'auto']]) {
    const hw = top(q, scheme);
    assert.ok(hw.some((h) => h.startsWith('कृष्ण')), `${q} (${scheme}) -> ${hw}`);
  }
});

test('stems match nominative headwords: kamala -> कमलम्', opts, () => {
  assert.ok(top('kamala').includes('कमलम्'), top('kamala'));
});

test('visarga and case endings are optional: rAmaH and rAma', opts, () => {
  assert.deepEqual(top('rAmaH', 'hk', 2).sort(), ['राम', 'रामः'].sort());
  assert.ok(top('राम').includes('रामः'));
});

test('prefix match while typing', opts, () => {
  const hw = dict.search('kamal', 'hk', 200).results.map((r) => r.headword);
  assert.ok(hw.includes('कमलाकरः') || hw.includes('कमला'), hw.slice(0, 10));
});

test('typo tolerance: plain-English spellings', opts, () => {
  assert.ok(top('krishna').some((h) => h.startsWith('कृष्ण')), top('krishna'));
  assert.ok(top('shiva').some((h) => h.startsWith('शिव')), top('shiva'));
  assert.ok(top('samskrta').some((h) => h.startsWith('संस्कृत')), top('samskrta'));
});

test('star headwords are found without the star', opts, () => {
  assert.ok(top('कृत्वस्').includes('*कृत्वस्'), top('कृत्वस्'));
});

test('homonyms are both returned', opts, () => {
  assert.equal(top('कंसः', 'auto', 10).filter((h) => h === 'कंसः').length >= 2, true);
});

test('reverse search: Hindi word -> Sanskrit headwords', opts, () => {
  const { results } = dict.reverse('प्याला');
  const hw = results.map((r) => r.headword);
  assert.ok(hw.includes('चषकः') && hw.includes('कंसः'), hw);
  assert.ok(results[0].senses[0].text.includes('प्याला'));
  // Romanised Hindi works too (HK reading of "pyAlA").
  assert.ok(dict.reverse('pyAlA', 'hk').results.length > 0);
});

test('entry tree and neighbours', opts, () => {
  const id = dict.search('अंश्').results.find((r) => r.headword === 'अंश्').id;
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
  for (const q of ['k', 'ka', 'kam', 'kama', 'kamal', 'krishna', 'xyzq']) dict.search(q);
  assert.ok(performance.now() - t < 1500, `${performance.now() - t} ms`);
});
