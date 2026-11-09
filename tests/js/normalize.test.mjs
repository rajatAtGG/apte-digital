import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { normalize, normalizeWords, loose } from '../../app/js/normalize.js';

const shared = JSON.parse(readFileSync(new URL('../shared/normalize_cases.json', import.meta.url)));

test('JS normalize agrees with the Python normaliser on the shared cases', () => {
  for (const [input, expected] of shared.cases) assert.equal(normalize(input), expected, input);
});

test('normalizeWords splits running Hindi text', () => {
  assert.deepEqual(normalizeWords('जल पीने का पात्र, प्याला'), ['जल', 'पीने', 'का', 'पात्र', 'प्याला']);
  assert.deepEqual(normalizeWords('काँसा'), ['कांसा']);
});

test('loose keys fold common spelling slips', () => {
  assert.equal(loose(normalize('क्रिश्न')), loose(normalize('कृष्ण')));  // ri/ṛ, sibilant, nasal
  assert.equal(loose('शिव'), loose('सिव'));
  assert.equal(loose('धर्म'), loose('दर्म'));                           // aspiration
  assert.equal(loose('गीता'), loose('गिता'));                           // vowel length
});
