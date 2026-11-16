"""Document cards: titles, outline levels, author validation and the author-ordinal exemption."""
import io
import json
from pathlib import Path

import pdfplumber
import pytest
from reportlab.pdfgen import canvas

from services.api import cards, documents, evidence_validation, jobs, store

CORPUS = Path(__file__).resolve().parents[2] / 'evals' / 'pdfs' / '科研小助手' / 'pdf'


@pytest.mark.parametrize('text,expected', [
    ('RA: -R', False), ('16 16', False), ('A B C', False),
    ('Mistral 7B', True), ('Layer Normalization', True), ('注意力机制研究', True),
])
def test_plausible_title_rejects_small_caps_fragments(text, expected):
    assert cards.plausible_title(text) is expected


@pytest.mark.skipif(not (CORPUS / '2106.09685v2.pdf').exists(), reason='contest corpus not present')
@pytest.mark.parametrize('name,expected', [
    ('2106.09685v2.pdf', 'LORA: LOW-RANK ADAPTATION OF LARGE LANGUAGE MODELS'),
    ('2010.11929v2.pdf', 'AN IMAGE IS WORTH 16X16 WORDS: TRANSFORMERS FOR IMAGE RECOGNITION AT SCALE'),
    ('1706.03762v7.pdf', 'Attention Is All You Need'),
])
def test_layout_title_keeps_small_caps_lines_together(name, expected):
    with pdfplumber.open(CORPUS / name) as pdf:
        assert cards.layout_title(pdf.pages[0]) == expected


@pytest.mark.skipif(not (CORPUS / '1706.03762v7.pdf').exists(), reason='contest corpus not present')
def test_bookmarks_give_levels_and_pages():
    marks = cards.pdf_bookmarks(str(CORPUS / '1706.03762v7.pdf'))
    titles = {(m['title'], m['level']) for m in marks}
    assert ('Multi-Head Attention', 3) in titles and ('Attention', 2) in titles
    assert all(isinstance(m['page_index'], int) for m in marks)


def test_heading_levels_from_numbering():
    assert cards.heading_level('3.2.2 Multi-Head Attention') == 3
    assert cards.heading_level('4 Experiments') == 1
    assert cards.heading_level('A.1 Extra results') == 2
    assert cards.heading_level('References') == 1
    assert cards.heading_level('Provided proper attribution is provided, Google') is None


def test_outline_tree_nests_by_level():
    flat = [{'title': '1 Intro', 'level': 1}, {'title': '3 Model', 'level': 1},
            {'title': '3.2 Attention', 'level': 2}, {'title': '3.2.2 Multi-Head', 'level': 3},
            {'title': '4 Training', 'level': 1}]
    tree = cards.outline_tree(flat)
    assert [n['title'] for n in tree] == ['1 Intro', '3 Model', '4 Training']
    assert tree[1]['children'][0]['children'][0]['title'] == '3.2.2 Multi-Head'


def test_build_outline_skips_title_page_boilerplate():
    blocks = [
        {'id': 'b1', 'type': 'heading', 'page_index': 0, 'reading_order': 0,
         'text': 'Provided proper attribution is provided, Google hereby grants permission to'},
        {'id': 'b2', 'type': 'heading', 'page_index': 0, 'reading_order': 1, 'text': 'Attention Is All You Need'},
        {'id': 'b3', 'type': 'heading', 'page_index': 0, 'reading_order': 2, 'text': 'Abstract'},
        {'id': 'b4', 'type': 'heading', 'page_index': 1, 'reading_order': 0, 'text': '1 Introduction'},
        {'id': 'b5', 'type': 'heading', 'page_index': 2, 'reading_order': 0, 'text': '3.2.2 Multi-Head Attention'},
    ]
    outline = cards.build_outline(blocks, [])
    assert [(e['title'], e['level']) for e in outline] == [
        ('Abstract', 1), ('1 Introduction', 1), ('3.2.2 Multi-Head Attention', 3)]


def test_model_author_strings_must_occur_in_the_page():
    page = 'Ashish Vaswani  Noam Shazeer\nGoogle Brain   Google Brain\navaswani@google.com'
    data = {'authors': [
        {'name': 'Ashish Vaswani', 'affiliations': ['Google Brain'], 'emails': ['avaswani@google.com']},
        {'name': 'Noam Shazeer', 'affiliations': ['Stanford University'], 'emails': []},
        {'name': 'Invented Person', 'affiliations': ['Google Brain'], 'emails': []},
    ]}
    kept, dropped = cards._validated_authors(data, page)
    assert [a['name'] for a in kept] == ['Ashish Vaswani', 'Noam Shazeer']
    assert kept[1]['affiliations'] == []
    assert 'Invented Person' in dropped and any('Stanford' in d for d in dropped)


def test_reference_order_wins_and_takes_pdf_affiliations():
    reference = [{'name': 'Aidan N. Gomez', 'affiliations': []}, {'name': 'Łukasz Kaiser', 'affiliations': []}]
    extracted = [{'name': 'Lukasz Kaiser', 'affiliations': ['Google Brain'], 'emails': [], 'notes': []},
                 {'name': 'Aidan N. Gomez', 'affiliations': ['University of Toronto'], 'emails': [], 'notes': []}]
    merged = cards._merge_authors(reference, extracted)
    assert [a['name'] for a in merged] == ['Aidan N. Gomez', 'Łukasz Kaiser']
    assert merged[0]['affiliations'] == ['University of Toronto']
    assert merged[1]['affiliations'] == ['Google Brain'] and merged[1]['source'] == 'arxiv+pdf_title_page'


@pytest.fixture
def workspace_doc(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'DATA', tmp_path)
    monkeypatch.setattr(documents, 'DATA', tmp_path)
    store.migrate()
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer)
    pdf.setFont('Helvetica-Bold', 20)
    pdf.drawString(72, 760, 'Fixture Paper On Card Metadata')
    pdf.setFont('Helvetica', 10)
    pdf.drawString(72, 730, 'Alice Example *   Bob Sample *   Carol Third *')
    pdf.drawString(72, 716, 'Example University   Sample Lab   Third Institute')
    pdf.setFont('Helvetica-Bold', 12)
    pdf.drawString(72, 690, 'Abstract')
    pdf.setFont('Helvetica', 10)
    pdf.drawString(72, 676, 'We study fixtures for metadata cards in a controlled setting.')
    pdf.setFont('Helvetica-Bold', 12)
    pdf.drawString(72, 650, '1 Introduction')
    pdf.setFont('Helvetica', 10)
    pdf.drawString(72, 636, 'Body text of the introduction section.')
    pdf.save()
    uploaded = documents.upload_document('ws-card', 'renamed.pdf', buffer.getvalue(), index_dense=False)
    while jobs.work_once(pool='documents'):
        pass
    return uploaded['document']['id']


def test_card_is_built_offline_after_parse(workspace_doc):
    card = cards.get_card('ws-card', workspace_doc)
    assert card is not None and card['version'] == cards.CARD_VERSION
    assert card['title']['value'] == 'Fixture Paper On Card Metadata'
    assert card['title']['source'] in ('pdf_layout', 'pdf_metadata')
    assert [e['title'] for e in card['outline']] == ['Abstract', '1 Introduction']
    assert card['abstract']['source'] == 'pdf_abstract_section'
    assert 'fixtures for metadata cards' in card['abstract']['text']


def test_card_authors_exempt_author_ordinals_from_number_checks(workspace_doc):
    from services.api.snapshots import selected_parse, snapshot_blocks
    parse_id = selected_parse('ws-card', workspace_doc)['id']
    card = cards.get_card('ws-card', workspace_doc)
    card['authors'] = [{'name': n, 'affiliations': [], 'emails': [], 'notes': [], 'position': i + 1}
                       for i, n in enumerate(['Alice Example', 'Bob Sample', 'Carol Third'])]
    cards.save_card('ws-card', workspace_doc, parse_id, card)
    blocks = [{**b, 'bbox': json.loads(b['bbox'])} for b in snapshot_blocks('ws-card', workspace_doc, parse_id)]
    author_block = next(b for b in blocks if 'Carol Third' in b['text'])
    answer = {'claims': [{'id': 'c1', 'type': 'source_fact', 'text': '第3作者是 Carol Third。',
                          'evidence': [{'block_id': author_block['id'], 'quote': 'Carol Third'}]}]}
    result = evidence_validation.validate(answer, blocks, workspace='ws-card', version_ids=[workspace_doc])
    assert result['claims'][0]['evidence'][0]['quote'] == 'Carol Third'
    wrong = {'claims': [{'id': 'c1', 'type': 'source_fact', 'text': '第2作者是 Carol Third。',
                         'evidence': [{'block_id': author_block['id'], 'quote': 'Carol Third'}]}]}
    with pytest.raises(ValueError):
        evidence_validation.validate(wrong, blocks, workspace='ws-card', version_ids=[workspace_doc])
