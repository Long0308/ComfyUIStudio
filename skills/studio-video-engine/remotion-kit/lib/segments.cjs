'use strict';
// Segment plan of a film (T-E42 ending segment, foundation of T-E45 P2). Pure Node: the compositor functions it needs are INJECTED
// (render.cjs imports the ESM modules and passes them), so this file has no Remotion / React dependency and is unit-testable.
//
// A plan is a list of segments [{id, kind, start, end_exclusive, frames}] that covers [0, total) exactly. Every segment is rendered as
// SILENT closed-GOP video and joined by stream copy (tools/join-segments.cjs); the audio is one mix, never cut at a join.
//
// Default cut (decision, see SKILL-SECTION-T-E42-kit-ending.md): a config with an iris ending is cut into `main` and `ending` at the
// first frame after which NO shot video is mounted. The MAIN segment owns the iris (an iris is a mask over the last shot's picture, so
// it depends on shot video); the ending (logo disc, hold, vocab cards, plate, EndLogo) is vector + fonts + logo only.

const crypto = require('node:crypto');
const fs = require('node:fs');
const {spawnSync} = require('node:child_process');

const SCHEMA = 'jjk-remotion-kit/segments/v1';
const SAMPLES_PER_SECOND = 48000;

const sha256Text = (text) => crypto.createHash('sha256').update(text).digest('hex');

// Every frame in [from, to] on which the compositor mounts a shot video (a shot picture that is drawn, or an outgoing tail that is on
// screen), and WHICH shots / tails those are. The same pure functions the renderer and the per-frame audit use, so "needs video" can
// never drift from "draws video".
function videoUsage(config, deps, from, to) {
  const idx = deps.transitionIndex(config);
  const tails = config.transitions.map((t) => ({t, w: deps.tailWindow(t)})).filter((x) => x.w);
  const frames = [];
  const shots = new Set();
  const tailIds = new Set();
  for (let f = from; f <= to; f += 1) {
    let needs = false;
    const shot = config.shots.find((s) => f >= s.start && f < s.start + s.frames);
    if (shot) {
      const mode = deps.pictureMode({shot, frame: f - shot.start, inT: idx.incoming(shot), outT: idx.outgoing(shot), ending: config.ending || {}, motion: deps.motion});
      if (!['hidden', 'backdrop'].includes(mode.kind)) {
        needs = true;
        shots.add(shot.id);
      }
    }
    for (const {t, w} of tails) {
      if (f >= w.from && f < w.from + w.frames && deps.tailVisibleAt(t, f)) {
        needs = true;
        tailIds.add(t.id);
      }
    }
    if (needs) frames.push(f);
  }
  return {frames, shots, tails: tailIds};
}

const videoFrames = (config, deps, from, to) => videoUsage(config, deps, from, to).frames;

const total = (config) => config.timeline.mainFrames + config.timeline.endCardFrames;

// transitions a cut must never fall inside: the iris window, and every window that mounts both pictures or a dip schedule
function effectWindows(config, deps) {
  const rows = [];
  for (const t of config.transitions) {
    if (!(t.frames > 0)) continue;
    const kind = deps.rendersAs(t);
    const showsBoth = deps.showsBoth ? deps.showsBoth(t) : t.shows_both === true;
    const both = showsBoth && !['card_slide', 'plate_in', 'none', 'cut'].includes(kind);
    if (kind === 'iris' || kind === 'dip_white' || both) {
      const from = Math.min(t.start === undefined ? t.boundary : t.start, t.boundary);
      let to = Math.max(t.start === undefined ? t.boundary : t.start + t.frames, t.boundary + 1);
      // the iris effect is the picture mask over the last shot; once the logo disc is opaque (discIn + 3) the rest is vector content
      if (kind === 'iris' && config.ending && Number.isInteger(config.ending.discIn)) to = Math.min(to, config.ending.discIn + 3);
      rows.push({id: t.id, from, to});
    }
  }
  return rows;
}

function validateDeclared(config, deps, declared, n) {
  if (!Array.isArray(declared) || !declared.length) throw new Error('config.segments must be a non-empty array');
  const ids = new Set();
  let at = 0;
  declared.forEach((s, i) => {
    if (typeof s.id !== 'string' || !s.id) throw new Error(`segments[${i}].id must be a non-empty string`);
    if (ids.has(s.id)) throw new Error(`duplicate segment id ${s.id}`);
    ids.add(s.id);
    if (!Number.isInteger(s.start) || !Number.isInteger(s.end_exclusive)) throw new Error(`segment ${s.id}: start and end_exclusive must be integers`);
    if (i === 0 && s.start !== 0) throw new Error(`segments must start at 0 (the first starts at f${s.start})`);
    if (s.start > at) throw new Error(`gap before segment ${s.id}: f${at}..f${s.start - 1} belongs to no segment`);
    if (s.start < at) throw new Error(`overlap: segment ${s.id} starts at f${s.start} but the previous one runs to f${at - 1}`);
    if (s.end_exclusive - s.start < 1) throw new Error(`segment ${s.id}: frames must be >= 1`);
    at = s.end_exclusive;
  });
  if (at !== n) throw new Error(`segments do not end at the end of the film (f${at} != ${n})`);
  const windows = effectWindows(config, deps);
  for (const s of declared.slice(1)) {
    for (const w of windows) {
      if (s.start > w.from && s.start < w.to) {
        throw new Error(`cut at f${s.start} (start of ${s.id}) falls inside the effect window of ${w.id} (f${w.from}..f${w.to - 1}): one effect must belong to one segment`);
      }
    }
  }
}

/**
 * @param {object} config kit config
 * @param {{pictureMode:Function, transitionIndex:Function, tailWindow:Function, tailVisibleAt:Function, motion:object, rendersAs:Function}} deps
 * @returns {{schema:string, total:number, source:'config'|'ending'|'single', segments:Array<{id,kind,start,end_exclusive,frames}>, sha256:string}}
 */
function planSegments(config, deps) {
  const n = total(config);
  let source;
  let list;
  if (config.segments !== undefined) {
    validateDeclared(config, deps, config.segments, n);
    source = 'config';
    list = config.segments.map((s) => ({id: s.id, kind: s.kind || 'main', start: s.start, end_exclusive: s.end_exclusive}));
  } else if (config.ending && Number.isInteger(config.ending.irisStart) && config.timeline.endCardFrames > 0) {
    const need = videoFrames(config, deps, config.ending.irisStart, n - 1);
    const cut = need.length ? need[need.length - 1] + 1 : config.ending.irisStart;
    if (cut >= n) throw new Error(`the ending has no shot-video-free frames (the last shot video frame is f${cut - 1} of ${n})`);
    source = 'ending';
    list = [{id: 'main', kind: 'main', start: 0, end_exclusive: cut}, {id: 'ending', kind: 'ending', start: cut, end_exclusive: n}];
  } else {
    source = 'single';
    list = [{id: 'main', kind: 'main', start: 0, end_exclusive: n}];
  }
  const segments = list.map((s) => ({...s, frames: s.end_exclusive - s.start}));
  return {schema: SCHEMA, total: n, source, segments, sha256: sha256Text(JSON.stringify(segments.map((s) => [s.id, s.kind, s.start, s.end_exclusive])))};
}

function segmentRecord(plan, id, used) {
  const s = plan.segments.find((x) => x.id === id);
  if (!s) throw new Error(`unknown segment ${id} (the plan has: ${plan.segments.map((x) => x.id).join(', ')})`);
  return {
    id: s.id, kind: s.kind, start: s.start, end_exclusive: s.end_exclusive, frames: s.frames, plan_sha256: plan.sha256, plan_source: plan.source,
    uses_shot_video: (used || []).some((u) => u.role === 'picture' || u.role === 'tail'),
  };
}

// ONE codec parameter set for every segment of a film (the join refuses segments whose stream parameters differ). Closed GOP: a keyframe
// on the first frame of every segment and no frame referencing across the segment end. MEASURED (Remotion 4.0.536, ffmpeg libx264 medium): the
// default encode already joins framemd5-identical (libx264 is closed-GOP unless open-gop=1, B-frames stay inside the file); open-gop=0 is
// stated explicitly so the property does not depend on a default. `ffmpegArgs` go in front of the output of Remotion's 'pre-stitcher'
// (the libx264 encode; the 'stitcher' step only stream-copies it).
function codecParams({mode}) {
  return {
    codec: 'h264', pixelFormat: 'yuv420p', crf: mode === 'master' ? 16 : 18, colorSpace: 'bt709', muted: true, x264Preset: 'medium',
    x264: 'open-gop=0', ffmpegArgs: ['-x264-params', 'open-gop=0'],
  };
}

// Remotion's ffmpegOverride for a segment encode: the closed-GOP arguments go in front of the output file (the last argument). KIT_FFMPEG_LOG
// (a file path) appends the final argument list for audit.
function ffmpegOverride(codec) {
  return ({type, args}) => {
    if (process.env.KIT_FFMPEG_LOG) require('node:fs').appendFileSync(process.env.KIT_FFMPEG_LOG, `${type}: ${JSON.stringify(args)}
`);
    if (type !== 'pre-stitcher' || !codec.ffmpegArgs.length) return args;
    return [...args.slice(0, -1), ...codec.ffmpegArgs, args[args.length - 1]];
  };
}

// streaming (a 4K core is larger than a Buffer may be)
const sha256File = (file) => require('./hashcache.cjs').sha256Stream(file);

function run(cmd, args, what) {
  const r = spawnSync(cmd, args, {encoding: 'utf8', maxBuffer: 1 << 28});
  if (r.error) throw new Error(`${what}: ${cmd} is not available (${r.error.message})`);
  if (r.status !== 0) throw new Error(`${what} failed (exit ${r.status}): ${(r.stderr || '').trim().split('\n').slice(-3).join(' | ')}`);
  return r;
}

// framemd5 of the first video stream: md5 of every decoded frame (column 6), plus pts / duration for continuity checks. A segment's pts
// restarts at 0, so rows are never compared whole; only the md5 column is (T-E45 3.2).
function framemd5(file) {
  const r = run('ffmpeg', ['-v', 'error', '-i', file, '-map', '0:v:0', '-f', 'framemd5', '-'], `framemd5 ${file}`);
  const rows = r.stdout.split(/\r?\n/).filter((l) => l && !l.startsWith('#')).map((l) => {
    const c = l.split(',').map((x) => x.trim());
    return {dts: Number(c[1]), pts: Number(c[2]), duration: Number(c[3]), size: Number(c[4]), md5: c[5]};
  });
  const md5s = rows.map((x) => x.md5);
  return {rows, md5s, digest: sha256Text(md5s.join('\n'))};
}

// ONE decode that yields the frame hashes, the decoded frame count and whether the decoder complained (stderr empty = clean): the film
// proof needs all three, and each used to be its own full decode (framemd5, -count_frames, -f null)
function framemd5Checked(file) {
  const r = spawnSync('ffmpeg', ['-v', 'error', '-i', file, '-map', '0:v:0', '-f', 'framemd5', '-'], {encoding: 'utf8', maxBuffer: 1 << 28});
  if (r.error) throw new Error(`framemd5 ${file}: ffmpeg is not available (${r.error.message})`);
  const rows = r.stdout.split(/\r?\n/).filter((l) => l && !l.startsWith('#')).map((l) => {
    const c = l.split(',').map((x) => x.trim());
    return {dts: Number(c[1]), pts: Number(c[2]), duration: Number(c[3]), size: Number(c[4]), md5: c[5]};
  });
  const md5s = rows.map((x) => x.md5);
  const stderr = (r.stderr || '').trim();
  return {rows, md5s, digest: sha256Text(md5s.join('\n')), clean: r.status === 0 && !stderr, stderr, status: r.status};
}

const STREAM_FIELDS = ['width', 'height', 'r_frame_rate', 'avg_frame_rate', 'pix_fmt', 'codec_name', 'profile', 'level', 'time_base', 'color_space', 'color_transfer', 'color_primaries', 'color_range', 'field_order'];

// stream parameters that must be identical across the segments of one film (what makes a stream-copy join legal)
function probeStream(file, {count = false} = {}) {
  const args = ['-v', 'error', '-select_streams', 'v:0', ...(count ? ['-count_frames'] : []), '-show_entries', `stream=${STREAM_FIELDS.join(',')}${count ? ',nb_read_frames' : ''}`, '-of', 'json', file];
  const stream = (JSON.parse(run('ffprobe', args, `ffprobe ${file}`).stdout).streams || [])[0];
  if (!stream) throw new Error(`${file} has no video stream`);
  const fields = Object.fromEntries(STREAM_FIELDS.map((k) => [k, stream[k] === undefined ? null : stream[k]]));
  return count ? {...fields, nb_read_frames: Number(stream.nb_read_frames)} : fields;
}

module.exports = {SCHEMA, SAMPLES_PER_SECOND, STREAM_FIELDS, framemd5Checked, planSegments, effectWindows, videoFrames, videoUsage, segmentRecord, codecParams, ffmpegOverride, sha256Text, sha256File, framemd5, probeStream, run};
