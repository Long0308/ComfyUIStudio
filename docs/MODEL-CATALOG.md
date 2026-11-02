# MODEL-CATALOG - J:\2.Model-AI-Local

Provenance index of every local AI model moved to this drive. App layouts are kept as each app requires (model files are NOT renamed or moved: ComfyUI loads by filename under `ComfyUI/<type>/` and saved workflows reference those names; Hugging Face cache folders `models--<org>--<name>` already encode the source repo). This catalog is the naming/provenance index; machine-readable twin: `MODEL-CATALOG.json` (schema `model-ai-local/catalog/v1`).

Sources marked **unknown** were not provable from local evidence (no download record, receipt or header names them). A filename-based guess appears only in the JSON notes as `guess:`. Proof column: `receipt-hash-verified` = receipt URL/repo + sha256 equal to the hash computed here; `download-record` = ComfyUI download record (url + byte count); `declared-url` = only a workflow/blueprint names the URL (weaker); `hf-cache-layout` = HF cache folder + refs/main.

Totals: 62 rows (ComfyUI 42, VoiceStudio 7, HuggingFace 5, project-local 8); 203,530,703,495 logical bytes (203.53 GB; hardlinked/duplicated files counted per row).

## ComfyUI  (`J:\2.Model-AI-Local\ComfyUI\<type>\<file>`)

### RMBG (1)

| file | size | sha256 (first 12) | source (repo / url) | revision | proof | used by (workflow jsons) |
|---|---|---|---|---|---|---|
| `BiRefNet-general.safetensors` | 0.44 GB | `9ab37426bf4d` | huggingface: Comfy-Org/BiRefNet | 25511f8787 | receipt-hash-verified | none found |

### background_removal (1)

| file | size | sha256 (first 12) | source (repo / url) | revision | proof | used by (workflow jsons) |
|---|---|---|---|---|---|---|
| `birefnet.safetensors` | 0.44 GB | `9ab37426bf4d` | huggingface: Comfy-Org/BiRefNet | 25511f8787 | receipt-hash-verified | 8: production-local/JennieJoyKids-Story/Newtecons-TienDo-KichTinh-30s/production-v2 |

### checkpoints (4)

| file | size | sha256 (first 12) | source (repo / url) | revision | proof | used by (workflow jsons) |
|---|---|---|---|---|---|---|
| `flux1-dev-fp8.safetensors` | 17.25 GB | `8e91b68084b5` | huggingface: Comfy-Org/Flux-1-Dev | 83c446ef27 | receipt-hash-verified | 8: wf/JENNIEJOYKIDS_04_MILK_AND_MOM/90_REJECTED_OR_BLOCKED/ (4 workflow json) |
| `hunyuan3d-dit-v2_fp16.safetensors` | 4.93 GB | `360bc281fc95` | huggingface: Comfy-Org/hunyuan3D_2.0_repackaged | - | download-record | none found |
| `stable_audio_3_small_sfx.safetensors` | 2.27 GB | `ed9cf1b6172f` | huggingface: Comfy-Org/stable-audio-3 | - | receipt-hash-verified | 63: wf/JENNIEJOYKIDS_04_MILK_AND_MOM/07_AUDIO_SFX/SFX-01-milk-pour-glass/ (3 workflo |
| `yue2_3b_int8_convrot.safetensors` | 3.96 GB | `96fe19937730` | huggingface: Comfy-Org/YuE2 | - | receipt-hash-verified | 60: wf/JENNIEJOYKIDS_04_MILK_AND_MOM/06_AUDIO_MUSIC/NHAC-1-ukulele-glockenspiel/ (3  |

### diffusion_models (9)

| file | size | sha256 (first 12) | source (repo / url) | revision | proof | used by (workflow jsons) |
|---|---|---|---|---|---|---|
| `acestep_v1.5_turbo.safetensors` | 4.79 GB | `3f6e0797fad4` | huggingface: Comfy-Org/ace_step_1.5_ComfyUI_files | - | declared-url | 12: wf/JENNIEJOYKIDS_04_MILK_AND_MOM/06_AUDIO_MUSIC/ACE-V2-1-guitar-marimba/ (3 work |
| `flux-2-klein-4b-fp8.safetensors` | 4.07 GB | `97ed34fe0567` | huggingface: black-forest-labs/FLUX.2-klein-4b-fp8 | 5b4408e593 | receipt-hash-verified | 1975: wf/NEWTECONS_8_NHAN_VAT/ (6 workflow json) |
| `krea2_turbo_int8_convrot.safetensors` | 13.49 GB | `8e4eeda70dd5` | huggingface: Comfy-Org/Krea-2 | 1171f4dc7e | receipt-hash-verified | 253: wf/NEWTECONS_CHAR08_UAT20_KREA2_V001/ (20 workflow json) |
| `minimax_h3_fl2va_pruned_int8_convrot.safetensors` | 20.97 GB | `e889202c41da` | huggingface: Comfy-Org/MiniMax-H3 | e5eb578a89 | receipt-hash-verified | 15: .agents/skills/create-video-jenniejoykids/references/production-snapshots/2026-1 |
| `minimax_h3_ref2va_pruned_int8_convrot.safetensors` | 20.97 GB | `9255f52b6677` | huggingface: Comfy-Org/MiniMax-H3 | e5eb578a89 | receipt-hash-verified | 126: wf/ (26 workflow json) |
| `seedvr2_3b_int8_convrot.safetensors` | 3.46 GB | `c3dec8bcc591` | huggingface: Comfy-Org/SeedVR2 | - | declared-url | 14: production-local/JennieJoyKids-Story/03-drinking-milk/picture-derivatives/seedvr |
| `seedvr2_7b_int8_convrot.safetensors` | 8.33 GB | `5aa0d25fc9d3` | huggingface: Comfy-Org/SeedVR2 | - | download-record | 60: wf/JENNIEJOYKIDS_04_MILK_AND_MOM/04_SEEDVR2_UPSCALE/ (14 workflow json) |
| `wan2.2_t2v_low_noise_14B_fp8_scaled.safetensors` | 14.29 GB | `e71b96d7c82e` | huggingface: Comfy-Org/Wan_2.2_ComfyUI_Repackaged | - | download-record | none found |
| `z_image_turbo_int8_convrot.safetensors` | 6.20 GB | `be517ebd47c9` | huggingface: Comfy-Org/Z-Image-Turbo | - | receipt-hash-verified | 3: production-local/JennieJoyKids-Story/Newtecons-TienDo-KichTinh-30s/casting/CHAR_ |

### liveportrait (5)

| file | size | sha256 (first 12) | source (repo / url) | revision | proof | used by (workflow jsons) |
|---|---|---|---|---|---|---|
| `landmark.onnx` | 0.11 GB | `31d22a504132` | huggingface: Kijai/LivePortrait_safetensors | 59f30f36d7 | receipt-hash-verified | none found |
| `landmark_model.pth` | 0.11 GB | `48ba55140fda` | huggingface: Kijai/LivePortrait_safetensors | 59f30f36d7 | receipt-hash-verified | none found |
| `motion_extractor.safetensors` | 0.11 GB | `3568cd410e29` | huggingface: Kijai/LivePortrait_safetensors | 59f30f36d7 | receipt-hash-verified | none found |
| `spade_generator.safetensors` | 0.22 GB | `ca04fbec7657` | huggingface: Kijai/LivePortrait_safetensors | 59f30f36d7 | receipt-hash-verified | none found |
| `warping_module.safetensors` | 0.18 GB | `f7b7834bd603` | huggingface: Kijai/LivePortrait_safetensors | 59f30f36d7 | receipt-hash-verified | none found |

### loras (6)

| file | size | sha256 (first 12) | source (repo / url) | revision | proof | used by (workflow jsons) |
|---|---|---|---|---|---|---|
| `bfs_body_swap_v1_krea2.safetensors` | 0.91 GB | `0b3d043714c9` | huggingface: Alissonerdx/BFS-Best-Face-Swap | 0ca3913ade | receipt-hash-verified | 18: production-local/JennieJoyKids-Story/Newtecons-TienDo-KichTinh-30s/production-v2 |
| `bfs_head_swap_v1.1_krea2.safetensors` | 0.91 GB | `abc6c468c578` | huggingface: Alissonerdx/BFS-Best-Face-Swap | 0ca3913ade | receipt-hash-verified | 41: wf/ (6 workflow json) |
| `flux1_turbo_alpha.safetensors` | 0.69 GB | `77f7523a5e9c` | huggingface: alimama-creative/FLUX.1-Turbo-Alpha | 7b29bf041b | receipt-hash-verified | 8: wf/JENNIEJOYKIDS_04_MILK_AND_MOM/90_REJECTED_OR_BLOCKED/ (4 workflow json) |
| `krea2_general_edit_v2.safetensors` | 1.83 GB | `fb5315477444` | huggingface: conradlocke/krea2-identity-edit | - | receipt-hash-verified | 1: wf/JENNIEJOYKIDS_04_MILK_AND_MOM/02_STORYBOARD_PREPARED/ (1 workflow json) |
| `krea2_identity_edit_v2.safetensors` | 1.83 GB | `c53843f94519` | huggingface: conradlocke/krea2-identity-edit | - | receipt-hash-verified | none found |
| `krea2_style_reference.safetensors` | 0.46 GB | `f50df5a9e62e` | huggingface: Comfy-Org/Krea-2 | - | declared-url | 190: wf/NEWTECONS_CHAR08_UAT20_KREA2_V001/ (20 workflow json) |

### text_encoders (7)

| file | size | sha256 (first 12) | source (repo / url) | revision | proof | used by (workflow jsons) |
|---|---|---|---|---|---|---|
| `qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors` | 15.69 GB | `35a88d510442` | huggingface: Comfy-Org/MiniMax-H3 | e5eb578a89 | receipt-hash-verified | 139: wf/ (29 workflow json) |
| `qwen3vl_4b_fp8_scaled.safetensors` | 5.24 GB | `54bd5144df0b` | huggingface: Comfy-Org/Krea-2 | 1171f4dc7e | receipt-hash-verified | 253: wf/NEWTECONS_CHAR08_UAT20_KREA2_V001/ (20 workflow json) |
| `qwen_0.6b_ace15.safetensors` | 1.19 GB | `fd4590c82153` | huggingface: Comfy-Org/ace_step_1.5_ComfyUI_files | - | declared-url | 12: wf/JENNIEJOYKIDS_04_MILK_AND_MOM/06_AUDIO_MUSIC/ACE-V2-1-guitar-marimba/ (3 work |
| `qwen_1.7b_ace15.safetensors` | 3.71 GB | `ed63e9247d1f` | unknown | - | none | 12: wf/JENNIEJOYKIDS_04_MILK_AND_MOM/06_AUDIO_MUSIC/ACE-V2-1-guitar-marimba/ (3 work |
| `qwen_3_4b.safetensors` | 8.04 GB | `6c671498573a` | huggingface: Comfy-Org/z_image_turbo | 6fc90a3b1b | receipt-hash-verified | 1975: wf/NEWTECONS_8_NHAN_VAT/ (6 workflow json) |
| `t5gemma_b_b_ul2.safetensors` | 1.19 GB | `1e1eba25be88` | huggingface: Comfy-Org/stable-audio-3 | - | receipt-hash-verified | 63: wf/JENNIEJOYKIDS_04_MILK_AND_MOM/07_AUDIO_SFX/SFX-01-milk-pour-glass/ (3 workflo |
| `umt5_xxl_fp8_e4m3fn_scaled.safetensors` | 6.74 GB | `c3355d30191f` | huggingface: Comfy-Org/Wan_2.2_ComfyUI_Repackaged | - | download-record | none found |

### upscale_models (1)

| file | size | sha256 (first 12) | source (repo / url) | revision | proof | used by (workflow jsons) |
|---|---|---|---|---|---|---|
| `RealESRGAN_x4plus.pth` | 67.0 MB | `4fa0d38905f7` | url: https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth | - | receipt-hash-verified | 1: docs/handoffs/model-comparison-20261018/realesrgan-x4plus-24f/ (1 workflow json) |

### vae (8)

| file | size | sha256 (first 12) | source (repo / url) | revision | proof | used by (workflow jsons) |
|---|---|---|---|---|---|---|
| `ace_1.5_vae.safetensors` | 0.34 GB | `6de92e3a862a` | huggingface: Comfy-Org/ace_step_1.5_ComfyUI_files | - | declared-url | 12: wf/JENNIEJOYKIDS_04_MILK_AND_MOM/06_AUDIO_MUSIC/ACE-V2-1-guitar-marimba/ (3 work |
| `ae.safetensors` | 0.34 GB | `afc8e28272cd` | huggingface: Comfy-Org/Z-Image-Turbo | - | receipt-hash-verified | 2228: wf/NEWTECONS_CHAR08_UAT20_KREA2_V001/ (20 workflow json) |
| `flux2-klein-4b-vae.safetensors` | 0.17 GB | `ca70d2202afe` | huggingface: black-forest-labs/FLUX.2-klein-4B | e7b7dc27f9 | receipt-hash-verified | 1973: wf/NEWTECONS_8_NHAN_VAT/ (6 workflow json) |
| `minimax_h3_audio_vae_fp32.safetensors` | 0.61 GB | `8e505d95dd15` | huggingface: Comfy-Org/MiniMax-H3 | e5eb578a89 | receipt-hash-verified | 139: wf/ (29 workflow json) |
| `minimax_h3_video_vae_int8_convrot.safetensors` | 2.81 GB | `52a2c8c73583` | huggingface: Comfy-Org/MiniMax-H3 | e5eb578a89 | receipt-hash-verified | 139: wf/ (29 workflow json) |
| `qwen_image_vae.safetensors` | 0.25 GB | `a70580f0213e` | huggingface: Comfy-Org/Krea-2 | 1171f4dc7e | receipt-hash-verified | 258: wf/NEWTECONS_CHAR08_UAT20_KREA2_V001/ (20 workflow json) |
| `seedvr2_ema_vae_fp16.safetensors` | 0.50 GB | `20678548f420` | huggingface: Comfy-Org/SeedVR2 | - | declared-url | 73: wf/JENNIEJOYKIDS_04_MILK_AND_MOM/04_SEEDVR2_UPSCALE/ (14 workflow json) |
| `wan_2.1_vae.safetensors` | 0.25 GB | `2fc39d31359a` | huggingface: Comfy-Org/Wan_2.2_ComfyUI_Repackaged | - | download-record | none found |

## VoiceStudio  (`J:\2.Model-AI-Local\VoiceStudio\hf_cache\`)

### Hugging Face cache - OmniVoice app

| repo / file | size | sha256 (first 12) | source | revision | proof | used by |
|---|---|---|---|---|---|---|
| `adefossez/HTDemucs` | 84.0 MB | `-` | huggingface: adefossez/HTDemucs | cbc8a9b1a8 | hf-cache-layout | VoiceStudio dub pipeline demucs "htdemucs": VoiceStudio/backend/services/dub_pipeline.py:1712; engine vocal gate (machine.json audio.vocal_gate -> dem |
| `csukuangfj/sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8` | 0.67 GB | `acfc2b445637` | huggingface: csukuangfj/sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8 | 2bda32ec70 | hf-cache-layout | VoiceStudio ASR (sherpa): VoiceStudio/pyproject.toml, backend tests test_asr_* |
| `csukuangfj/sherpa-onnx-whisper-tiny` | 0.26 GB | `e144c07dc6b5` | huggingface: csukuangfj/sherpa-onnx-whisper-tiny | 65176e2deb | hf-cache-layout | VoiceStudio dictation: VoiceStudio/backend/services/sherpa_dictation.py |
| `facebook/nllb-200-distilled-600M` | 2.48 GB | `c266c2cfd197` | huggingface: facebook/nllb-200-distilled-600M | f8d333a098 | hf-cache-layout | VoiceStudio translation: VoiceStudio/backend/services/translation_engines.py, backend/config/models.yaml |
| `k2-fsa/OmniVoice` | 3.27 GB | `730839316de5` | huggingface: k2-fsa/OmniVoice | c5fdb5ccb1 | hf-cache-layout | VoiceStudio core TTS engine (OmniVoice): VoiceStudio/omnivoice/models/omnivoice.py; hf cache in OmniVoice\hf_cache (app) and .cache\huggingface\hub (s |
| `openbmb/VoxCPM2` | 4.96 GB | `f7f964cfa9da` | huggingface: openbmb/VoxCPM2 | bffb3df5a2 | hf-cache-layout | VoiceStudio engine VoxCPM2: VoiceStudio/backend/config/models.yaml, VoiceStudio/docs/engines/voxcpm2.md |
| `Systran/faster-whisper-large-v3` | 3.09 GB | `69f74147e333` | huggingface: Systran/faster-whisper-large-v3 | edaa852ec7 | hf-cache-layout | VoiceStudio ASR: VoiceStudio/backend/config/models.yaml, backend/services/asr_backend.py (mentions) |

## HuggingFace shared cache  (`J:\2.Model-AI-Local\HuggingFace\hub\`)

### Hugging Face cache - shared

| repo / file | size | sha256 (first 12) | source | revision | proof | used by |
|---|---|---|---|---|---|---|
| `adefossez/HTDemucs` | 84.0 MB | `-` | huggingface: adefossez/HTDemucs | cbc8a9b1a8 | hf-cache-layout | VoiceStudio dub pipeline demucs "htdemucs": VoiceStudio/backend/services/dub_pipeline.py:1712; engine vocal gate (machine.json audio.vocal_gate -> dem |
| `eustlb/higgs-audio-v2-tokenizer` | 0.81 GB | `-` | huggingface: eustlb/higgs-audio-v2-tokenizer | 528e871c2a | hf-cache-layout | VoiceStudio OmniVoice audio-tokenizer fallback repo: VoiceStudio/omnivoice/models/omnivoice.py:84 |
| `k2-fsa/OmniVoice` | 2.46 GB | `-` | huggingface: k2-fsa/OmniVoice | c5fdb5ccb1 | hf-cache-layout | VoiceStudio core TTS engine (OmniVoice): VoiceStudio/omnivoice/models/omnivoice.py; hf cache in OmniVoice\hf_cache (app) and .cache\huggingface\hub (s |
| `Systran/faster-whisper-small` | 0.49 GB | `-` | huggingface: Systran/faster-whisper-small | 536b066274 | hf-cache-layout | engine: production-local/engine/machine.json timing.model_dir = C:\Users\Admin\.cache\huggingface\hub\models--Systran--faster-whisper-small; VoiceStud |
| `Systran/faster-whisper-small.en` | 0.49 GB | `-` | huggingface: Systran/faster-whisper-small.en | d1d751a5f8 | hf-cache-layout | no reference found in project text files (grep of repo name/"small.en") |

## Project-local (not moved to J:2; moves with J:\1.JennieHomeSchool)

| file / folder | location | size | sha256 (first 12) | source | proof |
|---|---|---|---|---|---|
| `3dspeaker_speech_campplus_sv_en_voxceleb_16k.onnx` | production-local/voice-library-classmagic-20261018/discovery-v1/models/3dspeaker_speech_campplus_sv_en_voxceleb_16k.onnx | 29.6 MB | `357a834f702b` | url: https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/3dspeaker_speech_campplus_sv_en_voxceleb_16k.onnx | receipt |
| `ComfyUI-RMBG/models` | production-local/ComfyUI/custom_nodes/ComfyUI-RMBG/models | - | `-` | unknown (python model-code folder of the ComfyUI-RMBG custom node (florence2, s) | n/a |
| `ctranslate2/models` | production-local/.gpu-asr-runtime/ctranslate2/models | - | `-` | unknown (python package folder of the CTranslate2 runtime (__init__.py only) - ) | n/a |
| `discovery-v1/checkpoints` | production-local/voice-library-classmagic-20261018/discovery-v1/checkpoints | - | `-` | unknown (JSON job checkpoints (~2 KB each), not model weights) | n/a |
| `unet.pth` | production-local/lipsync-lab-20261018/models/musetalkV15/unet.pth | 3.40 GB | `7ebf6c98c181` | huggingface: TMElyralab/MuseTalk | receipt |
| `diffusion_pytorch_model.bin` | production-local/lipsync-lab-20261018/models/sd-vae/diffusion_pytorch_model.bin | 0.33 GB | `1b4889b6b1d4` | huggingface: stabilityai/sd-vae-ft-mse | receipt |
| `s3fd-619a316812.pth` | production-local/lipsync-lab-20261018/torch-cache/hub/checkpoints/s3fd-619a316812.pth | 89.8 MB | `619a31681264` | url: https://www.adrianbulat.com/downloads/python-fan/s3fd-619a316812.pth | download-log+receipt |
| `pytorch_model.bin` | production-local/lipsync-lab-20261018/models/whisper/pytorch_model.bin | 0.15 GB | `9607f98a2b22` | huggingface: openai/whisper-tiny | receipt |

## Rows with source not fully proven

- `ComfyUI/diffusion_models/acestep_v1.5_turbo.safetensors` (declared-url): source is only DECLARED by a workflow/blueprint; no receipt proves these bytes came from there; sha256 recorded (without url) in D:/23.JennieHomeSchool/03 Voice/.agents/skills/studio-video-engine/recipes/audio/music-pick-v001.json and equals computed
- `ComfyUI/diffusion_models/seedvr2_3b_int8_convrot.safetensors` (declared-url): source is only DECLARED by a workflow/blueprint; no receipt proves these bytes came from there; sha256 recorded (without url) in D:/23.JennieHomeSchool/03 Voice/production-local/JennieJoyKids-Story/03-drinking-milk/qa/seedvr2-full-scene1-ab-v1/source-model-lock.json and equals computed
- `ComfyUI/loras/krea2_style_reference.safetensors` (declared-url): source is only DECLARED by a workflow/blueprint; no receipt proves these bytes came from there; sha256 recorded (without url) in D:/23.JennieHomeSchool/03 Voice/production-local/ComfyUI/user/default/workflows/NEWTECONS_8_NHAN_VAT/CHAR_08_Tran_Thao_Mai_10_Bieu_Cam_10_Hanh_Dong.json and equals computed; safetensors header: trainer=ai-toolkit; ss_base_model_version=krea2
- `ComfyUI/text_encoders/qwen_0.6b_ace15.safetensors` (declared-url): source is only DECLARED by a workflow/blueprint; no receipt proves these bytes came from there; sha256 recorded (without url) in D:/23.JennieHomeSchool/03 Voice/.agents/skills/studio-video-engine/recipes/audio/music-pick-v001.json and equals computed
- `ComfyUI/text_encoders/qwen_1.7b_ace15.safetensors` (none): guess: Comfy-Org/ace_step_1.5_ComfyUI_files split_files/text_encoders/ (sibling qwen_0.6b_ace15 is declared there) - NOT proven
- `ComfyUI/vae/ace_1.5_vae.safetensors` (declared-url): source is only DECLARED by a workflow/blueprint; no receipt proves these bytes came from there; sha256 recorded (without url) in D:/23.JennieHomeSchool/03 Voice/.agents/skills/studio-video-engine/recipes/audio/music-pick-v001.json and equals computed
- `ComfyUI/vae/seedvr2_ema_vae_fp16.safetensors` (declared-url): source is only DECLARED by a workflow/blueprint; no receipt proves these bytes came from there; sha256 recorded (without url) in D:/23.JennieHomeSchool/03 Voice/.agents/skills/studio-video-engine/recipes/seedvr2/v003-7b-int8-tile768-int17-raw21.json and equals computed
