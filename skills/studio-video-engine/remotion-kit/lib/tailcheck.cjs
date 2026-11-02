'use strict';
// Tail file check: a transition that plays the outgoing clip's native tail must find those frames IN the bound file.
// `startFrom` and the window length N are delivery frames (config fps); the file runs at its own native rate (ffprobe).
// Rule: EXACTLY the engine's check_tail (engine/editorial/transitions.py), for any native / delivery fps pair:
//   available = frames - editorialFrames            (native frames of the bound file after what the editorial cut uses)
//   need      = ceil(4 N / 5)                       (the engine's fixed ceil(0.8 N); it does not depend on the fps pair)
//   last      = ceil((startFrom + N - 1) * nativeFps / fps)
//   refuse if available < need or last > frames - 1.
// `editorialFrames` is a required input per tail (config tail.editorialFrames). A shared-fixture test runs the real engine
// and this function on the same wide grid (nine fps pairs, independent editorial / delivery values, 33,120 cases) and asserts
// zero disagreements; a second grid does the same for a dip_white row.

const {execFileSync} = require('node:child_process');

function parseRate(text) {
  const [n, d] = String(text).split('/').map(Number);
  if (!Number.isFinite(n) || !(n > 0)) throw new Error(`unreadable frame rate '${text}'`);
  return d ? n / d : n;
}

// frames = number of video frames (packet count, no decode), nativeFps = r_frame_rate
function probeClip(file) {
  let out;
  try {
    out = execFileSync('ffprobe', ['-v', 'error', '-count_packets', '-select_streams', 'v:0', '-show_entries', 'stream=nb_read_packets,r_frame_rate', '-of', 'json', file], {encoding: 'utf8'});
  } catch (error) {
    throw new Error(`ffprobe failed for ${file}: ${error.message.split('\n')[0]}`);
  }
  const stream = JSON.parse(out).streams[0];
  if (!stream) throw new Error(`no video stream in ${file}`);
  return {frames: Number(stream.nb_read_packets), nativeFps: parseRate(stream.r_frame_rate)};
}

// ceil of an exact rational computed in floating point: remove the representation noise first (5 * 0.8 = 4.000000000000001)
const ceilEps = (x) => Math.ceil(x - 1e-9);

function tailFits({frames, nativeFps, fps, startFrom, n, editorialFrames}) {
  const need = Math.floor((4 * n + 4) / 5); // ceil(4n/5), integer arithmetic
  const lastIndex = ceilEps(((startFrom + n - 1) * nativeFps) / fps);
  const available = frames - editorialFrames;
  const problems = [];
  if (lastIndex > frames - 1) problems.push(`last tail frame index ${lastIndex} is beyond the file (${frames} frames)`);
  if (available < need) problems.push(`only ${available} native frames after the ${editorialFrames} the editorial cut uses, need ${need}`);
  return {ok: problems.length === 0, firstIndex: editorialFrames, lastIndex, needed: need, available, problems};
}

function checkTailFile(file, {fps, startFrom, n, editorialFrames, fileFrames, label, probe: probeFn = probeClip}) {
  const probe = probeFn(file);
  // the bound file must be exactly the file the config describes (a full native clip where a 7-frame tail core is expected is refused)
  if (fileFrames !== undefined && probe.frames !== fileFrames) throw new Error(`tail ${label}: the bound file has ${probe.frames} frames, the config describes ${fileFrames} (${file})`);
  const r = tailFits({...probe, fps, startFrom, n, editorialFrames});
  if (!r.ok) throw new Error(`tail ${label}: ${r.problems.join('; ')} (file ${file}, ${probe.frames} frames @${probe.nativeFps} fps, startFrom ${startFrom}, editorialFrames ${editorialFrames}, ${n} output frames)`);
  return {...r, frames: probe.frames, nativeFps: probe.nativeFps};
}

// A picture segment clip must hold the native frames its delivery window plays: ceil(frames * ratio). strict = false reports
// instead of throwing (preview-only sources such as slates).
function checkSegmentFile(file, {fps, frames, label, strict = true, probe: probeFn = probeClip}) {
  const probe = probeFn(file);
  const needed = ceilEps(frames * (probe.nativeFps / fps));
  const ok = probe.frames >= needed;
  const result = {ok, frames: probe.frames, nativeFps: probe.nativeFps, needed};
  if (!ok && strict) throw new Error(`segment ${label}: file has ${probe.frames} native frames, its ${frames} delivery frames need ${needed} (${file})`);
  return result;
}

module.exports = {probeClip, tailFits, checkTailFile, checkSegmentFile, ceilEps};
