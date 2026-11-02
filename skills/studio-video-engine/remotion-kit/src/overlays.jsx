// Generic React layers for the catalog-driven transitions: LayerFx applies one descriptor (catalog-render.mjs) to a picture, DipOverlay draws
// the dip family's overlay (flat colour, seeded light leak, film burn). No decision lives here: every number comes from the pure
// descriptor, so what is drawn is exactly what the audit checked. All lengths are px of the 1920x1080 design canvas.
import React from 'react';
import {AbsoluteFill} from 'remotion';

// descriptor clip -> CSS. circle: a soft radial mask (like the ending iris); diamond / polygon: clip-path polygon; rects: one path of slats.
export function clipStyle(clip) {
  if (clip === null || clip === undefined) return {};
  if (clip.kind === 'circle') {
    const mask = `radial-gradient(circle at ${clip.cx.toFixed(2)}px ${clip.cy.toFixed(2)}px, #000 ${Math.max(0, clip.r).toFixed(2)}px, rgba(0,0,0,0) ${(Math.max(0, clip.r) + Math.max(0.5, clip.soft)).toFixed(2)}px)`;
    return {WebkitMaskImage: mask, maskImage: mask};
  }
  if (clip.kind === 'diamond') {
    const {cx, cy, d} = clip;
    return {clipPath: `polygon(${cx}px ${cy - d}px, ${cx + d}px ${cy}px, ${cx}px ${cy + d}px, ${cx - d}px ${cy}px)`};
  }
  if (clip.kind === 'polygon') return {clipPath: `polygon(${clip.points.map(([x, y]) => `${x.toFixed(2)}px ${y.toFixed(2)}px`).join(', ')})`};
  const path = clip.rects.map((r) => `M${r.x.toFixed(2)} ${r.y.toFixed(2)}h${r.w.toFixed(2)}v${r.h.toFixed(2)}h${(-r.w).toFixed(2)}z`).join('');
  return {clipPath: `path('${path}')`};
}

export function layerStyle(d, perspectivePx) {
  const parts = [];
  if (perspectivePx) parts.push(`perspective(${perspectivePx}px)`);
  parts.push(`translate(${d.tx}px, ${d.ty}px)`);
  if (d.rotX) parts.push(`rotateX(${d.rotX.toFixed(3)}deg)`);
  if (d.rotY) parts.push(`rotateY(${d.rotY.toFixed(3)}deg)`);
  if (d.scale !== 1) parts.push(`scale(${d.scale.toFixed(4)})`);
  const filters = [];
  if (d.blurPx > 0) filters.push(`blur(${d.blurPx.toFixed(2)}px)`);
  if (d.brightness !== 1) filters.push(`brightness(${d.brightness.toFixed(3)})`);
  return {opacity: d.opacity, transform: parts.join(' '), ...(filters.length ? {filter: filters.join(' ')} : {}), ...clipStyle(d.clip)};
}

// one picture (the incoming shot, or the outgoing native tail) drawn as its descriptor says; hidden when the descriptor says so
export function LayerFx({d, perspectivePx, children}) {
  if (!d.visible) return null;
  return <AbsoluteFill style={layerStyle(d, perspectivePx)}>{children}</AbsoluteFill>;
}

// the dip family's overlay over the picture (dipDescriptor().overlay)
export function DipOverlay({spec}) {
  if (spec.kind === 'colour') return <AbsoluteFill style={{background: spec.colour, opacity: spec.opacity}} />;
  return (
    <AbsoluteFill style={{opacity: spec.opacity}}>
      <AbsoluteFill style={{background: spec.base, opacity: spec.baseOpacity}} />
      {spec.blobs.map((b, i) => (
        <AbsoluteFill
          key={i}
          style={{
            background: `radial-gradient(circle at ${b.x.toFixed(1)}px ${b.y.toFixed(1)}px, ${b.colour} 0px, ${b.colour}00 ${b.r.toFixed(1)}px)`,
            mixBlendMode: spec.blend,
          }}
        />
      ))}
    </AbsoluteFill>
  );
}
