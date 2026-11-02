# Experimental LTX-2 Head-Swap Weights

The repository also contains experimental LTX-2 in-context LoRA checkpoints:

- [`bfs_head_swap_v1_ltx2_ic_lora_5000.safetensors`](../bfs_head_swap_v1_ltx2_ic_lora_5000.safetensors)
- [`bfs_head_swap_v1_ltx2_ic_lora_6000.safetensors`](../bfs_head_swap_v1_ltx2_ic_lora_6000.safetensors)
- [`bfs_head_swap_v1_ltx2_ic_lora_12000_train_3.safetensors`](../bfs_head_swap_v1_ltx2_ic_lora_12000_train_3.safetensors)

These files are experimental and are kept separate from the Qwen, Flux, and Krea release guides.
Use them only with an LTX-2 workflow that supports the corresponding in-context LoRA contract.
No LTX-2 workflow is bundled in this repository at the moment.

Do not assume that the Qwen or Flux image input order applies to LTX-2. Follow the input contract
of the LTX-2 workflow you are using and test the checkpoint before a long generation.

[Back to the repository index](../README.md)
