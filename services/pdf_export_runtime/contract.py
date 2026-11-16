"""Strict JSON contract. This module does not import the heavy PDF engines."""
from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


class ContractError(ValueError):
    """Messages are fixed error codes, never untrusted input."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def write_private_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = path.with_name(path.name + ".tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(json_bytes(value))
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


def private_path(root: Path, relative: str, *, must_exist: bool = True) -> Path:
    if not isinstance(relative, str) or len(relative) > 500:
        raise ContractError("invalid_path")
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts or not path.parts or path.parts[0] != "private":
        raise ContractError("path_outside_private_root")
    result = root / path
    current = root
    for part in path.parts:
        current = current / part
        if current.is_symlink():
            raise ContractError("symlink_rejected")
    try:
        result.resolve(strict=must_exist).relative_to(root.resolve(strict=True) / "private")
    except (ValueError, OSError):
        raise ContractError("path_outside_private_root") from None
    return result


def validate_callback_url(value: str) -> str:
    if not isinstance(value, str) or len(value) > 500 or any(ord(c) < 33 for c in value):
        raise ContractError("invalid_callback_url")
    try:
        url = urlsplit(value)
        address = ipaddress.ip_address(url.hostname or "")
        port = url.port
    except ValueError:
        raise ContractError("callback_requires_literal_loopback") from None
    # Literal loopback avoids DNS/rebinding, userinfo and redirects are forbidden.
    if (url.scheme != "http" or not address.is_loopback or address.version == 6 and address != ipaddress.ip_address("::1")
            or url.username is not None or url.password is not None or not port or url.query or url.fragment
            or not re.fullmatch(r"/[A-Za-z0-9_./-]+", url.path) or ".." in url.path.split("/")):
        raise ContractError("invalid_callback_url")
    return value


def read_token(path: Path) -> str:
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_uid != os.getuid() or info.st_size > 1024:
        raise ContractError("token_file_requires_private_owner")
    token = path.read_text().strip()
    if not re.fullmatch(r"[A-Za-z0-9_.~-]{24,512}", token):
        raise ContractError("invalid_callback_token")
    return token


@dataclass(frozen=True)
class ExportJob:
    root: Path
    job_id: str
    input_pdf: Path
    input_sha256: str
    token_file: Path
    callback_url: str
    source_lang: str
    target_lang: str
    page_start: int
    page_end: int
    mode: str
    qps: int
    pool: int
    callback_timeout_s: int
    timeout_s: int
    callback_label: str
    provenance: dict
    contract_sha256: str

    @property
    def directory(self) -> Path:
        return private_path(self.root, f"private/jobs/{self.job_id}", must_exist=False)

    def page_selection(self, total_pages: int, max_pages: int) -> tuple[int, int]:
        end = min(self.page_end, total_pages) if self.mode == "preview" else self.page_end
        if self.page_start > end or end > total_pages or end - self.page_start + 1 > max_pages:
            raise ContractError("page_limit_exceeded")
        if self.mode == "full" and (self.page_start != 1 or end != total_pages):
            raise ContractError("full_requires_every_page")
        return self.page_start, end


def load_job(root: Path, job_file: str) -> ExportJob:
    root = root.resolve(strict=True)
    path = private_path(root, job_file)
    if not path.is_file() or path.stat().st_size > 16384:
        raise ContractError("invalid_job_file")
    try:
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ContractError("duplicate_json_key")
                result[key] = value
            return result
        obj = json.loads(path.read_text(), object_pairs_hook=unique)
    except (UnicodeError, json.JSONDecodeError):
        raise ContractError("invalid_job_json") from None
    fields = {"job_id", "input_pdf", "input_sha256", "token_file", "callback_url", "source_lang", "target_lang",
              "pages", "mode", "qps", "pool", "callback_timeout_s", "timeout_s", "callback_label", "provenance"}
    if not isinstance(obj, dict) or set(obj) - fields:
        raise ContractError("unknown_job_fields")
    required = {"job_id", "input_pdf", "input_sha256", "token_file", "callback_url", "source_lang", "target_lang"}
    if not required <= obj.keys():
        raise ContractError("missing_job_fields")
    job_id = obj["job_id"]
    if not isinstance(job_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", job_id):
        raise ContractError("invalid_job_id")
    source, target = obj["source_lang"], obj["target_lang"]
    if not isinstance(source, str) or not isinstance(target, str) or source not in {"en", "zh", "zh-Hans", "auto"} or target not in {"en", "zh", "zh-Hans"} or source == target:
        raise ContractError("invalid_language_pair")
    pages = obj.get("pages", {"start": 1, "end": 2})
    if not isinstance(pages, dict) or set(pages) != {"start", "end"} or any(type(pages[k]) is not int for k in pages):
        raise ContractError("invalid_pages")
    if not 1 <= pages["start"] <= pages["end"] <= 10000:
        raise ContractError("invalid_pages")
    numbers = {}
    for name, default, low, high in (("qps", 1, 1, 4), ("pool", 1, 1, 4), ("callback_timeout_s", 240, 1, 600), ("timeout_s", 900, 10, 14400)):
        value = obj.get(name, default)
        if type(value) is not int or not low <= value <= high:
            raise ContractError("invalid_numeric_limit")
        numbers[name] = value
    mode = obj.get("mode", "preview")
    if not isinstance(mode, str) or mode not in {"preview", "full"}:
        raise ContractError("invalid_mode")
    label = obj.get("callback_label", "LEDGER_BRIDGE")
    if not isinstance(label, str) or label not in {"LEDGER_BRIDGE", "TEST_IDENTITY_FIXTURE"}:
        raise ContractError("invalid_callback_label")
    provenance = obj.get("provenance", {})
    if not isinstance(provenance, dict) or set(provenance) - {"workspace_id", "version_id", "parse_id", "provider_model", "parent_run_id"}:
        raise ContractError("invalid_provenance")
    if any(not isinstance(v, str) or not re.fullmatch(r"[A-Za-z0-9_.:/-]{1,200}", v) for v in provenance.values()):
        raise ContractError("invalid_provenance")
    digest = obj["input_sha256"]
    if not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest):
        raise ContractError("invalid_input_hash")
    input_pdf = private_path(root, obj["input_pdf"])
    if not input_pdf.is_file() or input_pdf.suffix.lower() != ".pdf" or input_pdf.stat().st_size > 128 * 1024 * 1024:
        raise ContractError("invalid_input_pdf")
    with input_pdf.open("rb") as stream:
        if not stream.read(8).startswith(b"%PDF-"):
            raise ContractError("invalid_input_pdf")
    if sha256_file(input_pdf) != digest:
        raise ContractError("input_hash_mismatch")
    token_file = private_path(root, obj["token_file"])
    read_token(token_file)
    return ExportJob(root, job_id, input_pdf, digest, token_file, validate_callback_url(obj["callback_url"]),
                     source, target, pages["start"], pages["end"], mode, numbers["qps"], numbers["pool"],
                     numbers["callback_timeout_s"], numbers["timeout_s"], label, provenance,
                     hashlib.sha256(json_bytes(obj)).hexdigest())
