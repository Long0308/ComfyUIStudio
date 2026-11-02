// Karaoke caption: the full line is laid out from the word timing; each word lights and pops on its start frame (GLOBAL
// frame minus the shot start = local frame), spoken words stay lit, keyword words use the pink accent. Every value is a
// function of useCurrentFrame(): no setTimeout / Date.now / CSS animation.
import React from 'react';
import {interpolate, useCurrentFrame} from 'remotion';
import {clampOpts, mixHex} from './presets.mjs';
import {useKit} from './context.jsx';

function Word({word, shotStart, nextStart, frame, cap}) {
  const local = word.startF - shotStart;
  const dt = frame - local;
  const lit = interpolate(dt, [0, cap.fillFrames], [0, 1], clampOpts);
  const pop = interpolate(dt, [0, cap.popPeakAt, cap.popFrames], [1, cap.popScale, 1], clampOpts);
  const activeEnd = Math.max(word.endF, word.startF + cap.popFrames) - shotStart;
  const active = dt >= 0 && frame < Math.min(activeEnd, nextStart - shotStart + 4) ? 1 : 0;
  const base = {
    display: 'inline-block',
    borderRadius: 14,
    padding: cap.pad,
    margin: cap.margin,
    transform: `scale(${pop})`,
    transformOrigin: '50% 70%',
    fontWeight: 700,
  };
  if (word.keyword) {
    return (
      <span
        style={{
          ...base,
          fontSize: '1.08em',
          lineHeight: 1.18,
          background: mixHex(cap.kwUnspokenBg, cap.kwBg, lit),
          color: mixHex(cap.kwUnspokenText, cap.kwText, lit),
          boxShadow: lit > 0 ? `0 6px 14px rgba(255,46,126,${0.28 * lit})` : 'none',
        }}
      >
        {word.w}
      </span>
    );
  }
  return (
    <span style={{...base, background: active ? cap.activeBg : 'transparent', color: mixHex(cap.unspoken, cap.spoken, lit)}}>
      {word.w}
    </span>
  );
}

export function KaraokeCaption({shot}) {
  const frame = useCurrentFrame();
  const {config, theme, motion} = useKit();
  const cap = motion.caption;
  if (!shot.words || shot.words.length === 0) {
    throw new Error(`caption: no word timing for ${shot.id} (no whole-line fallback by design)`);
  }
  const hideAt = Math.min(shot.frames, Math.ceil((shot.speechEndS + cap.hideAfterS) * config.fps));
  const opacity = Math.min(
    interpolate(frame, [0, cap.fadeIn], [0, 1], clampOpts),
    interpolate(frame, [hideAt - cap.fadeOut, hideAt], [1, 0], clampOpts),
  );
  if (opacity <= 0) return null;
  return (
    <div
      style={{
        position: 'absolute',
        left: cap.side,
        right: cap.side,
        bottom: cap.bottom,
        opacity,
        borderRadius: 30,
        background: '#FFFDF8F2',
        padding: '16px 36px 18px',
        textAlign: 'center',
        boxShadow: '0 12px 34px #061F1B66',
        color: theme.ink,
      }}
    >
      <div style={{fontSize: cap.fontEn, lineHeight: 1.3, fontWeight: 700}}>
        {shot.words.map((word, i) => (
          <React.Fragment key={i}>
            <Word
              word={word}
              shotStart={shot.start}
              nextStart={i + 1 < shot.words.length ? shot.words[i + 1].startF : shot.start + shot.frames}
              frame={frame}
              cap={cap}
            />
            {' '}
          </React.Fragment>
        ))}
      </div>
      <div style={{marginTop: 6, fontSize: cap.fontVi, lineHeight: 1.25, fontWeight: 400}}>{shot.vi}</div>
    </div>
  );
}
