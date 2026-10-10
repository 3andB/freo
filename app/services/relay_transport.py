"""Bounded HTTP transport guard hosted by the existing automation worker.

No decoding, buffering policy, reconnect loop or source selection lives here.
Liquidsoap requests each connection. Pin DNS, preserve TLS identity, reject
redirects/playlists and pass ICY bytes unchanged to Liquidsoap's decoder.
"""
import http.client
import ipaddress
import secrets
import socket
import ssl
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

AUDIO_TYPES = {'audio/mpeg', 'audio/mp3', 'audio/aac', 'audio/aacp', 'audio/ogg',
               'application/ogg', 'audio/flac', 'audio/x-flac', 'audio/wav', 'audio/x-wav'}


def validate_url(value):
    if not isinstance(value, str) or len(value) > 2048 or any(ord(c) < 33 or ord(c) > 126 for c in value):
        raise ValueError('Use an HTTP(S) stream URL of at most 2048 ASCII characters, without spaces.')
    try:
        parsed = urlsplit(value)
        if (parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username is not None
                or parsed.password is not None or parsed.fragment or '\\' in value or not 1 <= (parsed.port if parsed.port is not None else 80) <= 65535):
            raise ValueError()
        # Reject ambiguous host spellings; IP literals and ordinary DNS only.
        if '%' in parsed.hostname:
            raise ValueError()
    except ValueError:
        raise ValueError('Use a direct HTTP(S) audio URL without credentials or a fragment.') from None
    return parsed


def allowed_addresses(parsed, networks):
    allow = [ipaddress.ip_network(value.strip()) for value in networks.split(',') if value.strip()]
    addresses = list(dict.fromkeys(info[4][0] for info in socket.getaddrinfo(
        parsed.hostname, parsed.port or (443 if parsed.scheme == 'https' else 80), type=socket.SOCK_STREAM)))
    if not addresses:
        raise ValueError('Upstream hostname has no addresses.')
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        if ip.is_link_local or ip.is_multicast or ip.is_unspecified or (not ip.is_global and not any(ip in net for net in allow)):
            raise ValueError('Upstream address is not allowed by the operator network policy.')
    return addresses


def open_upstream(url, networks):
    parsed = validate_url(url)
    addresses = allowed_addresses(parsed, networks)
    port = parsed.port or (443 if parsed.scheme == 'https' else 80)
    connection = http.client.HTTPConnection(parsed.hostname, port, timeout=10)
    # Connect to a validated literal, never perform a second hostname lookup.
    connection.sock = socket.create_connection((addresses[0], port), timeout=10)
    response = None
    try:
        if parsed.scheme == 'https':
            connection.sock = ssl.create_default_context().wrap_socket(connection.sock, server_hostname=parsed.hostname)
        connection._relay_socket = connection.sock
        connection.request('GET', (parsed.path or '/') + ('?' + parsed.query if parsed.query else ''),
                           headers={'Icy-MetaData': '1', 'User-Agent': 'Freo Relay/1', 'Accept-Encoding': 'identity'})
        response = connection.getresponse()
        content_type = response.getheader('Content-Type', '').split(';')[0].strip().lower()
        if response.status != 200 or content_type not in AUDIO_TYPES:
            raise ValueError('Upstream must return direct audio with HTTP 200; redirects and playlists are unsupported.')
        return connection, response, content_type
    except Exception:
        if response is not None:
            response.close()
        connection.close()
        raise


class RelayTransport:
    def __init__(self, port=8092, networks=''):
        self.networks = networks
        self.entries = {}
        self.lock = threading.Lock()
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def setup(self):
                super().setup()
                self.connection.settimeout(10)

            def log_message(self, *args):
                pass  # Neither capability URLs nor upstream errors belong in logs.

            def do_GET(self):
                token = self.path.removeprefix('/')
                with owner.lock:
                    entry = owner.entries.get(token)
                    if entry is None or entry['busy']:
                        self.send_error(404)
                        return
                    entry['busy'] = True
                connection = response = None
                try:
                    connection, response, content_type = open_upstream(entry['url'], owner.networks)
                    with owner.lock:
                        if owner.entries.get(token) is not entry:
                            return
                        entry['connection'] = connection
                    self.send_response(200)
                    self.send_header('Content-Type', content_type)
                    interval = response.getheader('icy-metaint', '')
                    if interval.isdecimal() and 0 < int(interval) <= 1048576:
                        self.send_header('icy-metaint', interval)
                    self.send_header('Connection', 'close')
                    self.end_headers()
                    while True:
                        with owner.lock:
                            if owner.entries.get(token) is not entry:
                                break
                        data = response.read1(8192)
                        if not data:
                            break
                        self.wfile.write(data)
                except (OSError, ValueError, http.client.HTTPException):
                    # Closing the HTTP body makes the input fallible in Liquidsoap.
                    pass
                finally:
                    if response is not None:
                        response.close()
                    if connection:
                        connection.close()
                    with owner.lock:
                        entry['busy'] = False
                        entry['connection'] = None
                    self.close_connection = True

        self.server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def configure(self, station_id, url):
        with self.lock:
            for key, entry in list(self.entries.items()):
                if entry['station_id'] == station_id:
                    del self.entries[key]
                    connection = entry.get('connection')
                    upstream_socket = getattr(connection, '_relay_socket', None)
                    if upstream_socket is not None:
                        try:
                            upstream_socket.shutdown(socket.SHUT_RDWR)
                        except OSError:
                            pass
            if not url:
                return ''
            token = secrets.token_hex(32)
            self.entries[token] = dict(station_id=station_id, url=url, busy=False, connection=None)
        return f'http://127.0.0.1:{self.server.server_port}/{token}'

    def close(self):
        for station_id in {entry['station_id'] for entry in list(self.entries.values())}:
            self.configure(station_id, '')
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
