"""Bearer-authenticated loopback HTTP API; tokenization is independent of weights."""
import hmac
import os
import stat
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .catalog import Catalog, RuntimeUnavailable
from .supervisor import Busy, Supervisor
from .tokenization import TextTokenizer


class Selection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model_id: str = Field(min_length=3, max_length=180)
    revision: str = Field(pattern=r"^[0-9a-f]{40}$")


class Embed(Selection):
    texts: list[str] = Field(min_length=1, max_length=64)
    task: Literal["query", "document"] = "document"

    @model_validator(mode="after")
    def bounded(self):
        if any(not text.strip() for text in self.texts) or sum(len(t) for t in self.texts) > 500000:
            raise ValueError("Require nonempty texts totaling <=500000 characters")
        return self


class Split(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_tokens: int = Field(ge=1, le=32768)
    overlap: int = Field(default=0, ge=0, lt=32768)


class Tokenize(Embed):
    split: Split | None = None


class TokenizeSingle(Selection):
    text: str = Field(min_length=1, max_length=500000)
    max_tokens: int = Field(ge=1, le=32768)
    overlap: int = Field(default=32, ge=0, lt=32768)
    task: Literal["query", "document"] = "document"


class Rerank(Selection):
    revision: str | None = Field(default=None, pattern=r"^[0-9a-f]{40}$")
    query: str = Field(min_length=1, max_length=32768)
    documents: list[str] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def bounded(self):
        if not self.query.strip() or any(not d.strip() for d in self.documents):
            raise ValueError("Query and documents must be nonempty")
        if sum(len(d) for d in self.documents) + len(self.query) > 500000:
            raise ValueError("Request exceeds bounded text size")
        return self


def create_app(config=None, root=None, token_file=None):
    root = Path(root or os.environ.get("RT_RETRIEVAL_ROOT", "services/retrieval_runtime/private"))
    config = config or os.environ.get("RT_RETRIEVAL_CONFIG", "configs/retrieval-models.json")
    token_file = Path(token_file or os.environ.get("RT_RETRIEVAL_TOKEN_FILE", str(root / "private/auth.token")))
    info = token_file.stat()
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
        raise ValueError("Bearer token file must be owned by current user with mode 0600")
    token = token_file.read_text().strip()
    if len(token) < 32:
        raise ValueError("Bearer token must have at least 32 characters")
    catalog = Catalog(config, root)
    supervisor = Supervisor(catalog)
    tokenizers = {}

    @asynccontextmanager
    async def lifespan(app):
        yield
        supervisor.close()

    app = FastAPI(title="ResearchTrace private retrieval runtime", docs_url=None, redoc_url=None,
                  openapi_url=None, lifespan=lifespan)
    app.state.catalog = catalog
    app.state.supervisor = supervisor

    @app.middleware("http")
    async def authenticate(request: Request, call_next):
        supplied = request.headers.get("authorization", "")
        if not hmac.compare_digest(supplied.encode(), ("Bearer " + token).encode()):
            return JSONResponse(status_code=401, content={"detail": {"code": "unauthorized", "message": "Bearer authentication required"}})
        length = request.headers.get("content-length")
        if length and (not length.isdigit() or int(length) > 4 * 1024 * 1024):
            return JSONResponse(status_code=413, content={"detail": {"code": "body_too_large", "message": "Request limit is 4 MiB"}})
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 4 * 1024 * 1024:
                return JSONResponse(status_code=413, content={"detail": {"code": "body_too_large", "message": "Request limit is 4 MiB"}})
        request._body = bytes(body)
        return await call_next(request)

    def select(payload, kind=None):
        try:
            return catalog.select(payload.model_id, payload.revision, kind)
        except KeyError as error:
            raise HTTPException(404, {"code": "unknown_model", "message": str(error)}) from error
        except ValueError as error:
            raise HTTPException(409, {"code": "model_mismatch", "message": str(error)}) from error

    def tokenizer(spec):
        try:
            descriptor = catalog.descriptor(spec)
            key = descriptor["fingerprint"]
            if key not in tokenizers:
                tokenizers[key] = TextTokenizer(catalog, spec)
            return tokenizers[key]
        except (RuntimeUnavailable, OSError, ValueError) as error:
            raise HTTPException(503, {"code": "tokenizer_unavailable", "message": str(error)}) from error

    def response(spec, result):
        descriptor = catalog.descriptor(spec)
        descriptor["inference_verified"] = descriptor["fingerprint"] in supervisor.verified
        return {**result, "model_id": spec["model_id"], "revision": spec["revision"],
                "fingerprint": descriptor["fingerprint"], "metadata": descriptor}

    @app.get("/manifest")
    def manifest():
        models = []
        for spec in catalog.models:
            descriptor = catalog.descriptor(spec)
            descriptor["inference_verified"] = descriptor["fingerprint"] in supervisor.verified
            models.append(descriptor)
        return {"schema_version": 1, "models": models}

    @app.get("/healthz")
    def health():
        return {"live": True, "inference_verified": False, "level": "liveness_only"}

    @app.post("/tokenize")
    def tokenize(payload: TokenizeSingle | Tokenize):
        spec = select(payload)
        tok = tokenizer(spec)
        single = isinstance(payload, TokenizeSingle)
        texts = [payload.text] if single else payload.texts
        split = Split(max_tokens=payload.max_tokens, overlap=payload.overlap) if single else payload.split
        items = []
        for index, text in enumerate(texts):
            total = tok.count(text, payload.task)
            try:
                if split:
                    chunks = tok.split(text, payload.task, split.max_tokens, split.overlap)
                else:
                    chunks = [{"text": text, "token_count": total, "char_start": 0, "char_end": len(text)}]
            except ValueError as error:
                raise HTTPException(422, {"code": "token_budget_invalid", "message": str(error)}) from error
            items.append({"text_index": index, "token_count": total, "chunks": chunks})
        result = {"items": items}
        if single:
            result["chunks"] = [{"start": chunk["char_start"], "end": chunk["char_end"],
                                 "text": chunk["text"], "token_count": chunk["token_count"]}
                                for chunk in items[0]["chunks"]]
        return response(spec, result)

    def run(spec, payload):
        try:
            return response(spec, supervisor.run(spec, payload.model_dump()))
        except Busy as error:
            raise HTTPException(429, {"code": "runtime_busy", "message": str(error)}, headers={"Retry-After": "2"}) from error
        except (RuntimeUnavailable, RuntimeError, OSError) as error:
            raise HTTPException(503, {"code": "runtime_unavailable", "message": str(error)}) from error

    @app.post("/embed")
    def embed(payload: Embed):
        spec = select(payload, "embedding")
        tok = tokenizer(spec)
        if any(tok.count(text, payload.task) > spec["context_length"] for text in payload.texts):
            raise HTTPException(422, {"code": "context_exceeded", "message": "Split input using /tokenize first"})
        return run(spec, payload)

    @app.post("/rerank")
    def rerank(payload: Rerank):
        spec = select(payload, "reranker")
        tok = tokenizer(spec)
        if any(tok.count(text, query=payload.query) > spec["context_length"] for text in payload.documents):
            raise HTTPException(422, {"code": "context_exceeded", "message": "Query/document pair exceeds context"})
        return run(spec, payload)

    return app


def main():
    import uvicorn
    os.umask(0o077)
    # Loopback is mandatory. Cross-host use requires an authenticated SSH tunnel.
    uvicorn.run(create_app(), host="127.0.0.1", port=int(os.environ.get("RT_RETRIEVAL_PORT", "18985")),
                workers=1, access_log=False)


if __name__ == "__main__":
    main()
