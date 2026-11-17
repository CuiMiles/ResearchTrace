import gzip

from starlette.applications import Starlette
from starlette.testclient import TestClient

from services.api.static_assets import IMMUTABLE, PrecompressedStatic


def client(tmp_path, immutable=True):
    raw = b'export const value = 1;\n' * 200
    (tmp_path / 'index-abc.js').write_bytes(raw)
    (tmp_path / 'index-abc.js.gz').write_bytes(gzip.compress(raw))
    (tmp_path / 'plain.css').write_bytes(b'body{}' * 300)
    app = Starlette()
    app.mount('/assets', PrecompressedStatic(directory=tmp_path, immutable=immutable))
    return TestClient(app), raw


def test_serves_gzip_sibling_with_original_type(tmp_path):
    c, raw = client(tmp_path)
    r = c.get('/assets/index-abc.js', headers={'Accept-Encoding': 'gzip'})
    assert r.status_code == 200 and r.content == raw  # client transparently inflates
    assert r.headers['content-encoding'] == 'gzip'
    assert r.headers['content-type'].startswith('text/javascript')
    assert r.headers['vary'] == 'Accept-Encoding' and r.headers['cache-control'] == IMMUTABLE


def test_identity_when_gzip_not_accepted_or_refused(tmp_path):
    c, raw = client(tmp_path)
    for header in ('identity', 'gzip;q=0'):
        r = c.get('/assets/index-abc.js', headers={'Accept-Encoding': header})
        assert 'content-encoding' not in r.headers and r.content == raw


def test_missing_sibling_missing_file_and_revalidation(tmp_path):
    c, _ = client(tmp_path, immutable=False)
    r = c.get('/assets/plain.css', headers={'Accept-Encoding': 'gzip'})
    assert 'content-encoding' not in r.headers and r.headers['cache-control'] == 'no-cache'
    etag = r.headers['etag']
    assert c.get('/assets/plain.css', headers={'If-None-Match': etag}).status_code == 304
    assert c.get('/assets/nope.js', headers={'Accept-Encoding': 'gzip'}).status_code == 404
    assert c.get('/assets/../x', headers={'Accept-Encoding': 'gzip'}).status_code == 404
