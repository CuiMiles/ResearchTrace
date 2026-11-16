"""Operator-configured authenticated local retrieval; never Google model aliases."""
import hashlib
import json
import os
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit

import httpx
import numpy as np


class RetrievalUnavailable(ValueError):
    pass


def fingerprint(descriptor):
    if 'tokenizer' in descriptor and 'templates' in descriptor:
        keys=('model_id','revision','kind','dimension','dtype','context_length','pooling','normalization','tokenizer','templates','source_sha256','runtime_version','truncation','attention_implementation')
        if any(k not in descriptor for k in keys):
            raise RetrievalUnavailable('运行时模型指纹缺少必需字段')
        calculated='sha256:'+hashlib.sha256(json.dumps({k:descriptor[k] for k in keys},sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
        if descriptor.get('fingerprint')!=calculated:
            raise RetrievalUnavailable('运行时模型指纹校验失败')
        return calculated
    required = ('model_id','revision','tokenizer_revision','query_template','document_template','pooling','normalization','dimension','dtype')
    if any(k not in descriptor or descriptor[k] is None or descriptor[k]=='' for k in required):
        raise RetrievalUnavailable('模型指纹不完整，不能建立或混用索引')
    if not isinstance(descriptor['dimension'],int) or not 1<=descriptor['dimension']<=16384:
        raise RetrievalUnavailable('模型维度不符合约定')
    return hashlib.sha256(json.dumps({k:descriptor[k] for k in required},sort_keys=True,ensure_ascii=False).encode()).hexdigest()


class EmbeddingProvider(Protocol):
    def descriptor(self) -> dict: ...
    def split(self, text: str, max_tokens: int, overlap: int = 32) -> list[dict]: ...
    def embed(self, texts: list[str], task: str) -> dict: ...


class RerankProvider(Protocol):
    def rerank(self, query: str, documents: list[str]) -> dict: ...


class GeminiRetrievalProvider:
    """Separate cloud vector space; input split is an explicit UTF-8 upper bound.

    The upstream API alias is not an immutable weights revision. An operator can
    bump RT_CLOUD_INDEX_REVISION to build a new generation if it changes.
    """
    def __init__(self,run_id=None):
        from . import models
        self.run_id=run_id;self.model_id=models.EMBED
        if self.model_id!='gemini-embedding-001':
            raise RetrievalUnavailable('当前云向量适配器只支持已验证的gemini-embedding-001')

    def descriptor(self):
        return {'model_id':self.model_id,'revision':os.getenv('RT_CLOUD_INDEX_REVISION','gemini-api-v1beta-768-v1'),
                'tokenizer_revision':'utf8-byte-upper-bound-v1','query_template':'taskType=RETRIEVAL_QUERY: {text}',
                'document_template':'taskType=RETRIEVAL_DOCUMENT: {text}','pooling':'provider_managed',
                'normalization':'l2','dimension':768,'dtype':'float32','provider':'gemini',
                'immutable_weights_revision_available':False,'token_count_kind':'conservative_utf8_byte_upper_bound'}

    def split(self,text,max_tokens,overlap=32):
        parts=[];start=0
        while start<len(text):
            end=start;size=0
            while end<len(text) and size+len(text[end].encode())<=max_tokens:
                size+=len(text[end].encode());end+=1
            if end==start:raise RetrievalUnavailable('切分预算无法容纳单个Unicode字符')
            parts.append({'text':text[start:end],'start':start,'end':end,'token_count':size})
            if end==len(text):break
            next_start=end;used=0
            while next_start>start+1 and used+len(text[next_start-1].encode())<=overlap:
                next_start-=1;used+=len(text[next_start].encode())
            start=next_start
        return parts

    def embed(self,texts,task):
        from . import models,store
        # UTF-8 bytes are a conservative bound. Only the few larger inputs
        # need a real tokenizer request; never let the API silently truncate.
        for value in texts:
            if len(value.encode())<=2048:continue
            store.execute('CREATE TABLE IF NOT EXISTS embedding_token_counts(model TEXT,input_key TEXT,tokens INTEGER NOT NULL,PRIMARY KEY(model,input_key))')
            key=hashlib.sha256(value.encode()).hexdigest()
            saved=store.one('SELECT tokens FROM embedding_token_counts WHERE model=? AND input_key=?',(self.model_id,key))
            if saved:tokens=saved['tokens']
            else:
                counted,_=models.request(self.model_id,'countTokens',{'contents':[{'parts':[{'text':value}]}]},self.run_id,len(value.encode())+128)
                tokens=counted.get('totalTokens')
                if type(tokens) is not int or tokens<1:raise RetrievalUnavailable('上游未返回有效输入token数，拒绝可能截断的输入')
                store.execute('INSERT OR IGNORE INTO embedding_token_counts VALUES(?,?,?)',(self.model_id,key,tokens))
            if tokens>2048:raise RetrievalUnavailable('输入超过云模型2048 tokens限制，需独立重切分，原索引保持不变')
        response=models.embed(texts,self.run_id,task=task)
        vectors=np.asarray(response['vectors'],dtype=np.float32)
        if vectors.shape!=(len(texts),768) or not np.isfinite(vectors).all():
            raise RetrievalUnavailable('云向量数量、维度或数值非法')
        norms=np.linalg.norm(vectors,axis=1,keepdims=True)
        if (norms<=0).any():raise RetrievalUnavailable('云向量返回零长度')
        return {**response,'vectors':(vectors/norms).tolist(),'fingerprint':fingerprint(self.descriptor())}


def configured_provider(kind=None,run_id=None):
    kind=kind or os.getenv('RT_EMBED_PROVIDER','gemini')
    if kind=='gemini':return GeminiRetrievalProvider(run_id)
    if kind in ('local','auto'):return LocalRetrievalProvider()
    raise RetrievalUnavailable('索引提供方必须为gemini或local')


class LocalRetrievalProvider:
    def __init__(self, model_id=None,base=None):
        self.model_id=model_id or os.getenv('RT_LOCAL_EMBED_MODEL','nvidia/Nemotron-3.5-Embed-8B-BF16')
        self.base=(base or os.getenv('RT_RETRIEVAL_BASE','')).rstrip('/')
        parsed=urlsplit(self.base)
        if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise RetrievalUnavailable('本地检索服务尚未配置')
        if parsed.scheme!='https' and not (parsed.scheme=='http' and parsed.hostname in ('127.0.0.1','localhost','::1')):
            raise RetrievalUnavailable('跨机器检索服务需要 HTTPS 或本地 SSH 隧道')
        token_path=os.getenv('RT_RETRIEVAL_TOKEN_FILE','')
        if not token_path:
            raise RetrievalUnavailable('本地检索服务鉴权未配置')
        path=Path(token_path)
        if path.stat().st_mode & 0o077:
            raise RetrievalUnavailable('检索鉴权文件权限必须为600')
        self.token=path.read_text().strip()
        if len(self.token)<24:
            raise RetrievalUnavailable('检索服务鉴权值无效')
        self._descriptor=None
        self._client=httpx.Client(base_url=self.base,headers={'Authorization':'Bearer '+self.token},trust_env=False,
                                  follow_redirects=False,timeout=httpx.Timeout(min(1800,max(30,int(os.getenv('RT_RETRIEVAL_TIMEOUT','900')))),connect=10))

    def close(self):
        client=getattr(self,'_client',None)
        if client:client.close()

    def __del__(self):
        self.close()

    def _call(self, route, body=None,timeout=None):
        try:
            options={'timeout':timeout} if timeout else {}
            response=self._client.get(route,**options) if body is None else self._client.post(route,json=body,**options)
            if response.status_code!=200:
                raise RetrievalUnavailable('本地检索服务暂不可用 HTTP '+str(response.status_code))
            if len(response.content)>32*1024**2:
                raise RetrievalUnavailable('检索服务响应超过限制')
            return response.json()
        except (httpx.HTTPError,OSError,json.JSONDecodeError):
            raise RetrievalUnavailable('本地检索服务连接失败，未提交云端替代请求') from None

    def descriptor(self):
        if self._descriptor is None:
            result=self._call('/manifest')
            choices=result.get('models',[])
            self._descriptor=next((d for d in choices if d.get('model_id')==self.model_id),None)
            if self._descriptor is None:
                raise RetrievalUnavailable('本地服务未提供所选模型')
            fingerprint(self._descriptor)
        return dict(self._descriptor)

    def split(self,text,max_tokens,overlap=32):
        return self.split_many([text],max_tokens,overlap)[0]

    def split_many(self,texts,max_tokens,overlap=32):
        response=self._call('/tokenize',{'model_id':self.model_id,'revision':self.descriptor()['revision'],
                                       'texts':texts,'task':'document','split':{'max_tokens':max_tokens,'overlap':overlap}})
        if response.get('fingerprint')!=fingerprint(self.descriptor()):
            raise RetrievalUnavailable('切分时tokenizer指纹发生变化')
        items=response.get('items',[])
        if len(items)!=len(texts):raise RetrievalUnavailable('tokenizer 批次数量不一致')
        result=[]
        for text,item in zip(texts,items):
            parts=[{**p,'start':p['char_start'],'end':p['char_end']} for p in item.get('chunks',[])]
            self._check_parts(text,parts,max_tokens)
            result.append(parts)
        return result

    @staticmethod
    def _check_parts(text,parts,max_tokens):
        if not parts or len(parts)>10000:
            raise RetrievalUnavailable('tokenizer 未返回完整切分')
        covered=0
        for part in parts:
            start,end=part.get('start'),part.get('end')
            if not isinstance(start,int) or not isinstance(end,int) or not 0<=start<end<=len(text) or start>covered:
                raise RetrievalUnavailable('tokenizer 返回的原文跨度不完整')
            if part.get('text')!=text[start:end] or not 1<=part.get('token_count',0)<=max_tokens:
                raise RetrievalUnavailable('tokenizer 返回非法片段或静默截断')
            covered=max(covered,end)
        if covered!=len(text):
            raise RetrievalUnavailable('tokenizer 遗漏尾部原文')

    def embed(self,texts,task):
        desc=self.descriptor()
        response=self._call('/embed',{'model_id':self.model_id,'revision':desc['revision'],'texts':texts,'task':'query' if task=='RETRIEVAL_QUERY' else 'document'},timeout=min(60,max(5,int(os.getenv('RT_RETRIEVAL_QUERY_TIMEOUT','15')))) if task=='RETRIEVAL_QUERY' else None)
        if response.get('fingerprint')!=fingerprint(desc):
            raise RetrievalUnavailable('模型实际指纹与索引不匹配')
        vectors=np.asarray(response.get('vectors',[]),dtype=np.float32)
        if vectors.shape!=(len(texts),desc['dimension']) or not np.isfinite(vectors).all():
            raise RetrievalUnavailable('embedding数量、维度或数值非法')
        norms=np.linalg.norm(vectors,axis=1)
        if (norms<=0).any() or (desc['normalization']=='l2' and not np.allclose(norms,1,atol=.005)):
            raise RetrievalUnavailable('embedding 未按声明归一化')
        return response

    def rerank(self,query,documents):
        model_id=os.getenv('RT_LOCAL_RERANK_MODEL','nvidia/Nemotron-3.5-Rerank-8B-BF16')
        provider=LocalRetrievalProvider(model_id,os.getenv('RT_RERANK_BASE')) if os.getenv('RT_RERANK_BASE') else self
        manifest=provider._call('/manifest')
        desc=next((d for d in manifest['models'] if d['model_id']==model_id),None)
        if not desc:raise RetrievalUnavailable('所选重排模型尚未部署')
        expected=fingerprint(desc)
        response=provider._call('/rerank',{'model_id':model_id,'revision':desc['revision'],'query':query,'documents':documents},timeout=min(120,max(5,int(os.getenv('RT_RERANK_TIMEOUT','45')))))
        if response.get('fingerprint')!=expected:
            raise RetrievalUnavailable('重排模型实际指纹发生变化')
        response={**response,'model_id':model_id,'revision':desc['revision']}
        scores=np.asarray(response.get('scores',[]),dtype=np.float32)
        if scores.shape!=(len(documents),) or not np.isfinite(scores).all() or not response.get('revision'):
            raise RetrievalUnavailable('重排响应缺少实际模型版本或分数')
        return response


class GeminiEmbeddingProvider:
    """Legacy provider kept separate; never encodes local index queries."""
    def embed(self,texts,task,run_id=None):
        from .models import embed
        return embed(texts,run_id,task=task)
