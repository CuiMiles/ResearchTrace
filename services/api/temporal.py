"""Compare publication intervals, without inventing dates for year-only records."""
import calendar
from datetime import date
import re


def publication_window(metadata,identity=''):
    for name in ('published','publication_date','date'):
        value=metadata.get(name)
        if isinstance(value,str):
            try:
                day=date.fromisoformat(value[:10])
                return {'earliest':day.isoformat(),'latest':day.isoformat(),'precision':'day','source_field':name}
            except ValueError:pass
    arxiv=str(metadata.get('arxiv_id') or identity.removeprefix('arxiv:'))
    match=re.match(r'^(\d{2})(\d{2})\.\d{4,5}',arxiv)
    if match:
        year=2000+int(match[1]);month=int(match[2])
        if 1<=month<=12:
            return {'earliest':date(year,month,1).isoformat(),'latest':date(year,month,calendar.monthrange(year,month)[1]).isoformat(),
                    'precision':'month','source_field':'arxiv_identifier_original_submission_not_revision'}
    year=metadata.get('year')
    if type(year) is int and 1800<=year<=2200:
        return {'earliest':f'{year:04}-01-01','latest':f'{year:04}-12-31','precision':'year','source_field':'year'}
    return None


def compare_time(old,candidate):
    before=old.get('publication_window') or publication_window(old,old.get('identity',''))
    after=candidate.get('publication_window') or publication_window(candidate,candidate.get('identity',''))
    if not before or not after:return {'status':'unknown','source':before,'candidate':after,'reason':'来源或候选缺少可核验日期'}
    if after['earliest']>before['latest']:status='later';reason='候选发表区间完全晚于来源区间'
    elif after['latest']<before['earliest']:status='earlier';reason='候选早于来源'
    else:status='overlap';reason='日期区间重叠；同年或同月不足以确定先后'
    return {'status':status,'source':before,'candidate':after,'reason':reason}
