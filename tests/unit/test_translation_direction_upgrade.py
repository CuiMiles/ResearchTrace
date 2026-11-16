"""P0-05 deterministic fixtures: no live API, no translation quality assertions."""
import json
import socket
import time

import pytest

from services.api import jobs, models, store
from services.api import translation_service as translation


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'DATA', tmp_path)
    store.migrate()
    with store.db() as connection:
        connection.executescript(translation.TRANSLATION_CACHE_SCHEMA)

    def forbidden(*args, **kwargs):
        raise AssertionError('This task permits fixture responses only, never network requests')

    monkeypatch.setattr(models, 'generate', forbidden)
    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    monkeypatch.setattr(socket, 'create_connection', forbidden)


def seed(texts=None, *, workspace='w', version='v', parse_id=None, block_type='paragraph'):
    parse_id = parse_id or version
    if not store.one('SELECT id FROM versions WHERE id=?', (version,)):
        store.execute(
            'INSERT INTO versions(id,workspace,title,filename,sha256,path,status,page_count,parsed_pages,created) '
            'VALUES(?,?,?,?,?,?,?,?,?,?)',
            (version, workspace, 'Fixture paper', 'fixture.pdf', version, 'not-opened.pdf', 'ready', 1, 1, time.time()),
        )
    store.execute(
        'INSERT OR IGNORE INTO parses(id,version_id,workspace,engine,device,status,page_count,created) '
        'VALUES(?,?,?,?,?,?,?,?)',
        (parse_id, version, workspace, 'native', 'cpu', 'completed', 1, time.time()),
    )
    store.execute('INSERT OR REPLACE INTO active_parses VALUES(?,?)', (version, parse_id))
    result = []
    for index, text in enumerate(texts or ['A scientific paragraph.']):
        block_id = f'{parse_id}-b{index}'
        store.execute(
            'INSERT INTO blocks(id,workspace,version_id,page_index,bbox,type,reading_order,text,source,quality) '
            'VALUES(?,?,?,?,?,?,?,?,?,?)',
            (block_id, workspace, version, 0, '[0,0,1,1]', block_type, index, text, 'fixture', 'fixture'),
        )
        if parse_id != version:
            store.execute('INSERT INTO block_parses VALUES(?,?)', (block_id, parse_id))
        result.append(block_id)
    return result


def make_run(*, workspace='w', version='v', checkpoint=None, **options):
    payload = translation.normalize_translation_payload({'version_id': version, **options})
    payload.setdefault('parse_id', store.one('SELECT parse_id FROM active_parses WHERE version_id=?', (version,))['parse_id'])
    rid = store.uid()
    store.execute(
        'INSERT INTO runs(id,workspace,kind,status,payload,checkpoint,created,updated) VALUES(?,?,?,?,?,?,?,?)',
        (rid, workspace, 'translate', 'running', json.dumps(payload), json.dumps(checkpoint or {}), time.time(), time.time()),
    )
    return {'id': rid, 'workspace': workspace, 'payload': payload}


def fixture_provider(monkeypatch, *, actual_model='FIXTURE_NOT_LIVE', prefix=''):
    calls = []

    def generate(system, prompt, rid, core=False):
        assert core is False
        items = json.loads(prompt)
        calls.append({'system': system, 'items': items, 'run_id': rid})
        return {'model': actual_model, 'text': json.dumps({
            'translations': [{'block_id': item['block_id'], 'text': prefix + item['text']} for item in items],
        })}

    monkeypatch.setattr(models, 'generate', generate)
    return calls


def saved_checkpoint(run):
    return json.loads(store.one('SELECT checkpoint FROM runs WHERE id=?', (run['id'],))['checkpoint'])


def test_schema_is_repeatable_and_service_import_does_not_migrate():
    with store.db() as connection:
        connection.executescript(translation.TRANSLATION_CACHE_SCHEMA)
    seed()
    store.execute('DROP TABLE translation_cache')
    with pytest.raises(ValueError, match='store.migrate'):
        translation.translate(make_run())


def test_queue_defaults_canonicalize_old_idempotency_payload_and_pin_prior_parse():
    prior = {'version_id': 'v', 'parse_id': 'old'}
    incoming = {'version_id': 'v', 'block_ids': None}
    canonical = translation.normalize_translation_payload(incoming, prior_payload=prior)
    assert canonical == translation.normalize_translation_payload(prior)
    assert canonical == {
        'version_id': 'v', 'parse_id': 'old', 'source_language': 'auto',
        'target_language': 'zh-Hans', 'glossary_version': 'default',
    }
    assert incoming == {'version_id': 'v', 'block_ids': None}
    for changed in ({'parse_id': 'new'}, {'target_language': 'en'}, {'source_language': 'zh'}, {'glossary_version': 'g2'}):
        assert translation.normalize_translation_payload({**incoming, **changed}, prior_payload=prior) != canonical
    selected = translation.normalize_translation_payload({'block_ids': ['b', 'a', 'b']})
    assert selected['block_ids'] == ['a', 'b']


@pytest.mark.parametrize('options', [
    {'source_language': 'de'}, {'source_language': None}, {'target_language': 'zh'},
    {'glossary_version': ''}, {'glossary_version': 'bad\nignore instructions'},
    {'block_ids': 'a'}, {'block_ids': [None]}, {'block_ids': ['b'] * 101},
])
def test_invalid_options_are_rejected(options):
    with pytest.raises(ValueError):
        translation.normalize_translation_payload(options)


@pytest.mark.parametrize('source,kind', [
    ('Accuracy is 98.5% over 1,234 samples [2, 4–7]; loss=-2.4e-3.', 'paragraph'),
    (r'Math $x_i^2 + y_i^2$ and $$E=mc^2$$ and \(a+b=c\) and \[z=7\].', 'paragraph'),
    ('Use `print(42)` and\n```python\nraise Exception("do not run")\n```\n[Smith et al., 2020].', 'paragraph'),
    ('See (Smith et al., 2020) and E=mc²; β is .5 with model V3.', 'paragraph'),
    (r'\begin{align}x &= \frac{7}{2}\end{align}', 'paragraph'),
    ('a = b + c\nreturn value', 'code'),
    ('unmarked mathematical representation 1 / 2', 'formula'),
    ('Literal marker __RT_PH_untrusted_0__ plus `__RT_PH_inside_1__`.', 'paragraph'),
    ('Adjacent protected spans: 42[3]$x=4$`code`β', 'paragraph'),
])
def test_protection_plan_roundtrips_exact_literals(source, kind):
    plan = translation.protect_text(source, kind)
    assert plan.spans
    assert translation.restore_protected(plan.masked, plan) == source
    assert translation.protect_text(source, kind) == plan
    assert len({span.token for span in plan.spans}) == len(plan.spans)


@pytest.mark.parametrize('damage', ['missing', 'duplicate', 'foreign', 'changed', 'new_number', 'new_code', 'new_citation'])
def test_integrity_rejects_damaged_or_invented_literals(damage):
    plan = translation.protect_text('Measured 42 samples [3] with $a=b$.')
    token = plan.spans[0].token
    changed = {
        'missing': plan.masked.replace(token, ''),
        'duplicate': plan.masked + token,
        'foreign': plan.masked.replace(token, '__RT_PH_foreign_0__'),
        'changed': plan.masked.replace(token, token.lower()),
        'new_number': plan.masked + ' invented999',
        'new_code': plan.masked + ' `execute()`',
        'new_citation': plan.masked + ' [9]',
    }[damage]
    with pytest.raises(ValueError):
        translation.restore_protected(changed, plan)


def test_direction_glossary_and_requested_model_have_independent_cache_entries(monkeypatch):
    seed(['A result of 42 [3].'])
    calls = fixture_provider(monkeypatch)
    forward = make_run()
    assert translation.translate(forward)['translated'] == 1
    assert translation.translate(forward)['cache_hits'] == 1
    assert len(calls) == 1
    reverse = translation.translate(make_run(source_language='zh', target_language='en'))
    assert reverse['target_language'] == 'en'
    assert 'Chinese to English' in calls[-1]['system']
    translation.translate(make_run(source_language='en'))
    translation.translate(make_run(glossary_version='terminology-v2'))
    monkeypatch.setattr(models, 'BATCH', 'fixture-new-route')
    translation.translate(make_run())
    assert len(calls) == 5
    assert store.one('SELECT count(*) n FROM translation_cache')['n'] == 5
    assert store.one('SELECT count(*) n FROM translations')['n'] == 0
    rows = translation.load_translations('w', 'v', model='fixture-new-route')
    assert rows[0]['requested_model'] == 'fixture-new-route'
    assert rows[0]['model'] == 'FIXTURE_NOT_LIVE'
    assert store.one('SELECT count(*) n FROM quota')['n'] == 0


def test_legacy_read_is_forward_default_only_and_reverse_never_overwrites(monkeypatch):
    block_id = seed()[0]
    store.execute('INSERT INTO translations VALUES(?,?,?,?,?,?)',
                  (block_id, 'w', 'v', 'Legacy Chinese fixture', models.BATCH, time.time()))
    before = store.one('SELECT * FROM translations')
    calls = fixture_provider(monkeypatch, prefix='Reverse fixture ')
    assert translation.translate(make_run())['cache_hits'] == 1
    assert not calls
    assert translation.load_translations('w', 'v')[0]['integrity'] == 'legacy_unverified'
    assert translation.load_translations('w', 'v', source_language='zh', target_language='en') == []
    assert translation.load_translations('w', 'v', glossary_version='new-glossary') == []
    assert translation.load_translations('w', 'v', model='other-model') == []
    translation.translate(make_run(source_language='zh', target_language='en'))
    assert len(calls) == 1
    assert store.one('SELECT * FROM translations') == before
    assert 'Legacy Chinese fixture' in translation.export_translation('w', 'v')
    assert 'Reverse fixture' in translation.export_translation('w', 'v', source_language='zh', target_language='en')


def test_legacy_can_still_be_read_before_direction_migration():
    block_id = seed()[0]
    store.execute('INSERT INTO translations VALUES(?,?,?,?,?,?)',
                  (block_id, 'w', 'v', 'Old fixture', 'old-model', time.time()))
    store.execute('DROP TABLE translation_cache')
    assert translation.load_translations('w', 'v')[0]['text'] == 'Old fixture'


def test_snapshot_pin_selection_and_workspace_are_enforced(monkeypatch):
    original = seed(['Old source 17.'])[0]
    run = make_run(block_ids=[original], checkpoint={'tool_registry': {'fixture': 'keep'}})
    revised = seed(['New source 19.'], parse_id='new-parse')[0]
    calls = fixture_provider(monkeypatch)
    result = translation.translate(run)
    assert result['parse_id'] == 'v' and result['translated'] == 1
    assert saved_checkpoint(run)['tool_registry'] == {'fixture': 'keep'}
    assert saved_checkpoint(run)['translation_parse_id'] == 'v'
    assert translation.load_translations('w', 'v') == []
    assert translation.load_translations('w', 'v', parse_id='v')[0]['block_id'] == original
    assert '[尚未翻译]' in translation.export_translation('w', 'v')
    with pytest.raises(ValueError, match='解析快照'):
        translation.translate(make_run(block_ids=[original]))
    with pytest.raises(ValueError, match='解析快照'):
        translation.load_translations('w', 'v', parse_id='v', block_ids=[revised])
    with pytest.raises(ValueError, match='无权限'):
        translation.load_translations('foreign-workspace', 'v', parse_id='v')
    with pytest.raises(ValueError, match='解析快照'):
        translation.export_translation('w', 'v', parse_id='foreign-parse')
    assert len(calls) == 1


def test_old_unpinned_checkpoint_stays_pinned_after_reparse(monkeypatch):
    seed(['Old source.'])
    run = make_run(checkpoint={'translation_parse_id': 'v'})
    run['payload'].pop('parse_id')
    seed(['New source.'], parse_id='new-parse')
    fixture_provider(monkeypatch)
    assert translation.translate(run)['parse_id'] == 'v'
    run['payload']['target_language'] = 'en'
    with pytest.raises(ValueError, match='恢复参数'):
        translation.translate(run)


def test_resume_cannot_change_pinned_budget_or_selection(monkeypatch):
    seed()
    run = make_run()
    fixture_provider(monkeypatch)
    translation.translate(run)
    monkeypatch.setattr(translation, 'DEFAULT_INPUT_TOKEN_BUDGET', 2400)
    with pytest.raises(ValueError, match='恢复参数'):
        translation.translate(run)


def test_jobs_wrapper_can_delegate_without_worker_changes(monkeypatch):
    seed()
    fixture_provider(monkeypatch)
    queued = jobs.queue('w', 'translate', {'version_id': 'v'}, 'fixture-queue-translation')
    monkeypatch.setattr(jobs, 'translate', translation.translate)
    assert jobs.work_once()
    row = store.one('SELECT * FROM runs WHERE id=?', (queued['id'],))
    assert row['status'] == 'completed', row['error']
    assert json.loads(row['result'])['parse_id'] == 'v'


def test_completed_batches_survive_provider_failure_and_resume_without_repeating(monkeypatch):
    seed(['Short source.'] * 8)
    run = make_run()
    calls = []

    def generate(system, prompt, rid, core=False):
        items = json.loads(prompt)
        calls.append(items)
        if len(calls) == 2:
            raise models.ModelError('Fixture interruption')
        return {'model': 'FIXTURE_NOT_LIVE', 'text': json.dumps({'translations': [
            {'block_id': item['block_id'], 'text': item['text']} for item in items
        ]})}

    monkeypatch.setattr(models, 'generate', generate)
    with pytest.raises(models.ModelError, match='Fixture interruption'):
        translation.translate(run)
    assert store.one('SELECT count(*) n FROM translation_cache')['n'] == 6
    result = translation.translate(run)
    assert result['translated'] == result['total'] == 8
    assert result['cache_hits'] == 6
    assert len(calls) == 3
    assert {item['block_id'] for item in calls[0]}.isdisjoint({item['block_id'] for item in calls[2]})


def test_oversized_utf8_block_uses_bounded_segments_and_recovers_partial_block(monkeypatch):
    source = ('中文科学原文 and an English sentence with $x=7$ and 42 samples [3].\n' * 100)
    seed([source])
    monkeypatch.setattr(translation, 'DEFAULT_INPUT_TOKEN_BUDGET', 2600)
    run = make_run()
    successful_ids = []
    calls = []

    def generate(system, prompt, rid, core=False):
        items = json.loads(prompt)
        assert translation.estimate_input_tokens(system, items) <= 2600
        assert translation.estimate_output_tokens(items) <= translation.OUTPUT_TOKEN_BUDGET
        calls.append(items)
        if len(calls) == 2:
            raise models.ModelError('Fixture interruption')
        successful_ids.extend(item['block_id'] for item in items)
        return {'model': 'FIXTURE_NOT_LIVE', 'text': json.dumps({'translations': [
            {'block_id': item['block_id'], 'text': item['text'].strip()} for item in items
        ]})}

    monkeypatch.setattr(models, 'generate', generate)
    with pytest.raises(models.ModelError):
        translation.translate(run)
    assert saved_checkpoint(run)['translation_pending_segments']
    assert store.one('SELECT count(*) n FROM translation_cache')['n'] == 0
    result = translation.translate(run)
    assert result['translated'] == result['total'] == 1
    assert len(successful_ids) == len(set(successful_ids))
    assert len(calls) > 3
    assert translation.load_translations('w', 'v')[0]['text'] == source
    assert saved_checkpoint(run)['translation_pending_segments'] == {}
    assert translation.estimate_input_tokens('中', []) > translation.estimate_input_tokens('a', [])


@pytest.mark.parametrize('corruption', ['missing', 'duplicate', 'foreign_id', 'empty', 'wrong_shape', 'bad_placeholder', 'invalid_json'])
def test_bad_batch_is_atomic_and_never_marked_complete(monkeypatch, corruption):
    seed(['First 17 [2].', 'Second 18 [3].'])
    run = make_run()

    def generate(system, prompt, rid, core=False):
        items = json.loads(prompt)
        output = [{'block_id': item['block_id'], 'text': item['text']} for item in items]
        if corruption == 'missing':
            output.pop()
        elif corruption == 'duplicate':
            output[1] = dict(output[0])
        elif corruption == 'foreign_id':
            output[1]['block_id'] = 'foreign'
        elif corruption == 'empty':
            output[1]['text'] = ' '
        elif corruption == 'wrong_shape':
            output[1] = None
        elif corruption == 'bad_placeholder':
            output[1]['text'] = 'lost all protected source spans'
        return {'model': 'FIXTURE_NOT_LIVE', 'text': '{bad' if corruption == 'invalid_json' else json.dumps({'translations': output})}

    monkeypatch.setattr(models, 'generate', generate)
    with pytest.raises(ValueError):
        translation.translate(run)
    assert store.one('SELECT count(*) n FROM translation_cache')['n'] == 0
    assert not saved_checkpoint(run).get('translation_pending_segments')
    monkeypatch.setattr(models,'generate',lambda *a,**kw:pytest.fail('A received invalid response must not be silently billed again'))
    with pytest.raises(ValueError):translation.translate(run)


@pytest.mark.parametrize('during_request', [False, True])
def test_cancel_before_or_during_request_does_not_publish_response(monkeypatch, during_request):
    seed(['Text with 42 [2].'])
    run = make_run()
    calls = []

    def generate(system, prompt, rid, core=False):
        calls.append(prompt)
        store.execute("UPDATE runs SET status='cancelled' WHERE id=?", (rid,))
        return {'model': 'FIXTURE_NOT_LIVE', 'text': json.dumps({'translations': [
            {'block_id': item['block_id'], 'text': item['text']} for item in json.loads(prompt)
        ]})}

    monkeypatch.setattr(models, 'generate', generate)
    if not during_request:
        store.execute("UPDATE runs SET status='cancelled' WHERE id=?", (run['id'],))
    result = translation.translate(run)
    assert result['cancelled'] and result['translated'] == 0
    assert len(calls) == int(during_request)
    assert store.one('SELECT count(*) n FROM translation_cache')['n'] == 0


def test_export_selection_direction_and_html_escape(monkeypatch):
    ids = seed(['<script>untrusted()</script> value 7.', 'Another source.'])
    fixture_provider(monkeypatch, prefix='English fixture ')
    translation.translate(make_run(source_language='zh', target_language='en', block_ids=[ids[0]]))
    md = translation.export_translation('w', 'v', parse_id='v', source_language='zh', target_language='en', block_ids=[ids[0]])
    assert 'zh → en' in md and '解析快照：v' in md
    assert ids[0] in md and ids[1] not in md
    assert 'English fixture' in md
    assert '[尚未翻译]' in translation.export_translation('w', 'v')
    rendered = translation.export_translation('w', 'v', source_language='zh', target_language='en', format='html')
    assert '<script>' not in rendered and '&lt;script&gt;' in rendered
    with pytest.raises(ValueError, match='格式'):
        translation.export_translation('w', 'v', format='pdf')
