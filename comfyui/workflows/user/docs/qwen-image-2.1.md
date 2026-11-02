# BFS Head V1 / V1.1 for Qwen Image 2.1

The BFS head-swap LoRA for [`Qwen/Qwen-Image-2.1`](https://huggingface.co/Qwen/Qwen-Image-2.1)
ships in three versions:
[`bfs_head_v1.1_qwen_2.1.safetensors`](../bfs_head_v1.1_qwen_2.1.safetensors) (recommended),
[`bfs_head_v1.1_alternative_qwen_2.1.safetensors`](../bfs_head_v1.1_alternative_qwen_2.1.safetensors),
and the original [`bfs_head_v1_qwen_2.1.safetensors`](../bfs_head_v1_qwen_2.1.safetensors).
All three are drop-in replacements for each other: same workflow, same prompt, strength `1.0`.

This release is separate from the Qwen Image Edit 2509/2511 weights. Use the Qwen Image 2.1
base model and the included workflow:

[`workflows/Head Swap V1 Qwen 2.1 Workflow.json`](../workflows/Head%20Swap%20V1%20Qwen%202.1%20Workflow.json)

## Versions

### V1.1: reduced skin softening

V1 transfers identity well, but it also softens skin: pores, freckles and fine lines get smoothed
out, and results can read as slightly plastic. That softening does not come from the whole LoRA.
It comes from one specific part of it.

The LoRA touches six modules in each of the 32 transformer blocks: four attention projections
(`to_q`, `to_k`, `to_v`, `to_out.0`) and two MLP ones (`img_mlp.gate_up`, `img_mlp.out`).
Disabling them group by group and comparing generations under a fixed seed, prompt and sampler
shows the blur is carried by the `img_mlp.gate_up` path. Attention routes information from the
reference head; the MLP path is where the model's notion of how a surface looks gets rewritten,
so that is where training pulled skin texture toward the dataset.

V1.1 is V1 with the `img_mlp.gate_up` modules removed from the second half of the network
(blocks 16-31), 16 of the 192 modules. Every attention module, every `img_mlp.out` module and
the first-half `gate_up` modules are byte-identical to V1. Nothing was rescaled, re-ranked or
retrained.

The cut stops at block 16 for a reason. The early-block MLP path is what makes the LoRA copy head
rotation, eye direction and expression from `<image1>`. Removing `img_mlp.gate_up` everywhere
yields even more skin detail, but the LoRA then stops following the source pose and degenerates
into pasting the reference head onto the body, which is close to what the base model already does
without any LoRA. V1.1 sits at the point where texture improves while that behaviour still works.

Measured across five image pairs at a fixed seed, V1.1 raises skin micro-detail inside the face
(bilateral residual) by about a third over V1, closing roughly two thirds of the distance to what
the base model produces without any LoRA. Identity similarity and head-pose error stay close to
V1. Expression transfer still works, but it is weaker than V1. On a deliberately extreme test
case (a wide-open mouth in `<image1>`), V1 reproduces the expression more fully than V1.1.

### V1.1 alternative - stronger expression transfer

`bfs_head_v1.1_alternative_qwen_2.1.safetensors` attacks the same problem from the other side.
Instead of removing `img_mlp.gate_up` modules, it keeps all 192 modules and scales the whole
`img_mlp` path down to 35% of its trained magnitude, leaving the 128 attention modules untouched.
Scaling preserves the direction of the weight update and only reduces its strength, so the
behaviour that depends on the MLP path survives instead of being switched off.

In testing this version keeps more skin detail than V1.1 and copies expression from `<image1>`
noticeably better - on the wide-open-mouth test case it reproduces the expression more fully than
V1.1 and more fully than V1 itself. It pays for that with a slightly larger head-pose error, about
one degree on average across the test pairs.

Pick this one when the source image has a strong expression or the mouth and eyes carry the shot.
Pick V1.1 when head angle fidelity matters most.


### V1: original release

The original release, kept for reproducibility and for anyone who already tuned a pipeline around
it. It has the softest skin of the three. Note that the V1.1 alternative above matches or beats it
at copying expression while keeping more skin detail, so there is little reason to prefer V1 unless
you want to handle texture yourself in post.


## Inputs

The workflow uses two images:

- **Image 1 / `<image1>`:** the target or base image. Its body, pose, composition, lighting, and
  environment provide the foundation for the result.
- **Image 2 / `<image2>`:** the reference face/head. Its identity, hair, eye color, nose
  structure, and other visible head features are transferred.

Keep this order. Reversing the images changes which person is treated as the target.

## Prompt

The included workflow uses this starting prompt:

```text
head_swap: start with <image1> as the base image, keeping its lighting, environment, and background. remove the head from <image1> completely and replace it with the head from <image2>, strictly preserving the hair, eye color, nose structure from <image2>. copy the direction of the eye, head rotation, micro expressions from <image1>, high quality, sharp details, 4k
```

Replace `<image1>` and `<image2>` only if your node or workflow uses a different reference-token
notation. Keep the edit localized to the head when the body and background should remain unchanged.

## ComfyUI setup

1. Put `bfs_head_v1.1_qwen_2.1.safetensors` (or one of the other two versions) in `ComfyUI/models/loras/`.
2. Load the Qwen Image 2.1 diffusion model, Qwen3-VL text encoder, and matching Qwen Image 2.1
   VAE required by the workflow.
3. Open the included workflow and connect the target image to Image 1 and the reference head to
   Image 2.
4. Start with LoRA strength `1.0` and adjust only after checking the identity, hair boundary,
   skin blending, and expression transfer.

The workflow also contains an optional Pruna 8-step acceleration LoRA. It is not part of BFS and
can be disabled if it is not installed.

## Resolution and quality

Qwen Image 2.1 supports native high-resolution generation. The included workflow starts from a
moderate resolution and supports custom sizing in multiples of 32. For this head-swap use case,
larger output sizes can help retain facial detail and reduce the broad color or softness shifts
that may appear at lower resolutions. Higher resolution does not guarantee perfect preservation.

## Examples

<p align="center">
  <img src="../images/bfs_qwen_2.1_1.png" width="49%" />
  <img src="../images/bfs_qwen_2.1_2.png" width="49%" />
  <img src="../images/bfs_qwen_2.1_3.png" width="49%" />
  <img src="../images/bfs_qwen_2.1_4.png" width="49%" />
  <img src="../images/bfs_qwen_2.1_5.png" width="49%" />
  <img src="../images/bfs_qwen_2.1_6.png" width="49%" />
  <img src="../images/bfs_qwen_2.1_7.png" width="49%" />
  <img src="../images/bfs_qwen_2.1_8.png" width="49%" />
</p>

## Limitations and responsible use

Small faces, extreme angles, occlusion, hands over the face, hair boundaries, and strong lighting
changes can reduce fidelity. Always inspect the result for unintended changes to the body,
clothing, background, text, and identity. Do not use or share results involving public figures or
people who have not given consent.

[Back to the repository index](../README.md)
