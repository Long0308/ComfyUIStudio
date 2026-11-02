// Kit config + sources validation. Pure ESM (no React): the Film composition calls it at mount, render.cjs calls it
// before bundling, and the node tests call it directly. All checks are structural or arithmetic on the config itself;
// no episode number appears here.
import {DEFAULT_MOTION, LEGACY_DIP, PRESETS, APPROVED_DIP, directionMessage, framesMessage, paramsMessages, presetName, presetOf, resolveMotion, resolveParams, resolvePresetName, scheduleOf, unknownKeys, windowOf} from './presets.mjs';
import {TRANSITION_TYPES, TYPE_TABLE, auditPictureLayers, dipSpan, edgeIds, tailWindow, whipCoverage, whipSteps} from './picture-mode.mjs';
import {DESCRIPTOR_KINDS, auditPreset} from './catalog-render.mjs';

export {TRANSITION_TYPES, TYPE_TABLE};

export const SCHEMA = 'jjk-remotion-kit/config/v1';
const DIP_SHOTS = ['out', 'out_tail', 'in', 'none'];
const ENDING_REQUIRED_IRIS = ['irisStart', 'irisClosed', 'irisCentre', 'discIn', 'discSlideStart', 'discSlideEnd', 'discSlideX', 'discFadeStart'];
const ENDING_REQUIRED_PLATE = ['plateStart', 'speechEndFrame', 'plateEn', 'plateVi'];

const isInt = (v) => Number.isInteger(v);
const isStr = (v) => typeof v === 'string' && v.length > 0;

// Rules that a historical config may waive EXPLICITLY (config.waivers = [{rule, transition, reason}]); a waiver is never
// silent: it is listed by collectWaived() and printed / recorded by render.cjs. Only these rules are waivable.
// The first SPOKEN frame of a shot. Caption timing can start on the unvoiced pre-roll of the WAV; word-timing onset evidence
// (shot.speechOnsetF, the first sustained / voiced onset) wins when the config carries it, otherwise the caption start is used and the
// basis says so ("caption-based") in every message and in the rule report.
export function firstSpoken(shot) {
  if (Number.isInteger(shot.speechOnsetF)) return {frame: shot.speechOnsetF, basis: `onset evidence (${shot.onsetEvidence || 'word-timing onset'})`};
  return {frame: Math.min(...shot.words.map((w) => w.startF)), basis: 'caption start (caption-based)'};
}

export const WAIVABLE_RULES = ['dip_peak_before_first_word', 'dip_sparkle_before_first_word'];
const SHA256_HEX = /^[0-9a-f]{64}$/;
// a REAL calendar date (2026-02-30 is not one); a time part after the date is allowed
function isRealDate(text) {
  const m = /^(\d{4})-(\d{2})-(\d{2})(?:[T ].*)?$/.exec(String(text || ''));
  if (!m) return false;
  const [y, mo, d] = [Number(m[1]), Number(m[2]), Number(m[3])];
  const date = new Date(Date.UTC(y, mo - 1, d));
  return date.getUTCFullYear() === y && date.getUTCMonth() === mo - 1 && date.getUTCDate() === d;
}

function analyse(config) {
  const issues = [];
  const waived = [];
  const waivers = Array.isArray(config && config.waivers) ? config.waivers : [];
  const usedWaivers = new Set();
  // an APPROVED waiver names who approved it and when; a reproduction-only waiver (parity runs) states that it is NOT an approval and
  // may only be used by a render run with --reproduction-only DIR (render.cjs)
  const goodWaiver = (x) => isStr(x.reason) && SHA256_HEX.test(String(x.review_render_sha256 || ''))
    && (x.reproduction_only === true ? x.approved_by === undefined && x.approved_at === undefined : isStr(x.approved_by) && isRealDate(x.approved_at));
  const bad = (msg, key) => {
    const w = key && waivers.find((x) => x.rule === key.rule && x.transition === key.transition && goodWaiver(x));
    if (w) {
      usedWaivers.add(w);
      waived.push({rule: key.rule, transition: key.transition, reason: w.reason, approved_by: w.approved_by, approved_at: w.approved_at,
        reproduction_only: w.reproduction_only === true, review_render_sha256: w.review_render_sha256, message: msg});
    } else issues.push(msg);
  };
  if (!config || typeof config !== 'object') return {issues: ['config is not an object'], waived};
  for (const w of waivers) {
    if (!WAIVABLE_RULES.includes(w.rule) || !isStr(w.transition)) bad(`waiver ${JSON.stringify(w)} names no waivable rule / transition (waivable: ${WAIVABLE_RULES.join(', ')})`);
    else if (!goodWaiver(w)) bad(`waiver for rule ${w.rule} on ${w.transition} needs reason, review_render_sha256 (64 hex) and either approved_by + approved_at (a real YYYY-MM-DD date) or reproduction_only: true (and then no approval fields)`);
  }
  if (config.schema !== SCHEMA) bad(`schema must be ${SCHEMA}`);
  if (!isStr(config.id)) bad('id (episode id) is required');
  if (!isInt(config.fps) || config.fps <= 0) bad('fps must be a positive integer');
  const tl = config.timeline || {};
  for (const key of ['introFrames', 'mainFrames', 'endCardFrames', 'outroStart', 'outroFrames']) {
    if (!isInt(tl[key]) || tl[key] < 0) bad(`timeline.${key} must be a non-negative integer`);
  }
  const motion = resolveMotion(config);
  for (const key of unknownKeys(DEFAULT_MOTION, config.motion || {})) bad(`motion.${key} is not a known preset key`);

  const shots = Array.isArray(config.shots) ? config.shots : [];
  if (shots.length === 0) bad('shots[] is empty');
  const ids = new Set();
  let cursor = tl.introFrames;
  for (const shot of shots) {
    if (!isStr(shot.id) || ids.has(shot.id)) bad(`shot id missing or duplicated: ${shot.id}`);
    ids.add(shot.id);
    if (!isInt(shot.start) || !isInt(shot.frames) || shot.frames <= 0) bad(`${shot.id}: start/frames must be integers`);
    if (shot.start !== cursor) bad(`${shot.id}: start ${shot.start} breaks the contiguous clock (expected ${cursor})`);
    cursor = shot.start + shot.frames;
    if (!Array.isArray(shot.words) || shot.words.length === 0) bad(`${shot.id}: no word timing (no whole-line caption fallback by design)`);
    else {
      let prev = -Infinity;
      for (const w of shot.words) {
        if (!isStr(w.w) || !isInt(w.startF) || !isInt(w.endF)) bad(`${shot.id}: malformed word ${JSON.stringify(w)}`);
        if (w.startF < prev) bad(`${shot.id}: word '${w.w}' starts before the previous word`);
        prev = w.startF;
        if (w.startF < shot.start || w.startF >= shot.start + shot.frames) bad(`${shot.id}: word '${w.w}' starts outside its shot window`);
      }
    }
    if (![1, 2].includes(shot.captionLines)) bad(`${shot.id}: captionLines must be 1 or 2`);
    if (shot.speechOnsetF !== undefined && (!isInt(shot.speechOnsetF) || shot.speechOnsetF < shot.start || shot.speechOnsetF >= shot.start + shot.frames)) bad(`${shot.id}: speechOnsetF must be an integer inside the shot window`);
    if (typeof shot.speechEndS !== 'number') bad(`${shot.id}: speechEndS (speech end inside the window, seconds) is required`);
    if (!Array.isArray(shot.segments) || shot.segments.length === 0) {
      bad(`${shot.id}: segments[] is empty`);
    } else {
      let seg = 0;
      for (const s of shot.segments) {
        if (!isStr(s.id)) bad(`${shot.id}: segment without id`);
        if (s.from !== seg) bad(`${shot.id}/${s.id}: segment starts at ${s.from}, expected ${seg} (contiguous)`);
        seg = s.from + s.frames;
      }
      if (seg !== shot.frames) bad(`${shot.id}: segments cover ${seg} frames, shot has ${shot.frames}`);
    }
  }
  if (cursor !== tl.outroStart) bad(`dialogue ends at ${cursor}, timeline.outroStart is ${tl.outroStart}`);
  if (tl.outroStart + tl.outroFrames !== tl.mainFrames) bad('outroStart + outroFrames must equal mainFrames');
  // optional hash-locked master clock (the old per-episode SHOT_TABLE guard): every shot must equal it
  if (config.clock && config.clock.shotTable) {
    for (const shot of shots) {
      const want = config.clock.shotTable[shot.id];
      if (!want || want[0] !== shot.start || want[1] !== shot.frames) bad(`master clock mismatch for ${shot.id}`);
    }
    for (const id of Object.keys(config.clock.shotTable)) if (!ids.has(id)) bad(`clock.shotTable names unknown shot ${id}`);
  }

  // ---- transitions ----------------------------------------------------------------------------------------------
  const transitions = Array.isArray(config.transitions) ? config.transitions : [];
  const tids = new Set();
  const firstSeg = new Set();
  const lastSeg = new Set();
  for (const shot of shots) {
    if (!shot.segments || !shot.segments.length) continue;
    const e = edgeIds(shot);
    firstSeg.add(shot.id).add(e.first);
    lastSeg.add(shot.id).add(e.last);
  }
  // global start / end frame of every shot and segment id (a transition names a shot id or its first / last segment id)
  const segStart = new Map();
  const segEnd = new Map();
  const shotOf = new Map();
  for (const shot of shots) {
    if (!shot.segments || !shot.segments.length) continue;
    segStart.set(shot.id, shot.start);
    segEnd.set(shot.id, shot.start + shot.frames);
    shotOf.set(shot.id, shot.id);
    for (const s of shot.segments) {
      segStart.set(s.id, shot.start + s.from);
      segEnd.set(s.id, shot.start + s.from + s.frames);
      shotOf.set(s.id, shot.id);
    }
  }
  const graphics = new Set(['INTRO', 'OUTRO', 'END_PLATE', 'ENDLOGO']);
  const cardTerms = new Set((Array.isArray(config.cards) ? config.cards : []).map((c) => `CARD_${c.term}`));
  const knownRef = (ref) => segStart.has(ref) || graphics.has(ref) || cardTerms.has(ref);
  // canonical EDGE segment of an id: a shot id enters at its first segment and leaves at its last; a segment id is itself
  const inKey = new Map();
  const outKey = new Map();
  for (const shot of shots) {
    if (!shot.segments || !shot.segments.length) continue;
    const e = edgeIds(shot);
    inKey.set(shot.id, e.first);
    outKey.set(shot.id, e.last);
    for (const sg of shot.segments) {
      inKey.set(sg.id, sg.id);
      outKey.set(sg.id, sg.id);
    }
  }
  const toShots = new Map(); // segment id -> transition ids that enter it
  const fromShots = new Map();
  for (const t of transitions) {
    if (!isStr(t.id) || tids.has(t.id)) bad(`transition id missing or duplicated: ${t.id}`);
    tids.add(t.id);
    // the catalog entry this row means (explicit `preset`, else its type; dip_white at 9 frames is the first build's schedule)
    const name = typeof t.type === 'string' ? presetName(t) : undefined;
    const preset = name === undefined ? undefined : PRESETS[name];
    const props = TYPE_TABLE[name];
    const kind = preset ? preset.renders_as : undefined;
    if (!props) {
      if (preset && preset.status === 'planned') bad(`${t.id}: preset '${name}' is planned, not implemented (${preset.kids_note || 'its renderer is not built yet'}); choose a ready preset: ${TRANSITION_TYPES.join(', ')}`);
      else bad(`${t.id}: unknown transition type '${t.type}' (canonical: ${TRANSITION_TYPES.join(', ')})`);
    }
    if (props && t.preset !== undefined && t.preset !== resolvePresetName(t.type, t.frames)) bad(`${t.id}: preset '${t.preset}' does not match type '${t.type}'`);
    if (props && t.renders_as !== undefined && t.renders_as !== kind) bad(`${t.id}: renders_as '${t.renders_as}' contradicts ${name} (it renders as '${kind}')`);
    // an explicit shows_both (the engine's per-type property) must agree with the catalog
    const claimed = t.shows_both !== undefined ? t.shows_both : t.showsBoth;
    if (claimed !== undefined && props && claimed !== props.showsBoth) bad(`${t.id}: shows_both ${claimed} contradicts type ${t.type}`);
    if (t.continuity !== undefined && !['agree', 'mismatch', 'unknown'].includes(t.continuity)) bad(`${t.id}: continuity must be 'agree', 'mismatch' or 'unknown'`);
    // a both-sides type needs continuity 'agree' only when a PICTURE SHOT is on either side (between two graphics it is allowed)
    const pictureSide = shotOf.has(t.from) || shotOf.has(t.to); // a shot, its first, last OR middle segment id
    if (props && props.showsBoth && pictureSide && t.continuity !== 'agree') {
      bad(`${t.id}: ${t.type} shows both sides in one frame and a picture shot is on one side; it needs continuity:'agree'; use whip / dip_white / bloom / cut`);
    }
    // a preset that takes frames from the outgoing native tail (all / half) needs the tail; a dip schedule only when it has out_tail rows
    if (preset && props && !['none', 'schedule'].includes(preset.tail_frames) && !t.tail) {
      bad(`${t.id}: ${t.type} needs an outgoing tail (the outgoing shot must keep playing under it); continuity:'agree' does not replace it`);
    }
    // safe_for: a graphics-only preset between two pictures, a picture-only preset between two graphics
    if (props && !['none', 'cut'].includes(name)) {
      const pictures = (shotOf.has(t.from) ? 1 : 0) + (shotOf.has(t.to) ? 1 : 0);
      if (pictures === 2 && !preset.safe_for.includes('picture')) bad(`${t.id}: ${name} is for graphic boundaries only (cards, end plate, intro/outro), not between two picture shots`);
      if (pictures === 0 && !preset.safe_for.includes('graphic')) bad(`${t.id}: ${name} is for picture shots only, not between two graphics (cards, end plate, intro/outro); use card_slide, plate_in, iris, bloom or cut`);
    }
    // every from / to names a real shot, segment or graphic (a typo would silently attach to nothing)
    for (const [side, ref] of [['from', t.from], ['to', t.to]]) {
      if (!knownRef(ref)) bad(`${t.id}: '${side}' ${ref} is not a known shot, segment or graphic (INTRO, OUTRO, END_PLATE, ENDLOGO, CARD_<term>)`);
    }
    // picture-layer presets are drawn on the shot pictures; iris leaves the outgoing shot only
    const pictureLayer = props !== undefined && props.drawn && !['iris', 'bloom'].includes(kind);
    if (props && props.drawn && kind !== 'bloom') {
      if (!lastSeg.has(t.from) && (pictureLayer || kind === 'iris')) bad(`${t.id}: 'from' ${t.from} is not a shot or last segment`);
      if (!firstSeg.has(t.to) && pictureLayer) bad(`${t.id}: 'to' ${t.to} is not a shot or first segment`);
    }
    // each shot has at most ONE incoming and ONE outgoing transition (an indexed lookup would silently let the last one win)
    if (inKey.has(t.to)) toShots.set(inKey.get(t.to), [...(toShots.get(inKey.get(t.to)) || []), t.id]);
    if (outKey.has(t.from)) fromShots.set(outKey.get(t.from), [...(fromShots.get(outKey.get(t.from)) || []), t.id]);
    // anchoring: the transition window must sit where the picture is (integer start; boundary = outgoing end / incoming start)
    if (props && props.drawn && !isInt(t.start)) bad(`${t.id}: start must be an integer global frame`);
    if (props && props.drawn && kind !== 'bloom' && !isInt(t.boundary)) bad(`${t.id}: boundary must be an integer global frame`);
    if (props && props.drawn && isInt(t.boundary) && kind !== 'bloom') {
      if (pictureLayer && segStart.has(t.to) && segStart.get(t.to) !== t.boundary) {
        bad(`${t.id}: boundary ${t.boundary} is not the start of the incoming shot / segment ${t.to} (${segStart.get(t.to)})`);
      }
      if ((pictureLayer || kind === 'iris') && segEnd.has(t.from) && segEnd.get(t.from) !== t.boundary) {
        bad(`${t.id}: boundary ${t.boundary} is not the end of the outgoing shot / segment ${t.from} (${segEnd.get(t.from)})`);
      }
    }
    if (props && preset && !['none', 'schedule'].includes(preset.tail_frames) && isInt(t.start) && isInt(t.boundary)) {
      // tail presets run on the outgoing tail from the boundary; their picture layer runs on the incoming shot's first frames
      if (t.start !== t.boundary) bad(`${t.id}: ${t.type} must start on its boundary (start ${t.start}, boundary ${t.boundary})`);
      if (segStart.has(t.to) && t.start !== segStart.get(t.to)) bad(`${t.id}: ${t.type} start ${t.start} is not the start of the incoming shot (${segStart.get(t.to)})`);
    }
    // catalog rules: direction, frames (a dip row's own schedule is judged by that schedule), params
    const ownSchedule = kind === 'dip_white' && Array.isArray(t.schedule);
    const shape = [];
    if (props) {
      const dm = directionMessage(preset, name, t.direction, t.id);
      if (dm) shape.push(dm);
      if (ownSchedule) {
        if (!(t.frames > 0)) shape.push(`${t.id}: ${t.type} frames must be greater than 0`);
        else if (t.frames !== t.schedule.length) shape.push(`${t.id}: ${t.type} frames ${t.frames} must equal its schedule length ${t.schedule.length}`);
      } else {
        const fm = framesMessage(preset, name, t.frames, t.id);
        if (fm) shape.push(fm);
      }
      shape.push(...paramsMessages(preset, name, t.params, t.id));
      for (const m of shape) bad(m);
    }
    // window: where the catalog's window mode puts this row (the iris window needs its own disc_fade_frames)
    if (props && props.drawn && shape.length === 0 && isInt(t.boundary) && isInt(t.start)) {
      const prm = {...resolveParams(preset, t.params), ...(isInt(t.disc_fade_frames) ? {disc_fade_frames: t.disc_fade_frames} : {})};
      if (preset.window !== 'iris' || isInt(prm.disc_fade_frames)) {
        const [from, to] = windowOf(preset, t.boundary, t.frames, prm, scheduleOf(t));
        if (t.start !== from) bad(`${t.id}: start ${t.start} is not where ${name} places its window (${preset.window}: frame ${from} for boundary ${t.boundary}, ${t.frames} frames)`);
        if (t.end_exclusive !== undefined && t.end_exclusive !== to) bad(`${t.id}: end_exclusive ${t.end_exclusive} is not where ${name} ends its window (${to})`);
      }
    }
    if (kind === 'whip') {
      for (const [key, arrs] of [['outFrames', ['outOffset', 'outBlur', 'outZoom']], ['inFrames', ['inOffset', 'inBlur', 'inZoom']]]) {
        if (!isInt(t[key]) || t[key] <= 0) bad(`${t.id}: ${key} must be a positive integer`);
        for (const a of arrs) if (t[key] > motion.whip[a].length) bad(`${t.id}: ${key} ${t[key]} exceeds motion.whip.${a} (${motion.whip[a].length})`);
      }
    }
    if (kind === 'whip' && [1, -1].includes(t.direction) && isInt(t.outFrames) && isInt(t.inFrames) && t.outFrames <= motion.whip.outOffset.length && t.inFrames <= motion.whip.inOffset.length) {
      // the extender strip must really reach the canvas border for every offset the schedule draws
      for (const step of whipSteps(t, motion)) {
        const cov = whipCoverage(step.offset, step.zoomK, motion);
        if (!cov.covered) {
          bad(`${t.id}: whip extender strip does not cover the exposed ${cov.side} side by ${cov.gapPx.toFixed(1)} px at ${step.phase} frame ${step.k} (motion.whip.extenderWidth ${motion.whip.extenderWidth})`);
          break;
        }
      }
    }
    if (kind === 'bloom' && (!isInt(t.start) || !isInt(t.frames))) bad(`${t.id}: bloom needs start/frames`);
    if (kind === 'dip_white') {
      const schedule = scheduleOf(t);
      if (!Array.isArray(schedule) || schedule.length === 0) bad(`${t.id}: dip needs a schedule`);
      else {
        let peaks = 0;
        const tails = [];
        for (const e of schedule) {
          if (!DIP_SHOTS.includes(e.shot)) bad(`${t.id}: schedule shot '${e.shot}' not in ${DIP_SHOTS.join('/')}`);
          // 'out' is the outgoing shot's own last editorial frame(s) (t < 0); from the boundary on the outgoing picture can only
          // come from the native tail ('out_tail'); 'in' is only legal from the boundary on
          if (e.shot === 'out' && !(e.t < 0)) bad(`${t.id}: schedule 'out' at t=${e.t}; the outgoing shot has ended at the boundary (use out_tail with a tail)`);
          if (e.shot === 'out_tail' && !(e.t >= 0)) bad(`${t.id}: schedule 'out_tail' at t=${e.t} must be at or after the boundary`);
          if (e.shot === 'in' && !(e.t >= 0)) bad(`${t.id}: schedule 'in' at t=${e.t} must be at or after the boundary`);
          if (typeof e.white !== 'number' || e.white < 0 || e.white > 1) bad(`${t.id}: schedule white out of 0..1`);
          if (e.white === 1) peaks += 1;
          if (e.shot === 'out_tail') tails.push(e.t);
        }
        if (peaks !== 1) bad(`${t.id}: a dip needs exactly one pure-white frame (found ${peaks})`);
        // the white peak may not hide the incoming shot's first spoken word (jenniejoy-remotion rule: peak no later than the
        // frame before the first word): peak frame < first word startF of the shot that starts at this boundary
        const peakRow = schedule.find((e) => e.white === 1);
        const target = shots.find((sh) => sh.segments && sh.segments.length && (sh.id === t.to || sh.segments[0].id === t.to));
        if (peakRow && isInt(t.boundary) && target && Array.isArray(target.words) && target.words.length) {
          const spoken = firstSpoken(target);
          const firstWord = spoken.frame;
          const peakFrame = t.boundary + peakRow.t;
          const sparklesOn = resolveParams(preset, t.params).sparkles !== false; // params.sparkles false => no sparkle burst
          const reach = motion.dip.sparkles > 0 && sparklesOn ? motion.dip.peakSpan : 0; // the sparkle burst is drawn peak +- peakSpan frames
          if (peakFrame >= firstWord) {
            bad(`${t.id}: dip_peak_before_first_word: the white peak (f${peakFrame}) must come before the first spoken word of ${target.id} (f${firstWord}); it would hide ${peakFrame - firstWord + 1} spoken frame(s) [first spoken frame from ${spoken.basis}]`, {rule: 'dip_peak_before_first_word', transition: t.id});
          } else if (peakFrame + reach >= firstWord) {
            bad(`${t.id}: dip_sparkle_before_first_word: the sparkle burst around the white peak (f${peakFrame}+${reach}) reaches the first spoken word of ${target.id} (f${firstWord}); set motion.dip.sparkles 0 (or params.sparkles false) or move the peak earlier [first spoken frame from ${spoken.basis}]`, {rule: 'dip_sparkle_before_first_word', transition: t.id});
          }
        }
        if (tails.length > 0 && !t.tail) bad(`${t.id}: schedule uses out_tail frames but the transition has no tail`);
        // the tail plays on frames boundary .. boundary+n-1: the out_tail rows must be exactly t = 0 .. n-1 (no gap, no shift)
        const sorted = [...tails].sort((a, b) => a - b);
        if (sorted.some((v, i) => v !== i)) bad(`${t.id}: out_tail rows must be contiguous t=0..n-1 (found t=${sorted.join(',')})`);
        if (!isInt(t.boundary)) bad(`${t.id}: dip needs boundary`);
        else if (schedule.some((e) => !isInt(e.t)) || dipSpan(t) < 1) bad(`${t.id}: schedule t values must be integers`);
      }
    }
    if (t.centre !== undefined && !(Array.isArray(t.centre) && t.centre.length === 2)) bad(`${t.id}: ${t.type} centre must be [x,y]`);
    if (t.seed !== undefined && !isInt(t.seed)) bad(`${t.id}: ${t.type} seed must be an integer`);
    if (t.tail && !isInt(t.tail.startFrom)) bad(`${t.id}: tail.startFrom must be an integer delivery-frame offset into the bound tail file`);
    if (t.tail && !(isInt(t.tail.fileFrames) && t.tail.fileFrames > 0)) bad(`${t.id}: tail.fileFrames (the frame count of the bound tail file; the probe must match it) must be a positive integer`);
    if (t.tail && !(isInt(t.tail.verifiedFrames) && t.tail.verifiedFrames > 0)) bad(`${t.id}: tail.verifiedFrames (output frames the build's tail check covered: events tail_output_frames, receipt-bound) must be a positive integer`);
    else if (t.tail) {
      // the transition may play at most as many tail frames as the engine verified for it (fewer is safe)
      const w = tailWindow(t);
      if (w && w.frames > t.tail.verifiedFrames) bad(`${t.id}: plays ${w.frames} tail frames but only ${t.tail.verifiedFrames} were verified (tail.verifiedFrames)`);
    }
    if (t.tail && !(isInt(t.tail.editorialFrames) && t.tail.editorialFrames >= 0)) bad(`${t.id}: tail.editorialFrames (native frames of the bound file the editorial cut already uses) must be an integer >= 0`);
    // descriptor presets: prove the endpoints / one-shot property of the very descriptors the compositor draws
    if (props && DESCRIPTOR_KINDS.includes(kind) && shape.length === 0) {
      for (const m of auditPreset(name, resolveParams(preset, t.params), t.frames, t.direction)) bad(`${t.id}: ${name} descriptor audit: ${m}`);
    }
  }
  for (const [label, map] of [['incoming', toShots], ['outgoing', fromShots]]) {
    for (const [seg, list] of map) if (list.length > 1) bad(`shot / segment ${seg} has several ${label} transitions (${list.join(', ')}); only one is allowed`);
  }

  // ---- icons -----------------------------------------------------------------------------------------------------
  for (const ev of Array.isArray(config.icons) ? config.icons : []) {
    const shot = shots.find((s) => s.id === ev.shot);
    if (!shot) bad(`icon ${ev.id}: unknown shot ${ev.shot}`);
    else if (ev.frame < shot.start || ev.frame >= shot.start + shot.frames) bad(`icon ${ev.id}: frame ${ev.frame} outside ${shot.id}`);
    if (!isStr(ev.icon)) bad(`icon ${ev.id}: icon key missing`);
    if (!isInt(ev.totalFrames) || ev.totalFrames <= 0) bad(`icon ${ev.id}: totalFrames must be positive`);
  }

  // ---- cards -----------------------------------------------------------------------------------------------------
  const cards = Array.isArray(config.cards) ? config.cards : [];
  let prevEnd = 0;
  for (const c of cards) {
    if (!isStr(c.term)) bad('card without term');
    if (c.start < prevEnd) bad(`card ${c.term}: window starts ${c.start} before the previous card ends ${prevEnd}`);
    prevEnd = c.start + c.frames;
  }
  if (cards.length && prevEnd > tl.outroFrames) bad(`cards end at ${prevEnd}, beyond outroFrames ${tl.outroFrames}`);

  // ---- strings / intro ---------------------------------------------------------------------------------------------
  const strings = config.strings || {};
  for (const key of ['cardsHeader', 'cardsHeaderClosing']) if (!isStr(strings[key])) bad(`strings.${key} is required`);
  const intro = config.intro || {};
  if (tl.introFrames > 0) {
    for (const key of ['kicker', 'pill', 'footer']) if (!isStr(intro[key])) bad(`intro.${key} is required`);
    if (!Array.isArray(intro.titleLines) || intro.titleLines.length === 0) bad('intro.titleLines[] is required');
    if (!['drop', 'none'].includes(intro.mark)) bad("intro.mark must be 'drop' or 'none'");
  }

  // ---- ending ------------------------------------------------------------------------------------------------------
  const ending = config.ending || {};
  if (transitions.some((t) => t.type === 'iris')) {
    for (const key of ENDING_REQUIRED_IRIS) if (ending[key] === undefined) bad(`ending.${key} is required (an iris transition exists)`);
    if (!(Array.isArray(ending.irisCentre) && ending.irisCentre.length === 2)) bad('ending.irisCentre must be [x,y]');
    const seq = ['irisStart', 'irisClosed', 'discIn', 'discSlideStart', 'discSlideEnd', 'discFadeStart'].map((k) => ending[k]);
    if (seq.some((v) => !isInt(v)) || seq.some((v, i) => i > 0 && v < seq[i - 1])) bad('ending frames must be integers in order: irisStart <= irisClosed <= discIn <= discSlideStart <= discSlideEnd <= discFadeStart');
    if (isInt(ending.discFadeStart) && ending.discFadeStart < tl.outroStart) bad('ending.discFadeStart is before the outro');
    // "no overlay over a vocab word while it is spoken": the disc must be proven clear of the first card's pill
    const m = resolveMotion(config).ending;
    const first = cards[0];
    const discR = ending.discR !== undefined ? ending.discR : m.discR;
    const discBusy = first && isInt(ending.discFadeStart) && ending.discFadeStart <= tl.outroStart + first.start + first.frames;
    if (discBusy) {
      if (typeof ending.pillLeftX !== 'number') bad('ending.pillLeftX (measured left edge of the first card pill) is required to prove the logo disc clears the vocab word');
      else if (ending.discSlideX + discR >= ending.pillLeftX) bad(`logo disc right edge ${ending.discSlideX + discR} covers the first vocab pill (left edge ${ending.pillLeftX})`);
      // the slide must finish before (or on) the first spoken frame so the pill is never under the disc
      if (isInt(ending.discSlideEnd) && ending.discSlideEnd > tl.outroStart + first.start) bad('logo disc is still sliding after the first vocab word starts');
    }
  }
  {
    const plate = resolveMotion(config).ending.plate;
    const style = ending.plateStyle !== undefined ? ending.plateStyle : plate.style;
    if (!Object.prototype.hasOwnProperty.call(plate.styles, style)) bad(`ending.plateStyle ${JSON.stringify(style)} is not a known plate style (${Object.keys(plate.styles).join(', ')})`);
  }
  if (ending.plateStart !== undefined && !(tl.endCardFrames > 0)) bad('ending.plateStart is set but timeline.endCardFrames is 0 (the end plate belongs to the end card)');
  if (ending.plateStart !== undefined || tl.endCardFrames > 0) {
    for (const key of ENDING_REQUIRED_PLATE) if (ending[key] === undefined) bad(`ending.${key} is required`);
    if (typeof ending.speechEndFrame === 'number' && typeof ending.plateStart === 'number' && ending.plateStart < ending.speechEndFrame) {
      bad(`end plate starts at ${ending.plateStart}, before the last vocab word ends (${ending.speechEndFrame}): it would cover the word while spoken`);
    }
    if (typeof ending.plateStart === 'number' && ending.plateStart >= tl.mainFrames) bad('ending.plateStart must be inside the main film');
    // speechEndFrame must not precede any speech it claims to follow: the last dialogue word and the last vocab word window start
    const lastShot = shots[shots.length - 1];
    const lastWordEnd = lastShot && Array.isArray(lastShot.words) && lastShot.words.length ? Math.max(...lastShot.words.map((w) => w.endF)) : 0;
    if (typeof ending.speechEndFrame === 'number' && ending.speechEndFrame < lastWordEnd) bad(`ending.speechEndFrame ${ending.speechEndFrame} is before the last dialogue word ends (${lastWordEnd})`);
    const lastCard = cards[cards.length - 1];
    if (lastCard && typeof ending.speechEndFrame === 'number' && ending.speechEndFrame < tl.outroStart + lastCard.start) bad(`ending.speechEndFrame ${ending.speechEndFrame} is before the last vocab word starts (${tl.outroStart + lastCard.start})`);
  }
  if (tl.endCardFrames > 0 && !isInt(ending.tailFrom)) bad('ending.tailFrom (music tail start frame) is required when there is an end card');

  // one-shot-per-frame audit: only meaningful once the structural checks above passed
  if (issues.length === 0) {
    for (const v of auditPictureLayers(config, motion)) {
      bad(`f${v.frame}: ${v.layers} shot pictures at once (${v.transitions.join(',') || v.slot}); only continuity:'agree' transitions may overlap`);
    }
  }
  for (const w of waivers) {
    if (WAIVABLE_RULES.includes(w.rule) && isStr(w.transition) && goodWaiver(w) && !usedWaivers.has(w)) bad(`waiver for rule ${w.rule} on ${w.transition} is unused (that transition does not violate the rule): remove it`);
  }
  return {issues, waived};
}

// Build warnings (never refusals): same_framing between two pictures with a visible transition (same seat / angle: a hard cut or a
// cut_push reads better), and the legacy 9-frame dip schedule. Mirrors the engine's row_warnings; render.cjs may print them.
const NOT_VISIBLE = ['cut', 'cut_push', 'none'];
export function collectWarnings(config) {
  const warnings = [];
  const transitions = config && Array.isArray(config.transitions) ? config.transitions : [];
  const shotIds = new Set();
  for (const shot of config && Array.isArray(config.shots) ? config.shots : []) {
    shotIds.add(shot.id);
    for (const s of shot.segments || []) shotIds.add(s.id);
  }
  for (const t of transitions) {
    const preset = typeof t.type === 'string' ? presetOf(t) : undefined;
    if (!preset || preset.status !== 'ready') continue;
    if (presetName(t) === LEGACY_DIP) {
      const how = t.type === APPROVED_DIP ? 'resolved from type dip_white with 9 frames; write type dip_white_legacy to keep it explicitly' : 'kept only to reproduce the first build';
      warnings.push(`${t.id}: legacy 9-frame dip_white schedule in use (preset ${LEGACY_DIP}, ${how}); drop frames (or write dip_white) for the approved 8-row schedule`);
    }
    if (t.framing === 'same_framing' && shotIds.has(t.from) && shotIds.has(t.to) && !NOT_VISIBLE.includes(preset.renders_as)) {
      warnings.push(`${t.id}: framing is same_framing but ${presetName(t)} is a visible transition; same seat/angle: use cut_push, flash or camera move only when angle/scene changes`);
    }
  }
  return warnings;
}

export function collectIssues(config) {
  return analyse(config).issues;
}

// waived rule violations (explicit config.waivers with a reason): reported by render.cjs, never silent
export function collectWaived(config) {
  return analyse(config).waived;
}

export function validateConfig(config) {
  const issues = collectIssues(config);
  if (issues.length) throw new Error(`remotion-kit config invalid:\n - ${issues.join('\n - ')}`);
  return true;
}

// sources = staged file names (what staticFile() resolves). `partial` allows nulls for stills that only need part of the film.
export function collectSourceIssues(config, sources, {partial = false} = {}) {
  const issues = [];
  const need = (value, what) => {
    if (!isStr(value) && !partial) issues.push(`sources: ${what} missing`);
  };
  if (!sources || typeof sources !== 'object') return ['sources is not an object'];
  need(sources.logo, 'logo');
  need(sources.music, 'music');
  if (config.timeline.introFrames > 0) need(sources.opening, 'opening');
  need(sources.fonts && sources.fonts.regular, 'fonts.regular');
  need(sources.fonts && sources.fonts.bold, 'fonts.bold');
  for (const shot of config.shots) {
    const s = (sources.shots || {})[shot.id];
    if (!s) {
      if (!partial) issues.push(`sources.shots.${shot.id} missing`);
      continue;
    }
    need(s.audio, `shots.${shot.id}.audio`);
    for (const seg of shot.segments) need((s.segments || {})[seg.id], `shots.${shot.id}.segments.${seg.id}`);
  }
  for (const t of config.transitions) if (t.tail) need((sources.tails || {})[t.id], `tails.${t.id}`);
  for (const ev of config.icons) need((sources.icons || {})[ev.icon], `icons.${ev.icon}`);
  config.cards.forEach((c, i) => {
    const s = (sources.cards || [])[i] || {};
    need(s.icon, `cards[${i}].icon`);
    need(s.audio, `cards[${i}].audio`);
  });
  return issues;
}

export function validateSources(config, sources, opts) {
  const issues = collectSourceIssues(config, sources, opts);
  if (issues.length) throw new Error(`remotion-kit sources invalid:\n - ${issues.join('\n - ')}`);
  return true;
}

export const totalFrames = (config) => config.timeline.mainFrames + config.timeline.endCardFrames;
