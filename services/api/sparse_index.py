"""Symmetric CJK tokenization in a derived index; original text stays immutable."""
import hashlib
import re
from . import store


LEXICON = {'作者':('author','authors','affiliation'), '机构':('affiliation','organization'),
           '训练':('train','trained','training'), '显卡':('GPU','GPUs','accelerator'),
           '优化器':('optimizer','optimization'), '参数':('parameters','hyperparameters'),
           '层归一化':('layer','normalization'), '上下文':('context','length'),
           '注意力':('attention',), '模型':('model','models'), '翻译':('translation',),
           '成本':('cost','expense'), '批量':('batch',), '学习率':('learning','rate')}


FTS_OPERATORS = {'OR', 'AND', 'NOT', 'NEAR'}


def tokens(text):
    text = re.sub(r'\b(?:OR|AND|NOT|NEAR)\b', ' ', text or '')
    out = re.findall(r'[A-Za-z][A-Za-z0-9_]*|[βγδε]\s*\d*|\d+(?:\.\d+)?|[\u4e00-\u9fff]+',text)
    result=[]
    for token in out:
        if re.fullmatch(r'[\u4e00-\u9fff]+',token):
            result.append(token)
            result.extend(token[i:i+2] for i in range(len(token)-1))
        else:
            result.append(re.sub(r'\s+','',token))
    return list(dict.fromkeys(result))


def indexed_text(block):
    text=block['text']
    cjk=[t for t in tokens(text) if re.search(r'[\u4e00-\u9fff]',t)]
    # A role tag helps authorship retrieval; it is not a claimed author/entity.
    role=' frontmatter author authors affiliation organization' if block['page_index']==0 else ''
    return text+role+'\n'+' '.join(cjk)


def ensure(workspace,version_ids,parse_id=None):
    if not version_ids:return
    placeholders=','.join('?' for _ in version_ids)
    with store.db() as c:
        table='blocks' if parse_id else 'current_blocks'
        constraint=' AND COALESCE(bp.parse_id,b.version_id)=?' if parse_id else ''
        blocks=c.execute(f'SELECT b.id,b.text,b.page_index FROM {table} b JOIN versions v ON v.id=b.version_id LEFT JOIN block_parses bp ON bp.block_id=b.id LEFT JOIN sparse_index_state s ON s.block_id=b.id WHERE b.workspace=? AND b.version_id IN ({placeholders}) AND v.deleted=0 AND s.block_id IS NULL'+constraint,(workspace,*version_ids,*([parse_id] if parse_id else []))).fetchall()
        if not blocks:return
        c.execute('BEGIN IMMEDIATE')
        for row in blocks:
            block=dict(row)
            if c.execute('SELECT 1 FROM sparse_index_state WHERE block_id=?',(block['id'],)).fetchone():continue
            c.execute('INSERT INTO sparse_blocks_v2(block_id,text) VALUES(?,?)',(block['id'],indexed_text(block)))
            c.execute('INSERT INTO sparse_index_state VALUES(?,?)',(block['id'],hashlib.sha256(block['text'].encode()).hexdigest()))


def search(workspace,version_ids,question,limit=50,parse_id=None):
    ensure(workspace,version_ids,parse_id)
    expanded=tokens(question)
    translated=[]
    for key,words in LEXICON.items():
        if key in question:
            translated.extend(words)
    expanded=list(dict.fromkeys(expanded+translated))
    for token in list(expanded):
        if re.fullmatch(r'[βγδε]\d+',token):expanded.append(token[0])
    match=' OR '.join('"'+t.replace('"','""')+'"'+('*' if re.fullmatch(r'[A-Za-z]{3,}',t) else '') for t in expanded[:60] if len(t)>1 or t in 'βγδε')
    if not match:return [],translated
    placeholders=','.join('?' for _ in version_ids)
    table='blocks' if parse_id else 'current_blocks'
    constraint=' AND COALESCE(bp.parse_id,b.version_id)=?' if parse_id else ''
    result=store.rows(f'SELECT b.*,COALESCE(bp.parse_id,b.version_id) AS parse_id,bm25(sparse_blocks_v2) AS sparse_score FROM sparse_blocks_v2 JOIN {table} b ON b.id=sparse_blocks_v2.block_id LEFT JOIN block_parses bp ON bp.block_id=b.id JOIN versions v ON v.id=b.version_id WHERE sparse_blocks_v2 MATCH ? AND b.workspace=? AND b.version_id IN ({placeholders}) AND v.deleted=0'+constraint+' ORDER BY sparse_score LIMIT ?', (match,workspace,*version_ids,*([parse_id] if parse_id else []),limit))
    return result,translated
