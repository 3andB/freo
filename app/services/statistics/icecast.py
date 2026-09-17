"""Private, bounded, credential-isolated Icecast 2.5 observations."""
import base64
import json
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, build_opener, ProxyHandler
import xml.etree.ElementTree as ET


class Icecast:
    def __init__(self, credential_file):
        secret = json.loads(Path(credential_file).read_text())
        self.authorization = 'Basic ' + base64.b64encode(('admin:' + secret['admin']).encode()).decode()
        self.opener = build_opener(ProxyHandler({}))

    def read(self, endpoint):
        request = Request('http://127.0.0.1:8001' + endpoint, headers={'Authorization': self.authorization})
        with self.opener.open(request, timeout=2) as response:
            body = response.read(5 * 1024 * 1024 + 1)
        if len(body) > 5 * 1024 * 1024 or b'<!DOCTYPE' in body:
            raise ValueError('Invalid stats response')
        return ET.fromstring(body)

    def observe(self, stations):
        try:
            root = self.read('/admin/stats')
            if root.tag != 'icestats':
                raise ValueError('Unexpected stats response')
            epoch = root.findtext('instance_uuid') or root.findtext('server_start_iso8601') or root.findtext('server_start')
            mounts = {node.get('mount'): node for node in root.findall('source')}
        except (OSError, ValueError, ET.ParseError):
            return {s.id: dict(online=None, listeners=None, clients=None) for s in stations}
        output = {}
        for station in stations:
            node = mounts.get('/' + station.slug)
            if node is None:
                output[station.id] = dict(online=False, listeners=0, clients=[], epoch=epoch)
                continue
            def number(name):
                try:
                    value = int(node.findtext(name))
                    return value if value >= 0 else None
                except (ValueError, TypeError):
                    return None
            row = dict(online=True, listeners=number('listeners'), bytes=number('total_bytes_sent'),
                epoch=epoch, source_epoch=node.findtext('instance_uuid') or node.findtext('stream_start_iso8601') or node.findtext('stream_start'), clients=None)
            try:
                clients = self.read('/admin/listclients?mount=' + quote('/' + station.slug, safe=''))
                row['clients'] = [dict(id=n.findtext('id') or n.findtext('ID') or n.get('id'),
                    ip=n.findtext('ip') or n.findtext('IP'),
                    agent=n.findtext('useragent') or n.findtext('UserAgent') or '')
                    for n in clients.findall('.//listener')]
            except (OSError, ValueError, ET.ParseError):
                pass
            output[station.id] = row
        return output
