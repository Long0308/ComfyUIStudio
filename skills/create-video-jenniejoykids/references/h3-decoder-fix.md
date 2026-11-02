# MiniMax H3 INT8 CPU VAE attention fix

The CUDA host capability flag also applies when `--cpu-vae` puts actual query/key/value tensors on CPU. The decoder previously invoked CUDA-only `comfy_kitchen.int8_attention` and failed with `q, k, and v must be on the same CUDA device`.

## Minimal diff

- `ComfyUI/comfy/ldm/minimax/vae.py`: require actual CUDA query and matching Q/K/V devices before the existing INT8 kernel call. Select the existing fallback through `optimized_attention_for_device(query.device)` so CPU also works when global `--use-ck-attention` selects CUDA-only attention. The eligible CUDA path stays unchanged. Existing offloaded qk_norm_scale correction remains intact.
- `ComfyUI/tests-unit/comfy_test/test_minimax_h3_vae.py`: use real INT8 quantized QKV weights with batch=2; assert CPU skips the kernel even with global CK attention selected; assert CUDA routes to the kernel with tiny actual CUDA tensors; compare outputs with capability-disabled fallback, preserving dtype/device/shape.

## Verification

Isolated checkout `.venv/Scripts/python.exe -m pytest tests-unit/comfy_test/test_minimax_h3_vae.py -q`: **4 passed in 3.05s**. Includes existing offloaded-scale and still-frame regressions. `git diff --check`: passed.

Environment: PyTorch 2.14.1+cu130, cuDNN 92400, RTX 5070; tiny CUDA allocation passed. Installed pytest 9.1.1 (plus iniconfig and pluggy) only in checkout `.venv`, since pytest/pip were absent; no global environment changed.

## Review and limits

Independent code review identified the global CK fallback edge; the final patch resolves it using the existing device selector. Final re-review: **APPROVE**, no remaining findings; CPU regression covers global CK selection and CUDA dispatch remains intact.

CUDA regression substitutes SDPA for the INT8 attention kernel to check dispatch and output reshape without exercising large kernels. CPU quantized linear math and CPU attention execute normally. No server restart or full model sampling performed by this subtask. Root owns the subsequent visible real-checkpoint CPU decode diagnostic. Smallest native latent `[1,24,1,1,1]` decodes to `[1,3,1,16,16]`; the planned root diagnostic uses `[1,24,2,2,2]` for a short 32x32 clip. These probes check decoding correctness, not final image quality.
