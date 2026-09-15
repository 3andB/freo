"""Measure real Liquidsoap output rather than only inspecting gain metadata."""
import json
import subprocess


def measure(path):
    result=subprocess.run(['ffmpeg','-nostdin','-hide_banner','-i',str(path),'-af',
        'loudnorm=I=-16:TP=-1.5:print_format=json','-f','null','-'],capture_output=True,text=True,check=True,timeout=30)
    return json.loads(result.stderr[result.stderr.rfind('{'):])


def test_liquidsoap_normalizes_different_song_levels(tmp_path):
    for number,volume in enumerate((1,2)):
        source=tmp_path/f'source{number}.mp3';output=tmp_path/f'normalized{number}.wav'
        subprocess.run(['ffmpeg','-nostdin','-hide_banner','-loglevel','error','-f','lavfi','-i',
            'sine=frequency=440:duration=4','-af',f'volume={volume}','-codec:a','libmp3lame',str(source)],check=True,timeout=20)
        before=measure(source);gain=-16-float(before['input_i'])
        uri=f'annotate:freo_gain="{gain:.3f} dB":{source}'
        script=tmp_path/f'gain{number}.liq'
        script.write_text('settings.init.allow_root := true\nsettings.log.stdout := true\nsettings.log.level := 2\n'
            's = request.once(request.create('+json.dumps(uri)+'))\n'
            's = amplify(override="freo_gain", 1.0, s)\n'
            's = limit(attack=1.0, release=100.0, threshold=-1.5, ratio=100.0, gain=0.0, s)\n'
            'output.file(%wav, '+json.dumps(str(output))+', fallible=true, on_stop=fun () -> shutdown(), s)\n')
        subprocess.run(['liquidsoap',str(script)],check=True,capture_output=True,text=True,timeout=40)
        after=measure(output)
        assert abs(float(after['input_i'])+16)<.5
        assert float(after['input_tp'])<=-1.5
