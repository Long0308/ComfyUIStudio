// The kit must carry NO episode numbers or names: shot table, end frames, bubble centre, special-case shot ids, totals.
// Scans every kit file except episodes/ (adapters + parity live there), tests/ and any node_modules / scratch outputs.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const KIT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const SKIP_DIRS = new Set(['episodes', 'tests', 'node_modules', '.git']);
const EXTS = new Set(['.js', '.mjs', '.cjs', '.jsx', '.json', '.md']);

// whole-number literals that belong to the ep04 review/master clock, plus its names
const PATTERNS = [
  ['ep04 frame literal', /(?<![\w.])(2520|2580|2160|2116|2140|2142|2152|2159|2166|2445|2515(?:\.3)?|2516|2490|2490)(?![\w])/],
  ['iris centre 940,570', /940\s*,\s*570/],
  ['bubble centre 1000,620', /1000\s*,\s*620/],
  ['disc slide x / pill edge', /(discSlideX|pillLeftX)\s*[:=]\s*\d+/],
  ['dip / shot boundary frames', /(?<!\d)(1010|1310|1610)(?!\d)/],
  ['transition id literal', /\bT\d{3,4}\b/],
  ['special-case shot id', /\bS0\d_[AB]\d?\b/],
  ['episode text', /\b(Milk|Mom|Creamy|Alice|Ice Cream|Dairy Cow)\b/],
  ['episode / build names', /\bep0\d\b|-v00\d/i],
  ['episode id', /04-milk-and-mom|milk-mom|MilkMom/i],
];

function* files(dir) {
  for (const entry of fs.readdirSync(dir, {withFileTypes: true})) {
    if (entry.isDirectory()) {
      if (!SKIP_DIRS.has(entry.name)) yield* files(path.join(dir, entry.name));
    } else if (EXTS.has(path.extname(entry.name))) {
      yield path.join(dir, entry.name);
    }
  }
}

test('no ep04 literals anywhere in the kit (src, lib, render.cjs, README)', () => {
  const hits = [];
  let scanned = 0;
  for (const file of files(KIT)) {
    scanned += 1;
    const lines = fs.readFileSync(file, 'utf8').split(/\r?\n/);
    lines.forEach((origLine, i) => {
      // the README may POINT at the adapter files (`episodes/ep04/...`); those paths are not episode data in the kit
      const line = origLine.replace(/episodes\/ep0\d\/[\w.-]*/g, '');
      for (const [what, re] of PATTERNS) {
        // the section texts for SKILL.md describe the first episode's rule-report findings by transition id; only they may name those
        if (/^SKILL-SECTION-/.test(path.basename(file)) && ['dip / shot boundary frames', 'transition id literal'].includes(what)) continue;
        if (re.test(line)) hits.push(`${path.relative(KIT, file)}:${i + 1} [${what}] ${line.trim().slice(0, 100)}`);
      }
    });
  }
  assert.ok(scanned >= 12, `scan looks too small (${scanned} files)`);
  assert.deepEqual(hits, [], `episode literals found in the kit:\n${hits.join('\n')}`);
  console.log(`# scanned ${scanned} kit files, 0 ep04 literals`);
});

test('the grep itself works: every pattern fires on a sample that contains the literal', () => {
  const samples = ['x = 2520;', 'c = [940, 570]', 'c = [1000,620]', 'discSlideX: 520', 'id === "S06_B"', 'Milk and Mom', 'Say hi Mom!', 'MilkMom-ReviewHD', 'ep04', 'review-v008', 'Ice Cream', 'irisStart: 2116', 'f1010', 'T1310'];
  for (const s of samples) assert.ok(PATTERNS.some(([, re]) => re.test(s)), `no pattern matches ${s}`);
});
