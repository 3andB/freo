"""Check local candidate player assets against an actual stream without deployment.

Requires Playwright and its browsers; use --url for a disposable staging player.
"""
from playwright.sync_api import sync_playwright
from pathlib import Path
import json,re,argparse,shutil
from urllib.parse import urlparse
parser=argparse.ArgumentParser(description="Read-only live-stream check with local candidate player assets.")
parser.add_argument("--url",required=True)
parser.add_argument("--engines",default="chromium,webkit")
args=parser.parse_args()
root=Path(__file__).resolve().parents[1];modes=['fractal','spectrum','waveform','particles','ambient','aurora','ethereal','space']
with sync_playwright() as p:
 for engine in args.engines.split(','):
  options={}
  if engine=='chromium':
   options['args']=['--no-sandbox']
   if executable:=shutil.which('chromium-browser'):options['executable_path']=executable
  browser=getattr(p,engine).launch(headless=True,**options)
  for device in ({'viewport':{'width':1440,'height':1000}},p.devices['Pixel 7' if engine=='chromium' else 'iPhone 13']):
   context=browser.new_context(**device,reduced_motion='reduce')
   def document(route):
    response=route.fetch();body=response.text()
    if 'id="volume-help"' not in body:
     body=body.replace('</label></div>\n<audio id="station-audio"','</label><small id="volume-help" hidden>Use your device volume buttons.</small></div>\n<audio id="station-audio"')
    body=re.sub(r'(<select id="visual-mode".*?</select>)',lambda m:m[0].replace('</select>',''.join(f'<option value="{mode}">{mode.title()}</option>' for mode in modes[-3:] if f'value="{mode}"' not in m[0])+'</select>'),body)
    route.fulfill(response=response,body=body)
   context.route('**'+urlparse(args.url).path,document)
   context.route('**/static/player*.js?*',lambda route:route.fulfill(content_type='application/javascript',body=(root/'app/static'/route.request.url.split('/')[-1].split('?')[0]).read_text()))
   context.route('**/static/player.css?*',lambda route:route.fulfill(content_type='text/css',body=(root/'app/static/player.css').read_text()))
   context.route('**/static/freo.css?*',lambda route:route.fulfill(content_type='text/css',body=(root/'app/static/freo.css').read_text()))
   context.add_init_script('''localStorage.setItem('freo-motion','reduced');window.probe={peak:0,samples:0,frames:0,contexts:[]};
     const Native=AudioContext;window.AudioContext=class extends Native{constructor(){super();probe.contexts.push(this)}};
     const sample=AnalyserNode.prototype.getByteFrequencyData;AnalyserNode.prototype.getByteFrequencyData=function(a){sample.call(this,a);probe.samples++;probe.peak=Math.max(probe.peak,...a)};
     const clear=CanvasRenderingContext2D.prototype.clearRect;CanvasRenderingContext2D.prototype.clearRect=function(...args){probe.frames++;return clear.apply(this,args)};''')
   page=context.new_page();errors=[];streams=[]
   page.on('pageerror',lambda e:errors.append(str(e)))
   page.on('request',lambda r:streams.append(r.url) if '/listen/' in r.url else None)
   page.goto(args.url,wait_until='domcontentloaded')
   page.locator('#play-button').click();page.wait_for_function('() => document.getElementById("station-audio").currentTime>1',timeout=30000)
   if device.get('is_mobile'):assert page.locator('#volume').is_visible() == (engine=='chromium')
   page.locator('#visualizer-open').click();page.wait_for_function('() => probe.peak>0',timeout=15000)
   initial=len(streams)
   for mode in modes:
    page.locator('#visual-mode').select_option(mode)
    page.wait_for_function('(mode) => document.getElementById("player-visual").dataset.mode===mode',arg=mode)
    # Real radio may contain silence; require real sampling and continued frames,
    # not fabricated movement during every arbitrarily chosen time window.
    before=page.evaluate('() => ({frames:probe.frames,samples:probe.samples})')
    page.wait_for_function('(before) => probe.frames>before.frames && probe.samples>before.samples',arg=before,timeout=20000)
    assert page.locator('#player-visual').get_attribute('data-analysis')=='live'
   for mode in modes*3:page.locator('#visual-mode').select_option(mode)
   assert page.evaluate('() => probe.contexts.filter(c=>c.state!=="closed").length')==1
   page.emulate_media(reduced_motion='reduce')
   count=page.evaluate('() => probe.frames');page.wait_for_function('(count) => probe.frames>count',arg=count)
   assert 'Reduced motion' not in page.locator('#visual-status').inner_text()
   page.emulate_media(reduced_motion='no-preference');page.wait_for_function('(count) => probe.frames>count',arg=count)
   page.locator('#visualizer-close').click();page.wait_for_timeout(300)
   count=page.evaluate('() => probe.frames');page.wait_for_timeout(300);assert page.evaluate('() => probe.frames')<=count+1
   assert len(streams)==initial
   page.locator('#play-button').click();page.locator('#play-button').click();page.wait_for_function('() => document.getElementById("station-audio").currentTime>1',timeout=30000)
   page.locator('#visualizer-open').click();page.wait_for_function('() => document.getElementById("player-visual").dataset.analysis==="live"')
   page.evaluate('() => {CanvasRenderingContext2D.prototype.clearRect=()=>{throw Error("test renderer failure")};}')
   page.wait_for_function('() => document.getElementById("visual-status").textContent.includes("Visualization unavailable")')
   page.locator('#visualizer-close').click();before=page.evaluate('() => document.getElementById("station-audio").currentTime');page.wait_for_timeout(600)
   assert page.evaluate('() => document.getElementById("station-audio").currentTime')>before
   assert not errors,errors
   print(json.dumps({'engine':engine,'mobile':device.get('is_mobile',False),'peak':page.evaluate('() => probe.peak'),'modes':modes,'errors':errors,'passed':True}),flush=True)
   context.close()
  browser.close()
