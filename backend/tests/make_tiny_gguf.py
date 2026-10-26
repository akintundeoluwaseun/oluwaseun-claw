"""TEST FIXTURE — writes a tiny random-weight 'llama' model in GGUF format.

It is not a useful model (its words are random). It lets the tests start the
real llama.cpp engine, load a model, and get schema-constrained JSON back,
without downloading multi-GB weights. Byte-level vocabulary, ChatML template.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from gguf import GGUFWriter, TokenType

N_EMBD, N_HEAD, N_FF, N_LAYER, N_CTX = 64, 4, 128, 2, 2048
SPECIALS = ["<|endoftext|>", "<|im_start|>", "<|im_end|>"]
CHATML = (
    "{% for m in messages %}<|im_start|>{{ m['role'] }}\n{{ m['content'] }}<|im_end|>\n{% endfor %}"
    "{% if add_generation_prompt %}<|im_start|>assistant\n{% endif %}"
)


def byte_tokens() -> list[str]:
    # GPT-2 byte-to-unicode table, so every byte is one token
    bs = list(range(ord("!"), ord("~") + 1)) + list(range(ord("¡"), ord("¬") + 1)) + list(range(ord("®"), ord("ÿ") + 1))
    cs = bs[:]
    n = 0
    for b in range(256):
        if b not in bs:
            bs.append(b)
            cs.append(256 + n)
            n += 1
    table = dict(zip(bs, (chr(c) for c in cs)))
    return [table[b] for b in range(256)]


def write(path: Path, seed: int = 0) -> Path:
    rng = np.random.default_rng(seed)
    tokens = byte_tokens() + ["ĠĠ"] + SPECIALS  # one merged token: llama.cpp requires a non-empty merge list
    n_vocab = len(tokens)
    w = GGUFWriter(str(path), "llama")
    w.add_name("claw-test-tiny")
    w.add_context_length(N_CTX)
    w.add_embedding_length(N_EMBD)
    w.add_block_count(N_LAYER)
    w.add_feed_forward_length(N_FF)
    w.add_head_count(N_HEAD)
    w.add_head_count_kv(N_HEAD)
    w.add_layer_norm_rms_eps(1e-5)
    w.add_rope_dimension_count(N_EMBD // N_HEAD)
    w.add_file_type(0)  # all F32
    w.add_tokenizer_model("gpt2")
    w.add_tokenizer_pre("default")
    w.add_token_list(tokens)
    w.add_token_types([TokenType.NORMAL] * 257 + [TokenType.CONTROL] * len(SPECIALS))
    w.add_token_merges(["Ġ Ġ"])
    w.add_bos_token_id(257)
    w.add_eos_token_id(259)
    w.add_add_bos_token(False)
    w.add_chat_template(CHATML)

    def t(name, *shape):
        w.add_tensor(name, (rng.standard_normal(shape) * 0.02).astype(np.float32))

    t("token_embd.weight", n_vocab, N_EMBD)
    w.add_tensor("output_norm.weight", np.ones(N_EMBD, dtype=np.float32))
    t("output.weight", n_vocab, N_EMBD)
    for i in range(N_LAYER):
        w.add_tensor(f"blk.{i}.attn_norm.weight", np.ones(N_EMBD, dtype=np.float32))
        w.add_tensor(f"blk.{i}.ffn_norm.weight", np.ones(N_EMBD, dtype=np.float32))
        for n in ("attn_q", "attn_k", "attn_v", "attn_output"):
            t(f"blk.{i}.{n}.weight", N_EMBD, N_EMBD)
        t(f"blk.{i}.ffn_gate.weight", N_FF, N_EMBD)
        t(f"blk.{i}.ffn_up.weight", N_FF, N_EMBD)
        t(f"blk.{i}.ffn_down.weight", N_EMBD, N_FF)
    w.write_header_to_file()
    w.write_kv_data_to_file()
    w.write_tensors_to_file()
    w.close()
    return path


if __name__ == "__main__":
    print(write(Path(sys.argv[1])))
