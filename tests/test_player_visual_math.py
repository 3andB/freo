"""Tempo acceptance: periodic transients, jitter, sustained sound and reset."""
from pathlib import Path
import shutil
import subprocess
import pytest


def test_music_tempo_estimates_and_sustained_sound_has_no_fake_beat():
    node=shutil.which('node')
    if not node:pytest.skip('Node is unavailable')
    source=Path(__file__).resolve().parents[1]/'app/static/player_scenes.js'
    script=r'''const fs=require('fs'),vm=require('vm'),assert=require('assert');
      global.window={};vm.runInThisContext(fs.readFileSync(process.argv[1],'utf8'));
      for(const bpm of [90,120,150,180]){
        const tracker=window.FreoVisualScenes.createTempo();let result;
        for(let i=0;i<600;i++){
          const t=i/30,a=new Uint8Array(512),envelope=Math.exp(-(t%(60/bpm))*25);
          for(let bin=1;bin<30;bin++)a[bin]=Math.round(200*envelope);
          result=tracker.sample(a,1/30,true);
        }
        assert(Math.abs(result.bpm-bpm)<5,JSON.stringify({bpm,result}));
        assert(result.onsets>10);
        assert.strictEqual(tracker.sample(new Uint8Array(512),1/30,false).bpm,0);
      }
      const tracker=window.FreoVisualScenes.createTempo();let result;
      for(let i=0;i<600;i++)result=tracker.sample(new Uint8Array(512).fill(180),1/30,true);
      assert.strictEqual(result.bpm,0);assert.strictEqual(result.onsets,0);
    '''
    subprocess.run([node,'-e',script,str(source)],check=True,capture_output=True,text=True)
