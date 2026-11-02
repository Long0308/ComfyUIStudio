// Renders the music bed plan (music-plan.mjs) with Remotion <Audio> segments: one Sequence per segment, the stem started at the segment's
// startFromFrame, volume = the segment's linear fade x the ducking gain under the words. Mounted by film.jsx ONLY when the config declares a
// music policy (selectMusicMode); without one the film plays its stem exactly as before.
import React, {useMemo} from 'react';
import {Audio, Sequence, staticFile} from 'remotion';
import {useKit} from './context.jsx';
import {musicPolicy, planMusic, segmentGain, wordWindows} from './music-plan.mjs';

export function MusicBed() {
  const {config, sources} = useKit();
  const total = config.timeline.mainFrames + config.timeline.endCardFrames;
  const plan = useMemo(() => {
    const policy = musicPolicy(config);
    return planMusic({totalFrames: total, fps: config.fps, stemSeconds: policy.stemSeconds, bed: policy.bed, windows: wordWindows(config)});
  }, [config, total]);
  return (
    <>
      {plan.segments.map((seg, i) => (
        <Sequence key={`music${i}`} from={seg.from} durationInFrames={seg.durationInFrames}>
          <Audio src={staticFile(sources.music)} startFrom={seg.startFromFrame} volume={(f) => segmentGain(seg, f) * plan.duck(seg.from + f)} />
        </Sequence>
      ))}
    </>
  );
}
