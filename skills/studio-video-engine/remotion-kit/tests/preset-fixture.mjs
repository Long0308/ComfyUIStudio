// Builders for the preset-driven tests: a catalog-correct transition row for ANY preset, placed on the synthetic episode.
// The row is derived from the generated catalog (defaults for frames / params / direction, the window start the catalog's window
// mode gives, a tail that covers exactly the frames the preset needs), so a new catalog entry is exercised without editing tests.
import {CATALOG} from '../src/catalog.generated.mjs';
import {defaultFrames, resolveParams, tailFrameCount, windowOf} from '../src/presets.mjs';
import {makeConfig} from './fixture.mjs';

export const READY = Object.entries(CATALOG.presets).filter(([, p]) => p.status === 'ready').map(([name]) => name);
export const PLANNED = Object.entries(CATALOG.presets).filter(([, p]) => p.status === 'planned').map(([name]) => name);
// presets that sit on a picture / picture boundary and touch the shot layers (the others are informational or ending-only)
export const PICTURE_LAYER = READY.filter((n) => !['none', 'cut', 'iris', 'bloom', 'card_slide', 'plate_in'].includes(CATALOG.presets[n].renders_as));
export const DESCRIPTOR = ['cut_push', 'push_slide', 'zoom_through', 'zoom_out', 'iris_circle', 'iris_diamond', 'clock_wipe', 'blinds', 'blur_crossfade', 'focus_pull', 'card_flip_3d'];

export function presetRow(name, over = {}) {
  const p = CATALOG.presets[name];
  const frames = over.frames !== undefined ? over.frames : defaultFrames(p);
  const params = over.params !== undefined ? over.params : {};
  const direction = over.direction !== undefined ? over.direction : p.direction === 'required' ? 1 : 0;
  const boundary = over.boundary !== undefined ? over.boundary : 90;
  const [start] = windowOf(p, boundary, frames, resolveParams(p, params));
  const n = tailFrameCount(p, frames);
  const row = {id: 'P1', type: name, boundary, from: 'X1', to: 'X2a', frames, direction, start, params, continuity: 'agree'};
  if (p.renders_as === 'whip') Object.assign(row, {outFrames: Math.floor(frames / 2), inFrames: Math.floor(frames / 2)});
  if (n > 0) row.tail = {startFrom: 0, editorialFrames: 0, fileFrames: 30, verifiedFrames: n};
  return {...row, ...(over.row || {})};
}

// the synthetic episode with its whip replaced by ONE row of preset `name` (X1 -> X2a); the iris at the end stays
export function presetConfig(name, over = {}) {
  const c = makeConfig();
  c.transitions = [presetRow(name, over), ...c.transitions.filter((t) => t.id !== 'W1')];
  return c;
}

export const has = (issues, text) => issues.some((i) => i.includes(text));
