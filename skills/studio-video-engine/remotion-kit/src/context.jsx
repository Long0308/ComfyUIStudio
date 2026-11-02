// Kit context: the resolved theme / motion presets plus the config and the staged source names, shared by every component.
import React, {createContext, useContext, useMemo} from 'react';
import {interpolate, spring} from 'remotion';
import {clampOpts, resolveMotion, resolveTheme} from './presets.mjs';
import {transitionIndex} from './picture-mode.mjs';

const KitContext = createContext(null);

export function KitProvider({config, sources, scale, children}) {
  const value = useMemo(
    () => ({config, sources, scale, theme: resolveTheme(config), motion: resolveMotion(config), tx: transitionIndex(config)}),
    [config, sources, scale],
  );
  return <KitContext.Provider value={value}>{children}</KitContext.Provider>;
}

export function useKit() {
  const kit = useContext(KitContext);
  if (!kit) throw new Error('remotion-kit: component rendered outside <KitProvider>');
  return kit;
}

export const ramp = (frame, delay, length) => interpolate(frame, [delay, delay + length], [0, 1], clampOpts);

export function springAt(frame, delay, fps, config) {
  return spring({frame: Math.max(0, frame - delay), fps, config});
}

// Card windows relative to the outro start. t0 = first visual frame (window start minus the lead-in; card 1 has none).
export function cardTimeline(cards, index, lead) {
  const card = cards[index];
  const start = card.start;
  const end = start + card.frames;
  const t0 = index === 0 ? start : start - lead;
  return {start, end, t0, last: index === cards.length - 1};
}
