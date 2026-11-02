// remotion-kit entry: registers the Film composition (review cut or master, chosen by the `scale` prop) and the standalone
// EndLogo. width / height / duration come from calculateMetadata, i.e. from the config and `scale`; nothing is hard-coded.
import React from 'react';
import {Composition, registerRoot} from 'remotion';
import {EndLogo, Film} from './film.jsx';
import {totalFrames, validateConfig} from './validate.mjs';

const CANVAS = {width: 1920, height: 1080}; // the design canvas; scale 1 = 1080p review, 2 = 4K master

function size(props) {
  const scale = props.scale === undefined ? 1 : props.scale;
  if (!Number.isInteger(scale) || scale < 1) throw new Error(`scale must be a positive integer, got ${props.scale}`);
  return {width: CANVAS.width * scale, height: CANVAS.height * scale};
}

const Root = () => (
  <>
    <Composition
      id="Film"
      component={Film}
      defaultProps={{config: null, scale: 1, label: null, previewMark: null, sources: null, partial: false}}
      durationInFrames={1}
      width={CANVAS.width}
      height={CANVAS.height}
      fps={30}
      calculateMetadata={({props}) => {
        validateConfig(props.config);
        return {durationInFrames: totalFrames(props.config), fps: props.config.fps, ...size(props)};
      }}
    />
    <Composition
      id="EndLogo"
      component={EndLogo}
      defaultProps={{config: null, scale: 1, sources: null, partial: false}}
      durationInFrames={1}
      width={CANVAS.width}
      height={CANVAS.height}
      fps={30}
      calculateMetadata={({props}) => {
        validateConfig(props.config);
        return {durationInFrames: props.config.timeline.endCardFrames, fps: props.config.fps, ...size(props)};
      }}
    />
  </>
);

registerRoot(Root);
