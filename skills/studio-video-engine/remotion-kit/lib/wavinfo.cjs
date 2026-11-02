'use strict';
// Duration of a RIFF/WAVE file from its header (no decode, no ffprobe): data chunk bytes / byte rate. Pure Node.

const fs = require('node:fs');

function wavSeconds(file) {
  const fd = fs.openSync(file, 'r');
  try {
    const size = fs.fstatSync(fd).size;
    const head = Buffer.alloc(12);
    fs.readSync(fd, head, 0, 12, 0);
    if (head.toString('ascii', 0, 4) !== 'RIFF' || head.toString('ascii', 8, 12) !== 'WAVE') throw new Error(`${file} is not a RIFF/WAVE file`);
    let pos = 12;
    let byteRate = 0;
    const chunk = Buffer.alloc(8);
    while (pos + 8 <= size) {
      fs.readSync(fd, chunk, 0, 8, pos);
      const id = chunk.toString('ascii', 0, 4);
      const len = chunk.readUInt32LE(4);
      if (id === 'fmt ') {
        const fmt = Buffer.alloc(Math.min(len, 16));
        fs.readSync(fd, fmt, 0, fmt.length, pos + 8);
        byteRate = fmt.readUInt32LE(8);
      } else if (id === 'data') {
        if (!(byteRate > 0)) throw new Error(`${file}: data chunk before the fmt chunk`);
        const bytes = len === 0xffffffff || pos + 8 + len > size ? size - (pos + 8) : len; // a streamed WAV may carry a placeholder length
        return bytes / byteRate;
      }
      pos += 8 + len + (len % 2);
    }
    throw new Error(`${file}: no data chunk`);
  } finally {
    fs.closeSync(fd);
  }
}

module.exports = {wavSeconds};
