'use strict';
// Verify every binding of a kit config WITHOUT staging it: each bound file must still hash to its recorded sha256 (a `materialized` stream-copy
// cache too), and in master mode every final picture / tail must carry a receipt whose CONTENT attests it (lib/receipts.cjs, the same check stage()
// runs). With a verified-hash cache (lib/hashcache.cjs) an unchanged file costs one stat instead of a read: this is the "verify of N shots" that took
// ~400 s on the first episode's 4K cores and is skipped, with the stat identity as the declared trust boundary, when nothing changed.
// `--rehash-all` (HashCache rehashAll) is the audit path that reads every byte again.

const fs = require('node:fs');
const {requireReceiptBinding} = require('./stage.cjs');

function collect(config) {
  const items = [];
  const b = config.bindings || {};
  const add = (role, label, binding) => {
    if (binding && typeof binding === 'object' && typeof binding.path === 'string') items.push({role, label, binding});
  };
  add('opening', 'opening', b.opening);
  add('logo', 'logo', b.logo);
  add('music', 'music', b.music);
  add('ambience', 'ambience', b.ambience);
  for (const [id, sb] of Object.entries(b.shots || {})) {
    add('dialogue', `voice-${id}`, sb.audio);
    for (const [seg, binding] of Object.entries(sb.segments || {})) add('picture', `${id}/${seg}`, binding);
  }
  for (const [id, binding] of Object.entries(b.tails || {})) add('tail', id, binding);
  for (const [name, binding] of Object.entries(b.icons || {})) add('vocabulary_icon', name, binding);
  (b.cards || []).forEach((c, i) => {
    add('vocabulary_icon', `card-${i}`, c && c.icon);
    add('vocabulary_audio', `card-${i}`, c && c.audio);
  });
  return items;
}

/**
 * @param {object} config kit config with bindings
 * @param {{hashCache: {sha256:Function, stats:Function}, requireReceipts?: boolean}} opts
 * @returns {{files:number, verified:number, problems:string[], seconds:number, hash_cache:object}}
 */
function verifyBindings(config, {hashCache, requireReceipts = false}) {
  const t0 = Date.now();
  const problems = [];
  const items = collect(config);
  let verified = 0;
  for (const {role, label, binding} of items) {
    const target = binding.materialized || binding;
    try {
      for (const f of binding.materialized ? [binding.path, target.path] : [binding.path]) if (!fs.existsSync(f)) throw new Error(`${role} ${label}: file missing: ${f}`);
      if (hashCache.sha256(binding.path) !== binding.sha256) throw new Error(`${role} ${label}: hash changed: ${binding.path}`);
      if (binding.materialized && hashCache.sha256(target.path) !== target.sha256) throw new Error(`${role} ${label}: materialized hash changed: ${target.path}`);
      if (requireReceipts && !binding.preview && (role === 'picture' || role === 'tail')) requireReceiptBinding(binding, role, label);
      verified += 1;
    } catch (error) {
      problems.push(error.message);
    }
  }
  return {files: items.length, verified, problems, seconds: (Date.now() - t0) / 1000, hash_cache: hashCache.stats()};
}

module.exports = {verifyBindings, collect};
