import copy
import pytest
from services.api import jobs
from services.api.evidence_validation import apply_semantic_review


@pytest.fixture
def block():
    return {'id':'b1','version_id':'v1','parse_id':'p1','page_index':4,'bbox':[0,0,1,1],
            'text':'We trained our models on one machine with 8 NVIDIA P100 GPUs. The run took 80 hours.'}


def answer(text='The experiment used 8 NVIDIA P100 GPUs.',quote='We trained our models on one machine with 8 NVIDIA P100 GPUs.'):
    return {'answer':text,'claims':[{'id':'c1','text':text,'type':'source_fact','evidence':[{'block_id':'b1','quote':quote}]}]}


def test_review_numeric_counterexample_rejected_even_when_number_is_elsewhere(block):
    data=answer('The experiment used 80 NVIDIA P100 GPUs.',block['text'])
    with pytest.raises(ValueError,match='数值|单位'):jobs.validate_answer(data,[block])


def test_live_hardware_model_name_is_not_gpu_count():
    from services.api.evidence_validation import numeric_findings
    quote='We trained our models on one machine with 8 NVIDIA P100 GPUs.'
    assert numeric_findings('使用8张 NVIDIA P100 GPU训练模型。',[quote])==[]
    assert numeric_findings('使用80张 NVIDIA P100 GPU训练模型。',[quote])
    assert numeric_findings('论文 arxiv:1706.03762 使用8张 NVIDIA P100 GPU。',[quote],['arxiv:1706.03762'])==[]
    assert numeric_findings('论文 arxiv:9999.99999 使用8张 GPU。',[quote],['arxiv:1706.03762'])


def test_chinese_magnitude_and_decimal_equivalence():
    from services.api.evidence_validation import numeric_findings
    assert not numeric_findings('训练10万步，每步1秒。',['We trained for 100,000 steps. Step time was 1.0 seconds.'])
    assert not numeric_findings('epsilon=10^-9。',['epsilon =10 −9.'])
    assert not numeric_findings('epsilon=1e-9。',['epsilon =10 −9.'])


def test_source_locator_numbers_are_checked_metadata_not_gpu_counts(block):
    from services.api.evidence_validation import metadata_spans,numeric_findings
    evidence=[{'block_id':block['id']}]
    text='page_index: 4 的原文说使用8张GPU。'
    assert not numeric_findings(text,[block['text']],metadata_spans(text,evidence,[block]))
    wrong='page_index: 40 的原文说使用80张GPU。'
    assert numeric_findings(wrong,[block['text']],metadata_spans(wrong,evidence,[block]))


def test_review_answer_prose_cannot_bypass_claims(block):
    data=answer();data['answer']='The experiment used 80 GPUs and cost 100 million dollars.'
    with pytest.raises(ValueError,match='正文'):jobs.validate_answer(data,[block])


@pytest.mark.parametrize('quote',['   ','\n\t','\u200b\u200c'])
def test_review_empty_quote_rejected(block,quote):
    with pytest.raises(ValueError,match='空引文|空白'):jobs.validate_answer(answer(quote=quote),[block])


def test_quote_offsets_and_review_do_not_claim_semantic_support(block):
    result=jobs.validate_answer(answer(),[block]);citation=result['claims'][0]['evidence'][0]
    assert block['text'][citation['quote_span']['start']:citation['quote_span']['end']]==citation['quote']
    assert citation['parse_id']=='p1'
    assert result['claims'][0]['review']['status']=='not_checked'
    assert result['status']=='partial'
    assert result['answer_segments'][0]['claim_ids']==['c1']


def test_unknown_segments_or_paraphrase_are_not_unchecked_facts(block):
    # Prose that differs from its checked claim is replaced by the claim text, never published.
    data=answer();data['answer_segments']=[{'text':'It cost a billion dollars.','claim_ids':['c1']}]
    result=jobs.validate_answer(data,[block])
    assert 'billion' not in result['answer'] and result['unchecked_prose_replaced']==1
    assert result['answer_segments'][0]['text']==result['claims'][0]['text']
    data['answer_segments'][0]['claim_ids']=['foreign']
    with pytest.raises(ValueError,match='未知主张'):jobs.validate_answer(data,[block])


def test_unbound_nonnumeric_free_prose_is_dropped(block):
    data=answer();data['answer']='The authors secretly work at a different institution.'
    result=jobs.validate_answer(data,[block])
    assert result['answer']==data['claims'][0]['text']
    assert result['legacy_answer_replaced']


def test_independent_critic_can_reject_without_rewriting_history(block):
    result=jobs.validate_answer(answer(),[block]);before=copy.deepcopy(block)
    result=apply_semantic_review(result,{'reviews':[{'claim_id':'c1','status':'insufficient','reason':'Condition not supported by selected quote'}]})
    assert result['claims'][0]['type']=='insufficient'
    assert result['status']=='partial' and '未获原文支持' in result['answer']
    assert block==before
    with pytest.raises(ValueError):apply_semantic_review(result,{'reviews':[]})


def test_quote_snapshot_and_workspace_checked_against_source(tmp_path,monkeypatch,block):
    from services.api import store
    monkeypatch.setattr(store,'DATA',tmp_path);store.migrate()
    with pytest.raises(ValueError,match='工作区|快照'):jobs.validate_answer(answer(),[block],workspace='other',version_ids=['v1'])
    with pytest.raises(ValueError,match='版本'):jobs.validate_answer(answer(),[block],version_ids=['another-version'])
