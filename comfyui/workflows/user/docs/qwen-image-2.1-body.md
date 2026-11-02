# BFS Body Swap V1.0 for Qwen Image 2.1

[`bfs_body_swap_v1.0_qwen_2.1.safetensors`](../bfs_body_swap_v1.0_qwen_2.1.safetensors) replaces
the **whole person** in a scene with the person from a reference image, keeping the scene's pose,
framing, lighting and background. It is separate from the head-swap weights: use this one when the
body, clothing and proportions should come from the reference, not only the head.

Base model: [`Qwen/Qwen-Image-2.1`](https://huggingface.co/Qwen/Qwen-Image-2.1). Strength `1.0`.

## Inputs

- **Image 1 / `<image1>`:** the scene. Its pose, framing, lighting and background are kept.
- **Image 2 / `<image2>`:** the reference person, whose face, clothing and body proportions are
  transferred.

Keep this order.

## Prompt

```text
body_swap: start with <image1> as the base image, keeping its lighting, environment, and background. replace the body from <image1> with the body from <image2>, strictly preserving the clothing, body shape and proportions from <image2>. copy the pose, direction of the eye, head rotation, micro expressions from <image1>
```

## The reference image matters more than anything else

This model was trained with references in one consistent format: **the person standing, full body,
facing the camera, on a plain light background**, filling most of a square frame. A reference in
that format is inside the distribution the model learned. A tight portrait with a busy background
is not, and that is where results fall apart: the reference's own background starts bleeding into
the output and identity gets weaker.

Two things follow from that.

**Give the reference room, not resolution.** If you feed both images at their native size, a
reference larger than the scene takes more tokens and starts overriding it. Scaling the reference
to roughly 0.59 MP (about 768x768 of area) while keeping its aspect ratio measurably improved how
well the scene's background survived, at every output size tested. Scaling the reference *up* to
match the scene's size was the worst setting measured, worse than doing nothing.

**Normalize the reference first if it is not full body.** A single pass through Qwen Image 2.1
itself, with no LoRA, turns a portrait into a reference in the trained format:

```text
full body studio reference photo of the person from <image1>: standing upright on both feet, facing the camera, front view, camera at chest height and perfectly level, arms relaxed at the sides, neutral expression, looking straight at the camera. plain seamless light background, soft even studio lighting, no props and no cast shadows on the backdrop. the person fills almost the whole height of the square frame, from the top of the head down to the shoes, with a small even margin above and below. strictly keep the same face, hairstyle, clothing and body proportions as <image1>. sharp photographic detail
```

Run that at 1024x1024 and use the result as `<image2>`. It reconstructs legs and shoes that the
original crop did not show, so expect some loss of facial likeness in the reference itself; whether
the round trip is worth it depends on how far your source is from the trained format.

## ComfyUI setup

1. Put the file in `ComfyUI/models/loras/`.
2. Load the Qwen Image 2.1 diffusion model, the Qwen3-VL text encoder and the matching VAE.
3. Scale the **scene** to about 2 MP and the **reference** to about 0.59 MP, both preserving aspect
   ratio (`ImageScaleToTotalPixels` does this).
4. Feed both to `TextEncodeQwenImage21` with `resolution: 0`, scene first.
5. Take the sampler's latent from that node's `latent` output: it is already sized to the scene, so
   the aspect ratio follows without a separate `EmptyLatentImage` to keep in sync.

## Limitations

Faces get less accurate as the subject gets smaller in frame; the drop is measurable and it is the
main open weakness. Very large changes between scene and reference (different sex, age or build at
the same time) are the cases most likely to fail outright. Pose is followed approximately, not
exactly, and prompt wording moves it only a few percent. Always check the result for unintended
changes to the background, clothing and text.

Do not use or share results involving public figures or people who have not given consent.

[Back to the repository index](../README.md)
