# Qwen Image Edit LoRAs

This family contains the original BFS releases for Qwen Image Edit 2509 and the later 2511
head-swap continuation. Use the matching Qwen base model and keep the input order for the selected
version.

## Downloads

### Qwen Image Edit 2509

- [`bfs_face_v1_qwen_image_edit_2509.safetensors`](../bfs_face_v1_qwen_image_edit_2509.safetensors)
- [`bfs_head_v1_qwen_image_edit_2509.safetensors`](../bfs_head_v1_qwen_image_edit_2509.safetensors)
- [`bfs_head_v2_qwen_image_edit_2509.safetensors`](../bfs_head_v2_qwen_image_edit_2509.safetensors)
- [`bfs_head_v3_qwen_image_edit_2509.safetensors`](../bfs_head_v3_qwen_image_edit_2509.safetensors)
- [`bfs_head_v4_qwen_image_edit_2509.safetensors`](../bfs_head_v4_qwen_image_edit_2509.safetensors)

### Qwen Image Edit 2511

- [`bfs_head_v5_2511_original.safetensors`](../bfs_head_v5_2511_original.safetensors)
- [`bfs_head_v5_2511_merged_version_rank_16_fp16.safetensors`](../bfs_head_v5_2511_merged_version_rank_16_fp16.safetensors)
- [`bfs_head_v5_2511_merged_version_rank_32_fp32.safetensors`](../bfs_head_v5_2511_merged_version_rank_32_fp32.safetensors)

The V5 files are the latest 2511 release. The merged versions combine the V5 2511 training with
the earlier V4 behavior; the FP16 file is the practical default, while the FP32 file is kept for
maximum numerical fidelity when storage and VRAM allow it.

## Input order

| Version | Image 1 | Image 2 |
|---|---|---|
| Face V1 | Reference face | Target body |
| Head V1/V2 | Reference face | Target body |
| Head V3/V4/V5 | Target body | Reference face |

The V3, V4, and V5 releases intentionally use the inverted body-first order. Do not reuse the
Face V1/V2 order with those files.

## Prompts

Face V1:

```text
face swap face from Image 1 to Image 2. swap only the face, match the skin tone, and keep the target pose and lighting.
```

Head V1/V2:

```text
head swap from Image 1 to Image 2
```

Head V3/V4/V5:

```text
head_swap: start with Picture 1 as the base image, keeping its lighting, environment, and background. remove the head from Picture 1 completely and replace it with the head from Picture 2, strictly preserving the hair, eye color, and nose structure of Picture 2. copy the eye direction, head rotation, and micro-expressions from Picture 1.
```

## Workflow

The repository contains workflows for the V3, V4, and V5-style Qwen setup. Use the workflow that
matches the base model and version, then start around LoRA strength `1.0` and adjust based on the
reference image and resolution.

This family is separate from the [Qwen Image 2.1 release](qwen-image-2.1.md), which uses
`<image1>`/`<image2>` in its dedicated workflow.

[Back to the repository index](../README.md)
