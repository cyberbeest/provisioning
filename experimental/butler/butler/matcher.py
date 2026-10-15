import re
import numpy as np, onnxruntime as ort
from pathlib import Path
from tokenizers import Tokenizer
from . import loader

MODEL_DIR = Path(__file__).resolve().parent.parent / "model"
MODEL_TAG = "paraphrase-multilingual-MiniLM-L12-v2-q8-numnorm1"   # tag changes invalidate the embedding cache
CACHE = Path.home() / ".cache/cyberbeest/butler"

_NUM = re.compile(r"\d+(?:[.,]\d+)?")

def normalize(text):
    """Canonical form for matching: every number becomes 50 and '40 %' becomes '50%'. Digits otherwise
    pull a sentence away from its examples ('set the volume to 40 %' scored below 'set the volume').
    The real value is read from the original text by slots.py."""
    t = re.sub(r"(\d)\s*%", r"\1%", text)
    return re.sub(r"\s+", " ", _NUM.sub("50", t)).strip()


class Matcher:
    def __init__(self, cmds):
        self.tok = Tokenizer.from_file(str(MODEL_DIR / "tokenizer.json"))
        self.tok.enable_padding(); self.tok.enable_truncation(64)
        so = ort.SessionOptions(); so.intra_op_num_threads = 2
        self.sess = ort.InferenceSession(str(MODEL_DIR / "onnx/model_quantized.onnx"), so, providers=["CPUExecutionProvider"])
        self._in = {i.name for i in self.sess.get_inputs()}
        self.cmds = cmds
        self.owner, self.neg, texts = [], [], []
        for i, c in enumerate(cmds):
            for s, neg in loader.all_examples(c):
                texts.append(s); self.owner.append(i); self.neg.append(neg)
        self.owner = np.array(self.owner); self.neg = np.array(self.neg)
        key = loader.catalog_hash(cmds, MODEL_TAG)
        f = CACHE / f"emb-{key}.npy"
        if f.exists(): self.E = np.load(f)
        else:
            self.E = self.embed(texts); CACHE.mkdir(parents=True, exist_ok=True); np.save(f, self.E)

    def embed(self, texts):
        enc = self.tok.encode_batch([normalize(t) for t in texts])
        ids = np.array([e.ids for e in enc], dtype=np.int64); m = np.array([e.attention_mask for e in enc], dtype=np.int64)
        feed = {"input_ids": ids, "attention_mask": m}
        if "token_type_ids" in self._in: feed["token_type_ids"] = np.zeros_like(ids)
        h = self.sess.run(None, feed)[0]
        v = (h * m[..., None]).sum(1) / m.sum(1, keepdims=True)
        return v / np.linalg.norm(v, axis=1, keepdims=True)

    def match(self, text, k=3):
        s = self.E @ self.embed([text])[0]
        res = []
        for i, c in enumerate(self.cmds):
            sel = self.owner == i
            pos = s[sel & ~self.neg].max()
            neg = s[sel & self.neg].max() if (sel & self.neg).any() else -1
            res.append((pos * (0.5 if neg >= pos else 1.0), i))
        res.sort(reverse=True)
        return [(self.cmds[i], float(sc)) for sc, i in res[:k]]
