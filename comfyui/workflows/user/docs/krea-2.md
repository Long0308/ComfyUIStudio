# Krea 2 Head and Body Swap LoRAs

## Head Swap V1.1

[`bfs_head_swap_v1.1_krea2.safetensors`](../bfs_head_swap_v1.1_krea2.safetensors) is the updated
Krea 2 head-swap release and replaces the earlier V1 file.

Use the included [`Head Swap Krea 2 - V1 Simple Workflow.json`](../workflows/Head%20Swap%20Krea%202%20-%20V1%20Simple%20Workflow.json).

Inputs:

- Image 1: base image
- Image 2: reference head

Prompt:

```text
head_swap: replace the head with the reference head.
```

## Body Swap V1 (experimental)

[`bfs_body_swap_v1_krea2.safetensors`](../bfs_body_swap_v1_krea2.safetensors) replaces the
source person with the reference person. Exact pose transfer is not guaranteed.

Use the included [`Body Swap Krea 2 - V1 Simple Workflow.json`](../workflows/Body%20Swap%20Krea%202%20-%20V1%20Simple%20Workflow.json).

Inputs:

- Image 1: base image
- Image 2: reference person

Prompt:

```text
body_swap: replace the person with the reference person.
```

To request a new background, append:

```text
BG: [describe the new background]
```

Start around LoRA strength `0.5` for body swap and adjust from there. The head workflow can be
combined with the body workflow when additional head-identity control is useful.

[Back to the repository index](../README.md)
