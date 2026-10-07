"""Simulate pending Safari resume/interruption against a disposable live player.

Requires Playwright WebKit. This is not physical iPhone testing.
"""
from pathlib import Path
from playwright.sync_api import sync_playwright
import json,argparse
parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--url',required=True);parser.add_argument('--deployed',action='store_true');args=parser.parse_args()
root=Path(__file__).resolve().parents[1]
with sync_playwright() as p:
 browser=p.webkit.launch(headless=True);context=browser.new_context(**p.devices['iPhone 13'])
 def document(route):
  response=route.fetch();body=response.text()
  if 'id="visualizer-retry"' not in body:body=body.replace('<button id="visualizer-fullscreen"','<button type="button" id="visualizer-retry" hidden>Enable visuals</button><button id="visualizer-fullscreen"')
  route.fulfill(response=response,body=body)
 if not args.deployed:
  context.route(args.url,document)
  context.route('**/static/player*.js?*',lambda r:r.fulfill(content_type='application/javascript',body=(root/'app/static'/r.request.url.split('/')[-1].split('?')[0]).read_text()))
 context.add_init_script('''window.allowContext=false;window.resumeCalls=0;window.contexts=[];
  const Native=AudioContext,get=Object.getOwnPropertyDescriptor(BaseAudioContext.prototype,'state').get,resume=Native.prototype.resume;
  Object.defineProperty(Native.prototype,'state',{get(){return allowContext?get.call(this):'interrupted'}});
  Native.prototype.resume=function(){resumeCalls++;return allowContext?resume.call(this):new Promise(()=>{});};
  window.AudioContext=class extends Native {constructor(){super();contexts.push(this);}};''')
 page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
 page.goto(args.url,wait_until='domcontentloaded');page.locator('#play-button').click();page.wait_for_function('() => document.getElementById("station-audio").currentTime>1',timeout=30000)
 page.locator('#visualizer-open').click();page.locator('#visualizer-retry').wait_for(state='visible')
 page.evaluate("() => document.getElementById('visualizer-retry').addEventListener('click',()=>{allowContext=true},{capture:true,once:true})");page.locator('#visualizer-retry').click();page.wait_for_function('() => document.getElementById("player-visual").dataset.signal==="present"',timeout=20000)
 image=page.locator('#player-visual').evaluate('(c)=>c.toDataURL()');page.wait_for_function('(image)=>document.getElementById("player-visual").toDataURL()!==image',arg=image,timeout=20000)
 page.evaluate('() => {allowContext=false;contexts[0].dispatchEvent(new Event("statechange"));document.dispatchEvent(new Event("visibilitychange"));}');page.locator('#visualizer-retry').wait_for(state='visible')
 page.evaluate("() => document.getElementById('visualizer-retry').addEventListener('click',()=>{allowContext=true},{capture:true,once:true})");page.locator('#visualizer-retry').click();page.wait_for_function('() => document.getElementById("player-visual").dataset.signal==="present"',timeout=20000)
 assert page.evaluate('() => contexts.filter(c=>c.state!=="closed").length')==1
 assert page.evaluate('() => FreoAudioAnalysis.read(document.getElementById("station-audio")).sink.gain.value')==0
 page.locator('#visualizer-close').click();before=page.evaluate('() => document.getElementById("station-audio").currentTime');page.wait_for_timeout(700);assert page.evaluate('() => document.getElementById("station-audio").currentTime')>before
 assert page.evaluate('() => !FreoAudioAnalysis.read(document.getElementById("station-audio")).sink')
 assert not errors,errors
 print(json.dumps({'engine':'webkit','profile':'iPhone 13','simulated_interruption_recovery':True,'resume_calls':page.evaluate('() => resumeCalls'),'changed_pixels':True,'audio_continues':True,'errors':errors,'deployed':args.deployed}),flush=True)
 context.close();browser.close()
