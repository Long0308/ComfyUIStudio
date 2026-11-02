# Flux 2 Klein Head-Swap LoRAs

These BFS weights target Flux 2 Klein 4B/9B variants. They use the body-first input contract:

- **Image 1:** target body/base image
- **Image 2:** reference face/head

Do not reverse the images for these releases.

## Downloads

- [`bfs_head_v1_flux-klein_4b.safetensors`](../bfs_head_v1_flux-klein_4b.safetensors)
- [`bfs_head_v1_flux-klein_9b_step3500_rank128.safetensors`](../bfs_head_v1_flux-klein_9b_step3500_rank128.safetensors)
- [`bfs_head_v1_flux-klein_9b_step3750_rank64.safetensors`](../bfs_head_v1_flux-klein_9b_step3750_rank64.safetensors)
- [`bfs_head_v1.1_optional_flux-klein_4b.safetensors`](../bfs_head_v1.1_optional_flux-klein_4b.safetensors)

## Prompt

```text
head_swap: start with Picture 1 as the base image, keeping its lighting, environment, and background. remove the head from Picture 1 completely and replace it with the head from Picture 2, strictly preserving the hair, eye color, and nose structure of Picture 2. copy the direction of the eye, head rotation, and micro-expressions from Picture 1. Keep the body, clothing, pose, framing, and background intact.
```

You can add a short expression or pose instruction when it is visible in the target image. Keep
the edit focused on the head and avoid requesting an unrelated scene change in the same prompt.

## Workflow

[`workflows/Head Swap V1 Flux 2 Klein 4b_9b (base_distill).json`](../workflows/Head%20Swap%20V1%20Flux%202%20Klein%204b_9b%20(base_distill).json)

Start around LoRA strength `1.0`; adjust after checking identity preservation, hair boundaries,
expression transfer, and skin blending.

[Back to the repository index](../README.md)
