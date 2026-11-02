// Picture layer: whip pans (single copy + edge extender), dip-to-white, tail-only dissolve / cloud / bubble wipes (legal only
// with continuity 'agree'), iris-out. What is drawn on a frame is decided by pictureMode() (picture-mode.mjs), the same
// function the per-frame audit uses. All values are pure functions of the frame; the only randomness is a fixed seed.
import React from 'react';
import {AbsoluteFill, OffthreadVideo, Sequence, staticFile, useCurrentFrame} from 'remotion';
import {easeInOut, overlayOf, presetName, presetOf, rendersAs, resolveParams, scheduleOf, seeded} from './presets.mjs';
import {dipEntry, paramsOf, pictureMode, tailLayers, whipCoverage, whipGeometry} from './picture-mode.mjs';
import {DESCRIPTOR_KINDS, descriptor, dipDescriptor, outAbove} from './catalog-render.mjs';
import {DipOverlay, LayerFx} from './overlays.jsx';
import {Backdrop} from './cards.jsx';
import {useKit} from './context.jsx';

const coverStyle = {width: '100%', height: '100%', objectFit: 'cover'};

function Video({src, startFrom}) {
  // objectFit cover: aspect preserved, a native 864x480 (1.80) source is cropped ~0.74 % per side at 1.778
  return <OffthreadVideo src={staticFile(src)} style={coverStyle} muted startFrom={startFrom} />;
}

export function Segments({shot}) {
  const {sources} = useKit();
  const files = sources.shots[shot.id].segments;
  return (
    <>
      {shot.segments.map((segment) => (
        <Sequence key={segment.id} from={segment.from} durationInFrames={segment.frames}>
          <Video src={files[segment.id]} />
        </Sequence>
      ))}
    </>
  );
}

// masked wipes share ONE mask/ring pipeline. kind 'cloud' = seeded cloud-bump front sweeping across (direction +1 = left to
// right, -1 = right to left); kind 'bubble' = radial splash wipe around spec.centre. Both need continuity 'agree'.
const bumpCache = new Map();
function cloudBumps(seed, count) {
  const key = `c${seed}:${count}`;
  if (!bumpCache.has(key)) {
    const rnd = seeded(seed);
    bumpCache.set(key, Array.from({length: count}).map((_, i) => ({y: -40 + i * 125 + rnd() * 30, dx: (rnd() - 0.5) * 150, r: 120 + rnd() * 80})));
  }
  return bumpCache.get(key);
}
function bubbleSet(seed, count) {
  const key = `b${seed}:${count}`;
  if (!bumpCache.has(key)) {
    const rnd = seeded(seed);
    bumpCache.set(key, Array.from({length: count}).map((_, i) => ({a: (i / count) * Math.PI * 2 + (rnd() - 0.5) * 0.25, r: 45 + rnd() * 55})));
  }
  return bumpCache.get(key);
}

export function cloudFront(u) {
  return -360 + easeInOut(u) * (1920 + 760);
}
export function bubbleRadius(u) {
  return -40 + easeInOut(u) * 1400;
}

const circlesSvg = (bumps, front, grow) =>
  bumps.map((c) => `<circle cx="${(front + c.dx).toFixed(1)}" cy="${c.y.toFixed(1)}" r="${(c.r + grow).toFixed(1)}"/>`).join('');
const slabSvg = (front, extra) =>
  `<rect x="-400" y="-10" width="${(front - 120 + 400 + extra).toFixed(1)}" height="1100"/>`;

function shapeFor(spec, u, wipe) {
  if (spec.kind === 'bubble') {
    const R = bubbleRadius(u);
    const bubbles = bubbleSet(spec.seed, wipe.bubbleCount);
    return (grow) => {
      if (R + grow <= 0) return '';
      const [cx, cy] = spec.centre;
      const dots = bubbles
        .map((b) => `<circle cx="${(cx + R * Math.cos(b.a)).toFixed(1)}" cy="${(cy + R * Math.sin(b.a)).toFixed(1)}" r="${(b.r + grow).toFixed(1)}"/>`)
        .join('');
      return `<circle cx="${cx}" cy="${cy}" r="${(R + grow).toFixed(1)}"/>${dots}`;
    };
  }
  const front = cloudFront(u);
  const bumps = cloudBumps(spec.seed, spec.straight ? 0 : wipe.cloudBumps); // 'wipe' = the cloud front without bumps (straight soft edge)
  return (grow) => {
    const body = slabSvg(front, grow > 0 ? grow + 2 : 0) + circlesSvg(bumps, front, grow);
    return spec.dir < 0 ? `<g transform="matrix(-1 0 0 1 1920 0)">${body}</g>` : body;
  };
}

function maskUri(shape, wipe) {
  const svg =
    '<svg xmlns="http://www.w3.org/2000/svg" width="1920" height="1080" viewBox="0 0 1920 1080">' +
    '<defs><filter id="b" x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur stdDeviation="' + wipe.maskBlur + '"/></filter></defs>' +
    `<g filter="url(#b)" fill="#fff">${shape(0)}</g></svg>`;
  return `url("data:image/svg+xml;utf8,${encodeURIComponent(svg)}")`;
}

function WipeRing({shape, strength, wipe}) {
  return (
    <svg viewBox="0 0 1920 1080" style={{position: 'absolute', inset: 0, width: '100%', height: '100%', opacity: strength}}>
      <defs>
        <filter id="cb" x="-20%" y="-20%" width="140%" height="140%">
          <feGaussianBlur stdDeviation={wipe.ringBlur} />
        </filter>
        <mask id="hole">
          <rect x="0" y="0" width="1920" height="1080" fill="#fff" />
          <g fill="#000" dangerouslySetInnerHTML={{__html: shape(-2)}} />
        </mask>
      </defs>
      <g mask="url(#hole)" filter="url(#cb)" fill="#FFFFFF" dangerouslySetInnerHTML={{__html: shape(wipe.ringGrow)}} />
    </svg>
  );
}

// The moving layer is ONE full copy of the shot. The side exposed by the translation is filled by an edge extender: the shot's
// edge columns flipped (scaleX(-K)) and stretched ~K times, i.e. smeared edge pixels. The strip's box comes from whipGeometry()
// and must lie outside the shot rect, so no character is ever duplicated in the visible area (asserted below on the box used).
function WhipTiles({shot, offset, blur, zoomK, frame}) {
  const {motion} = useKit();
  const id = `wb${frame}`;
  const z = 1 + (motion.whip.zoom - 1) * zoomK;
  const geo = whipGeometry(offset, motion);
  if (!geo.outside) throw new Error(`whip extender strip overlaps the shot rect (offset ${offset})`);
  const cov = whipCoverage(offset, zoomK, motion); // the strip rendered below must really reach the canvas border
  if (!cov.covered) throw new Error(`whip extender strip does not cover the exposed ${cov.side} side by ${cov.gapPx.toFixed(1)} px (offset ${offset}, zoomK ${zoomK})`);
  const right = geo.right; // picture moved left -> the right side is exposed
  const W = geo.strip.width;
  const K = motion.whip.extend;
  return (
    <AbsoluteFill style={{filter: `url(#${id})`}}>
      <svg width="0" height="0" style={{position: 'absolute'}}>
        <defs>
          <filter id={id} filterUnits="userSpaceOnUse" x="-600" y="-40" width="3120" height="1160">
            <feGaussianBlur stdDeviation={`${blur} 0`} />
          </filter>
        </defs>
      </svg>
      <AbsoluteFill style={{transform: `translateX(${offset}px) scale(${z})`}}>
        <AbsoluteFill>
          <Segments shot={shot} />
        </AbsoluteFill>
        <div style={{position: 'absolute', top: 0, height: 1080, width: W, left: geo.strip.left, overflow: 'hidden'}}>
          <div
            style={{
              position: 'absolute',
              top: 0,
              width: 1920,
              height: 1080,
              left: right ? -1920 : W,
              transformOrigin: right ? '100% 0' : '0 0',
              transform: `scaleX(${-K})`,
            }}
          >
            <Segments shot={shot} />
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
}

// Dip-to-white: the outgoing shot brightens (exposure + a little glow) to pure white, the incoming shot emerges from white.
// In every frame at most ONE shot is visible (the schedule comes from config.transitions[].schedule; the per-frame
// assertion is auditPictureLayers() in picture-mode.mjs, run by the Film at mount and by the tests).
// The look of a frame comes from dipDescriptor(): the white dip keeps the config-overridable motion.dip.colour, dip_black dims instead of
// brightening, light_leak / film_burn draw seeded radial overlays (seed = the boundary frame).
function DipFrame({white, t, children}) {
  const {motion} = useKit();
  const d = dipDescriptor(overlayOf(t), white, motion, t.boundary);
  return (
    <AbsoluteFill>
      <AbsoluteFill style={{filter: `brightness(${d.brightness.toFixed(3)}) blur(${d.blurPx.toFixed(2)}px)`}}>{children}</AbsoluteFill>
      <DipOverlay spec={d.overlay} />
    </AbsoluteFill>
  );
}

// The outgoing native tail as a descriptor-driven layer: `t` = the local frame inside its Sequence (window frame), so the descriptor of
// the very frame the audit checked is applied to the tail video.
function TailDescLayer({tr, src, frame}) {
  const d = descriptor(presetName(tr), paramsOf(tr), tr.frames, tr.direction, frame);
  if (!d) return null;
  return (
    <LayerFx d={d.out} perspectivePx={d.perspectivePx}>
      <Video src={src} startFrom={tr.tail.startFrom} />
    </LayerFx>
  );
}

function TailDescInner({tr, src}) {
  return <TailDescLayer tr={tr} src={src} frame={useCurrentFrame()} />;
}

// The incoming shot drawn as its descriptor says. For the kinds whose outgoing picture sits ABOVE the incoming one (zoom_out) the
// outgoing tail is mounted here, in the same stack, so it never covers the caption layer that follows this picture.
function DescPicture({mode, shot}) {
  const {sources} = useKit();
  const tr = mode.transition;
  return (
    <AbsoluteFill>
      <LayerFx d={mode.d} perspectivePx={mode.perspectivePx}>
        <Segments shot={shot} />
      </LayerFx>
      {mode.outAbove && mode.out.visible ? (
        <LayerFx d={mode.out}>
          <Video src={sources.tails[tr.id]} startFrom={tr.tail.startFrom} />
        </LayerFx>
      ) : null}
    </AbsoluteFill>
  );
}

// frame = local frame in the shot Sequence; inT / outT = transition rows or undefined
export function ShotPicture({shot, frame, inT, outT}) {
  const {config, motion} = useKit();
  const mode = pictureMode({shot, frame, inT, outT, ending: config.ending, motion});
  switch (mode.kind) {
    case 'hidden':
      return null;
    case 'dip':
      return (
        <DipFrame white={mode.white} t={mode.t}>
          <Segments shot={shot} />
        </DipFrame>
      );
    case 'desc':
      return <DescPicture mode={mode} shot={shot} />;
    case 'whip':
      return <WhipTiles shot={shot} offset={mode.offset} blur={mode.blur} zoomK={mode.zoomK} frame={mode.frame} />;
    case 'dissolve':
      return (
        <AbsoluteFill style={{opacity: mode.opacity}}>
          <Segments shot={shot} />
        </AbsoluteFill>
      );
    case 'mask': {
      const shape = shapeFor(mode.spec, mode.u, motion.wipe);
      const mask = maskUri(shape, motion.wipe);
      const ring = Math.min(1, Math.max(0, Math.sin(Math.PI * mode.u) * 1.6));
      return (
        <AbsoluteFill>
          <AbsoluteFill
            style={{
              WebkitMaskImage: mask,
              maskImage: mask,
              WebkitMaskSize: '100% 100%',
              maskSize: '100% 100%',
              WebkitMaskRepeat: 'no-repeat',
              maskRepeat: 'no-repeat',
            }}
          >
            <Segments shot={shot} />
          </AbsoluteFill>
          <WipeRing shape={shape} strength={ring} wipe={motion.wipe} />
        </AbsoluteFill>
      );
    }
    case 'backdrop':
      return <Backdrop />;
    case 'iris': {
      const e = config.ending;
      const m = motion.ending;
      const end = e.irisEndRadius !== undefined ? e.irisEndRadius : m.irisEndRadius;
      const R = m.irisStartRadius + (end - m.irisStartRadius) * mode.u;
      const [cx, cy] = e.irisCentre;
      const mask = `radial-gradient(circle at ${cx}px ${cy}px, #000 ${R}px, rgba(0,0,0,0) ${R + 5}px)`;
      return (
        <AbsoluteFill>
          <Backdrop />
          <AbsoluteFill style={{WebkitMaskImage: mask, maskImage: mask}}>
            <Segments shot={shot} />
          </AbsoluteFill>
        </AbsoluteFill>
      );
    }
    default:
      return <Segments shot={shot} />;
  }
}

// tail-only layer: the outgoing clip keeps playing on its native tail frames
function TailDipInner({t, src}) {
  const f = useCurrentFrame();
  const e = dipEntry(t, f);
  return (
    <DipFrame white={e ? e.white : 1} t={t}>
      <Video src={src} startFrom={t.tail.startFrom} />
    </DipFrame>
  );
}

export function TailLayers() {
  const {config, sources} = useKit();
  return (
    <>
      {tailLayers(config).filter(({t}) => !outAbove(rendersAs(t))).map(({t, from, frames}) => (
        <Sequence key={t.id} from={from} durationInFrames={frames}>
          {rendersAs(t) === 'dip_white' ? (
            <TailDipInner t={t} src={sources.tails[t.id]} />
          ) : DESCRIPTOR_KINDS.includes(rendersAs(t)) ? (
            <TailDescInner tr={t} src={sources.tails[t.id]} />
          ) : (
            <AbsoluteFill>
              <Video src={sources.tails[t.id]} startFrom={t.tail.startFrom} />
            </AbsoluteFill>
          )}
        </Sequence>
      ))}
    </>
  );
}

// pure-white peak frame + a tiny seeded sparkle burst around it (cartoon touch)
export function DipPeak({t}) {
  const f = useCurrentFrame(); // 0 = boundary frame B (sequence starts at B)
  const {motion} = useKit();
  const d = motion.dip;
  const peak = scheduleOf(t).find((e) => e.white === 1);
  const pure = dipDescriptor(overlayOf(t), 1, motion, t.boundary).overlay; // the pure-colour frame: flat colour, or the leak / burn base
  const flat = pure.kind === 'colour' ? pure.colour : pure.base;
  const sparkles = resolveParams(presetOf(t), t.params).sparkles !== false ? d.sparkles : 0; // params.sparkles false: no burst
  const rnd = seeded(t.boundary);
  const stars = Array.from({length: sparkles}).map(() => ({x: 160 + rnd() * 1600, y: 120 + rnd() * 760, s: 38 + rnd() * 40, c: rnd() < 0.5}));
  const k = f - peak.t; // frames around the white peak
  const op = Math.abs(k) <= d.peakSpan ? 1 - Math.abs(k) * 0.45 : 0;
  return (
    <AbsoluteFill>
      {f === peak.t ? <AbsoluteFill style={{background: flat}} /> : null}
      {stars.map((st, i) => (
        <svg key={i} width={st.s} height={st.s} viewBox="-10 -10 20 20" style={{position: 'absolute', left: st.x, top: st.y, opacity: op}}>
          <path d="M0 -10 L2.6 -2.6 L10 0 L2.6 2.6 L0 10 L-2.6 2.6 L-10 0 L-2.6 -2.6 Z" fill={st.c ? '#FFD84D' : '#FF2E7E'} />
        </svg>
      ))}
    </AbsoluteFill>
  );
}
