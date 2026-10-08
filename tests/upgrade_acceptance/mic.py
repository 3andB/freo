import asyncio,aiohttp,array,math,json,re,sys,subprocess
from pathlib import Path
from aiortc import RTCPeerConnection,RTCConfiguration,RTCSessionDescription,AudioStreamTrack
assert subprocess.check_output(['hostname'],text=True).strip()=='Freo-v1-Test-1'
E=Path('/root/freo-upgrade-tests')/sys.argv[1];E.mkdir(exist_ok=True)
base='http://209.38.64.12';slug='acceptance'
class Tone(AudioStreamTrack):
 async def recv(self):
  f=await super().recv();f.planes[0].update(array.array('h',[int(6000*math.sin(2*math.pi*1000*(f.pts+i)/f.sample_rate)) for i in range(f.samples)]).tobytes());return f
async def main():
 pc=RTCPeerConnection(RTCConfiguration(iceServers=[]));pc.addTrack(Tone())
 async with aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True)) as session:
  async with session.get(base+'/admin/login') as r:body=await r.text()
  csrf=re.search(r'name="csrf" value="([^"]+)"',body).group(1)
  async with session.post(base+'/admin/login',data={'csrf':csrf,'email':'acceptance@example.test','password':'private native acceptance passphrase'}) as r:
   assert '/admin/login' not in str(r.url),await r.text()
  async with session.get(base+'/admin/stations/'+slug+'/live') as r:body=await r.text()
  csrf=re.search(r'data-csrf="([^"]+)"',body).group(1)
  token=''
  async def post(action,**data):
   async with session.post(base+'/admin/api/stations/'+slug+'/live-mic/'+action,data=dict(csrf=csrf,token=token,**data)) as r:
    value=await r.json();assert r.status==200,(action,r.status,value);return value
  try:
   await pc.setLocalDescription(await pc.createOffer());answer=await post('offer',sdp=pc.localDescription.sdp);token=answer['token']
   await pc.setRemoteDescription(RTCSessionDescription(sdp=answer['sdp'],type=answer['type']))
   for _ in range(100):
    state=await post('heartbeat')
    if state.get('healthy') and state.get('engine',{}).get('ready'):break
    await asyncio.sleep(.2)
   else:raise AssertionError(('microphone never ready',state))
   await post('go',fade='1')
   for _ in range(100):
    state=await post('heartbeat')
    if state.get('phase')=='LIVE' or state.get('engine',{}).get('phase')=='LIVE':break
    await asyncio.sleep(.2)
   else:raise AssertionError(('microphone never live',state))
   async def keepalive():
    while True:
     await post('heartbeat');await asyncio.sleep(.5)
   keeper=asyncio.create_task(keepalive())
   path=E/'mic-program.f32'
   proc=await asyncio.create_subprocess_exec('ffmpeg','-nostdin','-v','error','-i','http://127.0.0.1:8001/'+slug,'-t','20','-ac','1','-ar','8000','-f','f32le','-y',str(path))
   assert await asyncio.wait_for(proc.wait(),45)==0
   keeper.cancel()
   try:await keeper
   except asyncio.CancelledError:pass
   values=array.array('f',path.read_bytes())[-24000:];rms=math.sqrt(sum(v*v for v in values)/len(values))
   frequency=sum(a<0<=b for a,b in zip(values,values[1:]))*8000/len(values)
   assert rms>.02 and 950<frequency<1050,(rms,frequency)
   await pc.close()
   for _ in range(100):
    async with session.get(base+'/admin/api/stations/'+slug+'/live-status') as r:status=await r.json()
    if status.get('mode')=='AUTO':break
    await asyncio.sleep(.3)
   else:raise AssertionError(('did not return to auto',status.get('mode')))
   result={'status':'passed','transport':'real installed WebRTC gateway, Liquidsoap and Icecast','source':'generated 1000 Hz microphone','decoded_rms':rms,'decoded_frequency_hz':frequency,'disconnect_return':'AUTO'}
   (E/'microphone.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
  finally:await pc.close()
asyncio.run(main())
