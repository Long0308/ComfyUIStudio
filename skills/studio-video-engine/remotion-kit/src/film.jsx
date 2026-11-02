// The Film composition: ONE config-driven compositor for review cuts (scale 1, labelled) and the 4K master (scale 2, no label).
// Props: {config, scale, label, sources}. The design canvas is always 1920x1080; the whole canvas is scaled by
// width/1920 so every vector element, caption and card renders natively at the target size.
import React, {useEffect, useMemo, useState} from 'react';
import {AbsoluteFill, Audio, Sequence, interpolate, cancelRender, continueRender, delayRender, staticFile, useCurrentFrame, useVideoConfig} from 'remotion';
import {KitProvider, useKit} from './context.jsx';
import {clampOpts, rendersAs} from './presets.mjs';
import {validateConfig, validateSources} from './validate.mjs';
import {Intro} from './intro.jsx';
import {Outro} from './cards.jsx';
import {KaraokeCaption} from './caption.jsx';
import {IconPop} from './icons.jsx';
import {DipPeak, ShotPicture, TailLayers} from './transitions.jsx';
import {Bloom, EndPlate, LogoDisc} from './ending.jsx';
import {MusicBed} from './music.jsx';
import {selectMusicMode} from './music-plan.mjs';

function ScaledCanvas({children}) {
  const {width} = useVideoConfig();
  const {sources, theme} = useKit();
  const [fontHandle] = useState(() => delayRender('Loading brand fonts'));
  useEffect(() => {
    Promise.all([document.fonts.load('400 31px StudioSans'), document.fonts.load('700 54px StudioSans')])
      .then(() => continueRender(fontHandle))
      .catch(cancelRender);
  }, [fontHandle]);
  const fontStyle = `
@font-face { font-family: StudioSans; src: url("${staticFile(sources.fonts.regular)}") format("truetype"); font-weight: 400; font-display: block; }
@font-face { font-family: StudioSans; src: url("${staticFile(sources.fonts.bold)}") format("truetype"); font-weight: 700; font-display: block; }
`;
  return (
    <AbsoluteFill style={{background: theme.paper, overflow: 'hidden'}}>
      <style>{fontStyle}</style>
      <AbsoluteFill
        style={{
          width: 1920,
          height: 1080,
          fontFamily: 'StudioSans, sans-serif',
          transform: `scale(${width / 1920})`,
          transformOrigin: 'top left',
        }}
      >
        {children}
      </AbsoluteFill>
    </AbsoluteFill>
  );
}

// small on-screen quality label: review cuts only (the master carries none, enforced by render.cjs)
function ReviewLabel({text}) {
  const {motion} = useKit();
  return (
    <div
      style={{
        position: 'absolute',
        top: motion.label.top,
        left: motion.label.left,
        zIndex: 100,
        borderRadius: 8,
        padding: '6px 12px 7px',
        background: '#143D38D9',
        color: '#FFFDF8',
        fontFamily: 'StudioSans',
        fontSize: motion.label.fontSize,
        lineHeight: 1,
        fontWeight: 700,
        letterSpacing: 0.2,
      }}
    >
      {text}
    </div>
  );
}

// shown when the picture bindings include preview-only sources (never on a real master, which refuses them)
function PreviewMark({text}) {
  const {motion} = useKit();
  return (
    <div
      style={{
        position: 'absolute',
        top: motion.previewMark.top,
        right: motion.previewMark.right,
        zIndex: 100,
        borderRadius: 8,
        padding: '6px 12px 7px',
        background: '#B3261ED9',
        color: '#FFFDF8',
        fontFamily: 'StudioSans',
        fontSize: motion.previewMark.fontSize,
        lineHeight: 1,
        fontWeight: 700,
        letterSpacing: 0.2,
      }}
    >
      {text}
    </div>
  );
}

function DialogueSlot({shot}) {
  const frame = useCurrentFrame(); // local frame inside the shot Sequence
  const {sources, tx} = useKit();
  return (
    <AbsoluteFill>
      <ShotPicture shot={shot} frame={frame} inT={tx.incoming(shot)} outT={tx.outgoing(shot)} />
      <KaraokeCaption shot={shot} />
      <Audio src={staticFile(sources.shots[shot.id].audio)} />
    </AbsoluteFill>
  );
}

function FilmBody({label, previewMark}) {
  const {config, sources, theme, motion} = useKit();
  const tl = config.timeline;
  const ending = config.ending;
  const total = tl.mainFrames + tl.endCardFrames;
  const E = {...motion.ending, ...ending};
  const hasIris = config.transitions.some((t) => rendersAs(t) === 'iris');
  const shotById = (id) => config.shots.find((s) => s.id === id);
  // 'plan' only when the config declares a music bed policy; otherwise the stem and the end-card tail play exactly as before
  const musicMode = selectMusicMode(config);
  return (
    <AbsoluteFill style={{background: theme.paper}}>
      {musicMode === 'plan' ? <MusicBed /> : <Audio src={staticFile(sources.music)} />}
      {sources.ambience ? <Audio src={staticFile(sources.ambience)} /> : null}
      {tl.introFrames > 0 ? (
        <Sequence durationInFrames={tl.introFrames}>
          <Intro />
        </Sequence>
      ) : null}
      <TailLayers />
      {config.shots.map((shot) => (
        <Sequence key={shot.id} from={shot.start} durationInFrames={shot.frames}>
          <DialogueSlot shot={shot} />
        </Sequence>
      ))}
      {config.transitions.filter((t) => rendersAs(t) === 'dip_white').map((t) => (
        <Sequence key={`dip${t.id}`} from={t.boundary} durationInFrames={motion.dip.peakFrames}>
          <DipPeak t={t} />
        </Sequence>
      ))}
      <Sequence from={tl.outroStart} durationInFrames={tl.outroFrames}>
        <Outro />
      </Sequence>
      {config.transitions.filter((t) => rendersAs(t) === 'bloom').map((t) => (
        <Sequence key={t.id} from={t.start} durationInFrames={t.frames}>
          <Bloom frames={t.frames} />
        </Sequence>
      ))}
      {config.icons.map((ev) => (
        <Sequence key={ev.id} from={ev.frame} durationInFrames={ev.totalFrames}>
          <IconPop ev={ev} src={sources.icons[ev.icon]} shot={shotById(ev.shot)} />
        </Sequence>
      ))}
      {hasIris ? (
        <Sequence from={E.discIn} durationInFrames={E.discFadeStart + E.discFadeFrames - E.discIn}>
          <LogoDisc />
        </Sequence>
      ) : null}
      {tl.endCardFrames > 0 && musicMode === 'legacy' ? (
        <Sequence from={tl.mainFrames} durationInFrames={tl.endCardFrames}>
          {/* End-card audio tail: the quiet resolving phrase of the music stem (from ending.tailFrom) replayed under the static
              logo, fade in / out per motion.ending. The main-film audio is untouched, so there is no cut. No dialogue. */}
          <Audio
            src={staticFile(sources.music)}
            startFrom={ending.tailFrom}
            volume={(f) => interpolate(f, [0, E.tailFadeIn, E.tailFadeStart, tl.endCardFrames], [0, 1, 1, 0], clampOpts)}
          />
        </Sequence>
      ) : null}
      {ending.plateStart !== undefined ? (
        <Sequence from={ending.plateStart} durationInFrames={total - ending.plateStart}>
          <EndPlate />
        </Sequence>
      ) : null}
      {label ? <ReviewLabel text={label} /> : null}
      {previewMark ? <PreviewMark text={previewMark} /> : null}
    </AbsoluteFill>
  );
}

function useValidated(config, sources, partial) {
  return useMemo(() => {
    validateConfig(config);
    validateSources(config, sources, {partial});
    return true;
  }, [config, sources, partial]);
}

export function Film({config, scale = 1, label = null, previewMark = null, sources, partial = false}) {
  useValidated(config, sources, partial);
  return (
    <KitProvider config={config} sources={sources} scale={scale}>
      <ScaledCanvas>
        <FilmBody label={label} previewMark={previewMark} />
      </ScaledCanvas>
    </KitProvider>
  );
}

// Standalone end card (same EndPlate component, starts at the join state of the main film, then static).
export function EndLogo({config, scale = 1, sources, partial = false}) {
  useValidated(config, sources, partial);
  return (
    <KitProvider config={config} sources={sources} scale={scale}>
      <ScaledCanvas>
        <EndLogoInner />
      </ScaledCanvas>
    </KitProvider>
  );
}

function EndLogoInner() {
  const {motion, theme} = useKit();
  return (
    <AbsoluteFill style={{background: theme.paper}}>
      <EndPlate t0={motion.ending.plateJoinT} />
    </AbsoluteFill>
  );
}
