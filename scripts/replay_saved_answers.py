"""Replay saved real answers into a local workspace for screen recording.

Reads the historical public runs in evidence/recording-ready-20261118/
production-runs.json (real Gemini 4 Hydrogen / 3.5 Flash Lite answers from
2026-11-18) and writes them as completed runs into a local workspace that holds
the same PDF. Each quote is located again in the local parse of that PDF; a
quote that cannot be found on its page aborts the import rather than being
shown with a wrong location.

The replayed run keeps the original question, claims, review results, model
name and timing. Its only steps are "queued" and "completed" at the original
times: the original step log was not saved, so none is invented. The result
records `replayed_from` so a replay is never mistaken for a live run. No model
or provider is called.

    PYTHONPATH=. python scripts/replay_saved_answers.py --workspace <id> --version <local v7 id>
"""
import argparse
import json
import re
import time
from pathlib import Path

from services.api import store

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'evidence/recording-ready-20261118/production-runs.json'
CASES = ('qa-scale', 'qa-heads', 'qa-adam')


def squash(text):
    return re.sub(r'\s+', '', text or '')


def locate(workspace, version_id, page_index, quote):
    blocks = store.rows('SELECT id,version_id,page_index,bbox,text FROM current_blocks WHERE workspace=? AND version_id=? AND page_index=?',
                        (workspace, version_id, page_index))
    wanted = squash(quote)
    for block in blocks:
        if wanted and wanted in squash(block['text']):
            return block
    raise SystemExit(f'quote not found on page {page_index + 1}: {quote[:80]}')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--workspace', required=True)
    parser.add_argument('--version', required=True, help='local version id of the same PDF (Transformer v7)')
    parser.add_argument('--thread', default='th-replay-20261118')
    args = parser.parse_args()
    source = json.loads(SOURCE.read_text())
    from services.api.snapshots import block_parse
    created_ids = []
    for name in CASES:
        case = source['cases'][name]
        claims = []
        for claim in case['claims']:
            evidence = []
            for item in claim.get('evidence', []):
                block = locate(args.workspace, args.version, item['page_index'], item['quote'])
                evidence.append({**item, 'block_id': block['id'], 'version_id': args.version,
                                 'bbox': json.loads(block['bbox']) if isinstance(block['bbox'], str) else block['bbox'],
                                 'parse_id': block_parse(block['id'], args.version)})
            claims.append({**claim, 'evidence': evidence})
        result = {
            'answer': case['answer'] if len(case['claims']) == 1 else '\n\n'.join(c['text'] for c in claims),
            'answer_segments': [{'text': c['text'], 'claim_ids': [c['id']]} for c in claims],
            'claims': claims,
            'status': case['answer_status'],
            'model': case['model'],
            'retrieval': case.get('retrieval', {}),
            'replayed_from': {'file': str(SOURCE.relative_to(ROOT)), 'case': name,
                              'original_run_id': case['run_id'], 'original_finished_at': case['finished_at'],
                              'note': 'saved real answer replayed for recording; not a live run'},
        }
        finished = float(case['finished_at'])
        started = finished - float(case['elapsed_seconds'])
        rid = store.uid()
        payload = {'question': case['question'], 'version_ids': [args.version], 'thread_id': args.thread}
        with store.db() as c:
            c.execute('INSERT INTO runs(id,workspace,kind,status,payload,result,created,updated) VALUES(?,?,?,?,?,?,?,?)',
                      (rid, args.workspace, 'qa', 'completed', json.dumps(payload, ensure_ascii=False),
                       json.dumps(result, ensure_ascii=False), started, finished))
            c.execute('INSERT INTO steps(run_id,event,data,created) VALUES(?,?,?,?)', (rid, 'queued', '{}', started))
            c.execute('INSERT INTO steps(run_id,event,data,created) VALUES(?,?,?,?)', (rid, 'completed', '{}', finished))
        created_ids.append(rid)
        print(name, rid, len(claims), 'claims', sum(len(c['evidence']) for c in claims), 'quotes located')
    print(json.dumps({'thread_id': args.thread, 'runs': created_ids, 'provider_calls': 0, 'at': time.time()}))


if __name__ == '__main__':
    main()
