"""Actual HF tokenizer JSON + model-provided Jinja; no weights or torch imports."""
import json

from jinja2.sandbox import ImmutableSandboxedEnvironment
from tokenizers import Tokenizer

from .catalog import RuntimeUnavailable


class TextTokenizer:
    def __init__(self, catalog, spec):
        self.spec = spec
        self.directory = catalog.directory(spec)
        self.descriptor = catalog.descriptor(spec)
        if not self.descriptor["tokenizer_ready"]:
            raise RuntimeUnavailable("Pinned tokenizer files have not finished downloading")
        self.raw = Tokenizer.from_file(str(self.directory / "tokenizer.json"))
        self.raw.no_padding()
        self.raw.no_truncation()
        self.config = json.loads((self.directory / "tokenizer_config.json").read_text())
        self.template = None
        if spec["family"] == "nemotron":
            environment = ImmutableSandboxedEnvironment(trim_blocks=True, lstrip_blocks=True)
            def reject(message):
                raise ValueError(str(message))
            environment.globals["raise_exception"] = reject
            self.template = environment.from_string((self.directory / "chat_template.jinja").read_text())

    def render(self, text, task="document", query=None):
        if self.spec["family"] == "qwen3":
            return self.spec["query_template"].format(text=text) if task == "query" else text
        content = [{"type": "text", "text": text}]
        if self.spec["kind"] == "reranker":
            messages = [{"role": "query", "content": [{"type": "text", "text": query or ""}]},
                        {"role": "document", "content": content}]
        else:
            messages = [{"role": "system", "content": "query:" if task == "query" else "passage:"},
                        {"role": "user", "content": content}]
        special = {key: value.get("content", "") if isinstance(value, dict) else value
                   for key, value in self.config.items() if key.endswith("_token")}
        return self.template.render(messages=messages, add_generation_prompt=False,
                                    tokenize=False, **special)

    def encode(self, text, task="document", query=None):
        # Nemotron chat template includes BOS/EOS; Qwen uses tokenizer postprocessor.
        return self.raw.encode(self.render(text, task, query),
                               add_special_tokens=self.spec["family"] == "qwen3")

    def count(self, text, task="document", query=None):
        return len(self.encode(text, task, query).ids)

    def split(self, text, task, maximum, overlap):
        if not 1 <= maximum <= self.spec["context_length"] or not 0 <= overlap < maximum:
            raise ValueError("Invalid max_tokens/overlap")
        overhead = self.count("", task)
        if maximum <= overhead or overlap >= maximum - overhead:
            raise ValueError("Token budget must leave room beyond the actual template")
        total = self.count(text, task)
        if total <= maximum:
            return [{"text": text, "token_count": total, "char_start": 0, "char_end": len(text)}]
        # Offsets refer to original Unicode characters, never decoded token strings.
        # Byte-fallback tokens can share a character; unique ends preserve it once.
        encoding = self.raw.encode(text, add_special_tokens=False)
        ends = sorted({end for start, end in encoding.offsets if end > start} | {len(text)})
        chunks = []
        start = 0
        while start < len(text):
            import bisect
            first = bisect.bisect_right(ends, start)
            lo, hi = first, len(ends) - 1
            best = None
            while lo <= hi:
                mid = (lo + hi) // 2
                end = ends[mid]
                count = self.count(text[start:end], task)
                if count <= maximum:
                    best = (end, count, mid)
                    lo = mid + 1
                else:
                    hi = mid - 1
            if best is None:
                # Extremely long single tokenizer span: bound by characters, verified again.
                end = start + 1
                count = self.count(text[start:end], task)
                if count > maximum:
                    raise ValueError("A single character exceeds the token budget with template")
                best = (end, count, first)
            end, count, _ = best
            chunks.append({"text": text[start:end], "token_count": count,
                           "char_start": start, "char_end": end})
            if end == len(text):
                break
            if not overlap:
                start = end
                continue
            # Measure overlap in actual raw content tokens and force forward progress.
            offsets = self.raw.encode(text[start:end], add_special_tokens=False).offsets
            proposed = start + offsets[max(0, len(offsets) - overlap)][0]
            start = max(start + 1, min(proposed, end))
        return chunks
