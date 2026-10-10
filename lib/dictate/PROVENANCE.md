Vendored from https://github.com/winidi/dictate (MIT, see LICENSE) at commit
56ac487, plus local changes: panel-icon-only start with autostart option, idle
unload of the local model, tray icon states and tooltip (model state, privacy,
hotkey), English/German UI, reliable typing of accented characters, a
single-word full-stop strip, and removal of the upstream feature that kept
recordings that came back empty on disk, and of the cloud providers (Groq,
OpenAI, Yorik), leaving two local models. Installed by 65-dictate.sh.

Speech models (not part of this repo; both CC-BY-4.0, converted to ONNX int8,
run with sherpa-onnx, downloaded by 65-dictate.sh or by Dictate itself on the
first hotkey press). Each is mirrored at https://cyberbeest.com/models/<name>/
<revision>/ with SHA-256 pins in local_stt.py (MODELS), and has a fallback source:

- "German only (faster)", nemo-de-fastconformer-int8: NVIDIA
  stt_de_fastconformer_hybrid_large_pc (FastConformer transducer, ~115M
  parameters, trained on 2500 h of German, https://huggingface.co/nvidia/
  stt_de_fastconformer_hybrid_large_pc), int8 ONNX export as packaged by
  sherpa-onnx (k2-fsa). Per its model card it only outputs . , ? as
  punctuation and does worse on technical terms and accented speech.
  Fallback: the sherpa-onnx release archive on GitHub.
- "Multi-language (slower)", parakeet-primeline-int8: primeline's German
  fine-tune of NVIDIA Parakeet (~600M parameters). Fallback: Hugging Face.

To publish a different model revision: upload the files to the mirror, then
update the mirror URL and SHA-256 values in MODELS.
