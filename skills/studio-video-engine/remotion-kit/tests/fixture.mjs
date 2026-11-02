// A tiny synthetic episode used to prove the kit is not bound to ep04: different ids, frames and texts.
export function makeConfig(over = {}) {
  const words = (start) => [
    {w: 'Hi', startF: start + 4, endF: start + 10, keyword: false},
    {w: 'moon', startF: start + 14, endF: start + 24, keyword: true},
  ];
  const base = {
    schema: 'jjk-remotion-kit/config/v1',
    id: 'epXX-synthetic',
    fps: 30,
    timeline: {introFrames: 30, mainFrames: 240, endCardFrames: 30, outroStart: 150, outroFrames: 90},
    review: {label: 'REVIEW test'},
    strings: {cardsHeader: 'Say it', cardsHeaderClosing: 'Bye'},
    intro: {kicker: 'KICKER', titleLines: ['One', 'Two', 'Three'], pill: 'pill', footer: 'footer', mark: 'none'},
    shots: [
      {id: 'X1', start: 30, frames: 60, speechEndS: 1.5, vi: 'xin chao', captionLines: 1, words: words(30), segments: [{id: 'X1', from: 0, frames: 60}]},
      {
        id: 'X2', start: 90, frames: 60, speechEndS: 1.5, vi: 'tam biet', captionLines: 2, words: words(90),
        segments: [{id: 'X2a', from: 0, frames: 40}, {id: 'X2b', from: 40, frames: 20}],
      },
    ],
    transitions: [
      {id: 'W1', type: 'whip', boundary: 90, from: 'X1', to: 'X2a', frames: 8, direction: -1, start: 86, outFrames: 4, inFrames: 4},
      {id: 'I1', type: 'iris', boundary: 150, from: 'X2b', to: 'OUTRO', frames: 20, direction: 0, start: 130},
    ],
    icons: [{id: 'IC1', shot: 'X1', icon: 'moon.png', frame: 44, totalFrames: 30}],
    ending: {
      irisStart: 130, irisClosed: 142, irisCentre: [900, 500], discIn: 144, discSlideStart: 146, discSlideEnd: 149, discSlideX: 400,
      discFadeStart: 150, pillLeftX: 900, plateStart: 236, speechEndFrame: 235.5, plateEn: 'The end', plateVi: 'Het', tailFrom: 100,
    },
    cards: [
      {term: 'Moon', ipa: '/m/', vi: 'trang', exampleEn: 'The moon.', start: 0, frames: 30},
      {term: 'Sun', ipa: '/s/', vi: 'mat troi', exampleEn: 'The sun.', start: 30, frames: 30},
      {term: 'Star', ipa: '/st/', vi: 'sao', exampleEn: 'The star.', start: 60, frames: 30},
    ],
  };
  return structuredClone({...base, ...over});
}
