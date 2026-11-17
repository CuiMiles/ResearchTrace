"""Static frontend files: precompressed gzip siblings and long-lived caching.

The build writes ``name.ext.gz`` next to each text asset. Serving those instead of
the raw files cuts the JS a reader needs from ~2.5 MB to ~0.7 MB, which matters on
slow cross-border links. Hashed ``/assets`` never change, so browsers may keep them;
unhashed vendor files are revalidated through their ETag.
"""
import mimetypes
import os
from pathlib import Path

from starlette.datastructures import Headers
from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

IMMUTABLE = 'public, max-age=31536000, immutable'
REVALIDATE = 'no-cache'


def _accepts_gzip(scope: Scope) -> bool:
    value = Headers(scope=scope).get('accept-encoding', '')
    for part in value.split(','):
        name, _, params = part.strip().partition(';')
        if name.strip().lower() == 'gzip' and params.replace(' ', '') not in ('q=0', 'q=0.0'):
            return True
    return False


class PrecompressedStatic(StaticFiles):
    def __init__(self, *, directory: Path, immutable: bool, **kwargs):
        super().__init__(directory=directory, check_dir=False, **kwargs)
        self.cache_control = IMMUTABLE if immutable else REVALIDATE

    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await super().get_response(path, scope)
        if response.status_code not in (200, 304):
            return response
        if response.status_code == 200 and _accepts_gzip(scope) and not path.endswith('.gz'):
            full_path, stat_result = self.lookup_path(path + '.gz')
            if stat_result is not None and os.path.isfile(full_path):
                compressed = self.file_response(full_path, stat_result, scope)
                media_type = mimetypes.guess_type(path)[0] or response.headers.get('content-type')
                if media_type:
                    if media_type.startswith('text/') and 'charset' not in media_type:
                        media_type += '; charset=utf-8'
                    compressed.headers['content-type'] = media_type
                if compressed.status_code == 200:
                    compressed.headers['content-encoding'] = 'gzip'
                response = compressed
        response.headers['vary'] = 'Accept-Encoding'
        response.headers['cache-control'] = self.cache_control
        return response
