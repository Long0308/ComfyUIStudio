# Independent review: native H3 FL2VA adapter

PASS. No remaining actionable findings on final adapter3a739729... and tests6dfd7f97....

An initial MEDIUM Windows-relative-path finding was corrected during review. First/last, optional reference_images and ordered reference_bindings.path now share the same path validation/normalization. Independently reran the original failing subfolder/backslash case with mixed binding separators: it now passes with normalized graph paths and unchanged caller inputs. Final malformed-engine/cast/scope/object-info guards also reject cleanly before any artifact creation.

Reviewed the new adapter, its nine tests and documentation, plus reused builder interfaces and static saved native-node/template evidence. Existing Ref2VA builder hashes remain unchanged.

Checks completed independently on final bytes:

- All nine focused FL2VA tests pass without skips. Coverage includes source immutability, exact first/last/native AV/canonical carry wiring, full literal cast with only consumed image bindings, derived timing/dimensions/steps/seeds, Ref2VA default preservation, unsupported/malformed inputs, Windows path normalization, final transformed schema validation, and CLI fresh-output/no-overwrite behavior. CLI tests use temporary JSON/output files only.
- Read the actual native MiniMaxH3ImageToVideo schema/execute source as text. First/last images are tokenized in that order, conditioning targets frame0 and native frame_count-1, and the joint AV latent remains output1. Saved official I2V/continuation templates match the FL2VA checkpoint and simple/res_multistep profile.
- Rebuilt actual `production-local/shots/S01-B-FL2VA-v12/config.json` in memory with fresh saved `installed-object-info-live-v12.json`. API and GUI graphs match exactly:27 nodes; final installed-schema validation passes; every saved builder provenance field matches. Graph SHA256 remains `4dd2421785d3907c34a78814a14506eeac3cd660d02f0b4e2fa85ab6379cc8e1` after the normalization/validation fixes.
- First8:0 and last20:0 feed native I2V6; positive6:0 feeds BasicGuider10 directly; latent6:1 still feeds the sampler. Ref2VA-only9/30/31 are absent and all surviving links resolve.
- Complete native images15:0 and generated audio16:0 feed17/18 unchanged. Canonical WAV7:0 feeds trim58 and editorial56. Hard carry is image8 plus generated1..119; boundary-end is actual generated119, not supplied last PNG20. Receipt correctly distinguishes native last123 from actual last USED119. General timing/dimension/steps/seed cases pass.
- Blocked all Path.open calls during actual pure graph builds and confirmed config, VIDEO items and schema inputs remain unchanged. No model file was read. The pinned checkpoint identity matches saved model metadata and the parent's external completed-download receipt; this review does not independently rehash the model. The builder correctly leaves model artifact verification as an external pending check.

No implementation, source config, model, runtime, queue, GPU, staged asset or live artifact was changed by this reviewer. Only this report was written/updated. Static/schema tests do not establish generated motion or production acceptance.

Final reviewed code identities:

- scripts/build_fl2va_workflow.py: `3a7397296d2e6a7dfc67ba4947d19537ed22544ede0b815386c56a169a1b6944`
- tests/test_fl2va_builder.py: `6dfd7f97af926eb57b98b72d1e4cff900de58ed4095a3241f4f2d326ded45645`
- references/comfy-fl2va.md: `ebc0747a9a53bb452512a9a450ad5db7043818dbb31162ad6c2453f9b99dc8dd`
- scripts/build_comfy_workflow.py: `f3516da0c650f9717db33ea0df3c88a90b60474193271d38527312f4b33d6ad5`
- scripts/build_continuous_workflow.py: `ba590c8cbad4ca543dacca26f2d9e5242bc3613a7909ccafaea8cf2e38721149`

## Review Summary

| Severity | Count | Status |
|----------|-------|--------|
| CRITICAL | 0 | pass |
| HIGH | 0 | pass |
| MEDIUM | 0 | pass |
| LOW | 0 | pass |

Verdict: APPROVE — no remaining actionable code issues in the reviewed scope.
