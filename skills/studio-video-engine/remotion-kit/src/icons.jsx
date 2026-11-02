// Vocabulary icon pop on the spoken word. Mounted by a Sequence whose `from` is the event frame. spring scale-in with a
// small overshoot, hold, soft fade, seeded sparkles (a few frames). Placement clears the caption panel of the shot.
import React from 'react';
import {Img, interpolate, spring, staticFile, useCurrentFrame} from 'remotion';
import {clampOpts, seeded} from './presets.mjs';
import {useKit} from './context.jsx';

function Sparkles({frame, seed}) {
  const {theme, motion} = useKit();
  const ICON = motion.icon;
  const rnd = seeded(seed);
  const n = ICON.sparkleCount;
  return (
    <>
      {Array.from({length: n}).map((_, i) => {
        const ang = (i / n) * Math.PI * 2 + rnd() * 0.5;
        const dist = ICON.box * (0.62 + rnd() * 0.12);
        const size = 22 + rnd() * 12;
        const t = interpolate(frame, [2, ICON.sparkleFrames + 2], [0, 1], clampOpts);
        const op = t <= 0 || t >= 1 ? 0 : Math.sin(Math.PI * t);
        const x = Math.cos(ang) * dist * (0.7 + 0.3 * t);
        const y = Math.sin(ang) * dist * (0.7 + 0.3 * t);
        return (
          <svg
            key={i}
            width={size}
            height={size}
            viewBox="-10 -10 20 20"
            style={{position: 'absolute', left: ICON.box / 2 + x - size / 2, top: ICON.box / 2 + y - size / 2, opacity: op}}
          >
            <path d="M0 -10 L2.6 -2.6 L10 0 L2.6 2.6 L0 10 L-2.6 2.6 L-10 0 L-2.6 -2.6 Z" fill={i % 2 ? '#FFD84D' : theme.pink} />
          </svg>
        );
      })}
    </>
  );
}

export function IconPop({ev, src, shot}) {
  const frame = useCurrentFrame(); // 0 = pop frame
  const {config, theme, motion} = useKit();
  const ICON = motion.icon;
  const p = spring({frame, fps: config.fps, config: ICON.spring});
  const hold = ev.holdFrames !== undefined ? ev.holdFrames : ICON.hold;
  const fadeLen = ev.fadeFrames !== undefined ? ev.fadeFrames : ICON.fade;
  const exitStart = hold + 6; // 6 f of spring settle counted in, then hold
  const fade = interpolate(frame, [exitStart, exitStart + fadeLen], [1, 0], clampOpts);
  const scale = (0.2 + 0.8 * p) * (1 - 0.08 * (1 - fade));
  const rot = (1 - p) * ICON.rotateFrom;
  const capH = ICON.capHeight[shot.captionLines];
  const bottom = motion.caption.bottom + capH + ICON.gap;
  return (
    <div
      style={{
        position: 'absolute',
        right: motion.caption.side,
        bottom,
        width: ICON.box,
        height: ICON.box,
        opacity: Math.min(1, frame * 0.5 + 0.2) * fade,
        transform: `scale(${scale}) rotate(${rot}deg)`,
        transformOrigin: '50% 100%',
      }}
    >
      <div
        style={{
          position: 'absolute',
          inset: 0,
          borderRadius: '50%',
          background: '#FFFDF8F2',
          border: `6px solid ${theme.mintDeep}`,
          boxSizing: 'border-box',
          boxShadow: '0 14px 30px #061F1B55',
        }}
      />
      <Img
        src={staticFile(src)}
        style={{position: 'absolute', left: -ICON.box * 0.12, top: -ICON.box * 0.12, width: ICON.box * 1.24, height: ICON.box * 1.24, objectFit: 'contain', clipPath: 'circle(48% at 50% 50%)'}}
      />
      <Sparkles frame={frame} seed={ICON.sparkleSeed + ev.frame} />
    </div>
  );
}
