"""Public installation assets; no authenticated response is cached offline."""
from flask import Blueprint, Response, jsonify, send_from_directory, current_app, request
studio_pwa = Blueprint('studio_pwa', __name__)


@studio_pwa.get('/admin/studio.webmanifest')
def manifest():
    response = jsonify(id='/admin/', name='Freo Studio', short_name='Freo', start_url='/admin/',
        scope='/admin/', display='standalone', background_color='#101f29', theme_color='#101f29',
        icons=[dict(src=f'/static/studio-{size}.png', sizes=f'{size}x{size}', type='image/png', purpose='any maskable') for size in (192,512)])
    response.mimetype = 'application/manifest+json'
    return response


@studio_pwa.get('/admin/studio-sw.js')
def worker():
    response = send_from_directory(current_app.static_folder, 'studio-sw.js', mimetype='application/javascript')
    response.headers['Cache-Control'] = 'no-cache'
    return response


@studio_pwa.get('/admin/offline')
def offline():
    return Response('''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="theme-color" content="#101f29"><title>Freo Studio · Offline</title><style>body{font:1.1rem system-ui;background:#101f29;color:#fff;max-width:32rem;margin:12vh auto;padding:1.5rem}a{color:#89dfd2}</style><h1>Freo Studio</h1><p>You’re offline. Connect to the internet to check the station and use its controls.</p><p>This screen does not indicate whether the station is broadcasting.</p><a href="/admin/">Try again</a></html>''', mimetype='text/html')


@studio_pwa.after_app_request
def management_cache_policy(response):
    if request.path.startswith('/admin') and not (request.endpoint or '').startswith('studio_pwa.'):
        response.headers['Cache-Control'] = 'private, no-store'
    return response
