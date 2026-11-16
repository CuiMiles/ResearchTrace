"""GROBID metadata sidecars; never imports or mutates the application database.

Only operator configuration may supply base_url/token_file. PDF/TEI data cannot
choose an endpoint, filesystem destination or executable. See GROBID_INTEGRATION.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import http.client
import io
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import secrets
import socket
import ssl
import stat
import tempfile
import threading
import time
import unicodedata
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET

TEI = "{http://www.tei-c.org/ns/1.0}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
MAX_XML_BYTES = 16 * 1024 * 1024
MAX_PDF_BYTES = 64 * 1024 * 1024
MAX_XML_NODES = 200_000
MAX_XML_DEPTH = 128
SCHEMA = "researchtrace-scholarly-metadata-v1"
VERSION = "0.9.1"
SOURCE_COMMIT = "523bb8e97f357e93682dc4eaa6d22faa8b5b93de"


class MetadataError(ValueError):
    """Sanitized error: no credentials, remote response body or URLs."""


def _text(element):
    return " ".join(" ".join(element.itertext()).split()) if element is not None else ""


def _find(element, path):
    return element.find("/".join(TEI + p for p in path.split("/"))) if element is not None else None


def _all(element, path):
    return element.findall("/".join(TEI + p for p in path.split("/"))) if element is not None else []


def _ids(element):
    return [{"type": e.get("type", "unknown"), "value": _text(e)}
            for e in _all(element, "idno") if _text(e)]


def _name(element):
    name = _find(element, "persName")
    if name is None:
        return {"name": _text(_find(element, "orgName")), "given_names": [], "family_name": ""}
    given = [_text(n) for n in _all(name, "forename") if _text(n)]
    surname = " ".join(_text(n) for n in _all(name, "surname") if _text(n))
    suffix = " ".join(_text(n) for n in _all(name, "genName") if _text(n))
    return {"name": " ".join(x for x in [*given, surname, suffix] if x) or _text(name),
            "given_names": given, "family_name": surname}


def _page_sizes(root, supplied):
    sizes = {}
    for surface in _all(root, "facsimile/surface"):
        try:
            i = int(surface.get("n", "0")) - 1
            width = float(surface.get("lrx")) - float(surface.get("ulx", "0"))
            height = float(surface.get("lry")) - float(surface.get("uly", "0"))
            if i >= 0 and all(math.isfinite(x) and x > 0 for x in (width, height)):
                sizes[i] = (width, height)
        except (ValueError, TypeError):
            pass
    if supplied is not None:
        entries = supplied.items() if isinstance(supplied, dict) else enumerate(supplied)
        for i, size in entries:
            if isinstance(i, bool) or not isinstance(i, int) or i < 0:
                raise MetadataError("page_sizes keys must be zero-based integer page indexes")
            if isinstance(size, dict):
                width, height = size.get("width"), size.get("height")
            else:
                try:
                    width, height = size
                except (ValueError, TypeError):
                    raise MetadataError("page_sizes requires width/height pairs") from None
            if any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) or x <= 0
                   for x in (width, height)):
                raise MetadataError("Invalid page dimensions")
            sizes[i] = (float(width), float(height))
    return sizes


def _positions(element, sizes, warnings):
    raw = element.get("coords", "") if element is not None else ""
    result = []
    for piece in raw.split(";") if raw else []:
        try:
            values = piece.split(",")
            if len(values) != 5 or not re.fullmatch(r"[1-9]\d*", values[0].strip()):
                raise ValueError
            page = int(values[0]) - 1
            x, y, w, h = map(float, values[1:])
            if not all(math.isfinite(v) for v in (x, y, w, h)) or min(x, y) < 0 or min(w, h) <= 0:
                raise ValueError
            bbox = None
            if page in sizes:
                width, height = sizes[page]
                if x + w > width + .1 or y + h > height + .1:
                    raise ValueError
                # Do not silently clamp out-of-page coordinates into valid evidence.
                bbox = [x / width, y / height, (x + w) / width, (y + h) / height]
                if any(v > 1 for v in bbox):
                    raise ValueError
            result.append({"page_index": page, "bbox_pdf_units": [x, y, x + w, y + h],
                           "bbox": bbox, "source": "grobid_tei", "source_coords": piece})
        except (ValueError, TypeError, OverflowError):
            warnings.append("invalid_tei_coordinates")
    return result


def parse_tei(xml: str | bytes, page_sizes=None) -> dict:
    """Pure, bounded TEI parser. page_sizes uses physical zero-based page indexes.

    Coordinates are GROBID's top-left PDF units; normalized bbox is None when
    dimensions are unavailable. Extracted strings are metadata, not quotations.
    DTDs/entities are rejected even if they would only reference local resources.
    """
    if not isinstance(xml, (str, bytes)):
        raise MetadataError("TEI must be UTF-8 text or bytes")
    raw = xml.encode("utf-8") if isinstance(xml, str) else xml
    if len(raw) > MAX_XML_BYTES:
        raise MetadataError("TEI response exceeds size limit")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise MetadataError("TEI must use UTF-8") from None
    if re.search(r"<!\s*(?:DOCTYPE|ENTITY)\b", text, re.I) or "\x00" in text:
        raise MetadataError("DTD/entities and non-UTF-8 XML are forbidden")
    encoding = re.match(r"\s*<\?xml[^>]*encoding\s*=\s*['\"]([^'\"]+)", text, re.I)
    if encoding and encoding[1].lower() not in ("utf-8", "utf8", "us-ascii"):
        raise MetadataError("TEI must use UTF-8")
    try:
        count = depth = 0
        parser = ET.iterparse(io.StringIO(text), events=("start", "end"))
        for event, _ in parser:
            if event == "start":
                count += 1
                depth += 1
                if count > MAX_XML_NODES or depth > MAX_XML_DEPTH:
                    raise MetadataError("TEI structure exceeds node/depth limit")
            else:
                depth -= 1
        root = parser.root
    except ET.ParseError:
        raise MetadataError("Malformed TEI XML") from None
    if root.tag != TEI + "TEI":
        raise MetadataError("Expected namespaced TEI document")
    sizes = _page_sizes(root, page_sizes)
    warnings = []
    positions = lambda el: _positions(el, sizes, warnings)
    source = _find(root, "teiHeader/fileDesc/sourceDesc/biblStruct")
    analytic = _find(source, "analytic")
    title_el = _find(analytic, "title")
    if not _text(title_el):
        title_el = _find(root, "teiHeader/fileDesc/titleStmt/title")
    affs, inline_affs, ambiguous_affs = {}, {}, set()
    for el in source.iter(TEI + "affiliation") if source is not None else []:
        key = el.get("key") or el.get(XML_ID)
        aff = {"tei_id": key, "tei_text": _text(el),
               "organizations": [{"type": n.get("type", "unknown"), "name": _text(n)}
                                 for n in _all(el, "orgName") if _text(n)],
               "address": _text(_find(el, "address")),
               "raw_affiliation": " ".join(_text(n) for n in _all(el, "note")
                                              if n.get("type") == "raw_affiliation"),
               "positions": positions(el)}
        inline_affs[id(el)] = aff
        if key and (aff["organizations"] or aff["tei_text"]):
            if key in affs and affs[key] != aff:
                ambiguous_affs.add(key)
                warnings.append("ambiguous_affiliation_identifier")
            else:
                affs[key] = aff
    authors = []
    for i, el in enumerate(_all(analytic, "author")):
        linked = []
        unresolved = []
        for af in _all(el, "affiliation"):
            key = af.get("key") or af.get(XML_ID)
            ref = af.get("ref", "").removeprefix("#")
            if _text(af):
                linked.append(inline_affs[id(af)])
            elif ref in affs and ref not in ambiguous_affs:
                linked.append(affs[ref])
            elif ref:
                unresolved.append(ref)
        authors.append({"order": i + 1, **_name(el),
                        "emails": [_text(n) for n in _all(el, "email") if _text(n)],
                        "identifiers": _ids(el), "affiliations": linked,
                        "unresolved_affiliation_refs": unresolved,
                        "positions": positions(_find(el, "persName")),
                        "association_status": "grobid_extracted_needs_source_review"})
    references = []
    for list_bibl in root.iter(TEI + "listBibl"):
        for el in list_bibl:
            if el.tag not in (TEI + "biblStruct", TEI + "bibl"):
                continue
            ana, mono = _find(el, "analytic"), _find(el, "monogr")
            ref_title = _find(ana, "title")
            if ref_title is None:
                ref_title = _find(mono, "title")
            date = _find(mono, "imprint/date")
            name_source = ana if ana is not None else mono
            references.append({"order": len(references) + 1, "tei_id": el.get(XML_ID),
                               "title": _text(ref_title),
                               "authors": [{"order": j + 1, **_name(a)}
                                           for j, a in enumerate(_all(name_source, "author"))],
                               "date": date.get("when") or _text(date) if date is not None else None,
                               "container_title": _text(_find(mono, "title")) if ana is not None else "",
                               "identifiers": _ids(el),
                               "raw_reference": " ".join(_text(n) for n in _all(el, "note")
                                                           if n.get("type") == "raw_reference"),
                               "positions": positions(el), "title_positions": positions(ref_title)})
    ref_ids = {r["tei_id"] for r in references if r["tei_id"]}
    markers = []
    for el in root.iter(TEI + "ref"):
        if el.get("type") != "bibr":
            continue
        targets = [p[1:] for p in el.get("target", "").split() if p.startswith("#")]
        markers.append({"tei_text": _text(el), "targets": targets,
                        "unresolved_targets": [p for p in targets if p not in ref_ids],
                        "positions": positions(el), "status": "tei_target_only"})
    applications = [{"ident": el.get("ident"), "version": el.get("version")}
                    for el in root.iter(TEI + "application")]
    # These are review flags, not a name correction heuristic. Never drop a
    # purported author, renumber the remaining authors or guess affiliations.
    if any(re.search(r"\b(university|institute|research|laboratory|department|college|corporation)\b", a["name"], re.I)
           for a in authors):
        warnings.append("possible_organization_in_author_list")
    if any(a["unresolved_affiliation_refs"] for a in authors):
        warnings.append("unresolved_author_affiliation")
    return {"schema": SCHEMA, "title": _text(title_el), "title_positions": positions(title_el),
            "authors": authors, "affiliations": list(affs.values()), "references": references,
            "citation_markers": markers, "applications": applications,
            "page_sizes": [{"page_index": i, "width": size[0], "height": size[1]}
                           for i, size in sorted(sizes.items())],
            "tei_sha256": hashlib.sha256(raw).hexdigest(), "warnings": sorted(set(warnings)),
            "quality": "extracted_metadata_not_verified_evidence", "publishable_as_verified_metadata": False,
            "coverage": {"title_present": bool(_text(title_el)), "authors_extracted": len(authors),
                         "authors_with_affiliations": sum(bool(a["affiliations"]) for a in authors),
                         "authors_with_contacts": sum(bool(a["emails"]) for a in authors),
                         "references_extracted": len(references)}, "ocr": False}


def _operator_endpoint(base_url, token_file):
    raw = base_url if base_url is not None else os.getenv("RT_GROBID_BASE", "http://127.0.0.1:18070")
    try:
        url = urlsplit(raw)
        port = url.port or (443 if url.scheme == "https" else 80)
        if url.scheme not in ("http", "https") or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError
        if not re.fullmatch(r"(?:/[A-Za-z0-9_-]+)*/?", url.path):
            raise ValueError
        if not 1 <= port <= 65535:
            raise ValueError
    except (ValueError, TypeError):
        raise MetadataError("Invalid operator GROBID endpoint") from None
    host = url.hostname
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    loopback = ip is not None and ip.is_loopback
    token_path = token_file if token_file is not None else os.getenv("RT_GROBID_TOKEN_FILE")
    token = None
    if token_path:
        try:
            with open(token_path, "r", encoding="ascii") as f:
                info = os.fstat(f.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_uid != os.getuid():
                    raise MetadataError("Token file must be private and owned by the operator")
                token = f.read(1025).strip()
            if not re.fullmatch(r"[A-Za-z0-9._~+/-]{16,1024}=*", token):
                raise MetadataError("Invalid operator authentication token")
        except (OSError, UnicodeError):
            raise MetadataError("Cannot read private operator token") from None
    if not loopback and (url.scheme != "https" or not token):
        raise MetadataError("Remote GROBID requires HTTPS and an operator token file")
    # Resolve once, reject non-public remote addresses, and pin that address for
    # the TLS connection while retaining the original hostname for SNI/cert checks.
    try:
        addresses = sorted({r[4][0] for r in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)})
    except OSError:
        raise MetadataError("GROBID endpoint DNS lookup failed") from None
    if not addresses or any(not ipaddress.ip_address(a).is_global for a in addresses) and not loopback:
        raise MetadataError("Remote GROBID resolved to a non-public address")
    if loopback and not all(ipaddress.ip_address(a).is_loopback for a in addresses):
        raise MetadataError("Invalid loopback endpoint")
    return url, port, addresses[0], token


@dataclass(frozen=True)
class MetadataResult:
    metadata: dict
    tei_xml: bytes
    provenance: dict


def fetch_metadata(pdf_path, base_url=None, token_file=None, *, mode="full", end_page=None,
                   page_sizes=None, timeout=180.0, max_response_bytes=MAX_XML_BYTES) -> MetadataResult:
    """CPU GROBID request, no retries, no environment proxy, no redirects.

    mode=full extracts header/references/coordinates; mode=header is the on-demand
    path for long books (default end_page=2). Not an OCR route. The caller owns
    authentication/workspace access to pdf_path and the persistence directory.
    """
    if mode not in ("full", "header") or (end_page is not None and
           (isinstance(end_page, bool) or not isinstance(end_page, int) or not 1 <= end_page <= 10000)):
        raise MetadataError("Invalid metadata extraction scope")
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 1 <= timeout <= 600:
        raise MetadataError("Metadata timeout must be between 1 and 600 seconds")
    if not isinstance(max_response_bytes, int) or not 1 <= max_response_bytes <= MAX_XML_BYTES:
        raise MetadataError("Invalid TEI response limit")
    url, port, address, token = _operator_endpoint(base_url, token_file)
    path = Path(pdf_path)
    boundary = "ResearchTrace" + secrets.token_hex(16)
    fields = [("consolidateHeader", "0"), ("consolidateCitations", "0"),
              ("consolidateFunders", "0"), ("includeRawAffiliations", "1"),
              ("includeRawCitations", "1"), ("generateIDs", "1")]
    endpoint = "processFulltextDocument" if mode == "full" else "processHeaderDocument"
    if mode == "header" and end_page is None:
        end_page = 2
    if end_page is not None:
        fields.append(("end", str(end_page)))
    if mode == "full":
        fields.extend(("teiCoordinates", tag) for tag in ("title", "persName", "affiliation", "biblStruct", "ref"))
    prefix = b"".join((f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n').encode()
                      for k, v in fields)
    prefix += (f'--{boundary}\r\nContent-Disposition: form-data; name="input"; filename="document.pdf"\r\n'
               'Content-Type: application/pdf\r\n\r\n').encode()
    suffix = f"\r\n--{boundary}--\r\n".encode()
    started = time.time()
    deadline = time.monotonic() + timeout
    connection = None
    watchdog = None
    try:
        with path.open("rb") as pdf:
            initial = os.fstat(pdf.fileno())
            if not stat.S_ISREG(initial.st_mode) or not 8 <= initial.st_size <= MAX_PDF_BYTES:
                raise MetadataError("PDF is not a regular file or exceeds size limit")
            if b"%PDF-" not in pdf.read(1024):
                raise MetadataError("Input is not a PDF")
            pdf.seek(0)
            digest = hashlib.file_digest(pdf, "sha256").hexdigest()
            pdf.seek(0)
            connection = http.client.HTTPConnection(url.hostname, port, timeout=min(5, timeout))
            sock = socket.create_connection((address, port), timeout=min(5, timeout))
            connection.sock = ssl.create_default_context().wrap_socket(sock, server_hostname=url.hostname) if url.scheme == "https" else sock
            request_socket = connection.sock
            def expire_request():
                try:
                    request_socket.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
            watchdog = threading.Timer(max(.01, deadline - time.monotonic()), expire_request)
            watchdog.daemon = True
            watchdog.start()
            def limit():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise MetadataError("GROBID request exceeded wall-time limit")
                connection.sock.settimeout(min(30, remaining))
            limit()
            connection.putrequest("POST", url.path.rstrip("/") + "/api/" + endpoint)
            connection.putheader("Content-Type", "multipart/form-data; boundary=" + boundary)
            connection.putheader("Content-Length", str(len(prefix) + initial.st_size + len(suffix)))
            connection.putheader("Accept", "application/xml")
            connection.putheader("Accept-Encoding", "identity")
            connection.putheader("Connection", "close")
            if token:
                connection.putheader("Authorization", "Bearer " + token)
            connection.endheaders()
            connection.send(prefix)
            while chunk := pdf.read(64 * 1024):
                limit()
                connection.send(chunk)
            connection.send(suffix)
            limit()
            # Header arrival includes CRF cold model loading, which exceeded 30s
            # in the real first request. The watchdog still bounds total time.
            connection.sock.settimeout(max(.01, deadline - time.monotonic()))
            response = connection.getresponse()
            if response.status != 200:
                # No retry: a timed-out request may already have consumed CPU.
                raise MetadataError("GROBID HTTP " + str(response.status))
            if response.getheader("Content-Encoding", "identity").lower() != "identity":
                raise MetadataError("Compressed TEI responses are forbidden")
            content_type = response.getheader("Content-Type", "").split(";", 1)[0].strip().lower()
            if content_type not in ("application/xml", "text/xml", "application/tei+xml"):
                raise MetadataError("GROBID returned a non-XML response")
            content_length = response.getheader("Content-Length")
            if content_length is not None:
                try:
                    if not 0 < int(content_length) <= max_response_bytes:
                        raise ValueError
                except ValueError:
                    raise MetadataError("TEI response exceeds size limit or has invalid length") from None
            data = bytearray()
            while True:
                # getresponse may detach a Connection:close socket; the response
                # still owns the same socket. Set its read timeout via fp.raw.
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise MetadataError("GROBID request exceeded wall-time limit")
                if response.fp is not None:
                    response.fp.raw._sock.settimeout(min(30, remaining))
                chunk = response.read1(min(64 * 1024, max_response_bytes + 1 - len(data)))
                if not chunk:
                    break
                data.extend(chunk)
                if len(data) > max_response_bytes:
                    raise MetadataError("TEI response exceeds size limit")
            if content_length and len(data) != int(content_length):
                raise MetadataError("Truncated TEI response")
            final = os.fstat(pdf.fileno())
            if (initial.st_size, initial.st_mtime_ns, initial.st_ctime_ns) != (final.st_size, final.st_mtime_ns, final.st_ctime_ns):
                raise MetadataError("PDF changed during metadata extraction")
            raw = bytes(data)
            parsed = parse_tei(raw, page_sizes)
            versions = [a["version"] for a in parsed["applications"] if "grobid" in (a["ident"] or "").lower()]
            if not versions or any(v != VERSION for v in versions):
                raise MetadataError("Unexpected or missing GROBID version; expected 0.9.1")
            provenance = {"schema": SCHEMA, "engine": "grobid", "engine_version": VERSION,
                          "expected_source_commit": SOURCE_COMMIT, "source_commit_attested": False,
                          "source_pdf_sha256": digest, "source_pdf_bytes": initial.st_size,
                          "tei_sha256": parsed["tei_sha256"], "mode": mode, "end_page": end_page,
                          "endpoint_transport": url.scheme, "loopback": ipaddress.ip_address(address).is_loopback,
                          "authenticated": bool(token), "started_unix": started, "finished_unix": time.time(),
                          "consolidation": False, "ocr": False, "model_api_calls": 0,
                          "request_parameters": fields}
            return MetadataResult(parsed, raw, provenance)
    except MetadataError:
        raise
    except (OSError, http.client.HTTPException, ssl.SSLError):
        raise MetadataError("GROBID transport failed or timed out; no automatic retry") from None
    finally:
        if watchdog:
            watchdog.cancel()
        if connection:
            connection.close()


def _json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def save_sidecar(result: MetadataResult, directory) -> dict:
    """Content-addressed, create-only bundle. Existing bytes must verify exactly.

    The directory must be an authorized per-workspace destination chosen by the
    caller. Nothing is written beside the source PDF or into original blocks.
    """
    xml_hash = hashlib.sha256(result.tei_xml).hexdigest()
    if xml_hash != result.provenance.get("tei_sha256") or xml_hash != result.metadata.get("tei_sha256"):
        raise MetadataError("Sidecar XML provenance hash mismatch")
    source_hash = result.provenance.get("source_pdf_sha256", "")
    if not re.fullmatch("[a-f0-9]{64}", source_hash):
        raise MetadataError("Sidecar source PDF hash missing")
    files = {"document.tei.xml": result.tei_xml, "metadata.json": _json_bytes(result.metadata),
             "provenance.json": _json_bytes(result.provenance)}
    hashes = {name: hashlib.sha256(value).hexdigest() for name, value in files.items()}
    sidecar_id = hashlib.sha256(_json_bytes({"source_pdf_sha256": source_hash, "files": hashes})).hexdigest()
    manifest = {"schema": SCHEMA, "sidecar_id": sidecar_id, "source_pdf_sha256": source_hash, "files": hashes}
    files["manifest.json"] = _json_bytes(manifest)
    parent = Path(directory)
    parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = parent / sidecar_id
    if not target.exists():
        with tempfile.TemporaryDirectory(prefix=".grobid-", dir=parent) as temp:
            staging = Path(temp) / "bundle"
            staging.mkdir(mode=0o700)
            for name, value in files.items():
                with (staging / name).open("xb") as f:
                    f.write(value)
                    f.flush()
                    os.fsync(f.fileno())
                (staging / name).chmod(0o400)
            try:
                staging.rename(target)
            except FileExistsError:
                pass
    if target.is_symlink() or not target.is_dir():
        raise MetadataError("Sidecar destination is not an immutable directory")
    for name, value in files.items():
        p = target / name
        if p.is_symlink() or not p.is_file() or p.read_bytes() != value:
            raise MetadataError("Existing sidecar failed integrity validation")
    return {**manifest, "path": str(target)}


def _normalized_offsets(text):
    chars, offsets = [], []
    for i, char in enumerate(text):
        for c in unicodedata.normalize("NFKC", char).casefold():
            if c.isspace():
                if chars and chars[-1] != " ":
                    chars.append(" ")
                    offsets.append(i)
            else:
                chars.append(c)
                offsets.append(i)
    return "".join(chars), offsets


def map_metadata_to_blocks(result: MetadataResult, blocks, *, version_id, parse_id, source_pdf_sha256) -> list[dict]:
    """Only literal normalized substrings of caller-authorized real blocks map.

    Each author name / organization / reference raw string maps separately.
    An author/affiliation association is never turned into a fabricated quote.
    Callers must load blocks from their workspace and revalidate before publish.
    """
    if source_pdf_sha256 != result.provenance.get("source_pdf_sha256"):
        raise MetadataError("Metadata and original PDF hash differ")
    candidates = [("title", result.metadata.get("title", ""))]
    for author in result.metadata.get("authors", []):
        candidates.append((f"authors.{author['order']}.name", author["name"]))
        for j, aff in enumerate(author["affiliations"]):
            for k, org in enumerate(aff.get("organizations", [])):
                candidates.append((f"authors.{author['order']}.affiliations.{j}.organizations.{k}", org["name"]))
    for ref in result.metadata.get("references", []):
        field = "raw_reference" if ref.get("raw_reference") else "title"
        candidates.append((f"references.{ref['order']}.{field}", ref.get(field, "")))
    mappings = []
    for block in blocks:
        if block.get("version_id") != version_id or block.get("parse_id") != parse_id:
            continue
        original = block.get("text")
        bbox = block.get("bbox")
        page = block.get("page_index")
        if not isinstance(block.get("id"), str) or not block["id"] or not isinstance(original, str):
            continue
        if isinstance(page, bool) or not isinstance(page, int) or page < 0:
            continue
        if not isinstance(bbox, (list, tuple)) or len(bbox) != 4 or any(
                isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not 0 <= v <= 1 for v in bbox):
            continue
        if bbox[0] >= bbox[2] or bbox[1] >= bbox[3]:
            continue
        normalized, offsets = _normalized_offsets(original)
        for field, value in candidates:
            needle = _normalized_offsets(value)[0].strip()
            if len(needle) < 3:
                continue
            start = normalized.find(needle)
            if start < 0:
                continue
            end = start + len(needle)
            if (start and normalized[start - 1].isalnum() and needle[0].isalnum()) or (
                    end < len(normalized) and normalized[end].isalnum() and needle[-1].isalnum()):
                continue
            first, last = offsets[start], offsets[start + len(needle) - 1] + 1
            mappings.append({"field": field, "version_id": version_id, "parse_id": parse_id,
                             "block_id": block["id"], "page_index": page, "bbox": list(bbox),
                             "quote": original[first:last], "char_start": first, "char_end": last,
                             "status": "located_semantics_pending", "metadata_association_verified": False,
                             "tei_sha256": result.metadata["tei_sha256"]})
    return mappings
