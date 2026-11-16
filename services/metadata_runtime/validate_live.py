"""Real, opt-in metadata validation. No model API/GPU; gold is explicitly scoped.

Run from project root using python -m services.metadata_runtime.validate_live.
First-page gold was checked directly against the two original PDFs. It is only
used here to score extraction; it is never part of the production client/parser.
"""
import argparse
import hashlib
import json
from pathlib import Path
import time

from services.api.scholarly_metadata import fetch_metadata, save_sidecar, MetadataError

CORE_GOLD = {
    "1706.03762v1.pdf": {"author_order": 6, "name": "Aidan N. Gomez", "institution": "University of Toronto"},
    "1706.03762v7.pdf": {"author_order": 6, "name": "Aidan N. Gomez", "institution": "University of Toronto"},
}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--pdf-directory", required=True)
    p.add_argument("--base-url", required=True)
    p.add_argument("--token-file", required=True)
    p.add_argument("--sidecar-directory", required=True)
    p.add_argument("--evidence", required=True)
    args = p.parse_args()
    cases = []
    evidence = {"status": "NOT RUN", "kind": "real_grobid_metadata_no_models", "cases": cases,
                "model_api_calls": 0, "gpu_used": False, "gold_source": "direct original PDF first page, user task author ordering"}
    for name, gold in CORE_GOLD.items():
        pdf = Path(args.pdf_directory) / name
        case = {"filename": name, "source_sha256": hashlib.sha256(pdf.read_bytes()).hexdigest(),
                "expected": gold, "status": "NOT RUN"}
        cases.append(case)
        start = time.monotonic()
        try:
            result = fetch_metadata(pdf, args.base_url, args.token_file)
            saved = save_sidecar(result, args.sidecar_directory)
            metadata = result.metadata
            sixth = metadata["authors"][5] if len(metadata["authors"]) >= 6 else None
            author_ok = bool(sixth and sixth["name"] == gold["name"])
            affs = [org["name"] for aff in (sixth or {}).get("affiliations", []) for org in aff["organizations"]]
            affiliation_ok = author_ok and gold["institution"] in affs
            case.update({"status": "PASS" if author_ok and affiliation_ok else "FAIL",
                         "transport_status": "PASS", "author_name_status": "PASS" if author_ok else "FAIL",
                         "sixth_author_affiliation_status": "PASS" if affiliation_ok else "FAIL",
                         "expected_institution_present_at_sixth_position": gold["institution"] in affs,
                         "sidecar": saved, "title": metadata["title"], "authors": metadata["authors"],
                         "references_count": len(metadata["references"]), "references": metadata["references"],
                         "citation_markers_count": len(metadata["citation_markers"]),
                         "coordinate_count": sum(len(ref["positions"]) for ref in metadata["references"]),
                         "warnings": metadata["warnings"], "provenance": result.provenance})
        except MetadataError as exc:
            case.update({"status": "FAIL", "transport_status": "FAIL", "error": str(exc)})
        case["elapsed_seconds"] = round(time.monotonic() - start, 3)
        evidence["status"] = "PASS" if len(cases) == len(CORE_GOLD) and all(c["status"] == "PASS" for c in cases) else "FAIL"
        Path(args.evidence).write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps({k: case.get(k) for k in ("filename", "status", "transport_status", "author_name_status", "sixth_author_affiliation_status", "error", "elapsed_seconds")}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
