"""Source-remapping fixtures never rewrite historical notes or source blocks."""
import json
import pytest
from services.api import store,version_impact


def test_changed_number_requires_review_and_old_notes_are_immutable(tmp_path,monkeypatch):
    monkeypatch.setattr(store,'DATA',tmp_path);store.migrate()
    with store.db() as c:
        c.execute("INSERT INTO works VALUES('work','w','Fixture paper','fixture:paper','{}')")
        for vid in ('old','new'):
            c.execute("INSERT INTO versions(id,workspace,work_id,title,filename,sha256,path,status,parsed_pages,page_count,created) VALUES(?, 'w','work','Fixture paper','fixture.pdf',?,'unused','ready',1,1,1)",(vid,vid))
        for bid,vid,text in [('old1','old','The experiment used 8 GPUs.'),('old2','old','An unchanged methodology sentence.'),('new1','new','The experiment used 80 GPUs.'),('new2','new','An unchanged methodology sentence.')]:
            c.execute("INSERT INTO blocks VALUES(?,'w',?,0,'[0,0,1,1]','paragraph',0,?,'fixture','native','{}')",(bid,vid,text))
    payload={'claims':[{'id':'c1','text':'8 GPUs','type':'source_fact','evidence':[{'version_id':'old','block_id':'old1','quote':'The experiment used 8 GPUs.'}]},
                       {'id':'c2','text':'Unchanged','type':'source_fact','evidence':[{'version_id':'old','block_id':'old2','quote':'An unchanged methodology sentence.'}]}]}
    aid=store.artifact('w',None,'research_note','fixture note',payload)
    before=store.one('SELECT payload FROM artifacts WHERE id=?',(aid,))
    blocks=store.rows('SELECT * FROM blocks ORDER BY id')
    result=version_impact.assess('w','old','new')
    assert result['unchanged']==1 and result['needs_review']==1
    changed=next(c for c in result['claims'] if c['claim_id']=='c1')
    assert changed['mappings'][0]['status']=='source_changed_requires_review'
    assert store.one('SELECT payload FROM artifacts WHERE id=?',(aid,))==before
    assert store.rows('SELECT * FROM blocks ORDER BY id')==blocks
    assert result['artifact_id']==version_impact.assess('w','old','new')['artifact_id']
    with pytest.raises(ValueError):version_impact.assess('foreign','old','new')
