"""Fixed offline inference child. Only the authenticated broker may launch it."""
import json
import os
import select
import sys
from pathlib import Path

from .catalog import Catalog
from .tokenization import TextTokenizer


def load(catalog, spec):
    import torch
    from transformers import AutoModel, AutoModelForSequenceClassification
    torch.set_num_threads(int(os.environ.get("RT_RETRIEVAL_CPU_THREADS", "4")))
    torch.set_num_interop_threads(1)
    directory = catalog.directory(spec)
    descriptor = catalog.descriptor(spec)
    if not descriptor["weights_ready"]:
        raise RuntimeError("Pinned weights not completely provisioned")
    mode = os.environ["RT_RETRIEVAL_EXECUTION_MODE"]
    kwargs = {"local_files_only": True, "dtype": torch.bfloat16, "attn_implementation": "sdpa"}
    if mode == "cpu":
        kwargs["device_map"] = {"": "cpu"}
    else:
        if not torch.cuda.is_available() or not torch.cuda.is_bf16_supported():
            raise RuntimeError("Selected CUDA device lacks BF16 support")
        budget = int(os.environ["RT_RETRIEVAL_GPU_MAX_MIB"])
        for index in range(torch.cuda.device_count()):
            total = torch.cuda.get_device_properties(index).total_memory
            torch.cuda.set_per_process_memory_fraction((budget - 384) * 1024**2 / total, index)
        if mode == "cuda":
            kwargs["device_map"] = {"": 0}
        elif mode == "cpu_offload":
            kwargs["device_map"] = "auto"
            kwargs["max_memory"] = {0: f"{budget - 2048}MiB", "cpu": "30GiB"}
            kwargs["offload_folder"] = os.environ["RT_RETRIEVAL_JOB_DIR"] + "/offload"
            kwargs["offload_state_dict"] = True
        elif mode == "cuda_sharded":
            if not 2<=torch.cuda.device_count()<=4:
                raise RuntimeError("Sharded profile requires2..4 guarded CUDA devices")
            kwargs["device_map"] = "balanced"
            headroom=768 if budget<8192 else 1536
            kwargs["max_memory"] = {**{i:f"{budget-headroom}MiB" for i in range(torch.cuda.device_count())},"cpu":"0GiB"}
        else:
            raise RuntimeError("Unknown execution mode")
    if spec["kind"] == "reranker":
        # Only this exact model.py hash, reviewed before launch, can execute.
        reviewed = json.loads((Path(os.environ["RT_RETRIEVAL_CONFIG"]).parent / "retrieval-models-code-review.json").read_text())
        expected = reviewed.get(spec["revision"])
        actual = descriptor["source_sha256"].get("model.py")
        if not expected or expected != actual:
            raise RuntimeError("Custom reranker code is not approved at this fixed revision/hash")
        model = AutoModelForSequenceClassification.from_pretrained(str(directory), trust_remote_code=True, **kwargs)
        # Upstream's direct tensor pooling bypasses Accelerate module hooks.
        # Keep its formula/precision, explicitly align mask and final linear input.
        from types import MethodType
        from transformers.modeling_outputs import SequenceClassifierOutputWithPast
        def aligned_forward(self,input_ids=None,attention_mask=None,**extra):
            outputs=self.model(input_ids=input_ids,attention_mask=attention_mask,**extra)
            hidden=outputs.last_hidden_state;mask=attention_mask.to(hidden.device)
            pooled=hidden.masked_fill(~mask[...,None].bool(),0).sum(1)/mask.sum(1)[:,None]
            logits=torch.nn.functional.linear(pooled.float().to(self.score.weight.device),self.score.weight.float())
            return SequenceClassifierOutputWithPast(logits=logits)
        model.forward=MethodType(aligned_forward,model)
    else:
        model = AutoModel.from_pretrained(str(directory), trust_remote_code=False, **kwargs)
    model.eval()
    placements = {str(value) for value in getattr(model, "hf_device_map", {"": "cpu"}).values()}
    if "disk" in placements:
        raise RuntimeError("Disk offload is not authorized by this bounded CPU offload profile")
    if mode == "cpu_offload" and not ({"cpu"} & placements):
        raise RuntimeError("CPU offload profile unexpectedly did not offload to CPU")
    if mode == "cuda_sharded" and ("cpu" in placements or not placements.issubset({str(i) for i in range(torch.cuda.device_count())}|{f'cuda:{i}' for i in range(torch.cuda.device_count())})):
        raise RuntimeError("Two-card GPU profile cannot silently use CPU or disk placement")
    return model, torch


def infer(model, torch, tokenizer, request):
    spec = tokenizer.spec
    vectors, scores, lengths = [], [], []
    if spec["kind"] == "reranker":
        texts = request["documents"]
    else:
        texts = request["texts"]
    device = model.get_input_embeddings().weight.device
    # Accelerate's hooks route the embedding module to its execution device.
    if device.type == "meta":
        device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    encoded=[tokenizer.encode(text,request.get("task","document"),request.get("query")).ids for text in texts]
    lengths=[len(ids) for ids in encoded]
    if any(n>spec["context_length"] for n in lengths):
        raise ValueError("Input exceeds pinned context; use /tokenize split before inference")
    offset=0;peak_batch=0
    while offset<len(encoded):
        group=[encoded[offset]]
        while offset+len(group)<len(encoded) and len(group)<8:
            candidate=encoded[offset+len(group)]
            if max(len(candidate),max(map(len,group)))*(len(group)+1)>2048:break
            group.append(candidate)
        width=max(map(len,group));peak_batch=max(peak_batch,len(group))
        pad=getattr(model.config,"pad_token_id",None) or 0
        batch={"input_ids":torch.tensor([ids+[pad]*(width-len(ids)) for ids in group],dtype=torch.long,device=device),
               "attention_mask":torch.tensor([[1]*len(ids)+[0]*(width-len(ids)) for ids in group],dtype=torch.long,device=device)}
        with torch.inference_mode():
            output=model(**batch,use_cache=False)
            if spec["kind"]=="reranker":
                values=output.logits.reshape(-1).float()
                if values.numel()!=len(group) or not torch.isfinite(values).all():
                    raise RuntimeError("Non-finite or wrong-size reranker output")
                scores.extend(values.cpu().tolist())
            else:
                hidden=output.last_hidden_state
                if spec["pooling"]=="mean":
                    mask=batch["attention_mask"].to(hidden.device).unsqueeze(-1)
                    pooled=(hidden*mask).sum(1)/mask.sum(1)
                else:
                    # Right padding: pick the last source token, never the padding.
                    indices=torch.tensor([len(ids)-1 for ids in group],device=hidden.device)
                    pooled=hidden[torch.arange(len(group),device=hidden.device),indices]
                vector=torch.nn.functional.normalize(pooled.float(),p=2,dim=-1)
                if vector.shape!=(len(group),spec["dimension"]) or not torch.isfinite(vector).all():
                    raise RuntimeError("Non-finite or wrong-size embedding")
                vectors.extend(vector.cpu().tolist())
        offset+=len(group)
        del output,batch
    if torch.cuda.is_available() and os.environ["RT_RETRIEVAL_EXECUTION_MODE"] != "cpu":
        torch.cuda.synchronize()
    return {("scores" if spec["kind"] == "reranker" else "vectors"): scores if spec["kind"] == "reranker" else vectors,
            "usage": {"inputs": len(texts), "input_tokens": sum(lengths), "batch_size": peak_batch, "padded_token_budget": 2048},
            "device_map": {key: str(value) for key, value in getattr(model, "hf_device_map", {}).items()}}


def main():
    # No sockets or provider credentials are available to the fixed model runner.
    import socket
    def denied(*args, **kwargs):
        raise PermissionError("Retrieval model runner is offline")
    socket.socket.connect = denied
    socket.create_connection = denied
    catalog = Catalog(os.environ["RT_RETRIEVAL_CONFIG"], os.environ["RT_RETRIEVAL_ROOT"])
    spec = catalog.select(os.environ["RT_RETRIEVAL_MODEL_ID"])
    tokenizer = TextTokenizer(catalog, spec)
    model, torch = load(catalog, spec)
    print(json.dumps({"ready": True}), flush=True)
    while select.select([sys.stdin], [], [], 120)[0]:
        line = sys.stdin.readline(4 * 1024 * 1024)
        if not line:
            return
        try:
            request = json.loads(line)
            result = infer(model, torch, tokenizer, request)
            print(json.dumps(result, allow_nan=False), flush=True)
        except (RuntimeError, ValueError, TypeError, KeyError, OSError) as error:
            print(json.dumps({"error": type(error).__name__ + ": " + str(error)[:400]}), flush=True)


if __name__ == "__main__":
    main()
