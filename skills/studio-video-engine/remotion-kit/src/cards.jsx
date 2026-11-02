// Outro vocabulary flashcards. Frame-driven only. Audio windows are the config card windows (Sequence from / duration);
// only the visuals use a lead-in (motion.cards.lead) so the word has landed when the word audio starts.
import React from 'react';
import {AbsoluteFill, Audio, Img, Sequence, interpolate, staticFile, useCurrentFrame} from 'remotion';
import {clampOpts, easeOut} from './presets.mjs';
import {cardTimeline, ramp, springAt, useKit} from './context.jsx';

export function Dots() {
  return (
    <svg viewBox="0 0 1920 1080" style={{position: 'absolute', inset: 0, width: '100%', height: '100%'}} aria-hidden="true">
      {Array.from({length: 17}).map((_, row) =>
        Array.from({length: 28}).map((__, column) => (
          <circle key={`${row}-${column}`} cx={42 + column * 70} cy={48 + row * 64} r="3" fill="#90B8A9" opacity="0.26" />
        )),
      )}
    </svg>
  );
}

const wordSize = (term) => (term.length > 12 ? 104 : term.length > 8 ? 116 : 132);

// One flashcard unit: icon tile + text block, drawn as one centred unit.
function CardUnit({card, src, tl, frame, index}) {
  const {config, theme, motion} = useKit();
  const CARD = motion.cards;
  const fps = config.fps;
  const D = {term: 0, ipa: motion.stagger, vi: motion.stagger, example: motion.stagger * 2};
  const tTile = frame - tl.t0; // tile spring clock: runs from T0 (window start - lead; card 1 = window start)
  const tWin = frame - tl.start; // text clock: 0 = word audio window start
  const iconP = springAt(tTile, 0, fps, motion.spring.land);
  const pillP = springAt(tWin, D.term, fps, motion.spring.pill);
  const infoP = (delay) => springAt(tWin, delay, fps, motion.spring.settle);
  const ipaP = infoP(D.ipa);
  const viP = infoP(D.vi);
  const exP = infoP(D.example);
  const rampF = (f, d, len = CARD.fadeFrames) => ramp(f, d, len);

  // quiet during the hold: one slow push, total 1.000 -> pushTo across the window
  const push = interpolate(frame, [tl.start, tl.end], [1, CARD.pushTo], clampOpts);
  // the outgoing unit keeps its full hold to the window end, then lingers xfadeAfter frames sliding + fading (fast ease-out);
  // the incoming unit slides in over the same frames. The last card holds to the end.
  const xo = tl.last ? 0 : interpolate(frame, [tl.end, tl.end + CARD.xfadeAfter], [0, 1], clampOpts);
  const exit = easeOut(xo);
  const xi = index > 0 ? interpolate(frame, [tl.start, tl.start + CARD.xfadeAfter], [0, 1], clampOpts) : 1;
  const inX = (1 - easeOut(xi)) * CARD.inShift;
  // the pill is fully opaque ON the audio start frame (scale then lands over ~3 f); the outgoing pill is gone over the
  // last 2 frames of its window so the incoming opaque pill never sits on top of a bigger old pill
  const pillOut = tl.last ? 1 : interpolate(frame, [tl.end - 2, tl.end], [1, 0], clampOpts);
  const pillOpacity = (tWin >= D.term ? 1 : 0) * pillOut;

  return (
    <div
      style={{
        position: 'absolute',
        left: 0,
        right: 0,
        top: 0,
        bottom: 0,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        gap: CARD.gap,
        opacity: 1 - exit,
        transform: `translateX(${exit * CARD.xfadeShift + inX}px) scale(${push})`,
        paddingTop: 20,
      }}
    >
      <div
        style={{
          width: CARD.tile,
          height: CARD.tile,
          flex: `0 0 ${CARD.tile}px`,
          boxSizing: 'border-box',
          borderRadius: 60,
          background: theme.white,
          border: `6px solid ${theme.mintDeep}`,
          boxShadow: '0 28px 56px #173A3428',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          overflow: 'hidden',
          // keeps its spring/position from T0 but stays invisible until the outgoing card has gone
          opacity: ramp(frame, tl.start, CARD.tileFade),
          transform: `translateY(${(1 - iconP) * CARD.iconRise}px) scale(${CARD.iconScaleFrom + (1 - CARD.iconScaleFrom) * iconP})`,
        }}
      >
        <Img src={staticFile(src)} style={{width: CARD.tileImg, height: CARD.tileImg, objectFit: 'contain'}} />
      </div>
      <div
        style={{
          width: CARD.textCol,
          flex: `0 0 ${CARD.textCol}px`,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          textAlign: 'center',
          color: theme.ink,
        }}
      >
        <div
          style={{
            display: 'inline-flex',
            maxWidth: CARD.textCol,
            borderRadius: 56,
            padding: '20px 44px 26px',
            background: theme.pink,
            color: theme.white,
            boxShadow: '0 16px 34px #FF2E7E45',
            fontSize: wordSize(card.term),
            lineHeight: 1.02,
            fontWeight: 700,
            whiteSpace: 'nowrap',
            opacity: pillOpacity,
            transform: `translateY(${(1 - pillP) * CARD.pillRise}px) scale(${CARD.pillScaleFrom + (1 - CARD.pillScaleFrom) * pillP})`,
          }}
        >
          {card.term}
        </div>
        <div
          style={{
            marginTop: 22,
            fontSize: 46,
            lineHeight: 1.2,
            fontStyle: 'italic',
            opacity: rampF(tWin, D.ipa),
            transform: `translateY(${(1 - ipaP) * CARD.infoRise}px)`,
          }}
        >
          {card.ipa}
        </div>
        <div
          style={{
            marginTop: 10,
            fontSize: 62,
            lineHeight: 1.2,
            fontWeight: 700,
            opacity: rampF(tWin, D.vi),
            transform: `translateY(${(1 - viP) * CARD.infoRise}px)`,
          }}
        >
          {card.vi}
        </div>
        <div
          style={{
            marginTop: 18,
            fontSize: CARD.exampleFont,
            lineHeight: 1.12,
            textWrap: 'balance',
            opacity: rampF(tWin, D.example) * 0.92,
            transform: `translateY(${(1 - exP) * CARD.infoRise}px)`,
          }}
        >
          {card.exampleEn}
        </div>
      </div>
    </div>
  );
}

function Pips({activeIndex, count}) {
  const {theme, motion} = useKit();
  return (
    <div style={{position: 'absolute', left: 0, right: 0, top: motion.cards.pipsY, display: 'flex', justifyContent: 'center', gap: 18}}>
      {Array.from({length: count}).map((_, i) => (
        <div
          key={i}
          style={{
            width: i === activeIndex ? 44 : 18,
            height: 18,
            borderRadius: 9,
            background: i === activeIndex ? theme.pink : i < activeIndex ? theme.mintDeep : '#173A3426',
          }}
        />
      ))}
    </div>
  );
}

function Header({activeIndex, count, closing}) {
  const {config, theme, motion} = useKit();
  const CARD = motion.cards;
  const margin = (1920 - (CARD.tile + CARD.gap + CARD.textCol)) / 2;
  return (
    <div
      style={{
        position: 'absolute',
        left: margin,
        right: margin,
        top: CARD.headerY,
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        color: theme.ink,
      }}
    >
      <div style={{fontSize: CARD.headerFont, lineHeight: 1.1, fontWeight: 700}}>
        {closing ? config.strings.cardsHeaderClosing : config.strings.cardsHeader}
      </div>
      <div
        style={{
          borderRadius: 999,
          padding: '14px 28px',
          background: closing ? theme.pink : theme.ink,
          color: theme.white,
          fontSize: 36,
          lineHeight: 1,
          fontWeight: 700,
        }}
      >
        {String(activeIndex + 1).padStart(2, '0')} / {count}
      </div>
    </div>
  );
}

// Everything visual for the cards lives in one stage so background, header and pips stay put and only the unit swaps.
function CardStage() {
  const frame = useCurrentFrame(); // 0 = outro start
  const {config, sources, theme, motion} = useKit();
  const CARD = motion.cards;
  const cards = config.cards;
  const timelines = cards.map((_, i) => cardTimeline(cards, i, CARD.lead));
  const activeIndex = timelines.reduce((acc, tl, i) => (frame >= tl.start ? i : acc), 0);
  // a logo hold: cards[0].start > 0 frames of the outro block carry the plain backdrop only (the logo disc is drawn by the ending layer);
  // the background / header ramps then run from the first card. cards[0].start = 0 (no hold) is exactly the old behaviour.
  const base = cards.length ? cards[0].start : 0;
  if (frame < base) return <Backdrop />;
  const bgIn = base > 0 ? 1 : CARD.bgFade > 0 ? ramp(frame, 0, CARD.bgFade) : 1;
  const closing = activeIndex === cards.length - 1;
  // header / counter / pips ramp in over the first frames (the closing logo disc steps aside); pill and tile logic untouched
  const headerO = interpolate(frame - base, [0, CARD.headerRamp], [0.25, 1], clampOpts);
  return (
    <AbsoluteFill style={{background: theme.paper}}>
      <AbsoluteFill style={{opacity: bgIn, background: `linear-gradient(135deg, ${theme.mint} 0%, ${theme.paper} 54%, ${theme.peach} 120%)`}} />
      <AbsoluteFill style={{opacity: bgIn}}>
        <Dots />
      </AbsoluteFill>
      <div style={{opacity: headerO}}>
        <Header activeIndex={activeIndex} count={cards.length} closing={closing} />
      </div>
      {cards.map((card, i) => {
        const tl = timelines[i];
        if (frame < tl.t0 || (!tl.last && frame >= tl.end + CARD.xfadeAfter)) return null;
        return <CardUnit key={card.term} card={card} src={sources.cards[i].icon} tl={tl} frame={frame} index={i} />;
      })}
      <div style={{opacity: headerO}}>
        <Pips activeIndex={activeIndex} count={cards.length} />
      </div>
    </AbsoluteFill>
  );
}

export function Backdrop() {
  const {theme} = useKit();
  return (
    <AbsoluteFill style={{background: theme.paper}}>
      <AbsoluteFill style={{background: `linear-gradient(135deg, ${theme.mint} 0%, ${theme.paper} 54%, ${theme.peach} 120%)`}} />
      <AbsoluteFill>
        <Dots />
      </AbsoluteFill>
    </AbsoluteFill>
  );
}

export function Outro() {
  const {config, sources} = useKit();
  return (
    <AbsoluteFill>
      <CardStage />
      {config.cards.map((card, i) => (
        <Sequence key={card.term} from={card.start} durationInFrames={card.frames}>
          <Audio src={staticFile(sources.cards[i].audio)} />
        </Sequence>
      ))}
    </AbsoluteFill>
  );
}
