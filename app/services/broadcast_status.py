"""Bounded worker-only Icecast polling; UI requests never wait on Icecast."""
import json
import time
from urllib.request import ProxyHandler, build_opener
from urllib.parse import urlsplit

_opener=build_opener(ProxyHandler({}))
_checked=0.0
_sources=None


def observation(slug):
    global _checked,_sources
    now=time.monotonic()
    if not _checked or now-_checked>=5:
        _checked=now
        try:
            with _opener.open('http://127.0.0.1:8001/status-json.xsl',timeout=1) as response:
                sources=json.load(response)['icestats'].get('source',[])
            if isinstance(sources,dict):sources=[sources]
            _sources={urlsplit(row.get('listenurl','')).path:row for row in sources}
        except (OSError,ValueError,KeyError,TypeError):
            _sources=None
    if _sources is None:return None,None
    source=_sources.get('/'+slug)
    if source is None:return False,0
    try:
        listeners=int(source['listeners'])
        return True,listeners if listeners>=0 else None
    except (KeyError,ValueError,TypeError):return True,None
