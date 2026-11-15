# Evaluation scope

No general accuracy percentage has been measured. Targets90% factual/95% support/90% insufficiency are acceptance goals, not results.

Data provenance and SHA256 are in `evals/manifest.json`, downloaded/prepared by `scripts/prepare_evals.py`. Renamed real Transformer v7/v1 and BERT PDFs test content-based identity and unseen inputs. Scan and541page long document are clearly derived/self-authored engineering fixtures; official scan/textbook remain BLOCKED. Twenty related papers are real verified metadata records, not twenty processed full texts.

Deterministic checks cover exact version scoping, raw source quote membership, IDs/bbox, sparse indexes, CSV maxima/deltas and source-bound graph edges. Mock network tests are explicit fixtures and do not establish live model availability. Live provider probes and complete saved runs are separate evidence.

`scripts/smoke.sh --live --max-hydrogen-calls 4` is a bounded end-to-end integration test, not an accuracy benchmark. Source fact audits must inspect whether the quoted material actually supports the claim. Located quotes are labelled semantic review pending. No model-generated labels count as independent ground truth.

A50-question reviewed dataset, direct-model/basic-retrieval/current-system baseline comparison, and statistical confidence intervals are NOT RUN. They require independent annotation and an explicit additional model budget. `scripts/evaluate.sh` states this and spends no tokens. No automatic fallback evaluation consumes the remaining Hydrogen quota.
