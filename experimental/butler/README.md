# Butler (working title)

Type or dictate a simple command ("make the display a bit brighter", "set the volume to 40"),
a small multilingual sentence-embedding model (MiniLM) picks the matching catalog command.
No text generation. Work in progress, experimental.

- `butler/catalog/*.json`  commands with EN + DE example sentences; check with `python -m butler.loader`
- `butler/`  loader, matcher, slot extraction, runner (only catalog commands run; argv lists, never shell strings)
- `butler_server.py`  JSON lines over stdin/stdout; gopanel's menu starts it (`butler-server` in PATH or `~/.local/bin`)
- `butler.py`  standalone popup window (GTK), `BUTLER_DRY=1` pretends every command succeeds

Not in git (about 250 MB): `venv/` (onnxruntime + tokenizers, `--system-site-packages`) and `model/`
(`Xenova/paraphrase-multilingual-MiniLM-L12-v2`: `tokenizer.json`, `config.json`, `onnx/model_quantized.onnx`).
User overrides live in `~/.config/cyberbeest/butler/`, embedding cache in `~/.cache/cyberbeest/butler`.
