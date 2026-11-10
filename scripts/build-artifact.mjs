// Turn a built app (scripts/build-app.mjs output) into a Claude artifact:
//   node scripts/build-artifact.mjs --dist dist_print --out artifact_print
// writes OUT/index.html (page content without <html>/<head>/<body>, which the
// artifact host adds) and OUT/files.json (published path -> source path) for
// the Artifact tool's `files` parameter. The service worker and web-app
// manifest are left out: artifacts can't install them.
import { readFileSync, writeFileSync, mkdirSync, readdirSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';

const arg = (name) => { const i = process.argv.indexOf(name); return i > 0 ? process.argv[i + 1] : null; };
const DIST = arg('--dist');
const OUT = arg('--out');
if (!DIST || !OUT) throw new Error('usage: build-artifact.mjs --dist DIR --out DIR');
mkdirSync(OUT, { recursive: true });

let html = readFileSync(join(DIST, 'index.html'), 'utf8');
const head = html.match(/<head>([\s\S]*?)<\/head>/)[1];
const body = html.match(/<body>([\s\S]*?)<\/body>/)[1];
const keepHead = head
  .split('\n')
  .filter((l) => !/<meta charset|<meta name="viewport"|rel="manifest"|rel="icon"|apple-touch-icon|apple-mobile-web-app|name="theme-color"/.test(l))
  .join('\n');
const named = keepHead.replace(/<title>[^<]*<\/title>/, '<title>आप्टे शब्दकोश</title>');
writeFileSync(join(OUT, 'index.html'), `${named.trim()}\n${body.trim()}\n`);

const walk = (dir) => readdirSync(dir).flatMap((f) => {
  const p = join(dir, f);
  return statSync(p).isDirectory() ? walk(p) : [p];
});
const files = {};
for (const p of walk(DIST)) {
  const rel = relative(DIST, p);
  if (rel === 'index.html' || rel === 'sw.js' || rel === 'manifest.webmanifest' || rel === '.nojekyll'
      || rel.startsWith('icons/') || rel.endsWith('.txt')) continue;
  files[rel] = p;
}
// The artifact host serves no .gz archives: ship the gzipped database as
// base64 text and point config.js at it (the app decodes "….b64.txt").
const dbKey = Object.keys(files).find((k) => k.startsWith('data/') && k.endsWith('.sqlite.gz'));
if (dbKey) {
  const b64 = readFileSync(files[dbKey]).toString('base64');
  const b64Name = `${dbKey}.b64.txt`;
  mkdirSync(join(OUT, 'data'), { recursive: true });
  writeFileSync(join(OUT, b64Name), b64);
  delete files[dbKey];
  files[b64Name] = join(OUT, b64Name);
  const config = readFileSync(files['js/config.js'], 'utf8')
    .replace(/DB_URL = '[^']*'/, `DB_URL = '${b64Name}'`)
    .replace(/DB_GZ_BYTES = \d+/, `DB_GZ_BYTES = ${b64.length}`);
  mkdirSync(join(OUT, 'js'), { recursive: true });
  writeFileSync(join(OUT, 'js', 'config.js'), config);
  files['js/config.js'] = join(OUT, 'js', 'config.js');
}
writeFileSync(join(OUT, 'files.json'), JSON.stringify(files, null, 1));
console.log(`artifact page ${join(OUT, 'index.html')} + ${Object.keys(files).length} files`);
