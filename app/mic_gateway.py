"""Loopback-only WebRTC receiver. Public requests pass through Flask authorization.

One ephemeral session per station; no recordings. Liquidsoap consumes bounded PCM
queues over HTTP. Losing the browser lease closes the source, independently of
Flask and the automation worker. Run with python -m app.mic_gateway.
"""
import asyncio
import contextlib
import json
import math
import os
import re
import struct
import time
import uuid
from dataclasses import dataclass, field

from aiohttp import web
from aiortc import RTCConfiguration, RTCIceServer, RTCPeerConnection, RTCSessionDescription
from av import AudioResampler

SLUG = re.compile(r'[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?')
WAV_HEADER = struct.pack('<4sI4s4sIHHIIHH4sI', b'RIFF', 0xffffffff, b'WAVE',
                         b'fmt ', 16, 1, 2, 48000, 192000, 4, 16, b'data', 0xffffffff)


@dataclass
class Session:
    owner: int
    pc: RTCPeerConnection
    token: str = field(default_factory=lambda: uuid.uuid4().hex)
    heartbeat: float = field(default_factory=time.monotonic)
    last_audio: float = 0
    desired: str = 'READY'
    fade: float = 3
    engine: dict = field(default_factory=dict)
    observed: float = 0
    subscribers: set = field(default_factory=set)
    tasks: set = field(default_factory=set)
    closed: bool = False

    @property
    def healthy(self):
        return not self.closed and time.monotonic() - self.last_audio < 2 and self.pc.connectionState == 'connected'

    def status(self):
        fresh = time.monotonic() - self.observed < 5
        engine = self.engine if fresh else {}
        return dict(token=self.token, owner=self.owner, healthy=self.healthy,
                    desired=self.desired, fade=self.fade, engine=engine,
                    ready=self.healthy and engine.get('ready', False) and engine.get('token') == self.token,
                    phase=engine.get('phase', 'CONNECTING'))

    async def close(self):
        self.closed = True
        for task in self.tasks:
            task.cancel()
        for queue in self.subscribers:
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(None)
        await self.pc.close()
        await asyncio.gather(*self.tasks, return_exceptions=True)


async def receive(session, track):
    resampler = AudioResampler(format='s16', layout='stereo', rate=48000)
    try:
        while not session.closed:
            frame = await track.recv()
            for pcm in resampler.resample(frame):
                data = bytes(pcm.planes[0])[:pcm.samples * 4]
                session.last_audio = time.monotonic()
                for queue in session.subscribers:
                    # Never accumulate delayed speech if the consumer falls behind.
                    if queue.full():
                        queue.get_nowait()
                    queue.put_nowait(data)
    except asyncio.CancelledError:
        raise
    except Exception:
        session.last_audio = 0


def create_gateway():
    app = web.Application(client_max_size=128 * 1024)
    sessions = {}
    app['sessions'] = sessions
    ice = json.loads(os.environ.get('FREO_MIC_ICE_SERVERS', '[]'))

    def slug_for(request):
        slug = request.match_info['slug']
        if not SLUG.fullmatch(slug):
            raise web.HTTPBadRequest()
        return slug

    async def control(request):
        slug = slug_for(request)
        data = await request.json()
        action = data.get('action')
        session = sessions.get(slug)
        if action == 'status':
            return web.json_response(session.status() if session else {'phase': 'OFF AIR'})
        if action == 'worker':
            if session and data.get('token') == session.token:
                previous_phase = session.engine.get('phase')
                session.engine = data.get('engine', {})
                if session.desired == 'END' and session.engine.get('phase') == 'READY' and previous_phase == 'RETURNING':
                    session.desired = 'READY'
                session.observed = time.monotonic()
            return web.json_response(session.status() if session else {})
        if action == 'offer':
            if session:
                raise web.HTTPConflict(text='Another microphone session owns this station. Disconnect it first.')
            if not isinstance(data.get('owner'), int) or not isinstance(data.get('sdp'), str) or len(data['sdp']) > 65536:
                raise web.HTTPBadRequest(text='Invalid microphone offer')
            pc = RTCPeerConnection(RTCConfiguration(iceServers=[RTCIceServer(**item) for item in ice]))
            session = Session(data['owner'], pc)
            sessions[slug] = session  # Reserve before awaiting signaling.

            @pc.on('track')
            def on_track(track):
                if track.kind == 'audio':
                    task = asyncio.create_task(receive(session, track))
                    session.tasks.add(task)
                else:
                    track.stop()
            try:
                await pc.setRemoteDescription(RTCSessionDescription(sdp=data['sdp'], type='offer'))
                if len(pc.getReceivers()) != 1 or pc.getReceivers()[0].track.kind != 'audio':
                    raise ValueError('One audio input is required')
                await pc.setLocalDescription(await pc.createAnswer())
            except Exception:
                if sessions.get(slug) is session:
                    sessions.pop(slug)
                await session.close()
                raise web.HTTPBadRequest(text='Could not connect microphone audio')
            session.heartbeat = time.monotonic()
            return web.json_response(dict(token=session.token, sdp=pc.localDescription.sdp, type='answer'))
        if not session or data.get('owner') != session.owner or data.get('token') != session.token:
            raise web.HTTPConflict(text='This microphone session is no longer yours. Reconnect the input.')
        session.heartbeat = time.monotonic()
        if action in ('go', 'end'):
            try:
                fade = float(data.get('fade', 3))
            except (ValueError, TypeError):
                raise web.HTTPBadRequest(text='Invalid fade length')
            if not math.isfinite(fade) or not 0 <= fade <= 10:
                raise web.HTTPBadRequest(text='Fade length must be between 0 and 10 seconds')
            status = session.status()
            if action == 'go' and (not status['ready'] or status['phase'] != 'READY'):
                raise web.HTTPConflict(text='Wait until the station confirms MIC READY')
            session.fade = fade
            session.desired = 'LIVE' if action == 'go' else 'END'
        elif action == 'disconnect':
            sessions.pop(slug)
            await session.close()
        elif action != 'heartbeat':
            raise web.HTTPBadRequest(text='Unknown microphone action')
        return web.json_response(session.status())

    async def audio(request):
        session = sessions.get(slug_for(request))
        if not session or request.query.get('token') != session.token or not session.healthy:
            raise web.HTTPNotFound()
        if session.subscribers:
            raise web.HTTPConflict()
        queue = asyncio.Queue(maxsize=10)
        session.subscribers.add(queue)
        response = web.StreamResponse(headers={'Content-Type': 'audio/wav', 'Cache-Control': 'no-store'})
        try:
            await response.prepare(request)
            await response.write(WAV_HEADER)
            while session.healthy:
                data = await asyncio.wait_for(queue.get(), timeout=2)
                if data is None:
                    break
                await asyncio.wait_for(response.write(data), timeout=2)
        except (TimeoutError, ConnectionError):
            pass
        finally:
            session.subscribers.discard(queue)
        return response

    async def lifecycle(app):
        async def reap():
            while True:
                await asyncio.sleep(1)
                for slug, session in list(sessions.items()):
                    if time.monotonic() - session.heartbeat > 10:
                        sessions.pop(slug)
                        await session.close()
        task = asyncio.create_task(reap())
        yield
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        await asyncio.gather(*(session.close() for session in sessions.values()))

    app.router.add_post('/control/{slug}', control)
    app.router.add_get('/audio/{slug}', audio)
    app.cleanup_ctx.append(lifecycle)
    return app


if __name__ == '__main__':
    from dotenv import load_dotenv
    load_dotenv(os.environ.get('FREO_ENV_FILE', '.env'))
    web.run_app(create_gateway(), host='127.0.0.1', port=8091, access_log=None)
