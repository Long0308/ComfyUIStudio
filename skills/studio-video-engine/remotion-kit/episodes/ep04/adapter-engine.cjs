#!/usr/bin/env node
'use strict';
// First-episode wrapper around the episode-neutral engine adapter (lib/adapter-engine.cjs): same API, and the CLI defaults --episode-text to the
// episode-text.json beside this file. Every other behaviour lives in the lib.
//
//   node adapter-engine.cjs --review-config F --events F --receipt SUMMARY.json --episode-root DIR [--episode-text FILE] [--allow-outside PATH]... --out kit-config.json

const path = require('node:path');
const lib = require('../../lib/adapter-engine.cjs');

module.exports = {adaptEngine: lib.adaptEngine, loadBuild: lib.loadBuild};
if (require.main === module) lib.cli(process.argv.slice(2), {adapterFile: __filename, defaultEpisodeText: path.join(__dirname, 'episode-text.json')});
