// remotion-kit presets: the DEFAULT look and motion of the JennieJoy review cut and master.
// Everything here is a default. A kit config overrides any leaf through `config.theme` (palette) and
// `config.motion` (timing / spring / layout presets) - see README "motion presets". There are NO episode numbers in this
// file: shot ids, frame positions, totals and text all come from the config.
// Pure ESM, no React: node tests import it directly.
import {CATALOG} from './catalog.generated.mjs';

export const DEFAULT_THEME = {
  pink: '#FF2E7E',
  pinkSoft: '#FFD5E4',
  ink: '#173A34',
  paper: '#FFF9ED',
  mint: '#DDF3D9',
  mintDeep: '#BFDDB9',
  peach: '#F4C7B0',
  sky: '#A9DDE2',
  white: '#FFFDF8',
  night: '#143D38',
  scrim: '#102D29',
};

export const DEFAULT_MOTION = {
  // remotion spring presets. overshootClamping false = the card visibly lands; settle = critically damped.
  spring: {
    land: {damping: 13, stiffness: 190, mass: 0.8, overshootClamping: false},
    pill: {damping: 18, stiffness: 500, mass: 0.7, overshootClamping: false},
    settle: {damping: 28, stiffness: 240, mass: 0.8, overshootClamping: true},
  },
  stagger: 3, // frames between icon -> term -> IPA/VI -> example
  // vocabulary flashcards (frames @fps, relative to the card's own window unless noted)
  cards: {
    lead: 3, // visual lead-in before the card's audio window (cards 2..n). 0 = none
    tileFade: 3,
    iconScaleFrom: 0.5,
    iconRise: 36,
    pillScaleFrom: 0.8,
    pillRise: 26,
    infoRise: 16,
    fadeFrames: 4,
    pushTo: 1.012,
    xfadeAfter: 6, // outgoing card lingers this many frames after its window end, sliding + fading
    xfadeShift: -300,
    inShift: 70,
    bgFade: 0,
    headerFont: 56,
    exampleFont: 56,
    tile: 540,
    tileImg: 660,
    gap: 70,
    textCol: 900,
    headerY: 72,
    pipsY: 968,
    headerRamp: 4, // header / counter / pips ramp-in over the first frames of the outro
  },
  intro: {
    bgScaleFrom: 1.04, // ends at 1.00 on the last intro frame (= framing of the first dialogue shot)
    scrimFade: 10,
    dropDelay: 0,
    dropRise: -140,
    kicker: 6,
    lineDelays: [9, 12],
    lineStep: 3, // extra title lines continue from the last delay in steps of this
    pill: 16,
    footer: 22,
    logo: 4,
    textRise: 40,
    exitFrames: 5, // text layer fades out over the last N frames of the intro
  },
  caption: {
    fontEn: 42,
    fontVi: 29,
    pad: '0 4px 2px',
    margin: '0 1px',
    fillFrames: 2,
    popFrames: 8,
    popPeakAt: 3,
    popScale: 1.12,
    unspoken: '#7C9690',
    spoken: '#173A34',
    activeBg: '#CFEFC9',
    kwUnspokenBg: '#FFE3EE',
    kwUnspokenText: '#E58FB0',
    kwBg: '#FF2E7E',
    kwText: '#FFFDF8',
    side: 150, // panel left/right inset (px of the 1920 design canvas)
    bottom: 36,
    fadeIn: 6,
    fadeOut: 6,
    hideAfterS: 0.3, // caption hides this long after speech_end
  },
  icon: {
    box: 232,
    gap: 16, // above the caption panel
    capHeight: {1: 135, 2: 190}, // caption panel height by line count (shot.captionLines)
    spring: {damping: 11, stiffness: 260, mass: 0.6, overshootClamping: false},
    rotateFrom: -8,
    sparkleFrames: 8,
    sparkleSeed: 4004,
    sparkleCount: 6,
    hold: 21,
    fade: 5,
  },
  // whip pan: px offsets of the 1920-wide strip, horizontal blur sigma px, zoom 0..1. Index = frame inside the whip.
  whip: {
    outOffset: [5, 16, 64, 720],
    outBlur: [0.5, 2, 8, 54],
    outZoom: [0.01, 0.04, 0.2, 1],
    inOffset: [720, 150, 22, 4],
    inBlur: [54, 16, 2.5, 0.5],
    inZoom: [1, 0.35, 0.06, 0.01],
    zoom: 1.04,
    extend: 24, // horizontal stretch factor of the edge extender (edge pixels stretched, never a mirrored copy)
    extenderWidth: 1500,
  },
  bloom: {peak: 0.55, frames: 6},
  dip: {
    colour: '#FFF8EC',
    brightness: 0.4, // picture exposure x(1 + brightness * white)
    blur: 2.5, // px per unit white
    sparkles: 7,
    peakSpan: 1, // sparkle opacity falls off over +-peakSpan frames around the white peak
    peakFrames: 5, // length of the sparkle / white-peak Sequence that starts on the boundary frame
  },
  wipe: {
    cloudBumps: 10,
    bubbleCount: 16,
    maskBlur: 12,
    ringBlur: 5,
    ringGrow: 42,
  },
  ending: {
    // style defaults; the episode-specific frames and positions are REQUIRED config (config.ending, see validate.mjs)
    irisStartRadius: 1250,
    irisEndRadius: 250,
    discCentre: [960, 540],
    discStartR: 262,
    discR: 430,
    discFadeFrames: 6,
    discRing: 12,
    discSpring: {damping: 15, stiffness: 260, mass: 0.7},
    plateJoinT: 4, // plate clock at the join with the end card: the standalone EndLogo starts here
    tailFadeIn: 6,
    tailFadeStart: 20,
    discLogoBase: 780, // logo size inside the disc = discLogoBase * (disc diameter / discLogoRef)
    discLogoRef: 860,
    discShadow: '0 22px 60px #061F1B55',
    // end plate layout (px of the 1920x1080 design canvas) and springs
    plate: {
      logoSize: 660,
      logoTop: 40,
      enTop: 735,
      enSize: 92,
      enRadius: 70,
      enPad: '16px 56px 22px',
      viTop: 905,
      viSize: 56,
      logoSpring: {damping: 14, stiffness: 420, mass: 0.6},
      textSpring: {damping: 16, stiffness: 420, mass: 0.6},
      // plate STYLE (config.ending.plateStyle wins over this default): the timing of the plate as data, see plateFrame().
      //   v008: the original plate (scrim 0 -> 1, springs).   v010: the approved v013 plate (scrim starts at 0.4, the logo is not drawn
      //   before plate clock 2, logo and pill ease out over 8 frames, text fades 3-6 / 4-7) so a faint logo never sits over the last pill.
      style: 'v008',
      styles: {
        v008: {
          scrim: {frames: 2, from: 0},
          logo: {fade: [0, 2], from: 0, curve: 'spring', delay: 0},
          text: {curve: 'spring', delay: 1},
          en: {fade: [1, 3]},
          vi: {fade: [2, 4]},
        },
        v010: {
          scrim: {frames: 2, from: 0.4},
          logo: {fade: [2, 5], from: 0.25, curve: 'easeOut', delay: 2, frames: 8, gate: 2},
          text: {curve: 'easeOut', delay: 3, frames: 8},
          en: {fade: [3, 6]},
          vi: {fade: [4, 7]},
        },
      },
    },
  },
  previewMark: {top: 14, right: 16, fontSize: 17},
  label: {
    top: 14,
    left: 16,
    fontSize: 17,
  },
};

const isObject = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);

// deepMerge(base, over): objects merge key by key, arrays and scalars are REPLACED. Never mutates its arguments.
export function deepMerge(base, over) {
  if (!isObject(base) || !isObject(over)) return over === undefined ? base : over;
  const out = {...base};
  for (const key of Object.keys(over)) {
    out[key] = isObject(base[key]) && isObject(over[key]) ? deepMerge(base[key], over[key]) : over[key];
  }
  return out;
}

// every key of `over` must exist in `base` (a misspelt override is an error, not a silent no-op)
export function unknownKeys(base, over, prefix = '') {
  const bad = [];
  if (!isObject(over)) return bad;
  for (const key of Object.keys(over)) {
    const at = prefix ? `${prefix}.${key}` : key;
    if (!(key in base)) bad.push(at);
    else if (isObject(base[key]) && isObject(over[key])) bad.push(...unknownKeys(base[key], over[key], at));
  }
  return bad;
}

export function resolveTheme(config) {
  return deepMerge(DEFAULT_THEME, (config && config.theme) || {});
}

export function resolveMotion(config) {
  return deepMerge(DEFAULT_MOTION, (config && config.motion) || {});
}

// ---- small pure maths shared by components and tests -------------------------------------------------------------
export const clampOpts = {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'};

export function mixHex(a, b, t) {
  const pa = [1, 3, 5].map((i) => parseInt(a.slice(i, i + 2), 16));
  const pb = [1, 3, 5].map((i) => parseInt(b.slice(i, i + 2), 16));
  const c = pa.map((v, i) => Math.round(v + (pb[i] - v) * t));
  return `rgb(${c[0]},${c[1]},${c[2]})`;
}

export const easeOut = (t) => (t < 0 ? 0 : t > 1 ? 1 : 1 - (1 - t) * (1 - t) * (1 - t));
export const easeInOut = (t) => (t < 0 ? 0 : t > 1 ? 1 : t * t * (3 - 2 * t));

const ramp = (t, [a, b], from, to) => (t <= a ? from : t >= b ? to : from + ((t - a) / (b - a)) * (to - from));

// One frame of the end plate at plate clock t (frames since plate start, plus the standalone EndLogo's join offset), as pure numbers.
// `plate` is motion.ending.plate (style already chosen by the caller via plateStyleOf); `springOf(kind, frame)` supplies the v008 springs
// ('logo' | 'text'), only called by styles whose curve is 'spring'.
export function plateFrame(plate, t, springOf) {
  const S = plate.styles[plate.style];
  const progress = (spec, kind) => (spec.curve === 'spring' ? springOf(kind, kind === 'text' ? Math.max(0, t - spec.delay) : t) : easeOut((t - spec.delay) / spec.frames));
  const gate = S.logo.gate;
  return {
    scrim: ramp(t, [0, S.scrim.frames], S.scrim.from, 1),
    logo: {
      shown: gate === undefined || t >= gate,
      opacity: gate !== undefined && t < gate ? 0 : ramp(t, S.logo.fade, S.logo.from, 1),
      scale: 0.6 + 0.4 * progress(S.logo, 'logo'),
    },
    en: {opacity: ramp(t, S.en.fade, 0, 1), k: progress(S.text, 'text')},
    vi: {opacity: ramp(t, S.vi.fade, 0, 1)},
  };
}

// the plate style of a config: ending.plateStyle (config data) over motion.ending.plate.style
export function plateStyleOf(config, motion) {
  const plate = motion.ending.plate;
  const name = (config.ending && config.ending.plateStyle) || plate.style;
  return {...plate, style: name};
}

export function seeded(seed) {
  let s = seed >>> 0;
  return () => {
    s = (Math.imul(s, 1664525) + 1013904223) >>> 0;
    return s / 4294967296;
  };
}

// ---- the transition-preset catalog: ONE reading of schemas/transition-presets.json (src/catalog.generated.mjs) -----------------
// A mirror of engine/editorial/presets.py (the catalog loader): the same frame / direction / param / tail / window rules, with the
// same wording where the engine has a message. The kit-vs-engine parity test runs both on every preset. Nothing here names an episode.
export const PRESETS = CATALOG.presets;
export const READY_PRESETS = Object.keys(PRESETS).filter((name) => PRESETS[name].status === 'ready');
export const PLANNED_PRESETS = Object.keys(PRESETS).filter((name) => PRESETS[name].status === 'planned');
export const LEGACY_DIP = 'dip_white_legacy';
export const APPROVED_DIP = 'dip_white';
export const LEGACY_DIP_FRAMES = 9;
const isNum = (v) => typeof v === 'number' && Number.isFinite(v);

// the preset a row means: an explicit `preset`, else its `type`; type dip_white with 9 frames is the first build's schedule
export function resolvePresetName(type, frames) {
  return type === APPROVED_DIP && frames === LEGACY_DIP_FRAMES ? LEGACY_DIP : type;
}
export const presetName = (t) => (typeof t.preset === 'string' ? t.preset : resolvePresetName(t.type, t.frames));
export const presetOf = (t) => PRESETS[presetName(t)];
export const rendersAs = (t) => {
  const p = presetOf(t);
  return p ? p.renders_as : undefined;
};
// the dip schedule of a transition: its own record (historic builds) or the catalog default of its preset
export const scheduleOf = (t) => (Array.isArray(t.schedule) ? t.schedule : (presetOf(t) || {}).schedule);
export const overlayOf = (t) => t.overlay || (presetOf(t) || {}).overlay || {kind: 'colour', colour: '#FFF8EC'};
export const defaultFrames = (preset) => ('fixed' in preset.frames ? preset.frames.fixed : preset.frames.default);

export function candidateFrames(preset) {
  const rule = preset.frames;
  if ('fixed' in rule) return [rule.fixed];
  const out = [];
  for (let n = rule.min; n <= rule.max; n += rule.even ? 2 : 1) out.push(n);
  return out;
}

// why `frames` is not allowed for this preset (null when it is); `id` prefixes the message
export function framesMessage(preset, name, frames, id) {
  const rule = preset.frames;
  if (!Number.isInteger(frames)) return `${id}: frames must be an integer, got ${JSON.stringify(frames)}`;
  if ('fixed' in rule) {
    if (frames === rule.fixed) return null;
    if (rule.fixed === 0) return name === 'none' ? `${id}: none needs frames 0 (got ${frames})` : `${id}: frames must be 0 for ${name}, got ${frames}`;
    const extra = name === APPROVED_DIP ? ` (the legacy ${LEGACY_DIP} schedule is ${LEGACY_DIP_FRAMES} frames)` : '';
    return `${id}: the ${name} schedule is ${rule.fixed} frames, got ${frames}${extra}`;
  }
  if (frames <= 0) return `${id}: ${name} frames must be greater than 0 (got ${frames})`;
  if (frames < rule.min || frames > rule.max) return `${id}: frames ${frames} is outside ${name}'s ${rule.min}..${rule.max}`;
  if (rule.even && frames % 2) return `${id}: ${name} needs an even frame count (got ${frames})`;
  return null;
}

export function directionMessage(preset, name, direction, id) {
  if (preset.direction !== 'required' || direction === 1 || direction === -1) return null;
  if (preset.renders_as === 'whip') return `${id}: whip direction must be 1 or -1 (a whip needs direction -1 or +1 and an even frame count)`;
  return `${id}: ${name} needs direction 1 or -1 (got ${JSON.stringify(direction)})`;
}

// every problem with the written params of a row: unknown keys refused, type / range / enum checked (required keys are the
// engine's iris layout numbers: the kit carries those in config.ending, so `required` is not enforced here)
export function paramsMessages(preset, name, written, id) {
  if (written === undefined || written === null) return [];
  if (typeof written !== 'object' || Array.isArray(written)) return [`${id}: params must be an object`];
  const out = [];
  const known = preset.params || {};
  for (const [key, value] of Object.entries(written)) {
    const spec = known[key];
    if (!spec) {
      out.push(`${id}: unknown param '${key}' for ${name} (allowed: ${Object.keys(known).join(', ') || 'none'})`);
      continue;
    }
    const where = `${id}: ${name} param '${key}'`;
    if (spec.type === 'boolean') {
      if (typeof value !== 'boolean') out.push(`${where} must be true or false, got ${JSON.stringify(value)}`);
    } else if (spec.type === 'enum') {
      if (!spec.values.includes(value)) out.push(`${where} must be one of ${JSON.stringify(spec.values)}, got ${JSON.stringify(value)}`);
    } else if (!(spec.type === 'integer' ? Number.isInteger(value) : isNum(value))) {
      out.push(`${where} must be ${spec.type === 'integer' ? 'an integer' : 'a number'}, got ${JSON.stringify(value)}`);
    } else if ((spec.min !== undefined && value < spec.min) || (spec.max !== undefined && value > spec.max)) {
      out.push(`${where} must be between ${spec.min} and ${spec.max}, got ${JSON.stringify(value)}`);
    }
  }
  return out;
}

// defaults filled for every param that has one (optional layout numbers are kept only when written)
export function resolveParams(preset, written) {
  const out = {};
  for (const [key, spec] of Object.entries(preset.params || {})) if (!spec.optional && !spec.required) out[key] = spec.default;
  return {...out, ...(written || {})};
}

// output frames that must come from the outgoing native tail (0 = none): none | all | half | schedule (the out_tail rows)
export function tailFrameCount(preset, frames, schedule) {
  switch (preset.tail_frames) {
    case 'none': return 0;
    case 'all': return frames;
    case 'half': return Math.ceil(frames / 2);
    default: return (schedule || preset.schedule || []).filter((row) => row.shot === 'out_tail').length;
  }
}

// [start, end_exclusive) in global frames for a boundary frame: at_boundary | centred | from_boundary | iris | schedule
export function windowOf(preset, boundary, frames, params, schedule) {
  switch (preset.window) {
    case 'at_boundary': return [boundary, boundary];
    case 'centred': return [boundary - Math.floor(frames / 2), boundary + Math.floor(frames / 2)];
    case 'from_boundary': return [boundary, boundary + frames];
    case 'iris': return [boundary - frames, boundary + ((params || {}).disc_fade_frames || 0)];
    default: {
      const times = (schedule || preset.schedule).map((row) => row.t);
      return [boundary + Math.min(...times), boundary + Math.max(...times) + 1];
    }
  }
}
