// HTML rendering of entries and result rows. Everything that comes from the
// data goes through esc(); markup is only ever added around it.

export const esc = (s) => String(s ?? '').replace(/[&<>"']/g,
  (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);

/** The source marks abbreviations with "*" (पुं*); print shows "०" (पुं०).
 *  Applied to every displayed text except headwords, which stay verbatim. */
export const abbr = (s) => esc(s).replaceAll('*', '०');

const TAG_CLASS = (tag) => `r-${tag.replace(/[^\w]/g, '')}`;

/** Render a run list (see pipeline/apte_parser.py) to HTML. */
export function runs(rs) {
  if (!rs) return '';
  return rs.map((r, i) => {
    if (typeof r === 'string') return abbr(r);
    const [tag, ...inner] = r;
    if (tag === 'citation') return `<cite>${runs(inner)}</cite>`;
    // Adjacent tags (<gaNa>चुरा*</gaNa><paxI>उभ*</paxI>) need a space.
    const gap = typeof rs[i + 1] === 'object' ? ' ' : '';
    return `<span class="${TAG_CLASS(tag)}">${runs(inner)}</span>${gap}`;
  }).join('');
}

const SEMANTIC_LABEL = { jAwi: 'जाति', upAXi: 'उपाधि', kind_of: 'प्रकार', is_a_part: 'अंग' };
const KIND_LABEL = {
  segmenthd: 'उपशब्द', subsegmenthd: 'उपशब्द', compound: 'समास', sublexhd: 'उपशब्द', compoundverb: 'क्रिया',
  form: 'रूप',
};

function headline(e, big) {
  return big ? `<div class="head">${esc(e.headword)}</div>` : `<span class="hw">${esc(e.headword)}</span>`;
}

/** Grammar, stems, segmentation and etymology as one line. */
function metaLine(e, opts, sub = false) {
  const parts = [];
  // A sub-entry's grammar label is already shown in its summary line.
  for (const g of sub ? [] : e.grammar || []) {
    const html = runs(g);
    if (html.trim()) parts.push(`<span class="g">${html}</span>`);
  }
  const stems = (e.stems || []).filter((s) => s.text && s.text !== e.headword);
  if (stems.length) {
    parts.push(`<span class="stem">प्राति० ${stems.map((s) => esc(s.text) + (s.gen ? ` (${abbr(s.gen)})` : '')).join(', ')}</span>`);
  }
  for (const s of e.segs || []) parts.push(`<span class="seg">[${esc(s)}]</span>`);
  for (const n of e.nums || []) parts.push(`<span class="g">${abbr(n)}</span>`);
  for (const et of e.etymology || []) parts.push(`<span class="ety">${runs(et)}</span>`);
  for (const v of e.vforms || []) parts.push(`<span class="r-vform">${abbr(v)}</span>`);
  return parts.length ? `<div class="meta-line">${parts.join(' ')}</div>` : '';
}

function body(e, opts, sub = false) {
  let h = metaLine(e, opts, sub);
  if (e.senses?.length) {
    // A single unnumbered sense gets no number, as in print.
    const plain = e.senses.length === 1 && !e.senses[0].n;
    h += '<ol class="senses">' + e.senses.map((s, i) => (plain
      ? `<li class="plain"><span>${runs(s.runs)}</span></li>`
      : `<li><span class="n">${esc(s.n || i + 1)}.</span><span>${runs(s.runs)}</span></li>`)).join('') + '</ol>';
  }
  if (e.notes?.length) h += `<p class="notes">${e.notes.map(abbr).join(' · ')}</p>`;
  if (opts.showCategories && e.semantic?.length) {
    // Group repeated tags: जाति: वायुः, ग्रहः · प्रकार: देवः
    const groups = new Map();
    for (const [tag, text] of e.semantic) {
      if (!groups.has(tag)) groups.set(tag, []);
      if (!groups.get(tag).includes(text)) groups.get(tag).push(text);
    }
    h += `<div class="cats">${[...groups].map(([t, v]) =>
      `<b>${SEMANTIC_LABEL[t] || esc(t)}:</b> ${v.map(esc).join(', ')}`).join(' · ')}</div>`;
  }
  return h;
}

function subEntry(e, opts, openIds) {
  const open = openIds.has(e.id) ? ' open' : '';
  const kind = KIND_LABEL[e.kind] ? `<span class="kind">${KIND_LABEL[e.kind]}</span>` : '';
  const gram = e.grammar_text ? `<span class="gram">${abbr(e.grammar_text)}</span>` : '';
  // Printed edition: compound/derived heads are printed as fragments (-पथः);
  // show the reconstructed full form (अघोरपथः) beside them.
  const full = (e.full || []).filter((f, i) => f && f !== (e.heads || [])[i]);
  const fullHtml = full.length ? `<span class="full">= ${esc(full.join(', '))}</span>` : '';
  return `<details class="sub" id="e${e.id}"${open}><summary>${headline(e)}${fullHtml}${gram}${kind}</summary>
    <div class="sub-body">${body(e, opts, Boolean(e.grammar_text))}${e.children.map((c) => subEntry(c, opts, openIds)).join('')}</div></details>`;
}

/** Full article for a main entry tree (from Dictionary.entry). `focusId`
 *  is a sub-entry to open (and its ancestors). */
export function article(e, opts, focusId) {
  const openIds = new Set();
  if (focusId && focusId !== e.id) {
    const path = (node) => node.id === focusId || node.children.some((c) => path(c) && openIds.add(c.id));
    path(e);
  }
  const subs = e.children.length
    ? `<div class="subs-head"><h2 class="section">उपशब्द व समास · ${e.children.length}</h2>
         <button class="btn small" type="button" data-act="expand">सब खोलें</button></div>
       ${e.children.map((c) => subEntry(c, opts, openIds)).join('')}`
    : '';
  return `<article class="article">${headline(e, true)}${body(e, opts)}${subs}</article>`;
}

/** One row of a result list. */
export function resultRow(r, extra = '') {
  const under = r.kind && r.kind !== 'main' && r.main_headword
    ? `<span class="under">↳ ${esc(r.main_headword)} के अन्तर्गत</span>` : '';
  const gram = r.grammar ? `<span class="gram">${abbr(r.grammar)}</span>` : '';
  const gloss = r.gloss ? `<span class="gloss">${abbr(r.gloss)}</span>` : '';
  return `<li><a href="#e-${r.id}">${under}${headline(r)}${gram}${extra || gloss}</a></li>`;
}

/** Highlight occurrences of (normalised) query words in a sense snippet. */
export function highlight(text, words) {
  let html = abbr(text);
  for (const w of words) {
    if (!w) continue;
    const re = new RegExp(`(${w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}[\\u0900-\\u097f]*)`, 'g');
    html = html.replace(re, '<mark>$1</mark>');
  }
  return html;
}
