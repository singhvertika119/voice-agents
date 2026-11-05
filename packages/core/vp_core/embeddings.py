"""Text embeddings, computed on our own machine: multilingual-e5-base (768 numbers per text), int8 ONNX (D-122).

Why not OpenAI any more: on the real knowledge it found the right section in the top 3 for 79% of test questions
against OpenAI text-embedding-3-small's 71%, and for Hindi in Devanagari 73% against 47%. It also takes about 20 ms on a
CPU instead of a ~0.25 s round trip from the agent in us-east. It is free and MIT-licensed.

e5 needs to know what a text is: questions are embedded as "query: ..." and stored sections as "passage: ...".
Use embed() for sections and embed_query()/embed_queries() for questions; mixing them up makes search worse.

The model files are baked into the Docker images (`download()`); on a laptop they are downloaded on first use.
"""
from __future__ import annotations

import asyncio
import logging
import os
import threading
from collections import OrderedDict
from collections.abc import Awaitable, Callable

import numpy as np

log = logging.getLogger("embeddings")

MODEL = "multilingual-e5-base"
REPO = "Xenova/multilingual-e5-base"                  # ONNX exports of intfloat/multilingual-e5-base (MIT)
REVISION = "1ec9243030a27d1a115d5c340572074c125b58b2"  # pinned: a different file would change every stored vector
ONNX_FILE = "onnx/model_int8.onnx"
DIMS = 768
MAX_TOKENS = 512

_cache: OrderedDict[str, list[float]] = OrderedDict()  # query embeddings repeat within a call; keep the last 256
_remote: Callable[[str], Awaitable[list[float]]] | None = None
_encoder: Encoder | None = None
_lock = threading.Lock()


def _files(local_only: bool) -> tuple[str, str]:
    from huggingface_hub import hf_hub_download
    get = lambda f: hf_hub_download(REPO, f, revision=REVISION, local_files_only=local_only)  # noqa: E731
    return get(ONNX_FILE), get("tokenizer.json")


def download() -> None:
    """Fetch the model files into the Hugging Face cache (run while building an image)."""
    _files(local_only=False)


class Encoder:
    """The model itself. Thread-safe: several threads may call encode() on one Encoder."""

    def __init__(self, threads: int = 1):
        import onnxruntime as ort
        from tokenizers import Tokenizer
        try:
            model_path, tok_path = _files(local_only=True)
        except Exception:
            log.info("embedding model not in the local cache; downloading %s", REPO)
            model_path, tok_path = _files(local_only=False)
        self._tok = Tokenizer.from_file(tok_path)
        self._tok.enable_truncation(MAX_TOKENS)
        opts = ort.SessionOptions()
        opts.intra_op_num_threads, opts.inter_op_num_threads = threads, 1
        self._session = ort.InferenceSession(model_path, opts, providers=["CPUExecutionProvider"])
        self._inputs = {i.name for i in self._session.get_inputs()}

    def encode(self, texts: list[str], kind: str) -> np.ndarray:
        """kind: "query" for questions, "passage" for stored sections. Returns unit-length float32 rows.
        One text at a time on purpose: the int8 model scales its numbers over the whole batch, so a text embedded
        next to others came out slightly different (cosine 0.99) from the same text alone. Alone, it is always the same."""
        prefix = {"query": "query: ", "passage": "passage: "}[kind]
        out = []
        for t in texts:
            enc = self._tok.encode_batch([prefix + t])
            ids = np.array([e.ids for e in enc], dtype=np.int64)
            mask = np.array([e.attention_mask for e in enc], dtype=np.int64)
            feed = {"input_ids": ids, "attention_mask": mask}
            if "token_type_ids" in self._inputs:
                feed["token_type_ids"] = np.zeros_like(ids)
            hidden = self._session.run(None, feed)[0]
            v = (hidden * mask[..., None]).sum(1) / np.maximum(mask.sum(1, keepdims=True), 1)  # mean of real tokens
            out.append(v / np.linalg.norm(v, axis=1, keepdims=True))
        return np.vstack(out).astype(np.float32) if out else np.zeros((0, DIMS), np.float32)


def encoder() -> Encoder:
    """One model per process, loaded on first use. EMBED_THREADS sets its CPU threads (default 2)."""
    global _encoder
    with _lock:
        if _encoder is None:
            _encoder = Encoder(threads=int(os.getenv("EMBED_THREADS", "2")))
        return _encoder


def use_remote(fn: Callable[[str], Awaitable[list[float]]] | None) -> None:
    """In a call, questions are embedded by the agent's shared model process instead of loading the model into every
    call process (agent_worker.embed_runner). fn(text) -> vector, raising on failure."""
    global _remote
    _remote = fn


async def embed(texts: list[str]) -> list[list[float]]:
    """Stored sections (passages)."""
    if not texts:
        return []
    return (await asyncio.to_thread(encoder().encode, texts, "passage")).tolist()


async def embed_queries(texts: list[str]) -> list[list[float]]:
    """Questions, several at once (no cache)."""
    if not texts:
        return []
    return (await asyncio.to_thread(encoder().encode, texts, "query")).tolist()


async def embed_query(text: str) -> list[float]:
    """One question. Failures raise, so callers fall back to keyword search."""
    if text in _cache:
        _cache.move_to_end(text)
        return _cache[text]
    if _remote is not None:
        vec = await _remote(text)
    else:
        vec = (await asyncio.to_thread(encoder().encode, [text], "query"))[0].tolist()
    _cache[text] = vec
    if len(_cache) > 256:
        _cache.popitem(last=False)
    return vec


def to_pg(vec: list[float]) -> str:
    """pgvector text format."""
    return "[" + ",".join(f"{x:.6f}" for x in vec) + "]"
