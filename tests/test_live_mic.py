"""Microphone authorization, ownership, readiness, and real audio handover."""
import asyncio
import math
import os
import time
from array import array
from pathlib import Path
from types import SimpleNamespace

import pytest
from tests.test_web import app


def operator(client):
    from tests.auth import authenticate
    authenticate(client, 1, 'mic-csrf')


def test_mic_requires_login_csrf_and_station_access(app, monkeypatch):
    client = app.test_client()
    url = '/admin/api/stations/test-station/live-mic/go'
    assert client.post(url).status_code == 302
    operator(client)
    assert client.post(url).status_code == 400
    monkeypatch.setattr('app.routes.admin_live.can_control_playout', lambda *args: False)
    assert client.post(url, data={'csrf': 'mic-csrf'}).status_code == 403


def test_status_never_exposes_another_session_token(app, monkeypatch):
    client = app.test_client(); operator(client)
    monkeypatch.setattr('app.routes.live_mic.gateway', lambda *a, **k: {
        'token': 'private', 'owner': 2, 'engine': {'token': 'private'}, 'phase': 'LIVE'})
    response = client.post('/admin/api/stations/test-station/live-mic/status', data={'csrf': 'mic-csrf'})
    assert response.status_code == 200
    assert 'private' not in response.text and response.json['owned'] is False


def test_selecting_mic_is_not_a_playout_mode(app):
    from app.services.live_assist import set_mode
    from app.models import Station, AdminUser
    with app.app_context():
        station = Station.query.filter_by(slug='test-station').one()
        with pytest.raises(ValueError):
            set_mode(station, AdminUser.query.first(), 'LIVE_MIC')
        assert station.automation.operator_mode == 'AUTO'


def test_worker_only_takes_ready_matching_healthy_session(monkeypatch):
    from app.services.live_mic import sync_live_mic
    monkeypatch.setenv('FREO_LIVE_MIC', '1')
    calls = []
    token = 'a' * 32
    engine = [f'{token}|READY|true']
    def command(slug, value):
        calls.append(value)
        return engine[0] if value == 'freo_mic.state' else 'OK'
    monkeypatch.setattr('app.services.playout_queue._command', command)
    session = dict(token=token, desired='LIVE', healthy=False, fade=3)
    monkeypatch.setattr('app.services.live_mic.gateway', lambda *a, **k: session)
    station = SimpleNamespace(slug='test-station')
    assert sync_live_mic(station) is False
    assert not any('take' in command for command in calls)
    session['healthy'] = True
    assert sync_live_mic(station) is True
    assert calls[-1] == f'freo_mic.take {token} 3.000'
    engine[0] = f'{token}|LIVE|true'; calls.clear()
    assert sync_live_mic(station) is True
    assert not any('take' in command for command in calls)
    session['token'] = 'b' * 32; calls.clear()
    assert sync_live_mic(station) is True
    assert not any('prepare' in command for command in calls)


def test_gateway_web_rtc_ownership_and_engine_readiness():
    pytest.importorskip('aiortc')
    asyncio.run(gateway_roundtrip())


async def gateway_roundtrip(engine_dir=None, station=None, graceful=False, feed_mode='DJ_BOOTH'):
    from aiohttp.test_utils import TestServer, TestClient
    from aiortc import RTCPeerConnection, RTCConfiguration, RTCSessionDescription, AudioStreamTrack
    from app.mic_gateway import create_gateway

    class ToneTrack(AudioStreamTrack):
        async def recv(self):
            frame = await super().recv()
            samples = array('h', [int(6000 * math.sin(2*math.pi*880*(frame.pts+i)/frame.sample_rate)) for i in range(frame.samples)])
            frame.planes[0].update(samples.tobytes())
            return frame

    gateway_app = create_gateway()
    client = TestClient(TestServer(gateway_app))
    await client.start_server()
    pc = RTCPeerConnection(RTCConfiguration(iceServers=[]))
    pc.addTrack(ToneTrack())
    proc = None
    token = None
    async def post(action, **data):
        response = await client.post('/control/test-station', json={'action': action, **data})
        return response
    try:
        # Invalid signaling releases the reserved owner.
        assert (await post('offer', owner=1, sdp='invalid')).status == 400
        await pc.setLocalDescription(await pc.createOffer())
        result = await post('offer', owner=1, sdp=pc.localDescription.sdp)
        assert result.status == 200
        answer = await result.json(); token = answer['token']
        assert (await post('offer', owner=2, sdp=pc.localDescription.sdp)).status == 409
        await pc.setRemoteDescription(RTCSessionDescription(sdp=answer['sdp'], type=answer['type']))
        for _ in range(100):
            state = await (await post('heartbeat', owner=1, token=token)).json()
            if state['healthy']: break
            await asyncio.sleep(.05)
        assert state['healthy']
        assert (await post('go', owner=1, token=token)).status == 409
        assert (await post('heartbeat', owner=2, token=token)).status == 409
        assert (await post('heartbeat', owner=1, token='stale')).status == 409
        assert (await post('go', owner=1, token=token, fade='nan')).status == 400
        if engine_dir is None:
            assert (await client.get('/audio/test-station?token=stale')).status == 404
            response = await client.get('/audio/test-station?token='+token)
            header = await response.content.readexactly(44)
            assert header.startswith(b'RIFF')
            pcm = await response.content.readexactly(3840)
            assert any(pcm)
            response.close()
            await post('worker', token=token, engine={'token':token,'phase':'READY','ready':True})
            assert (await post('go', owner=1, token=token, fade=1)).status == 200
            # Browser lease expiry is enforced even with healthy RTP.
            gateway_app['sessions']['test-station'].heartbeat = time.monotonic()-11
            await asyncio.sleep(1.2)
            assert 'test-station' not in gateway_app['sessions']
            return

        from app.services.station_runtime import render_liquidsoap
        source = render_liquidsoap(station, 'test-password')
        source = source.replace('/run/freo/playout/test-station', str(engine_dir))
        source = source.replace('http://127.0.0.1:8091/', str(client.make_url('/')))
        source = 'settings.init.allow_root := true\n' + source[:source.index('output.icecast(')]
        source += 'server.register(namespace="freo_test", "elapsed", fun (_) -> string.float(queue.elapsed()))\n'
        source += f'output.file(%wav, "{engine_dir}/output.wav", radio)\n'
        config = engine_dir/'engine.liq'; config.write_text(source)
        with (engine_dir/'engine.log').open('w') as log:
            proc = await asyncio.create_subprocess_exec('liquidsoap', str(config), stdout=log, stderr=log)
        async def command(value):
            reader, writer = await asyncio.open_unix_connection(str(engine_dir/'control.sock'))
            writer.write((value+'\n').encode()); await writer.drain()
            data = await asyncio.wait_for(reader.readuntil(b'END\r\n'), 3)
            writer.close(); await writer.wait_closed()
            return data.decode().split('END')[0].strip()
        # Liquidsoap parses the complete station graph before opening its socket.
        # Shared/slow acceptance hosts can need longer than 40 seconds to start.
        for _ in range(1200):
            await post('heartbeat', owner=1, token=token)
            if (engine_dir/'control.sock').exists(): break
            if proc.returncode is not None:
                pytest.fail((engine_dir/'engine.log').read_text()[-4000:])
            await asyncio.sleep(.1)
        assert (engine_dir/'control.sock').exists(), (engine_dir/'engine.log').read_text()[-4000:]
        song = engine_dir/'song.wav'
        generator = await asyncio.create_subprocess_exec('ffmpeg','-v','error','-f','lavfi','-i',
            'sine=frequency=440:duration=60','-y',str(song))
        assert await generator.wait() == 0
        assert await command('freo_mixer.mode '+feed_mode) == 'OK'
        bus='freo_a' if feed_mode=='DJ_BOOTH' else 'freo_queue'
        assert (await command(bus+'.push annotate:freo_decision=1234:'+str(song))).isdigit()
        await asyncio.sleep(.2)
        if feed_mode=='DJ_BOOTH':
            assert await command('freo_deck.take_a 0.000') == 'OK'
        async def position():
            if feed_mode=='AUTO':
                return float(await command('freo_test.elapsed'))
            return float((await command('freo_mixer.state')).split('|')[7])
        assert 'Decoding failed' not in (engine_dir/'engine.log').read_text(), 'Idle microphone attempted HTTP decoding'
        assert await command('freo_mic.prepare '+token) == 'OK'
        async def observed():
            await post('heartbeat', owner=1, token=token)
            await command('freo_mic.lease '+token)
            value = await command('freo_mic.state')
            return value.split('|')
        for _ in range(120):
            fields = await observed()
            if fields[2] == 'true': break
            await asyncio.sleep(.1)
        assert fields[2] == 'true', (engine_dir/'engine.log').read_text()[-4000:]
        # A READY microphone expiring while off air must not force DJ into AUTO.
        # Keep the browser session alive while deliberately withholding the engine lease.
        until=asyncio.get_running_loop().time()+6.5
        while asyncio.get_running_loop().time()<until:
            await post('heartbeat',owner=1,token=token)
            await asyncio.sleep(.1)
        assert (await command('freo_mic.state')).split('|')[1]=='OFF AIR'
        assert (await command('freo_mixer.state')).split('|')[0]==feed_mode
        assert await command('freo_mic.prepare '+token)=='OK'
        for _ in range(120):
            fields=await observed()
            if fields[2]=='true':break
            await asyncio.sleep(.1)
        assert fields[2]=='true'
        def voice_level(frequency=880):
            # Measure the received 880 Hz voice in the actual rendered WAV,
            # independently of engine control/state acknowledgements.
            raw = (engine_dir/'output.wav').read_bytes()
            if len(raw) < 40000:
                return 0.0
            samples = array('h'); samples.frombytes(raw[-35280:])
            mono = samples[::2]
            real = sum(value*math.cos(2*math.pi*frequency*n/44100) for n,value in enumerate(mono))
            imag = sum(value*math.sin(2*math.pi*frequency*n/44100) for n,value in enumerate(mono))
            return 2*math.hypot(real,imag)/len(mono)/32768
        async def wait_voice(predicate):
            for _ in range(50):
                await observed()
                value = voice_level()
                if predicate(value):
                    return value
                await asyncio.sleep(.1)
            pytest.fail(f'Unexpected rendered voice level: {value}')
        # Merely connecting and preparing does not attenuate the existing feed.
        assert fields[1] == 'READY'
        await asyncio.sleep(.5)
        assert voice_level() < .01
        assert await command(f'freo_mic.take {"b"*32} 1.000') == 'ERROR microphone not ready'
        assert await command(f'freo_mic.take {token} 1.000') == 'OK'
        assert (await observed())[1] == 'FADING'
        for _ in range(30):
            fields = await observed()
            if fields[1] == 'LIVE': break
            await asyncio.sleep(.1)
        assert fields[1] == 'LIVE'
        await wait_voice(lambda level: level > .11)
        await asyncio.sleep(.5)
        baseline = voice_level()
        paused_at = await position()
        # Existing OVER and TAKEOVER carts must apply to microphone audio.
        cart_path = engine_dir/'cart.wav'
        generator = await asyncio.create_subprocess_exec('ffmpeg','-v','error','-f','lavfi','-i',
            'sine=frequency=1320:duration=2','-y',str(cart_path))
        assert await generator.wait() == 0
        assert await command('freo_mixer.cart_mode OVER') == 'OK'
        assert await command('freo_mixer.duck 0.500') == 'OK'
        assert (await command('freo_cart.push '+str(cart_path))).isdigit()
        await wait_voice(lambda level: baseline*.35 < level < baseline*.65)
        await wait_voice(lambda level: level > baseline*.9)
        assert await command('freo_mixer.cart_mode TAKEOVER') == 'OK'
        assert (await command('freo_cart.push '+str(cart_path))).isdigit()
        await wait_voice(lambda level: level < .01)
        await wait_voice(lambda level: level > baseline*.9)
        assert abs(await position()-paused_at) < .15
        assert await command(f'freo_mic.end {token} 0.300') == 'OK'
        await asyncio.sleep(.5)
        assert (await observed())[1] == 'READY'
        await wait_voice(lambda level: level < .01)
        assert await position() > paused_at+.2
        assert await command(f'freo_mic.take {token} 0.000') == 'OK'
        await asyncio.sleep(.2)
        assert (await observed())[1] == 'LIVE'
        if graceful:
            before_return = await position()
            await post('worker', token=token, engine={'token':token,'phase':'LIVE','ready':True})
            # Same authenticated gateway action sent by pagehide or a tab switch.
            # UDP/WebRTC closure can arrive before the HTTP departure beacon.
            await pc.close()
            await asyncio.sleep(.15)
            assert (await post('disconnect', owner=1, token=token)).status == 200
            for _ in range(100):
                fields = (await command('freo_mic.state')).split('|')
                session = await (await post('worker', token=token,
                    engine=dict(token=fields[0], phase=fields[1], ready=fields[2]=='true'))).json()
                if not session:
                    break
                if session['healthy']:
                    await command('freo_mic.lease '+token)
                if session['desired']=='END' and fields[1] in ('FADING','LIVE'):
                    await command(f'freo_mic.end {token} {session["fade"]:.3f}')
                await asyncio.sleep(.1)
            assert not session, 'Intentional departure did not finish returning'
            await asyncio.sleep(.5)
            assert voice_level() < .01, 'Microphone is still audible after leaving'
            mixer = (await command('freo_mixer.state')).split('|')
            assert mixer[0] == feed_mode, 'Page exit changed the interrupted program mode'
            assert await position() > before_return+.2, 'Interrupted song did not resume'
            assert voice_level(440) > .02, 'Restored music is not audible'
            return
        await pc.close()
        for _ in range(90):
            fields = (await command('freo_mic.state')).split('|')
            if fields[1] == 'FAILED': break
            await asyncio.sleep(.1)
        assert fields[1] == 'FAILED'
        assert (await command('freo_mixer.state')).startswith('AUTO|')
    finally:
        await pc.close()
        if proc and proc.returncode is None:
            proc.terminate()
            await asyncio.wait_for(proc.wait(), 8)
        await client.close()


@pytest.mark.skipif(os.environ.get('FREO_ENGINE_TEST') != '1', reason='Explicit isolated Liquidsoap/WebRTC integration')
def test_real_microphone_fade_return_and_disconnect(app, tmp_path, monkeypatch):
    pytest.importorskip('aiortc')
    from app.models import Station
    monkeypatch.setenv('FREO_LIVE_MIC','1')
    with app.app_context():
        station=Station.query.filter_by(slug='test-station').one()
        asyncio.run(gateway_roundtrip(tmp_path, station))


@pytest.mark.skipif(os.environ.get('FREO_ENGINE_TEST') != '1', reason='Explicit isolated Liquidsoap/WebRTC integration')
@pytest.mark.parametrize('feed_mode',['AUTO','DJ_BOOTH'])
def test_real_microphone_page_exit_restores_interrupted_feed(app, tmp_path, monkeypatch, feed_mode):
    pytest.importorskip('aiortc')
    from app.models import Station
    monkeypatch.setenv('FREO_LIVE_MIC','1')
    with app.app_context():
        station=Station.query.filter_by(slug='test-station').one()
        asyncio.run(gateway_roundtrip(tmp_path, station, graceful=True, feed_mode=feed_mode))


def test_gateway_departure_cuts_speech_and_waits_for_worker_return():
    pytest.importorskip('aiortc')
    asyncio.run(gateway_departure())


async def gateway_departure():
    from aiohttp.test_utils import TestServer, TestClient
    from app.mic_gateway import Session, create_gateway
    class Peer:
        connectionState='connected'
        async def close(self):
            self.connectionState='closed'
    gateway_app=create_gateway()
    client=TestClient(TestServer(gateway_app))
    await client.start_server()
    session=Session(1, Peer(), last_audio=time.monotonic(), desired='LIVE',
        engine=dict(phase='LIVE'), observed=time.monotonic())
    gateway_app['sessions']['test-station']=session
    queue=asyncio.Queue(maxsize=10)
    session.subscribers.add(queue)
    queue.put_nowait(b'stale speech')
    async def post(action, **data):
        return await client.post('/control/test-station', json=dict(action=action, **data))
    try:
        assert (await post('disconnect', owner=2, token=session.token)).status == 409
        assert not session.leaving_at and session.healthy
        assert (await post('disconnect', owner=1, token=session.token)).status == 200
        started=session.leaving_at
        assert session.pc.connectionState=='closed'
        assert await asyncio.wait_for(queue.get(), 1)==bytes(3840)
        assert session.healthy and session.desired=='END'
        assert (await post('go', owner=1, token=session.token)).status == 409
        assert (await post('disconnect', owner=1, token=session.token)).status == 200
        assert session.leaving_at==started  # Repeated beacons cannot extend the deadline.
        for phase in ('LIVE', 'RETURNING'):
            response=await post('worker', token=session.token,
                engine=dict(token=session.token, phase=phase, ready=True))
            assert (await response.json())['desired']=='END'
        response=await post('worker', token=session.token,
            engine=dict(token=session.token, phase='READY', ready=True))
        assert await response.json()=={}
        assert session.closed and not gateway_app['sessions']
        # A hung worker cannot retain a departing session indefinitely, even
        # if an old tab continues heartbeating.
        orphan=Session(1, Peer(), last_audio=time.monotonic(), desired='LIVE')
        gateway_app['sessions']['test-station']=orphan
        await orphan.leave()
        orphan.leaving_at=time.monotonic()-16
        assert not orphan.healthy
        await asyncio.sleep(1.2)
        assert orphan.closed and not gateway_app['sessions']
    finally:
        await client.close()


def test_mic_commands_reject_injected_tokens_and_invalid_fades():
    from app.services.playout_queue import _command
    for command in ('freo_mic.prepare arbitrary', 'freo_mic.take '+ 'a'*32 +' nan',
                    'freo_mic.take '+ 'a'*32 +' 11.000', 'freo_mic.lease '+ 'a'*32 +'\nfreo_queue.skip'):
        with pytest.raises(ValueError):
            _command('test-station', command)


def test_failed_session_can_only_be_replaced_by_new_token(monkeypatch):
    from app.services.live_mic import sync_live_mic
    monkeypatch.setenv('FREO_LIVE_MIC', '1')
    calls=[]
    def command(slug, value):
        calls.append(value)
        return 'a'*32+'|FAILED|true' if value=='freo_mic.state' else 'OK'
    monkeypatch.setattr('app.services.playout_queue._command', command)
    session=dict(token='a'*32,desired='LIVE',healthy=True,fade=0)
    monkeypatch.setattr('app.services.live_mic.gateway',lambda *a,**k:session)
    station=SimpleNamespace(slug='test-station',automation=SimpleNamespace(operator_mode='AUTO'))
    assert sync_live_mic(station) is False
    assert calls == ['freo_mic.state']
    session['token']='b'*32
    assert sync_live_mic(station) is False
    assert calls[-1]=='freo_mic.prepare '+'b'*32


def test_live_mic_blocks_transport_but_failed_session_releases_it(app, monkeypatch):
    client=app.test_client(); operator(client)
    monkeypatch.setenv('FREO_LIVE_MIC','1')
    state={'desired':'LIVE','phase':'LIVE'}
    monkeypatch.setattr('app.services.live_mic.gateway',lambda *a,**k:state)
    with app.test_request_context():
        from flask import url_for
        url=url_for('admin_live.action',slug='test-station',action='mode')
    response=client.post(url,data={'csrf':'mic-csrf','mode':'DJ_BOOTH'},headers={'Accept':'application/json'})
    assert response.status_code == 409
    state.update(desired='END', phase='READY', leaving=True)
    response=client.post(url,data={'csrf':'mic-csrf','mode':'DJ_BOOTH'},headers={'Accept':'application/json'})
    assert response.status_code == 409
    state.update(desired='LIVE', leaving=False)
    state['phase']='FAILED'
    response=client.post(url,data={'csrf':'mic-csrf','mode':'DJ_BOOTH'},headers={'Accept':'application/json'})
    assert response.status_code == 200
