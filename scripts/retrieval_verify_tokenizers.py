#!/usr/bin/env python3
"""No-weight check against the pinned model's Transformers/AutoProcessor path."""
import argparse
import json
import os
from pathlib import Path

from services.retrieval_runtime.catalog import Catalog
from services.retrieval_runtime.tokenization import TextTokenizer


def verify(config, root):
    if os.environ.get("CUDA_VISIBLE_DEVICES") != "":
        raise RuntimeError("Set CUDA_VISIBLE_DEVICES='' for this CPU-only metadata check")
    from transformers import AutoProcessor, AutoTokenizer
    catalog = Catalog(config, root)
    rows = []
    samples = ["第六作者是谁？", "The experiment used eight GPUs.", "<s> [IMG] <test> a\n\nb", "中文🙂 emoji and naïve text"]
    for spec in catalog.models:
        tokenizer = TextTokenizer(catalog, spec)
        path = str(catalog.directory(spec))
        official = AutoTokenizer.from_pretrained(path, local_files_only=True) if spec["family"] == "qwen3" else AutoProcessor.from_pretrained(path, local_files_only=True)
        checked = 0
        for text in samples:
            for task in ("query", "document"):
                if spec["family"] == "qwen3":
                    rendered = tokenizer.render(text, task)
                    expected = official(rendered, truncation=False)["input_ids"]
                else:
                    if spec["kind"] == "reranker":
                        messages = [{"role": "query", "content": [{"type": "text", "text": "科研 GPU query"}]},
                                    {"role": "document", "content": [{"type": "text", "text": text}]}]
                    else:
                        messages = [{"role": "system", "content": "query:" if task == "query" else "passage:"},
                                    {"role": "user", "content": [{"type": "text", "text": text}]}]
                    expected = official.apply_chat_template(messages, tokenize=True, return_dict=True,
                                                            add_generation_prompt=False)["input_ids"][0]
                actual = tokenizer.encode(text, task, "科研 GPU query").ids
                if actual != list(expected):
                    raise RuntimeError("Tokenizer mismatch for " + spec["model_id"] + ": actual=" + str(actual) + " expected=" + str(expected))
                checked += 1
        rows.append({"model_id": spec["model_id"], "revision": spec["revision"], "status": "PASS", "cases": checked})
        print(json.dumps(rows[-1]), flush=True)
    return rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=Path("configs/retrieval-models.json"))
    args = parser.parse_args()
    verify(args.config, args.root)
