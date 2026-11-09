import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { toDevanagari, fromDevanagari, readings } from '../../app/js/translit.js';
import { normalize, loose } from '../../app/js/normalize.js';

const shared = JSON.parse(readFileSync(new URL('../shared/normalize_cases.json', import.meta.url)));

test('JS normalize agrees with the Python normaliser on the shared cases', () => {
  for (const [input, expected] of shared.cases) assert.equal(normalize(input), expected, input);
});

// One word in every scheme: कृष्णः, and a word with most vowel signs.
const SAME_WORD = {
  iast: ['kṛṣṇaḥ', 'saṃskṛtam', 'jñānam', 'rāmāyaṇam', 'aiśvaryam', 'ṛṣiḥ'],
  hk: ['kRSNaH', 'saMskRtam', 'jJAnam', 'rAmAyaNam', 'aizvaryam', 'RSiH'],
  itrans: ['kRiShNaH', 'saMskRitam', 'j~nAnam', 'rAmAyaNam', 'aishvaryam', 'RRiShiH'],
  slp1: ['kfzRaH', 'saMskftam', 'jYAnam', 'rAmAyaRam', 'ESvaryam', 'fziH'],
  wx: ['kqRNaH', 'saMskqwam', 'jFAnam', 'rAmAyaNam', 'ESvaryam', 'qRiH'],
};
const DEVA = ['कृष्णः', 'संस्कृतम्', 'ज्ञानम्', 'रामायणम्', 'ऐश्वर्यम्', 'ऋषिः'];

for (const [scheme, words] of Object.entries(SAME_WORD)) {
  test(`${scheme} -> Devanagari`, () => {
    words.forEach((w, i) => assert.equal(toDevanagari(w, scheme), DEVA[i], w));
  });
  test(`Devanagari -> ${scheme} round-trips`, () => {
    DEVA.forEach((d) => assert.equal(toDevanagari(fromDevanagari(d, scheme), scheme), d, d));
  });
}

test('inherent vowel, final consonant and pass-through', () => {
  assert.equal(toDevanagari('kamala', 'hk'), 'कमल');
  assert.equal(toDevanagari('kamal', 'hk'), 'कमल्');
  assert.equal(toDevanagari('a', 'hk'), 'अ');
  assert.equal(toDevanagari('rAma-kathA', 'hk'), 'राम-कथा');
  assert.equal(toDevanagari('Kṛṣṇa', 'iast'), 'कृष्ण'); // IAST ignores case
  assert.equal(toDevanagari('kSha', 'itrans'), 'क्ष');
  assert.equal(fromDevanagari('अग्निः'), 'agniḥ');
});

test('scheme-specific letters differ (WX x = द, SLP1 x = ऌ)', () => {
  assert.equal(toDevanagari('xeva', 'wx'), 'देव');
  assert.equal(toDevanagari('wawra', 'wx'), 'तत्र');
  assert.equal(toDevanagari('wawra', 'slp1'), 'टट्र');
});

test('auto readings', () => {
  assert.deepEqual(readings('कमल'), [{ scheme: 'deva', text: 'कमल' }]);
  assert.deepEqual(readings('kṛṣṇa').map((r) => r.text), ['कृष्ण']);
  const shiva = readings('shiva').map((r) => r.text);
  assert.ok(shiva.includes('शिव'), shiva); // ITRANS reading
  assert.deepEqual(readings('xeva', 'wx'), [{ scheme: 'wx', text: 'देव' }]);
  assert.deepEqual(readings('  '), []);
});

test('loose keys fold common confusions', () => {
  assert.equal(loose(normalize('क्रिश्न')), loose(normalize('कृष्ण')));
  assert.equal(loose('शिव'), loose('सिव'));
  assert.equal(loose('रामः'.replace('ः', '')), loose('रम'));
});
