"""Bound the wire body before multipart spooling, including chunked requests."""
from fastapi import HTTPException
from starlette.responses import JSONResponse


class UploadBodyLimit:
    def __init__(self,app,max_bytes=256*1024**2):
        self.app,self.max_bytes=app,max_bytes

    async def __call__(self,scope,receive,send):
        if scope['type']!='http' or scope.get('path')!='/api/v1/documents' or scope.get('method')!='POST':
            return await self.app(scope,receive,send)
        raw=dict(scope.get('headers',[])).get(b'content-length')
        if raw is not None:
            try:
                length=int(raw)
                if length<0:raise ValueError
            except ValueError:
                return await JSONResponse({'detail':'Content-Length无效'},status_code=400)(scope,receive,send)
            if length>self.max_bytes:
                return await JSONResponse({'detail':'上传请求总量超过256MiB'},status_code=413)(scope,receive,send)
        count=0
        async def bounded_receive():
            nonlocal count
            message=await receive()
            if message['type']=='http.request':
                count+=len(message.get('body',b''))
                if count>self.max_bytes:
                    raise HTTPException(413,'上传请求总量超过256MiB')
            return message
        return await self.app(scope,bounded_receive,send)
