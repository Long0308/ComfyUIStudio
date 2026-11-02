// Helpers of the render smoke test (solid-colour synthetic episode, minimal PNG reader), shared with ad-hoc visual checks.
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import zlib from 'node:zlib';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {presetRow} from './preset-fixture.mjs';

export const KIT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
export const WORKSPACE = path.resolve(KIT, '../../../..');
export const BROWSER = process.env.REMOTION_BROWSER
  || path.join(WORKSPACE, '.remotion', 'chrome-headless-shell', 'win64', 'chrome-headless-shell-win64', 'chrome-headless-shell.exe');
export const PACKAGES = process.env.REMOTION_PACKAGES || path.join(WORKSPACE, 'jenniejoy-zoo-film', 'node_modules');
export const FONTS = [path.join(process.env.WINDIR || 'C:/Windows', 'Fonts', 'trebuc.ttf'), path.join(WORKSPACE, 'jenniejoy-zoo-film', 'hyperframes', 'vendor', 'trebucbd.ttf')];

export const COLOURS = {red: [200, 30, 30], green: [30, 160, 60], blue: [30, 60, 200], magenta: [180, 30, 180], paper: [255, 249, 237]};
const sha = (file) => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const ffmpeg = (args) => spawnSync('ffmpeg', ['-v', 'error', '-y', ...args], {encoding: 'utf8'});

// minimal 8-bit RGB / RGBA PNG decoder (non-interlaced): enough to read the pixels of a still
export function decodePng(file) {
  const buf = fs.readFileSync(file);
  let pos = 8;
  let header = null;
  const idat = [];
  while (pos < buf.length) {
    const len = buf.readUInt32BE(pos);
    const type = buf.toString('ascii', pos + 4, pos + 8);
    const data = buf.subarray(pos + 8, pos + 8 + len);
    if (type === 'IHDR') header = {w: data.readUInt32BE(0), h: data.readUInt32BE(4), depth: data[8], colour: data[9], interlace: data[12]};
    if (type === 'IDAT') idat.push(data);
    pos += 12 + len;
  }
  assert.ok(header && header.depth === 8 && [2, 6].includes(header.colour) && header.interlace === 0, `unsupported PNG ${JSON.stringify(header)}`);
  const bpp = header.colour === 6 ? 4 : 3;
  const raw = zlib.inflateSync(Buffer.concat(idat));
  const stride = header.w * bpp;
  const px = Buffer.alloc(stride * header.h);
  for (let y = 0; y < header.h; y += 1) {
    const filter = raw[y * (stride + 1)];
    for (let x = 0; x < stride; x += 1) {
      const cur = raw[y * (stride + 1) + 1 + x];
      const left = x >= bpp ? px[y * stride + x - bpp] : 0;
      const up = y > 0 ? px[(y - 1) * stride + x] : 0;
      const upLeft = y > 0 && x >= bpp ? px[(y - 1) * stride + x - bpp] : 0;
      let add = 0;
      if (filter === 1) add = left;
      else if (filter === 2) add = up;
      else if (filter === 3) add = (left + up) >> 1;
      else if (filter === 4) {
        const p = left + up - upLeft;
        const [pa, pb, pc] = [Math.abs(p - left), Math.abs(p - up), Math.abs(p - upLeft)];
        add = pa <= pb && pa <= pc ? left : pb <= pc ? up : upLeft;
      }
      px[y * stride + x] = (cur + add) & 255;
    }
  }
  return {w: header.w, h: header.h, at: (x, y) => [px[y * stride + x * bpp], px[y * stride + x * bpp + 1], px[y * stride + x * bpp + 2]]};
}
export const nearest = (rgb) => {
  const [name, dist] = Object.entries(COLOURS).map(([n, c]) => [n, Math.hypot(rgb[0] - c[0], rgb[1] - c[1], rgb[2] - c[2])]).sort((a, b) => a[1] - b[1])[0];
  return dist < 90 ? name : 'other';
};
// colours found along a row (every 24 px) of a still
export const rowColours = (png, y) => {
  const set = new Set();
  for (let x = 12; x < png.w; x += 24) set.add(nearest(png.at(x, y)));
  return set;
};

export function build(dir) {
  const files = {};
  const clip = (name, colour, frames) => {
    const f = path.join(dir, `${name}.mp4`);
    const r = ffmpeg(['-f', 'lavfi', '-i', `color=c=${colour}:s=480x270:r=30`, '-frames:v', String(frames), '-pix_fmt', 'yuv420p', f]);
    assert.equal(r.status, 0, r.stderr);
    files[name] = f;
  };
  const colours = {S1: 'red', S2: 'green', S3: 'blue', S4: 'magenta'};
  for (const [id, c] of Object.entries(colours)) {
    clip(id, COLOURS[c].map((v) => v.toString(16).padStart(2, '0')).join('').replace(/^/, '0x'), 70);
    clip(`${id}tail`, COLOURS[c].map((v) => v.toString(16).padStart(2, '0')).join('').replace(/^/, '0x'), 40);
  }
  const wav = path.join(dir, 'silence.wav');
  assert.equal(ffmpeg(['-f', 'lavfi', '-i', 'anullsrc=r=16000:cl=mono', '-t', '3', wav]).status, 0);
  const png = path.join(dir, 'tile.png');
  assert.equal(ffmpeg(['-f', 'lavfi', '-i', 'color=c=0x808080:s=64x64', '-frames:v', '1', png]).status, 0);
  return {files, wav, png};
}

// one catalog-correct row of preset `name` between two of the four solid-colour shots (a tail file of the outgoing shot's colour is bound)
export function smokeRow(id, name, from, to, boundary, over = {}) {
  const row = presetRow(name, {...over, boundary, row: {id, from, to}});
  if (row.tail) row.tail = {...row.tail, fileFrames: 40};
  return row;
}
export const DEFAULT_ROWS = [smokeRow('A', 'cut_push', 'S1', 'S2', 60), smokeRow('B', 'push_slide', 'S2', 'S3', 120), smokeRow('C', 'card_flip_3d', 'S3', 'S4', 180)];

export function config({files, wav, png}, rows = DEFAULT_ROWS) {
  const bind = (file) => ({path: file, sha256: sha(file)});
  const words = (start) => [{w: 'Hi', startF: start + 4, endF: start + 10, keyword: false}, {w: 'moon', startF: start + 14, endF: start + 24, keyword: true}];
  const shot = (id, start) => ({id, start, frames: 60, speechEndS: 1.5, vi: 'xin chao', captionLines: 1, words: words(start), segments: [{id, from: 0, frames: 60}]});
  return {
    schema: 'jjk-remotion-kit/config/v1', id: 'smoke-synthetic', fps: 30,
    timeline: {introFrames: 0, mainFrames: 330, endCardFrames: 0, outroStart: 240, outroFrames: 90},
    review: {label: 'SMOKE'}, strings: {cardsHeader: 'Say it', cardsHeaderClosing: 'Bye'}, ending: {},
    shots: [shot('S1', 0), shot('S2', 60), shot('S3', 120), shot('S4', 180)],
    transitions: rows,
    icons: [], cards: [],
    bindings: {
      logo: bind(png), music: bind(wav), fonts: {regular: FONTS[0], bold: FONTS[1]},
      shots: Object.fromEntries(['S1', 'S2', 'S3', 'S4'].map((id) => [id, {audio: bind(wav), segments: {[id]: bind(files[id])}}])),
      tails: Object.fromEntries(rows.filter((r) => r.tail).map((r) => [r.id, bind(files[`${r.from}tail`])])), icons: {}, cards: [],
    },
  };
}

