Vendored from https://github.com/winidi/dictate (MIT, see LICENSE) at commit
56ac487, plus local changes: panel-icon-only start with autostart option, idle
unload of the local model, tray icon states and tooltip (model state, privacy,
hotkey), English/German UI, reliable typing of accented characters, and a
single-word full-stop strip. Installed by 65-dictate.sh.

The speech model (parakeet-primeline, CC-BY-4.0, primeline / NVIDIA) is not
part of this repo. It is mirrored at https://cyberbeest.com/models/
parakeet-primeline-onnx/<revision>/ (SHA-256 pinned in local_stt.py, Hugging
Face as fallback) and downloaded by 65-dictate.sh, or by Dictate itself on the
first hotkey press if that was skipped. To publish a different model revision:
upload the files there, then update MODEL_MIRROR and MODEL_SHA256.
