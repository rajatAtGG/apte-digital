// Search-key normalisation: a line-by-line port of pipeline/normalize.py.
// Both are tested against tests/shared/normalize_cases.json, so a query
// normalised here meets the keys the Python build stored in the database.

const VIRAMA = '्';
const ANUSVARA = 'ं';
const CANDRABINDU = 'ँ';
const VISARGA = 'ः';
const NUKTA = '़';
const AVAGRAHA = 'ऽ';

const INVISIBLE = /[​-‍﻿]/g;
const NOT_DEVANAGARI = /[^ऀ-ॣॱ-ॿ]/g;
// A nasal + virama before a consonant of its own class is written either
// way in the dictionary (शङ्कर / शंकर); both fold to anusvara.
const HOMORGANIC = new RegExp(
  `ङ${VIRAMA}(?=[कखगघ])|ञ${VIRAMA}(?=[चछजझ])|ण${VIRAMA}(?=[टठडढ])|` +
  `न${VIRAMA}(?=[तथदध])|म${VIRAMA}(?=[पफबभ])`, 'g');

/** Search key for a Devanagari string (see pipeline/normalize.py). */
export function normalize(text) {
  if (!text) return '';
  let s = text.normalize('NFC').replace(INVISIBLE, '');
  s = s.replaceAll(':', VISARGA);
  s = s.normalize('NFD').replaceAll(NUKTA, '').normalize('NFC');
  s = s.replaceAll(VISARGA, '').replaceAll(CANDRABINDU, ANUSVARA).replaceAll(AVAGRAHA, '');
  s = s.replace(NOT_DEVANAGARI, '');
  return s.replace(HOMORGANIC, ANUSVARA);
}

/** Normalise running Hindi text word by word (for reverse search). */
export function normalizeWords(text) {
  return (text.normalize('NFC').match(/[ऀ-ॣॱ-ॿ]+/g) || [])
    .map(normalize).filter(Boolean);
}

// A looser key, used only in the app for typo tolerance. It folds the
// distinctions people most often get wrong when spelling Sanskrit:
// vowel length, aspiration (ध/द), retroflex vs dental (ट/त), the three
// sibilants, ri/ṛ, and any remaining nasal cluster vs anusvara. It is never
// stored or displayed; matches through it rank below exact/prefix matches.
const LOOSE_RULES = [
  [/्रि/g, 'ृ'], [/्र्(?=[क-ह])/g, 'ृ'], [/रि/g, 'ृ'], [/^ऋ/, 'ृ'], [/ॠ/g, 'ृ'], [/ॄ/g, 'ृ'],
  [/आ/g, 'अ'], [/ा/g, ''], [/ी/g, 'ि'], [/ई/g, 'इ'], [/ू/g, 'ु'], [/ऊ/g, 'उ'],
  [/ै/g, 'े'], [/ऐ/g, 'ए'], [/ौ/g, 'ो'], [/औ/g, 'ओ'],
  [/[शष]/g, 'स'], [/ण/g, 'न'], [/[ङञणनम]्(?=[क-ह])/g, 'ं'], [/व/g, 'ब'],
  [/ळ/g, 'ल'], [/्$/, ''],
  [/ख/g, 'क'], [/घ/g, 'ग'], [/छ/g, 'च'], [/झ/g, 'ज'], [/[ठटथ]/g, 'त'],
  [/[ढडध]/g, 'द'], [/फ/g, 'प'], [/भ/g, 'ब'],
];
export function loose(key) {
  let s = key;
  for (const [re, to] of LOOSE_RULES) s = s.replace(re, to);
  return s;
}
