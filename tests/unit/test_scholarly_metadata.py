"""Explicit synthetic TEI/HTTP fixtures; no GROBID, network API or GPU claim."""
import copy
from dataclasses import replace
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import socket
import threading
import time

import pytest

from services.api import scholarly_metadata as sm
from services.metadata_runtime import server as gateway


TEI = '''<?xml version="1.0" encoding="UTF-8"?>
<TEI xmlns="http://www.tei-c.org/ns/1.0">
 <teiHeader><encodingDesc><appInfo><application ident="GROBID" version="0.9.1"/></appInfo></encodingDesc>
 <fileDesc><titleStmt><title>Wrong fallback</title></titleStmt><sourceDesc><biblStruct>
 <analytic><title coords="1,10,20,180,10">Synthetic metadata paper</title>
 <author><persName coords="1,30,50,75,10"><forename type="first">Ada</forename><surname>Example</surname></persName>
 <email>ada@example.invalid</email><idno type="ORCID">0000-fixture</idno><affiliation ref="#aff0"/></author>
 <author><persName><forename type="first">Bo</forename><forename type="middle">N.</forename><surname>Test</surname></persName>
 <affiliation key="aff0" coords="1,20,75,140,15"><orgName type="institution">Fixture University</orgName>
 <address><settlement>Test City</settlement><country>Testland</country></address>
 <note type="raw_affiliation">Fixture University, Test City</note></affiliation></author>
 <author><persName><forename>Cy</forename><surname>Other</surname></persName><affiliation ref="#missing"/></author>
 </analytic></biblStruct></sourceDesc></fileDesc></teiHeader>
 <facsimile><surface n="1" ulx="0" uly="0" lrx="200" lry="400"/><surface n="2" ulx="0" uly="0" lrx="600" lry="800"/></facsimile>
 <text><body><p>Prior work <ref type="bibr" target="#b0 #unknown" coords="1,15,200,10,5;2,10,20,5,5">[1]</ref>.</p></body>
 <back><div type="references"><listBibl><biblStruct xml:id="b0" coords="2,20,200,500,30">
 <analytic><title>Fixture reference title</title><author><persName><forename>A.</forename><surname>Writer</surname></persName></author></analytic>
 <monogr><title>Fixture Journal</title><imprint><date type="published" when="2020-02"/></imprint></monogr>
 <idno type="DOI">10.0000/fixture</idno><note type="raw_reference">A. Writer. Fixture reference title. 2020.</note>
 </biblStruct></listBibl></div></back></text></TEI>'''


def result():
    raw = TEI.encode()
    parsed = sm.parse_tei(raw)
    return sm.MetadataResult(parsed, raw, {"source_pdf_sha256": "a" * 64, "tei_sha256": parsed["tei_sha256"],
                                         "engine_version": "0.9.1", "model_api_calls": 0})


def test_order_affiliations_contact_references_and_citation_links():
    r = sm.parse_tei(TEI)
    assert r["title"] == "Synthetic metadata paper"
    assert [a["name"] for a in r["authors"]] == ["Ada Example", "Bo N. Test", "Cy Other"]
    assert [a["order"] for a in r["authors"]] == [1, 2, 3]
    assert r["authors"][0]["emails"] == ["ada@example.invalid"]
    assert r["authors"][0]["affiliations"][0]["organizations"][0]["name"] == "Fixture University"
    assert r["authors"][2]["unresolved_affiliation_refs"] == ["missing"]
    ref = r["references"][0]
    assert ref["tei_id"] == "b0" and ref["date"] == "2020-02"
    assert ref["raw_reference"] == "A. Writer. Fixture reference title. 2020."
    assert ref["identifiers"][0]["value"] == "10.0000/fixture"
    assert ref["authors"][0]["name"] == "A. Writer"
    assert r["citation_markers"][0]["unresolved_targets"] == ["unknown"]
    assert r["citation_markers"][0]["status"] == "tei_target_only"
    assert r["ocr"] is False and r["quality"] == "extracted_metadata_not_verified_evidence"


def test_physical_page_index_top_left_coordinates_and_explicit_dimensions():
    r = sm.parse_tei(TEI)
    box = r["references"][0]["positions"][0]
    assert box["page_index"] == 1
    assert box["bbox_pdf_units"] == [20, 200, 520, 230]
    assert box["bbox"] == pytest.approx([20 / 600, .25, 520 / 600, 230 / 800])
    r = sm.parse_tei(TEI, {0: (400, 800)})
    assert r["title_positions"][0]["bbox"] == pytest.approx([.025, .025, .475, .0375])
    assert len(r["citation_markers"][0]["positions"]) == 2


def test_no_dimensions_never_invents_normalized_coordinates():
    text = '<TEI xmlns="http://www.tei-c.org/ns/1.0"><teiHeader><fileDesc><titleStmt><title coords="1,1,2,3,4">Title</title></titleStmt></fileDesc></teiHeader></TEI>'
    assert sm.parse_tei(text)["title_positions"][0]["bbox"] is None


def test_duplicate_affiliation_ids_do_not_rebind_inline_authors_or_accept_ambiguous_refs():
    conflicting = TEI.replace('<affiliation ref="#missing"/>',
                             '<affiliation key="aff0"><orgName>Other Institution</orgName></affiliation>')
    r = sm.parse_tei(conflicting)
    assert r["authors"][0]["affiliations"] == []
    assert r["authors"][0]["unresolved_affiliation_refs"] == ["aff0"]
    assert r["authors"][1]["affiliations"][0]["organizations"][0]["name"] == "Fixture University"
    assert r["authors"][2]["affiliations"][0]["organizations"][0]["name"] == "Other Institution"
    assert "ambiguous_affiliation_identifier" in r["warnings"]


def test_organization_misread_as_person_flags_review_without_renumbering():
    r = sm.parse_tei(TEI.replace('<forename>Cy</forename><surname>Other</surname>',
                               '<forename>Fixture</forename><surname>Research</surname>'))
    assert "possible_organization_in_author_list" in r["warnings"]
    assert len(r["authors"]) == 3 and r["authors"][2]["order"] == 3
    assert r["publishable_as_verified_metadata"] is False


@pytest.mark.parametrize("coords", ["0,1,2,3,4", "1,-1,0,3,4", "1,nan,2,3,4", "1,1,2,0,4", "1,10,20,500,10", "1,1,2,3", "1.5,1,2,3,4"])
def test_invalid_coordinates_are_marked_not_clamped(coords):
    r = sm.parse_tei(TEI.replace("1,10,20,180,10", coords))
    assert r["title_positions"] == [] and "invalid_tei_coordinates" in r["warnings"]


@pytest.mark.parametrize("xml", [
    '<!DOCTYPE TEI [<!ENTITY x SYSTEM "file:///etc/passwd">]><TEI xmlns="http://www.tei-c.org/ns/1.0">&x;</TEI>',
    '<!DOCTYPE TEI SYSTEM "https://example.invalid/evil.dtd"><TEI xmlns="http://www.tei-c.org/ns/1.0"/>',
    '<!ENTITY x "not allowed"><TEI/>',
    TEI.encode("utf-16"), TEI.replace('encoding="UTF-8"', 'encoding="ISO-8859-1"'),
    '<TEI><broken></TEI>', '<TEI/>', '<other xmlns="http://www.tei-c.org/ns/1.0"/>',
])
def test_untrusted_xml_is_rejected(xml):
    with pytest.raises(sm.MetadataError):
        sm.parse_tei(xml)


def test_depth_nodes_bytes_are_bounded(monkeypatch):
    with pytest.raises(sm.MetadataError, match="depth"):
        sm.parse_tei('<TEI xmlns="http://www.tei-c.org/ns/1.0">' + '<p>' * 129 + '</p>' * 129 + '</TEI>')
    monkeypatch.setattr(sm, "MAX_XML_NODES", 3)
    with pytest.raises(sm.MetadataError, match="node"):
        sm.parse_tei(TEI)
    monkeypatch.setattr(sm, "MAX_XML_BYTES", 32)
    with pytest.raises(sm.MetadataError, match="size"):
        sm.parse_tei(TEI)


def test_sidecar_is_idempotent_create_only_and_tampering_fails(tmp_path):
    r = result()
    bundle = sm.save_sidecar(r, tmp_path)
    assert bundle == sm.save_sidecar(r, tmp_path)
    assert (Path(bundle["path"]) / "document.tei.xml").read_bytes() == TEI.encode()
    assert {p.name for p in tmp_path.iterdir()} == {bundle["sidecar_id"]}
    xml_file = Path(bundle["path"]) / "document.tei.xml"
    xml_file.chmod(0o600)
    xml_file.write_text("tampered")
    with pytest.raises(sm.MetadataError, match="integrity"):
        sm.save_sidecar(r, tmp_path)
    with pytest.raises(sm.MetadataError, match="hash mismatch"):
        sm.save_sidecar(replace(r, tei_xml=b"different"), tmp_path)


def test_mapping_requires_same_version_snapshot_sha_and_preserves_original_substrings():
    r = result()
    blocks = [{"id": "real:0:1", "version_id": "version-a", "parse_id": "parse-a", "page_index": 0,
               "bbox": [.1, .1, .9, .4], "text": "Ada\nExample*\nFixture University"},
              {"id": "other-version", "version_id": "version-b", "parse_id": "parse-a", "page_index": 0,
               "bbox": [.1, .1, .9, .4], "text": "Synthetic metadata paper"},
              {"id": "old-parse", "version_id": "version-a", "parse_id": "parse-old", "page_index": 0,
               "bbox": [.1, .1, .9, .4], "text": "Synthetic metadata paper"}]
    before = copy.deepcopy(blocks)
    mappings = sm.map_metadata_to_blocks(r, blocks, version_id="version-a", parse_id="parse-a", source_pdf_sha256="a" * 64)
    assert mappings and {m["block_id"] for m in mappings} == {"real:0:1"}
    name = next(m for m in mappings if m["field"] == "authors.1.name")
    assert name["quote"] == "Ada\nExample"
    for mapping in mappings:
        assert mapping["quote"] == blocks[0]["text"][mapping["char_start"]:mapping["char_end"]]
        assert mapping["status"] == "located_semantics_pending"
    assert blocks == before
    # Institution found elsewhere is not fabricated into a combined source quote.
    assert all("Ada" not in m["quote"] or "University" not in m["quote"] for m in mappings)
    with pytest.raises(sm.MetadataError, match="hash differ"):
        sm.map_metadata_to_blocks(r, blocks, version_id="version-a", parse_id="parse-a", source_pdf_sha256="b" * 64)


@pytest.fixture
def private_token(tmp_path):
    p = tmp_path / "auth.token"
    p.write_text("synthetic-test-token-123456789")
    p.chmod(0o600)
    return p


@pytest.mark.parametrize("url", ["http://example.com", "http://169.254.169.254", "https://127.0.0.2/../metadata", "https://host.invalid?url=x", "file:///tmp/a", "http://user:password@127.0.0.1", "http://127.0.0.1/#x"])
def test_no_arbitrary_endpoints_redirect_proxy_paths_or_credentials(url):
    with pytest.raises(sm.MetadataError):
        sm._operator_endpoint(url, None)


def test_private_https_and_dns_rebinding_target_blocked(private_token, monkeypatch):
    monkeypatch.setattr(sm.socket, "getaddrinfo", lambda *a, **k: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 443))])
    with pytest.raises(sm.MetadataError, match="non-public"):
        sm._operator_endpoint("https://grobid.example", private_token)


def test_operator_token_not_returned_in_errors(private_token):
    private_token.chmod(0o644)
    with pytest.raises(sm.MetadataError, match="private") as error:
        sm._operator_endpoint("https://example.com", private_token)
    assert private_token.read_text() not in str(error.value)


@pytest.fixture
def upstream():
    class Fixture(BaseHTTPRequestHandler):
        body = TEI.encode()
        code = 200
        content_type = "application/xml; charset=utf-8"
        content_length = None
        requests = []

        def log_message(self, *_):
            pass

        def do_GET(self):
            body = b"true" if self.path == "/api/isalive" else b"fixture"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            data = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            self.requests.append({"path": self.path, "body": data, "authorization": self.headers.get("Authorization")})
            self.send_response(self.code)
            self.send_header("Content-Type", self.content_type)
            self.send_header("Content-Length", str(len(self.body) if self.content_length is None else self.content_length))
            if self.code == 302:
                self.send_header("Location", "http://169.254.169.254/latest/meta-data/")
            self.end_headers()
            self.wfile.write(self.body)
    service = ThreadingHTTPServer(("127.0.0.1", 0), Fixture)
    thread = threading.Thread(target=service.serve_forever, daemon=True)
    thread.start()
    yield Fixture, service.server_port
    service.shutdown()
    service.server_close()
    thread.join(2)


def pdf(tmp_path):
    p = tmp_path / "local-fixture.pdf"
    p.write_bytes(b"%PDF-1.7\nExplicit synthetic HTTP transport fixture only\n")
    return p


def test_real_loopback_http_fixture_streams_pdf_no_env_proxy_or_consolidation(upstream, private_token, tmp_path, monkeypatch):
    fixture, port = upstream
    monkeypatch.setenv("HTTP_PROXY", "http://169.254.169.254:1")
    monkeypatch.setenv("HTTPS_PROXY", "http://169.254.169.254:1")
    p = pdf(tmp_path)
    r = sm.fetch_metadata(p, f"http://127.0.0.1:{port}", private_token)
    assert r.metadata["authors"][0]["name"] == "Ada Example"
    assert r.provenance["source_pdf_sha256"] == hashlib.sha256(p.read_bytes()).hexdigest()
    assert r.provenance["consolidation"] is False and r.provenance["model_api_calls"] == 0
    request = fixture.requests[0]
    assert request["path"] == "/api/processFulltextDocument"
    assert request["authorization"] == "Bearer " + private_token.read_text()
    assert b'name="teiCoordinates"' in request["body"]
    assert b'name="consolidateHeader"\r\n\r\n0' in request["body"]
    assert p.read_bytes() in request["body"] and len(fixture.requests) == 1


@pytest.mark.parametrize("failure", ["redirect", "size", "truncated", "html", "version"])
def test_upstream_failure_is_bounded_not_retried_or_disguised(upstream, tmp_path, failure):
    fixture, port = upstream
    kwargs = {}
    if failure == "redirect":
        fixture.code = 302
    elif failure == "size":
        kwargs["max_response_bytes"] = 30
    elif failure == "truncated":
        fixture.content_length = len(fixture.body) + 100
    elif failure == "html":
        fixture.content_type = "text/html"
    else:
        fixture.body = TEI.replace('version="0.9.1"', 'version="0.8.0"').encode()
    with pytest.raises(sm.MetadataError):
        sm.fetch_metadata(pdf(tmp_path), f"http://127.0.0.1:{port}", timeout=2, **kwargs)
    assert len(fixture.requests) == 1


def test_header_scope_for_long_book_is_explicit(upstream, tmp_path):
    fixture, port = upstream
    r = sm.fetch_metadata(pdf(tmp_path), f"http://127.0.0.1:{port}", mode="header")
    assert r.provenance["mode"] == "header" and r.provenance["end_page"] == 2
    assert fixture.requests[0]["path"] == "/api/processHeaderDocument"
    assert b'name="end"\r\n\r\n2' in fixture.requests[0]["body"]


def test_gateway_auth_route_whitelist_and_real_upstream_forward(upstream, private_token, tmp_path):
    fixture, port = upstream
    instance = gateway.BoundedServer(("127.0.0.1", 0), gateway.Handler)
    instance.token = private_token.read_text()
    instance.backend_port = port
    thread = threading.Thread(target=instance.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{instance.server_port}"
    try:
        with pytest.raises(sm.MetadataError, match="401"):
            sm.fetch_metadata(pdf(tmp_path), base)
        assert len(fixture.requests) == 0
        r = sm.fetch_metadata(pdf(tmp_path), base, private_token)
        assert r.metadata["title"] == "Synthetic metadata paper"
        # Only the whitelisted parser route is forwarded; no training or URL proxy.
        import http.client
        c = http.client.HTTPConnection("127.0.0.1", instance.server_port, timeout=10)
        c.request("POST", "/api/modelTraining", body=b"", headers={"Authorization": "Bearer " + instance.token})
        assert c.getresponse().status == 404
        c.close()
        assert len(fixture.requests) == 1
    finally:
        instance.shutdown()
        instance.server_close()
        thread.join(2)
