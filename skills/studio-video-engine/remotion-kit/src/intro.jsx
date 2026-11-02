// Intro (frames 0 .. timeline.introFrames-1). Frame-driven only. All texts come from config.intro; layout and timing are
// presets (motion.intro / motion.spring).
import React from 'react';
import {AbsoluteFill, Img, interpolate, staticFile, useCurrentFrame} from 'remotion';
import {clampOpts} from './presets.mjs';
import {ramp, springAt, useKit} from './context.jsx';

function DropMark({size}) {
  const {theme} = useKit();
  return (
    <svg width={size} height={size * 1.2} viewBox="0 0 180 216" aria-hidden="true" style={{filter: 'drop-shadow(0 20px 24px #06251F55)'}}>
      <path d="M90 8 C72 48 26 88 26 137 C26 178 55 207 90 207 C126 207 154 178 154 137 C154 88 108 48 90 8Z" fill={theme.white} />
      <path
        d="M54 138 C54 164 70 183 92 189 C70 194 48 177 44 155 C40 137 49 117 63 105 C56 117 54 127 54 138Z"
        fill="#C8EDEB"
        opacity="0.9"
      />
      <circle cx="67" cy="72" r="13" fill={theme.white} opacity="0.5" />
    </svg>
  );
}

// One text element: rises into place with a spring and fades in over motion.cards.fadeFrames.
function Rise({delay, children, style}) {
  const frame = useCurrentFrame();
  const {config, motion} = useKit();
  const p = springAt(frame, delay, config.fps, motion.spring.land);
  return (
    <div style={{opacity: ramp(frame, delay, motion.cards.fadeFrames), transform: `translateY(${(1 - p) * motion.intro.textRise}px)`, ...style}}>
      {children}
    </div>
  );
}

export function Intro() {
  const frame = useCurrentFrame();
  const {config, sources, theme, motion} = useKit();
  const I = motion.intro;
  const n = config.timeline.introFrames;
  const intro = config.intro;
  const fps = config.fps;
  // quiet during the hold: one slow push-out that ENDS at 1.00 (the framing of the first dialogue shot)
  const bgScale = interpolate(frame, [0, n], [I.bgScaleFrom, 1], clampOpts);
  const scrim = ramp(frame, 0, I.scrimFade);
  const exitStart = n - I.exitFrames;
  const textOut = interpolate(frame, [exitStart, exitStart + I.exitFrames], [1, 0], clampOpts);
  const dropP = springAt(frame, I.dropDelay, fps, motion.spring.land);
  const dropY = (1 - dropP) * I.dropRise;
  const dropRot = (1 - dropP) * -10;
  const lineDelay = (i) => (i < I.lineDelays.length ? I.lineDelays[i] : I.lineDelays[I.lineDelays.length - 1] + (i - I.lineDelays.length + 1) * I.lineStep);

  return (
    <AbsoluteFill style={{background: theme.night, overflow: 'hidden'}}>
      <Img src={staticFile(sources.opening)} style={{width: '100%', height: '100%', objectFit: 'cover', transform: `scale(${bgScale})`}} />
      {/* top-left scrim behind title */}
      <AbsoluteFill
        style={{
          inset: '0 auto auto 0',
          width: '58%',
          height: 520,
          opacity: scrim * textOut,
          WebkitMaskImage: 'linear-gradient(180deg, #000 0%, #000 72%, #0000 100%)',
          maskImage: 'linear-gradient(180deg, #000 0%, #000 72%, #0000 100%)',
          background: `linear-gradient(90deg, ${theme.scrim}EA 0%, ${theme.scrim}BF 58%, ${theme.scrim}00 100%)`,
        }}
      />
      {/* bottom-left scrim: contrast for the footer line */}
      <AbsoluteFill
        style={{
          inset: 'auto auto 0 0',
          width: '52%',
          height: 300,
          opacity: scrim * textOut,
          background: `radial-gradient(ellipse 100% 100% at 0% 100%, ${theme.scrim}CC 0%, ${theme.scrim}66 50%, ${theme.scrim}00 100%)`,
        }}
      />
      <AbsoluteFill
        style={{
          opacity: textOut,
          padding: '106px 74px 58px',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'space-between',
        }}
      >
        <div style={{width: 780, maxWidth: '43%', display: 'flex', alignItems: 'flex-start', gap: 30}}>
          {intro.mark === 'drop' ? (
            <div
              style={{
                opacity: ramp(frame, I.dropDelay, motion.cards.fadeFrames),
                transform: `translateY(${dropY}px) rotate(${dropRot}deg)`,
                transformOrigin: '50% 80%',
                flex: '0 0 150px',
              }}
            >
              <DropMark size={150} />
            </div>
          ) : null}
          <div style={{width: 600, maxWidth: '100%'}}>
            <Rise
              delay={I.kicker}
              style={{color: theme.sky, fontSize: 28, lineHeight: 1.1, fontWeight: 700, letterSpacing: 0, marginBottom: 14}}
            >
              {intro.kicker}
            </Rise>
            <div
              style={{
                color: theme.white,
                fontSize: 118,
                lineHeight: 0.94,
                fontWeight: 700,
                letterSpacing: 0,
                textShadow: '0 12px 34px #06251F66',
              }}
            >
              {intro.titleLines.map((line, i) => (
                <Rise key={i} delay={lineDelay(i)}>
                  {line}
                </Rise>
              ))}
            </div>
            <Rise delay={I.pill}>
              <div
                style={{
                  marginTop: 24,
                  maxWidth: 560,
                  display: 'inline-flex',
                  alignItems: 'center',
                  borderRadius: 999,
                  padding: '14px 22px 15px',
                  backgroundColor: theme.pink,
                  color: theme.white,
                  fontSize: 27,
                  lineHeight: 1.12,
                  fontWeight: 700,
                }}
              >
                {intro.pill}
              </div>
            </Rise>
          </div>
        </div>
        <Rise delay={I.footer} style={{display: 'flex', alignItems: 'flex-end', maxWidth: 760}}>
          <div
            style={{
              borderRadius: 999,
              padding: '13px 28px 15px',
              background: `${theme.scrim}F2`,
              color: theme.white,
              fontSize: 30,
              lineHeight: 1.15,
              fontWeight: 700,
              boxShadow: '0 8px 22px #06251F66',
            }}
          >
            {intro.footer}
          </div>
        </Rise>
      </AbsoluteFill>
      <Img
        src={staticFile(sources.logo)}
        style={{
          position: 'absolute',
          top: 24,
          right: 30,
          width: 132,
          height: 132,
          objectFit: 'contain',
          opacity: ramp(frame, I.logo, 8),
        }}
      />
    </AbsoluteFill>
  );
}
