# Apte Digital: आप्टे संस्कृत-हिन्दी कोश

An offline-first Sanskrit-Hindi dictionary built from **V. S. Apte's Sanskrit-Hindi
Kosh** as digitised by the **Samsaadhanii** project (University of Hyderabad).

**App:** an installable PWA that works fully offline on Android and iOS, deployed to
GitHub Pages by `.github/workflows/pages.yml` (https://rajatatgg.github.io/apte-digital/).

## Using the app

- **Search** in Devanagari or any romanisation: IAST (`kṛṣṇa`), Harvard-Kyoto
  (`kRSNa`), ITRANS (`kRiShNa`), SLP1 (`kfzRa`) or WX (`kqRNa`). With **Auto**
  every scheme is tried, and the line under the search box shows how your input
  was read. Results update as you type. Matching uses exact match, then prefix,
  then a "loose" key (vowel length, aspiration, sibilants, ṛ/ri, nasals), then
  typo tolerance (1–2 edits). Plain spellings such as `krishna`, `shiva` and
  `sanskrit` therefore work too.
- **Reverse search**: tap **सं→हि** to switch to **हि→सं**, then type a Hindi word
  (`प्याला`). This lists the Sanskrit headwords whose senses contain it, with the
  matching sense highlighted.
- **Entries** look like the printed page: the headword (with an optional IAST
  reading aid), grammar, stem, etymology, numbered senses with citations,
  semantic categories, then the sub-entries and compounds as collapsible
  sections. Arrows step to the previous and next headword in dictionary order.
- **Browse** by letter in varnamala order (स्वर, कवर्ग … ऊष्म).
- **Bookmarks** and **recent searches** are kept on the device (localStorage).
- **Settings**: light, dark or system theme; text size; default input method;
  IAST and category display; offline status. **About** gives the credits and
  the licence.

To install it, open the site, then use *Add to Home screen* (iOS Safari: Share,
then Add to Home Screen). On the first visit the service worker stores the app
and the 11.5 MB compressed dictionary. After that everything runs offline: the
database is decompressed in the browser and queried with SQLite compiled to
WebAssembly (`@sqlite.org/sqlite-wasm`, which, unlike the stock sql.js build,
includes FTS5).

## Credits and licence

- **Dictionary:** Vaman Shivram Apte, *Sanskrit-Hindi Kosh* (Hindi version of
  *The Practical Sanskrit-English Dictionary*).
- **Digital edition:** the [Samsaadhanii](https://github.com/samsaadhanii/scl)
  project, Department of Sanskrit Studies, University of Hyderabad. The XML data
  lives in `MT/data/hi/Apte_dict/` of that repository.
- **Licence of the source data:** the Samsaadhanii repository is distributed
  under the **GNU General Public License, version 2** (its `README.md` says "All
  the packages are available under GPL" and it ships the GPL v2 text as
  `COPYING`). The database and JSON produced here are derived from that data and
  are therefore distributed under the same GPL v2 terms. If you redistribute
  them, include the licence and these credits.
- **Typeface:** Noto Serif Devanagari (SIL Open Font License 1.1, `app/fonts/OFL.txt`).
- **SQLite** is public domain; the `@sqlite.org/sqlite-wasm` wrapper is Apache-2.0.

## Building

Requires git, Python 3.9+ (standard library only; `pytest` for the tests) and
Node 20+.

```sh
make build     # fetch the source XML and build build/apte.sqlite (validated)
make app       # + assemble the PWA in dist/
make serve     # http://localhost:8080/
make test      # pytest + node --test
```

Every push to `main` (or the current development branch) runs the same steps
in GitHub Actions and deploys `dist/` to GitHub Pages. In the repository
settings, *Pages → Source* must be set to **GitHub Actions**. The workflow tries
to enable this itself.

`scripts/fetch_data.sh` makes a shallow **sparse** checkout of only
`MT/data/hi/Apte_dict` (about 24 MB) at a pinned commit into `data/raw/`
(git-ignored). `pipeline/build.py` then writes:

| file | contents |
|---|---|
| `build/apte.sqlite` | SQLite database with an FTS5 index (~44 MB, ~12 MB gzipped) |
| `build/apte.json` | the same entries as one nested JSON document (~26 MB) |
| `build/report.txt` | the validation report |

The build **fails (exit status 1)** unless the parsed counts match
`pipeline/expected.json` exactly. Each count is checked twice: once from the
parsed tree and once by an independent regex over the raw XML.

```
check                         expected    parsed  raw grep  result
lexhead                          27699     27699     27699  OK
dentry                           54463     54463     54463  OK
sense                            98634     98634     98634  OK
citation                         27649     27649     27649  OK
duplicate_main_headwords           404       404            OK
star_headwords                       5         5            OK
empty_grammar                      200       200            OK
```

## Source format

There are 42 XML files (`a.xml` … `h.xml`, plus `apte.dtd` and `apte.css`), one
per initial letter. The file names are loose WX-style romanisations: `x` = द,
`w` = त, `q` = ऋ, `kh` = ख, `nn` = ण. A file is not strictly one letter: prefixed
verbs are filed under their root (`i.xml` contains अधी, `kh.xml` ends with ग).
For this reason the app files each word under its *own* initial letter.

`<lexhead no="N">` is one main entry. Inside it:

| element | meaning | stored as |
|---|---|---|
| `dentry` | headword (one per entry) | `entries.headword` (verbatim) |
| `prAwipaxikam gen=` | stem, optional gender | `body.stems[{text, gen}]`, `entries.stem` |
| `grammar` (→ `gaNa`, `paxI`, `vform`) | पुं*, नपुं*, वि* …; verb class and voice | `body.grammar` (runs) |
| `etymology` (→ `citation`, `vform`, and undocumented `v`, `vigrahavAkyam`/`vigrahavAkya`/`vigraha_vAkya`, `explanation`, `compound_type`) | derivation | `body.etymology` (runs) |
| `sense no=|n=` (→ `citation`, `vform`, `ref`) | numbered meaning | `body.senses[{n, runs}]` |
| `citation` (nestable) | source reference | inline run inside a sense |
| `jAwi`, `upAXi`, `kind_of`, `is_a_part` | semantic categories | `body.semantic[[tag, text]]` |
| `seg` | segmentation, e.g. अग्निः-कुमारः | `body.segs` |
| `num`, `cat`, `gen`, `root`, `vform` | number, misc. | `body.nums` etc. |
| `segmenthd` → `subsegmenthd` | sub-entry → sub-sub-entry | own `entries` rows, linked by `parent_id` |
| `compound`, `sublexhd`, `compoundverb` | compounds / other sub-entries | own `entries` rows |
| `h`, `ref` | defined in the DTD, unused in the data | handled generically as runs |

**Runs:** mixed content (text interleaved with tags) is stored as a list
whose items are strings or `[tag, ...runs]`. For example
`["मथुरा का राजा", ["citation", "भाग* १०।१"]]`. Nothing is rewritten. Display
conventions, such as showing the abbreviation mark `*` as `०` (`पुं*` → पुं०),
are applied by the app at render time.

### Known quirks (handled and tested)

- **404 repeated main headwords** are genuine homonyms (कंसः "cup" and कंसः
  "king of Mathura"). Both are kept as separate entries.
- **5 headwords start with a stray `*`** (`*द`, `*कृत्`, `*कृत्वस्`, `*जीविन्`
  and the sub-entry `*सात् कृ`). They are shown verbatim, and the `*` is ignored
  for searching and sorting.
- **200 empty `<grammar/>`** elements are kept as empty and are not displayed.
- **9 lexhead numbers have letter suffixes** (`138a`, `2685b`), so `lexhead_no`
  is stored as text.
- **Stray text inside entries:** 205 bits of encoding debris (`?`, `g`) are
  dropped and counted. Real Devanagari stray text is kept. For the 24
  sub-entries with no `<dentry>`, that text, or else the stem, becomes the
  display headword (`has_dentry = 0`).
- Some sense text runs a Hindi gloss straight into a Sanskrit quotation with no
  separator (e.g. `नाक का अग्र भागसमस्ता एव…`). This comes from the source, and
  is left as is.

## Database schema (`build/apte.sqlite`)

```sql
meta(key, value)               -- source commit, licence, build time, counts
entries(
  id, main_id, parent_id,      -- main_id = the lexhead; parent_id links sub-entries
  kind,                        -- main | segmenthd | subsegmenthd | compound | sublexhd
  depth, src_file, lexhead_no,
  headword,                    -- original text, always what is displayed
  has_dentry, stem,
  norm,                        -- normalised search key
  letter, sort_key,            -- initial varna; varnamala collation key
  grammar,                     -- plain text for result lists
  body                         -- JSON: stems, grammar, etymology, senses, semantic, segs …
)
search_keys(key, entry_id)     -- normalised headword AND stem keys; prefix search via PK
senses_fts(text)               -- FTS5, contentless, normalised Hindi sense text
                               -- rowid = entry_id * 1000 + index into body.senses
```

Example queries:

```sql
-- prefix search (key = normalised query)
SELECT e.* FROM search_keys k JOIN entries e ON e.id = k.entry_id
 WHERE k.key >= :key AND k.key < :key || char(0xFFFF);
-- a main entry with its sub-entries
SELECT * FROM entries WHERE main_id = :id ORDER BY id;
-- reverse search: Hindi word -> entries
SELECT rowid / 1000 AS entry_id, rowid % 1000 AS sense FROM senses_fts WHERE senses_fts MATCH 'प्याला';
-- browse a letter in varnamala order
SELECT id, headword FROM entries WHERE kind = 'main' AND letter = 'ख' ORDER BY sort_key;
```

## Normalisation and sorting (`pipeline/normalize.py`)

Search keys are deliberately lossy, but the display always uses the original
text. The rules:

- remove visarga (रामः → राम, and ASCII `:` is treated as a visarga typo);
- turn candrabindu into anusvara, and a nasal before a consonant of its own
  class into anusvara (शङ्कर → शंकर, सन्त → संत; अन्य is left alone);
- remove `*`, avagraha, nukta, zero-width joiners, spaces, digits and
  punctuation.

Both the headword and the stem are indexed, so `kamala` finds कमलम् through its
stem कमल.

**Varnamala order:** each word is split into units (consonant plus vowel, where
a virama means no vowel) and ranked: vowels अ…औ, then ं ः, then क…ह. ॠ sorts
after ऋ, not after ह as in Unicode, and the anusvara sorts before the
consonants, as in the printed dictionary. Entries sort by stem first, so अः
sits next to अ.

FTS5 note: SQLite's `unicode61` tokenizer splits Devanagari at vowel signs
(पात्र → प / त / र). The index therefore declares all Devanagari combining
marks as `tokenchars`.

## Layout

```
scripts/fetch_data.sh     sparse checkout of the source (pinned commit)
pipeline/apte_parser.py   XML -> dicts
pipeline/normalize.py     search keys, varnamala collation
pipeline/build.py         dicts -> SQLite/FTS5 + JSON + validation report
pipeline/expected.json    the counts the build must reproduce
app/                      the PWA (plain ES modules, no bundler)
  js/translit.js          IAST / HK / ITRANS / SLP1 / WX <-> Devanagari
  js/normalize.js         JS port of the search-key normaliser + loose key
  js/search.js            in-memory headword index: exact/prefix/loose/fuzzy
  js/dict.js              queries (search, reverse, entry tree, browse)
  js/render.js            entry and result HTML
  js/app.js               routing, views, settings
  sw.js                   offline cache (file lists filled in at build time)
scripts/build-app.mjs     app/ + sqlite-wasm + hashed, gzipped DB -> dist/
scripts/serve.mjs         local static server
scripts/make-icons.mjs    renders app/icons/icon.svg to PNGs
tests/                    pytest suite; tests/js/ node tests (transliteration,
                          search against the real DB); tests/shared/ cases
                          used by both the Python and JS normalisers
```
