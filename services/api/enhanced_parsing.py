"""Normalize genuine PaddleOCR / MinerU responses to the immutable block contract."""
import io
import os
import threading
from pathlib import Path

import httpx
import pypdfium2 as pdfium

from .store import ROOT

def external_page(pdf_path,page_index,engine,device='cpu',run_id=None):
    if engine not in ('paddleocr','paddleocr_vl','mineru'):
        raise ValueError('Unknown parser engine')
    socket=Path(os.getenv('RT_PARSER_SOCKET',ROOT/'data/parsing/parser.sock'))
    if not socket.exists():
        raise ValueError('PaddleOCR/MinerU private worker unavailable')
    doc=pdfium.PdfDocument(str(pdf_path))
    try:
        buffer=io.BytesIO()
        if engine in ('paddleocr','paddleocr_vl'):
            page=doc[page_index];scale=min(2.5,2400/max(page.get_size()))
            bitmap=page.render(scale=scale)
            image=bitmap.to_pil()
            try:
                image.save(buffer,format='PNG')
            finally:
                image.close();bitmap.close();page.close()
            name='page.png'
        else:
            single=pdfium.PdfDocument.new()
            try:
                single.import_pages(doc,[page_index]);single.save(buffer)
            finally:
                single.close()
            name='page.pdf'
    finally:
        doc.close()
    transport=httpx.HTTPTransport(uds=str(socket))
    with httpx.Client(transport=transport,base_url='http://parser',trust_env=False,timeout=930) as client:
        params={'device':device if engine=='mineru' else 'cpu'}
        if run_id:
            params['request_id']=run_id
        result_holder={}
        done=threading.Event()
        stop_waiting=threading.Event()
        def request():
            try:
                for attempt in range(31):
                    if stop_waiting.is_set():
                        raise ValueError('解析任务已取消')
                    response=client.post('/parse/'+engine,params=params,files={'file':(name,buffer.getvalue())})
                    if response.status_code!=429 or attempt==30:
                        result_holder['response']=response
                        break
                    # A local broker reservation is safe to retry; no inference started.
                    stop_waiting.wait(1)
            except Exception as exc:
                result_holder['error']=exc
            finally:
                done.set()
        thread=threading.Thread(target=request,daemon=True)
        thread.start()
        cancellation_sent=False
        while not done.wait(.25):
            if run_id:
                from .store import cancelled
                if cancelled(run_id):
                    stop_waiting.set()
                    # The private broker owns exactly this run's isolated process group.
                    # Retry 404 until the request has registered, never cancel another job.
                    response=client.post('/cancel/'+run_id,timeout=10)
                    if response.status_code==200:
                        cancellation_sent=True
                        if not done.wait(15):
                            raise ValueError('解析取消已请求；资源释放状态待检查')
                        break
        thread.join(timeout=1)
        if cancellation_sent:
            raise ValueError('解析任务已取消，已完成页面快照保留')
        if 'error' in result_holder:
            raise ValueError('解析 worker 连接异常；已完成页面保留') from None
        response=result_holder['response']
    if response.status_code!=200:
        detail=''
        try:
            payload=response.json()
            if isinstance(payload,dict) and isinstance(payload.get('detail'),str):
                detail=payload['detail'].strip()[:180]
        except ValueError:
            pass
        raise ValueError(f'{engine} unavailable; broker HTTP {response.status_code}'+(f': {detail}' if detail else ''))
    result=response.json()
    if result.get('engine')!=engine or not result.get('version'):
        raise ValueError('Parser provenance missing')
    entries=result.get('lines',[]) if engine=='paddleocr' else result.get('blocks',[])
    for item in entries:
        box=item.get('bbox',[])
        if len(box)!=4 or not all(isinstance(x,(int,float)) and 0<=x<=1 for x in box) or box[0]>box[2] or box[1]>box[3]:
            raise ValueError('Parser returned invalid page coordinates')
        if not isinstance(item.get('text'),str):
            raise ValueError('Parser returned invalid text')
    return result

def paddle_words(result,width,height):
    words=[]
    confidences=[]
    for line in result['lines']:
        x0,y0,x1,y1=line['bbox']
        words.append({'text':line['text'],'x0':x0*width,'x1':x1*width,'top':y0*height,'bottom':y1*height,'size':(y1-y0)*height,'upright':True})
        confidences.append(line.get('confidence',0))
    quality='ocr' if confidences and sum(confidences)/len(confidences)>=.8 else 'ocr_review_required'
    return words,quality

def mineru_blocks(result,version_id,page_index):
    blocks=[]
    source=result.get('engine','mineru')
    for i,item in enumerate(result['blocks']):
        kind=item.get('type','paragraph')
        metadata={**item.get('metadata',{}),'parser_version':result['version'],'device':result['device']}
        if metadata.get('text_level'):
            kind='heading'
        blocks.append({'id':f'{version_id}:{page_index}:{i}','version_id':version_id,'page_index':page_index,'bbox':item['bbox'],'type':kind,
            'reading_order':i,'text':item['text'],'source':source,'quality':'structured_review_required','metadata':metadata})
    return blocks
