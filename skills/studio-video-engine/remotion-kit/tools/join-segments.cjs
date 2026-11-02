#!/usr/bin/env node
'use strict';
// Join silent closed-GOP segments into one film by STREAM COPY, with a proof (T-E42 ending segment / T-E45 P2 section 3.2).
//
//   node tools/join-segments.cjs --segments main.mp4,ending.mp4 [--audio mix.wav] --out film.mp4 [--overwrite]
//
// Every segment must have the `<segment>.render-record.json` render.cjs wrote (its sha256, its framemd5 list, its plan sha, its range).
// The join REFUSES (exit 1, no film) when: a segment changed after its render (sha256 or framemd5 differs from its record), the records
// belong to different plans or are not contiguous in the given order, the stream parameters differ, the joined film's framemd5 column is
// not exactly the concatenation of the segments' columns, pts is not continuous, the frame count differs, or the audio mix does not match
// the film length. The audio is ONE mix rendered once (`render.cjs --audio-only`), never cut at a join: 48000 / 30 = 1600 samples per
// frame, so a join at frame J is sample J * 1600 exactly. The joined film (and ending alone, re-rendered) is byte-reproducible.

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {framemd5, framemd5Checked, probeStream, run, sha256File, STREAM_FIELDS} = require('../lib/segments.cjs');
const {wavSeconds} = require('../lib/wavinfo.cjs');

const SAMPLE_RATE = 48000;
const readJson = (file) => JSON.parse(fs.readFileSync(file, 'utf8').replace(/^\uFEFF/u, ''));

// element-by-element comparison of the film's md5 column with the concatenated segment columns
function compareHashes(segmentColumns, filmColumn) {
  const flat = segmentColumns.flat();
  const n = Math.max(flat.length, filmColumn.length);
  for (let i = 0; i < n; i += 1) if (flat[i] !== filmColumn[i]) return {equal: false, compared: n, firstDifference: i};
  return {equal: true, compared: n, firstDifference: null};
}

function loadSegment(file, position, state, cache = false, fast = null) {
  const recordFile = `${file}.render-record.json`;
  if (!fs.existsSync(file)) throw new Error(`segment ${file} is missing`);
  if (!fs.existsSync(recordFile)) throw new Error(`segment ${file} has no render record (${recordFile}): it cannot be joined, nothing attests what it is`);
  const record = readJson(recordFile);
  const seg = record.segment;
  if (!seg || !Number.isInteger(seg.frames)) throw new Error(`render record ${recordFile} has no segment block (render with render.cjs --segment ID)`);
  if (((fast && fast.hashFile) || sha256File)(file) !== record.output_sha256) throw new Error(`segment ${seg.id} changed after its render: sha256 differs from its record ${recordFile}`);
  // fast (cache) mode: the file is attested by its sha256 (verified above, through the verified-hash cache) and the record carries the frame
  // hashes of exactly those bytes: they are NOT decoded again here. The joined film is decoded once below and its column must equal the
  // concatenation of the recorded columns, so a lying record is still caught (the proof is computed from the film, not from the records).
  const fresh = fast ? {md5s: record.framemd5 || [], digest: record.framemd5_digest} : framemd5(file);
  if (fresh.md5s.length !== seg.frames) throw new Error(`segment ${seg.id}: ${fresh.md5s.length} decoded frames, its record says ${seg.frames}`);
  const wrong = fresh.md5s.findIndex((m, i) => m !== (record.framemd5 || [])[i]);
  if (wrong >= 0 || fresh.md5s.length !== (record.framemd5 || []).length) throw new Error(`segment ${seg.id}: framemd5 differs from its record at frame ${wrong < 0 ? 'count' : wrong} (the file is not what was rendered)`);
  if (cache) {
    // cached segments (T-E45 P2) were rendered under earlier plans: a segment is identified by its node key (the cache), the plan sha and
    // plan total are not comparable. Contiguity, stream parameters and the total (expectedTotal) are still proven below.
  } else if (position === 0) {
    state.planSha = seg.plan_sha256;
    state.planTotal = seg.plan_total;
  } else if (seg.plan_sha256 !== state.planSha) {
    throw new Error(`segment ${seg.id}: plan_sha256 ${String(seg.plan_sha256).slice(0, 12)} differs from the first segment's ${String(state.planSha).slice(0, 12)} (segments of different plans)`);
  }
  if (seg.start !== state.frames) throw new Error(`segment ${seg.id} starts at f${seg.start} but the previous segments end at f${state.frames} (not contiguous in the given order)`);
  state.frames += seg.frames;
  return {file, record, seg, fresh, stream: fast && record.stream ? record.stream : probeStream(file), sha256: record.output_sha256};
}

function audioProof(audio, totalFrames, fps) {
  const spf = SAMPLE_RATE / fps;
  const probe = JSON.parse(run('ffprobe', ['-v', 'error', '-select_streams', 'a:0', '-show_entries', 'stream=sample_rate,channels', '-of', 'json', audio], `ffprobe ${audio}`).stdout).streams[0];
  if (!probe || Number(probe.sample_rate) !== SAMPLE_RATE) throw new Error(`audio mix ${audio}: sample rate must be ${SAMPLE_RATE} Hz (got ${probe && probe.sample_rate})`);
  const samples = Math.round(wavSeconds(audio) * SAMPLE_RATE);
  const expected = totalFrames * spf;
  if (Math.abs(samples - expected) > spf) throw new Error(`audio mix ${audio} has ${samples} samples, the film needs ${expected} (${totalFrames} frames x ${spf}): the mix must cover the film within one frame`);
  return {channels: Number(probe.channels), samples, expected, spf};
}

// cache = true: the segments come from the segment cache (rendered under earlier plans); expectedTotal = frames of the current plan
async function joinSegments({segments, audio, out, overwrite = false, fps = 30, cache = false, expectedTotal, fast = null}) {
  if (!Array.isArray(segments) || !segments.length) throw new Error('--segments needs at least one segment file');
  const outFile = path.resolve(out);
  if (fs.existsSync(outFile) && !overwrite) throw new Error(`output exists: ${outFile}; pass --overwrite`);
  const state = {frames: 0};
  const loaded = segments.map((f, i) => loadSegment(path.resolve(f), i, state, cache, fast));
  for (const field of STREAM_FIELDS) {
    const first = loaded[0].stream[field];
    const other = loaded.find((s) => s.stream[field] !== first);
    if (other) throw new Error(`segments differ in ${field}: ${loaded[0].seg.id}=${first} vs ${other.seg.id}=${other.stream[field]} (a stream-copy join needs identical stream parameters)`);
  }
  const total = state.frames;
  if (cache && expectedTotal !== undefined && expectedTotal !== total) throw new Error(`the cached segments cover ${total} frames but the current plan has ${expectedTotal}`);
  if (state.planTotal !== undefined && state.planTotal !== total) throw new Error(`the segments cover ${total} frames but the plan has ${state.planTotal}: a segment is missing`);
  const audioInfo = audio ? audioProof(path.resolve(audio), total, fps) : null;

  const work = fs.mkdtempSync(path.join(os.tmpdir(), 'kit-join-'));
  const partial = `${outFile}.partial.mp4`;
  try {
    const list = path.join(work, 'list.ffconcat');
    fs.writeFileSync(list, `${loaded.map((s) => `file '${s.file.replace(/\\/g, '/').replace(/'/g, "'\\''")}'`).join('\n')}\n`);
    fs.mkdirSync(path.dirname(outFile), {recursive: true});
    fs.rmSync(partial, {force: true});
    const args = ['-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', list];
    if (audio) args.push('-i', path.resolve(audio));
    args.push('-map', '0:v:0', ...(audio ? ['-map', '1:a:0'] : []), '-c:v', 'copy');
    if (audio) args.push('-c:a', 'aac', '-b:a', '192k', '-ar', String(SAMPLE_RATE));
    args.push('-map_metadata', '-1', '-fflags', '+bitexact', '-flags:v', '+bitexact', '-flags:a', '+bitexact', '-movflags', '+faststart', partial);
    run('ffmpeg', args, 'concat join');

    const tFilm = Date.now();
    const film = fast ? framemd5Checked(partial) : framemd5(partial);
    const hashes = compareHashes(loaded.map((s) => s.fresh.md5s), film.md5s);
    const step = film.rows.length ? film.rows[0].duration : 0;
    const continuous = film.rows.length === total && film.rows.every((r, i) => r.pts === film.rows[0].pts + i * step) && film.rows[0].pts === 0;
    let before = 0;
    const firstPtsOk = loaded.map((s) => {
      const ok = film.rows[before] !== undefined && film.rows[before].pts === before * step;
      before += s.seg.frames;
      return ok;
    });
    // fast mode: the film's one decode above is also the frame count and the decoder-clean check (same ffmpeg, same stderr rule)
    const probed = fast ? {nb_read_frames: film.rows.length} : probeStream(partial, {count: true});
    const decode = fast ? {status: film.status, stderr: film.stderr} : require('node:child_process').spawnSync('ffmpeg', ['-v', 'error', '-i', partial, '-f', 'null', '-'], {encoding: 'utf8'});
    const decodeClean = fast ? film.clean : decode.status === 0 && !(decode.stderr || '').trim();
    const filmDecodeSeconds = (Date.now() - tFilm) / 1000;
    const proof = {
      hashes_equal: hashes.equal, compared: hashes.compared, first_difference: hashes.firstDifference, pts_continuous: continuous, pts_step: step,
      segment_first_pts_ok: firstPtsOk, nb_read_frames: probed.nb_read_frames, frames_expected: total, decode_clean: decodeClean,
      ...(fast ? {single_decode: true, film_decode_seconds: filmDecodeSeconds, segments_decoded_again: 0} : {}),
    };
    const failures = [];
    // fast mode trusts the stream parameters recorded with each segment: the joined film must still show exactly those
    if (fast) {
      const filmStream = probeStream(partial);
      const off = STREAM_FIELDS.filter((k) => filmStream[k] !== loaded[0].stream[k]);
      if (off.length) failures.push(`the joined film's stream differs from the recorded segment stream in ${off.map((k) => `${k} (${filmStream[k]} vs ${loaded[0].stream[k]})`).join(', ')}`);
    }
    if (!hashes.equal) failures.push(`framemd5 column of the film differs from the concatenated segments at frame ${hashes.firstDifference}`);
    if (!continuous) failures.push('pts is not continuous 0..N-1');
    if (firstPtsOk.some((v) => !v)) failures.push('a segment does not start at the pts of the frames before it');
    if (probed.nb_read_frames !== total) failures.push(`nb_read_frames ${probed.nb_read_frames} != ${total}`);
    if (!decodeClean) failures.push(`decode of the film is not clean: ${(decode.stderr || '').trim().slice(0, 200)}`);

    let audioJoin = null;
    if (audio) {
      const raw = require('node:child_process').spawnSync('ffmpeg', ['-v', 'error', '-i', partial, '-map', '0:a:0', '-f', 's16le', '-ar', String(SAMPLE_RATE), '-ac', String(audioInfo.channels), '-'], {maxBuffer: 1 << 30});
      const filmSamples = raw.status === 0 ? raw.stdout.length / (2 * audioInfo.channels) : -1;
      const slack = Math.abs(filmSamples - audioInfo.samples);
      audioJoin = {
        policy: 'single timeline mix, not cut at the join', samples_per_frame: audioInfo.spf, sample_rate: SAMPLE_RATE, mix_samples: audioInfo.samples, film_decoded_samples: filmSamples,
        mix_sha256: sha256File(path.resolve(audio)), pcm_of_film_vs_mix_slack_samples: slack, codec: 'aac 192k 48000 (encoded once, after the join)',
        joins: loaded.slice(1).map((s) => ({join_frame: s.seg.start, join_sample: s.seg.start * audioInfo.spf})),
        join_frame: loaded.length > 1 ? loaded[1].seg.start : null, join_sample: loaded.length > 1 ? loaded[1].seg.start * audioInfo.spf : null,
      };
      if (!(slack <= audioInfo.spf)) failures.push(`the film's audio is ${filmSamples} samples, the mix ${audioInfo.samples} (slack ${slack} > ${audioInfo.spf})`);
    }
    const base = {
      schema: 'jjk-remotion-kit/join-record/v1', plan_sha256: state.planSha === undefined ? null : state.planSha, from_cache: cache,
      segments: loaded.map((s) => ({id: s.seg.id, file: s.file, sha256: s.sha256, start: s.seg.start, frames: s.seg.frames, framemd5_digest: s.fresh.digest, uses_shot_video: s.seg.uses_shot_video, render_record: `${s.file}.render-record.json`})),
      joins: loaded.slice(1).map((s) => ({between: [loaded[loaded.indexOf(s) - 1].seg.id, s.seg.id], join_frame: s.seg.start})),
      stream: loaded[0].stream, method: 'ffmpeg concat demuxer, video stream copy (no re-encode)',
    };
    if (failures.length) {
      fs.writeFileSync(`${outFile}.join-refused.json`, `${JSON.stringify({...base, ok: false, proof, failures}, null, 2)}\n`);
      throw new Error(`join refused: ${failures.join('; ')}`);
    }
    fs.renameSync(partial, outFile);
    const record = {
      ...base, ok: true, film: {path: outFile, sha256: sha256File(outFile), frames: total, framemd5_digest: film.digest}, proof, audio_join: audioJoin,
    };
    fs.writeFileSync(`${outFile}.join-record.json`, `${JSON.stringify(record, null, 2)}\n`);
    return record;
  } finally {
    fs.rmSync(work, {recursive: true, force: true});
    fs.rmSync(partial, {force: true});
  }
}

module.exports = {joinSegments, compareHashes};

if (require.main === module) {
  const args = process.argv.slice(2);
  const opt = (name) => { const i = args.indexOf(name); return i >= 0 ? args[i + 1] : undefined; };
  const segs = opt('--segments');
  if (!segs || !opt('--out')) {
    process.stderr.write('usage: join-segments.cjs --segments a.mp4,b.mp4 [--audio mix.wav] --out film.mp4 [--overwrite] [--fps 30]\n');
    process.exitCode = 2;
  } else {
    joinSegments({segments: segs.split(','), audio: opt('--audio'), out: opt('--out'), overwrite: args.includes('--overwrite'), fps: Number(opt('--fps') || 30)})
      .then((r) => process.stdout.write(`joined ${r.film.path}: ${r.film.frames} frames, H_film == H_seg over ${r.proof.compared} frames, sha256 ${r.film.sha256}\n`))
      .catch((e) => { process.stderr.write(`${e.message}\n`); process.exitCode = 1; });
  }
}
