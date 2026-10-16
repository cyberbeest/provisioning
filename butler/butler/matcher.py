import hashlib, os, re
import numpy as np, onnxruntime as ort
from pathlib import Path
from tokenizers import Tokenizer
from . import loader

MODEL_DIR = Path(__file__).resolve().parent.parent / "model"
MODEL_TAG = "paraphrase-multilingual-MiniLM-L12-v2-q8-numnorm1"   # tag changes invalidate the embedding cache
CACHE = Path.home() / ".cache/cyberbeest/butler"
SEED = Path(__file__).resolve().parent.parent / "seed" / f"sentences-{MODEL_TAG}.npz"   # shipped with the catalog and factbook

_NUM = re.compile(r"\d+(?:[.,]\d+)?")

def normalize(text):
    """Canonical form for matching: every number becomes 50 and '40 %' becomes '50%'. Digits otherwise
    pull a sentence away from its examples ('set the volume to 40 %' scored below 'set the volume').
    The real value is read from the original text by slots.py."""
    t = re.sub(r"(\d)\s*%", r"\1%", text)
    return re.sub(r"\s+", " ", _NUM.sub("50", t)).strip()


class Matcher:
    def __init__(self, cmds, on_index=None):
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
        self.on_index = on_index   # called with the number of sentences about to be embedded, when the cache lacks some
        self.E = self._cached_embeddings(texts)
        # each command's sentences sit in one block (owner is sorted): where every block starts, for reduceat
        self.starts = np.flatnonzero(np.r_[True, self.owner[1:] != self.owner[:-1]])
        self.block_cmd = self.owner[self.starts]

    def _cached_embeddings(self, texts):
        """Embeddings per sentence: the cache is keyed on the sentence (and model), so editing one fact or adding a
        help entry embeds only the new sentences instead of the whole catalog. Sentences no longer used are dropped."""
        keys = [hashlib.sha1(normalize(t).encode()).hexdigest()[:20] for t in texts]
        f = CACHE / f"sentences-{MODEL_TAG}.npz"
        known = {}
        for src in (SEED, f):   # what ships with Butler first, then what this machine added or changed (it wins)
            try:
                with np.load(src) as z:
                    known.update(zip(z["keys"].tolist(), z["vecs"].astype(np.float32)))
            except (OSError, ValueError, KeyError):
                pass
        missing = [i for i, k in enumerate(keys) if k not in known]
        if missing:
            if self.on_index:
                self.on_index(len(missing))
            new = self.embed([texts[i] for i in missing])
            known.update({keys[i]: v for i, v in zip(missing, new)})
        E = np.stack([known[k] for k in keys]).astype(np.float32)
        if missing or len(known) != len(set(keys)):
            try:
                CACHE.mkdir(parents=True, exist_ok=True)
                used = sorted(set(keys))
                tmp = f.with_suffix(".tmp.npz")
                np.savez(tmp, keys=np.array(used), vecs=np.stack([known[k] for k in used]))
                os.replace(tmp, f)
                for old in CACHE.glob("emb-*.npy"):   # the old whole-catalog cache files
                    old.unlink(missing_ok=True)
            except OSError:
                pass   # a read-only cache only costs time
        return E

    def embed(self, texts, batch=16):
        """Unit vectors for texts. Long lists go in batches of similar length: padding every short command
        sentence up to the longest fact made the first (uncached) run take minutes on the laptop."""
        if len(texts) <= batch:
            return self._embed(texts)
        order = sorted(range(len(texts)), key=lambda i: len(texts[i]))
        out = np.empty((len(texts), 384), dtype=np.float32)
        for k in range(0, len(order), batch):
            idx = order[k:k + batch]
            out[idx] = self._embed([texts[i] for i in idx])
        return out

    def _embed(self, texts):
        enc = self.tok.encode_batch([normalize(t) for t in texts])
        ids = np.array([e.ids for e in enc], dtype=np.int64); m = np.array([e.attention_mask for e in enc], dtype=np.int64)
        feed = {"input_ids": ids, "attention_mask": m}
        if "token_type_ids" in self._in: feed["token_type_ids"] = np.zeros_like(ids)
        h = self.sess.run(None, feed)[0]
        v = (h * m[..., None]).sum(1) / m.sum(1, keepdims=True)
        return v / np.linalg.norm(v, axis=1, keepdims=True)

    def match(self, text, k=3):
        s = self.E @ self.embed([text])[0]
        # best positive and best negative score per command, each in one pass over all sentences
        pos = np.full(len(self.cmds), -np.inf, dtype=np.float32)
        neg = np.full(len(self.cmds), -1.0, dtype=np.float32)   # -1: the command has no negative examples
        pos[self.block_cmd] = np.maximum.reduceat(np.where(self.neg, -np.inf, s), self.starts)
        neg[self.block_cmd] = np.maximum(np.maximum.reduceat(np.where(self.neg, s, -np.inf), self.starts), -1.0)
        score = pos * np.where(neg >= pos, 0.5, 1.0)
        order = sorted(range(len(self.cmds)), key=lambda i: (-score[i], -i))[:k]   # ties: later command first, as before
        return [(self.cmds[i], float(score[i])) for i in order]
