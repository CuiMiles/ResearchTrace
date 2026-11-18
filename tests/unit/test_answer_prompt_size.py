import json

from services.api.jobs import cap_evidence, compact_observations


def test_retrieval_observations_shrink_to_ids_and_other_results_are_truncated():
    blocks = [{'id': f'b{i}', 'text': 'evidence text ' * 200} for i in range(30)]
    observations = [{'tool': 'retrieve_evidence', 'status': 'PASS', 'result': {'mode': 'hybrid', 'blocks': blocks, 'sparse': blocks, 'dense': blocks}},
                    {'tool': 'compare_versions', 'status': 'PASS', 'result': {'changes': ['x' * 9000]}},
                    {'tool': 'build_citation_graph', 'status': 'PASS', 'result': {'edges': 2}}]
    compact = compact_observations(observations)
    assert compact[0]['result'] == {'mode': 'hybrid', 'evidence_block_ids': [f'b{i}' for i in range(30)], 'note': '正文见 evidence 字段'}
    assert compact[1]['result'].endswith('（已截断）') and len(compact[1]['result']) < 4100
    assert compact[2]['result'] == {'edges': 2}
    assert len(json.dumps(compact, ensure_ascii=False)) < len(json.dumps(observations, ensure_ascii=False)) / 20
    assert observations[0]['result']['blocks'] is blocks  # input is not mutated


def test_evidence_keeps_rank_order_within_budget_and_never_drops_the_first_block():
    evidence = [{'id': f'e{i}', 'text': 'y' * 30000} for i in range(5)]
    assert [e['id'] for e in cap_evidence(evidence)] == ['e0', 'e1', 'e2']
    assert [e['id'] for e in cap_evidence([{'id': 'huge', 'text': 'z' * 200000}])] == ['huge']
