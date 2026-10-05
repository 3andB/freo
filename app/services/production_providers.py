"""Bounded server-only provider adapters. Never persist or relay provider error bodies."""
import json
import re
import socket
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit, quote
from urllib.request import Request, build_opener, HTTPRedirectHandler
from cryptography.fernet import Fernet, InvalidToken
from flask import current_app
from app.extensions import db
from app.models import ProviderCredential
from app.models.production import now

PROVIDERS = ('elevenlabs', 'openai', 'anthropic', 'xai')
HOSTS = {'elevenlabs': 'https://api.elevenlabs.io', 'openai': 'https://api.openai.com',
         'anthropic': 'https://api.anthropic.com', 'xai': 'https://api.x.ai'}
LIMIT = 64 * 1024 * 1024


class ProviderError(ValueError):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def cipher():
    try:
        return Fernet(current_app.config.get('FREO_PROVIDER_ENCRYPTION_KEY', '').encode())
    except (ValueError, TypeError):
        raise ProviderError('Provider encryption is not configured. Ask the installation administrator.') from None


def credential(provider, revision=None):
    if provider not in PROVIDERS:
        raise ProviderError('Choose a configured provider.')
    row = db.session.get(ProviderCredential, provider)
    if not row or not row.ciphertext:
        raise ProviderError('This provider is not configured.')
    if revision is not None and revision != row.revision:
        raise ProviderError('Provider credentials changed. Submit a new generation.')
    try:
        return cipher().decrypt(row.ciphertext.encode()).decode(), row
    except InvalidToken:
        raise ProviderError('Provider credentials cannot be decrypted. Ask the installation administrator.') from None


def save_credential(provider, key, model, revision, remove=False):
    if provider not in PROVIDERS or len(model) > 120 or not re.fullmatch(r'[\w.:-]*', model):
        raise ValueError('Choose a valid provider and model ID.')
    row = ProviderCredential.query.filter_by(provider=provider).with_for_update().first()
    if int(revision) != (row.revision if row else 0):
        raise ValueError('Provider settings changed. Refresh and try again.')
    row = row or ProviderCredential(provider=provider, revision=0)
    if remove:
        row.ciphertext = None
    elif key:
        if not 8 <= len(key) <= 1024 or any(ch.isspace() for ch in key):
            raise ValueError('Enter a valid API key.')
        row.ciphertext = cipher().encrypt(key.encode()).decode()
    row.model = model
    row.revision += 1
    row.updated_at = now()
    db.session.add(row)
    return row


def exchange(url, headers, payload=None, *, binary=False, timeout=180):
    request = Request(url, data=json.dumps(payload).encode() if payload is not None else None,
                      headers=dict(headers, **({'Content-Type':'application/json'} if payload is not None else {})))
    try:
        started = time.monotonic()
        with build_opener(NoRedirect()).open(request, timeout=timeout) as response:
            chunks, size = [], 0
            while True:
                chunk = response.read(65536)
                if not chunk:
                    break
                size += len(chunk)
                if size > LIMIT or time.monotonic() - started > timeout:
                    raise ProviderError('Provider response exceeded the size or time limit. Check usage before retrying.')
                chunks.append(chunk)
            raw = b''.join(chunks)
            usage = {key: response.headers[key][:160] for key in
                     ('request-id','x-request-id','character-cost','song-id') if response.headers.get(key)}
            if binary:
                return raw, usage
            result = json.loads(raw)
            if not isinstance(result, dict):
                raise ValueError()
            return result, usage
    except HTTPError as error:
        message = {401:'Provider API key is invalid.', 403:'This account or API key does not permit this capability.',
                   404:'The selected voice or model is unavailable.', 429:'Provider quota or rate limit reached. Check usage before retrying.',
                   422:'The provider rejected these generation settings.', 400:'The provider rejected these generation settings.'}.get(error.code,
                   'Provider request failed. Check usage before retrying.')
        raise ProviderError(message) from None
    except (URLError, socket.timeout, TimeoutError, OSError):
        raise ProviderError('Provider connection failed or timed out. Check usage before retrying; no automatic retry was made.') from None
    except (ValueError, UnicodeError) as error:
        if isinstance(error, ProviderError):
            raise
        raise ProviderError('Provider returned an invalid response.') from None


def call(provider, path, payload=None, *, binary=False, revision=None):
    key, _ = credential(provider, revision)
    headers = {'xi-api-key': key} if provider == 'elevenlabs' else (
        {'x-api-key':key, 'anthropic-version':'2023-06-01'} if provider == 'anthropic' else {'Authorization':'Bearer ' + key})
    return exchange(HOSTS[provider] + path, headers, payload, binary=binary, timeout=180 if payload is not None else 15)


def test_connection(provider):
    value, _ = call(provider, '/v2/voices?page_size=1' if provider == 'elevenlabs' else '/v1/models')
    return bool(value)


def voices(search='', cursor=''):
    query = {'page_size':30, 'search':search[:120]}
    if cursor:
        query['next_page_token'] = cursor[:500]
    data, _ = call('elevenlabs', '/v2/voices?' + urlencode(query))
    try:
        return {'voices':[{'id':v['voice_id'], 'name':v.get('name','Voice'), 'preview':bool(v.get('preview_url'))}
                          for v in data.get('voices', [])[:30]], 'cursor':data.get('next_page_token')}
    except (TypeError,KeyError):
        raise ProviderError('Provider returned an invalid voice list.') from None


def models():
    # This endpoint returns an array, unlike other provider JSON responses.
    raw, _ = call('elevenlabs','/v1/models', binary=True)
    try:
        rows = json.loads(raw)
        return [{'id':r['model_id'], 'name':r.get('name',r['model_id']),
                 'style':bool(r.get('can_use_style')), 'similarity':r['model_id'] != 'eleven_v3'}
                for r in rows if r.get('can_do_text_to_speech')]
    except (ValueError, TypeError, KeyError):
        raise ProviderError('Provider returned an invalid model list.') from None


def voice_preview(identifier):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,120}',identifier):
        raise ProviderError('Choose a valid voice.')
    data, _ = call('elevenlabs','/v1/voices/' + quote(identifier, safe=''))
    url = data.get('preview_url','')
    parts = urlsplit(url)
    # Provider-owned public samples only. Never forward credentials to sample hosts.
    if (parts.scheme != 'https' or parts.username or parts.password or parts.port not in (None,443)
        or not ((parts.hostname == 'storage.googleapis.com' and parts.path.startswith(('/eleven-public/','/eleven-public-prod/')))
                or parts.hostname in ('api.elevenlabs.io','cdn.elevenlabs.io'))):
        raise ProviderError('No supported preview is available for this voice.')
    return exchange(url, {}, binary=True, timeout=15)[0]


def write_script(provider, model, prompt, seconds, revision):
    instruction = ('Write only the spoken radio station imaging script, with no headings or production notes. '
                   'Preserve supplied station names and quoted wording. Aim for approximately ' + str(seconds) + ' seconds. '
                   'Do not invent factual claims, contact details, or promotions.')
    if provider == 'anthropic':
        payload = dict(model=model, max_tokens=1024, system=instruction, messages=[dict(role='user', content=prompt)])
        data, usage = call(provider, '/v1/messages', payload, revision=revision)
        text = '\n'.join(x.get('text','') for x in data.get('content',[]) if x.get('type') == 'text')
    else:
        data, usage = call(provider, '/v1/responses', dict(model=model, instructions=instruction,
            input=prompt, max_output_tokens=2048, store=False), revision=revision)
        text = '\n'.join(part.get('text','') for item in data.get('output',[]) if item.get('type') == 'message'
                         for part in item.get('content',[]) if part.get('type') == 'output_text')
    if not text.strip() or len(text) > 5000:
        raise ProviderError('No usable script was returned. Edit your prompt and try again.')
    # Only numeric usage is retained; no arbitrary provider response payloads.
    usage.update({k:v for k,v in data.get('usage',{}).items() if isinstance(v,(int,float)) and not isinstance(v,bool)})
    return text.strip(), usage
