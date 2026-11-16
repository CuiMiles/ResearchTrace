"""Immutable model descriptors derived from the provisioned repository files."""
import hashlib
import json
import re
from pathlib import Path


class RuntimeUnavailable(RuntimeError):
    pass


def digest(value):
    return "sha256:" + hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                              separators=(",", ":")).encode()).hexdigest()


def fingerprint(descriptor):
    """Full catalog fingerprint, also independently verified by the API client."""
    required = ("model_id", "revision", "kind", "dimension", "dtype", "context_length", "pooling",
                "normalization", "tokenizer", "templates", "source_sha256", "runtime_version",
                "truncation", "attention_implementation")
    return digest({k: descriptor[k] for k in required})


class Catalog:
    def __init__(self, config, root):
        self.root = Path(root).resolve()
        self.models = json.loads(Path(config).read_text())["models"]
        self._source_cache = {}
        if len({m["model_id"] for m in self.models}) != len(self.models):
            raise ValueError("Duplicate model IDs")
        for spec in self.models:
            if not re.fullmatch(r"[a-f0-9]{40}", spec["revision"]):
                raise ValueError("A full immutable HF commit is required")

    def select(self, model_id, revision=None, kind=None):
        spec = next((m for m in self.models if m["model_id"] == model_id), None)
        if spec is None:
            raise KeyError("Unknown model_id")
        if revision is not None and revision != spec["revision"]:
            raise ValueError("Requested revision differs from pinned revision")
        if kind and spec["kind"] != kind:
            raise ValueError("Wrong model kind for endpoint")
        return spec

    def directory(self, spec):
        path = self.root / "models" / spec["model_id"].replace("/", "--") / spec["revision"]
        resolved = path.resolve()
        if not resolved.is_relative_to(self.root):
            raise RuntimeUnavailable("Model directory escapes private provision root")
        return resolved

    def descriptor(self, spec):
        path = self.directory(spec)
        names = ["tokenizer.json", "tokenizer_config.json", "chat_template.jinja", "config.json",
                 "processor_config.json", "1_Pooling/config.json", "2_Dense/config.json",
                 "config_sentence_transformers.json", "model.py", "model.safetensors.index.json"]
        hashes = {}
        for name in names:
            file = path / name
            if file.is_file():
                if not file.resolve().is_relative_to(path):
                    raise RuntimeUnavailable("Model file escapes provisioned directory")
                key = (str(file), file.stat().st_mtime_ns, file.stat().st_size)
                if key not in self._source_cache:
                    self._source_cache[key] = hashlib.sha256(file.read_bytes()).hexdigest()
                hashes[name] = self._source_cache[key]
        tokenizer_ready = "tokenizer.json" in hashes and "tokenizer_config.json" in hashes
        if spec["family"] == "nemotron":
            tokenizer_ready = tokenizer_ready and "chat_template.jinja" in hashes
        templates = {"query": spec["query_template"], "document": spec["document_template"],
                     "sha256": hashes.get("chat_template.jinja") or digest(
                         [spec["query_template"], spec["document_template"]])[7:]}
        descriptor = {key: spec[key] for key in ("model_id", "revision", "kind", "dimension", "dtype",
                                                  "context_length", "pooling", "normalization")}
        descriptor.update({"tokenizer": {"revision": spec["revision"],
                                         "sha256": digest({k: v for k, v in hashes.items() if k.startswith("tokenizer")})[7:]},
                           "templates": templates, "source_sha256": hashes,
                           "runtime_version": "researchtrace-retrieval-v2-rerank-device-alignment" if spec['kind']=='reranker' else "researchtrace-retrieval-v1",
                           "truncation": "reject", "attention_implementation": "sdpa"})
        descriptor["tokenizer_revision"] = spec["revision"]
        # Opaque template strings include actual Jinja and tokenizer hashes, so
        # the nine-field compatibility fingerprint captures the complete rendering.
        for task in ("query", "document"):
            descriptor[task + "_template"] = json.dumps(
                {"format": spec[task + "_template"], "chat_template":
                 (path / "chat_template.jinja").read_text() if "chat_template.jinja" in hashes else None,
                 "tokenizer_sha256": descriptor["tokenizer"]["sha256"]},
                sort_keys=True, ensure_ascii=False)
        descriptor["provenance_fingerprint"] = digest(descriptor)
        descriptor["fingerprint"] = fingerprint(descriptor)
        descriptor["tokenizer_ready"] = bool(tokenizer_ready)
        ready = path / "weights-ready.json"
        descriptor["weights_ready"] = False
        if ready.is_file():
            record = json.loads(ready.read_text())
            descriptor["weights_ready"] = record.get("revision") == spec["revision"] and all(
                (path / item["path"]).is_file() and (path / item["path"]).stat().st_size == item["bytes"]
                for item in record.get("weights", [])
            ) and bool(record.get("weights"))
        # Verification is attached to actual broker requests; provisioning is not inference.
        descriptor["inference_verified"] = False
        return descriptor
