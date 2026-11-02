// Ending + bloom bridge. The iris itself lives in transitions.jsx (picture mask); this file draws what appears inside the
// closing circle (logo disc, which steps aside so it never covers the first vocab pill) and the final logo plate
// (EndPlate / EndLogo) over the last card.
import React from 'react';
import {AbsoluteFill, Img, interpolate, spring, staticFile, useCurrentFrame} from 'remotion';
import {clampOpts, easeInOut, plateFrame, plateStyleOf} from './presets.mjs';
import {Backdrop} from './cards.jsx';
import {useKit} from './context.jsx';

export function Bloom({frames}) {
  const f = useCurrentFrame(); // 0..frames-1
  const {motion} = useKit();
  const k = motion.bloom.frames / frames; // the preset curve is authored for motion.bloom.frames frames
  const o = motion.bloom.peak * interpolate(f * k, [0, 2.5, 3, 5.99], [0.1, 1, 1, 0], clampOpts);
  return (
    <AbsoluteFill
      style={{
        opacity: o,
        background: 'radial-gradient(circle at 50% 46%, #FFFBE8 0%, #FFE9B8 45%, rgba(255,233,184,0.0) 100%)',
        mixBlendMode: 'screen',
      }}
    />
  );
}

// local 0 = ending.discIn. The disc grows out of the closing iris circle, then slides to ending.discSlideX.
export function LogoDisc() {
  const t = useCurrentFrame();
  const {config, sources, theme, motion} = useKit();
  const E = {...motion.ending, ...config.ending};
  const fadeStart = E.discFadeStart - E.discIn;
  const discO = interpolate(t, [0, 3], [0, 1], clampOpts);
  const exit = interpolate(t, [fadeStart, fadeStart + E.discFadeFrames], [0, 1], clampOpts);
  const p = spring({frame: t, fps: config.fps, config: E.discSpring});
  const r = E.discStartR + (E.discR - E.discStartR) * p;
  const D = 2 * r;
  const ring = E.discRing;
  const logoSize = E.discLogoBase * (D / E.discLogoRef);
  // after growing, the full-size disc steps aside so the first vocab pill is never covered
  const slide = easeInOut((t - (E.discSlideStart - E.discIn)) / (E.discSlideEnd - E.discSlideStart));
  const cx0 = E.irisCentre[0] + (E.discCentre[0] - E.irisCentre[0]) * Math.min(1, p);
  const cx = cx0 + (E.discSlideX - E.discCentre[0]) * slide;
  const cy = E.irisCentre[1] + (E.discCentre[1] - E.irisCentre[1]) * Math.min(1, p);
  return (
    <AbsoluteFill
      style={{
        // the disc shrinks away (ease-in) while card 1 is already opaque underneath: no ghosted double exposure
        opacity: exit >= 1 ? 0 : 1,
        transform: `scale(${Math.max(0, 1 - exit * exit * (3 - 2 * exit) * 1.0)})`,
        transformOrigin: `${E.discSlideX}px ${E.discCentre[1]}px`,
      }}
    >
      <div
        style={{
          position: 'absolute',
          left: cx - D / 2,
          top: cy - D / 2,
          width: D,
          height: D,
          borderRadius: '50%',
          background: '#FFFDF8',
          border: `${ring}px solid ${theme.pink}`,
          boxSizing: 'border-box',
          boxShadow: E.discShadow,
          opacity: discO,
          overflow: 'hidden',
        }}
      >
        <Img
          src={staticFile(sources.logo)}
          style={{
            position: 'absolute',
            left: (D - ring * 2 - logoSize) / 2,
            top: (D - ring * 2 - logoSize) / 2,
            width: logoSize,
            height: logoSize,
            opacity: interpolate(t, [2, 5], [0, 1], clampOpts),
          }}
        />
      </div>
    </AbsoluteFill>
  );
}

// Starts right after the measured end of the last vocab word (ending.speechEndFrame); everything is quick because only a few
// fixed frames remain inside the main film; the end card (end_card frames) then simply holds the final state.
// t0 > 0: the standalone end-card composition starts at the join state of the main film.
export function EndPlate({t0 = 0}) {
  const frame = useCurrentFrame();
  const t = frame + t0;
  const {config, sources, theme, motion} = useKit();
  const plate = plateStyleOf(config, motion);
  const P = plate;
  // every timing number comes from plateFrame() (style v008 = the original plate, v010 = the approved v013 plate)
  const f = plateFrame(plate, t, (kind, fr) => spring({frame: fr, fps: config.fps, config: kind === 'logo' ? P.logoSpring : P.textSpring}));
  return (
    <AbsoluteFill>
      <AbsoluteFill style={{opacity: f.scrim}}>
        <Backdrop />
      </AbsoluteFill>
      <Img
        src={staticFile(sources.logo)}
        style={{
          display: f.logo.shown ? 'block' : 'none',
          position: 'absolute',
          left: 960 - P.logoSize / 2,
          top: P.logoTop,
          width: P.logoSize,
          height: P.logoSize,
          opacity: f.logo.opacity,
          transform: `scale(${f.logo.scale})`,
        }}
      />
      <div
        style={{
          position: 'absolute',
          left: 0,
          right: 0,
          top: P.enTop,
          display: 'flex',
          justifyContent: 'center',
          opacity: f.en.opacity,
          transform: `translateY(${(1 - f.en.k) * 22}px) scale(${0.88 + 0.12 * f.en.k})`,
        }}
      >
        <div
          style={{
            borderRadius: P.enRadius,
            padding: P.enPad,
            background: theme.pink,
            color: theme.white,
            fontSize: P.enSize,
            lineHeight: 1.05,
            fontWeight: 700,
            boxShadow: '0 16px 34px #FF2E7E45',
          }}
        >
          {config.ending.plateEn}
        </div>
      </div>
      <div
        style={{
          position: 'absolute',
          left: 0,
          right: 0,
          top: P.viTop,
          textAlign: 'center',
          color: theme.ink,
          fontSize: P.viSize,
          fontWeight: 700,
          opacity: f.vi.opacity,
        }}
      >
        {config.ending.plateVi}
      </div>
    </AbsoluteFill>
  );
}
