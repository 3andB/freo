"""Bounded audio evidence and timing/resource telemetry for endurance runs."""
import json
import re
import subprocess
import time

from tests.system_harness import stop_process


class SoakProbe:
    def __init__(self, stack, *, collect_issues=False):
        self.stack = stack
        self.collect_issues = collect_issues
        self.issues = {}
        self.started = time.monotonic()
        self.last_program = self.started
        self.next_resources = self.started
        self.next_save = self.started
        self.next_console = self.started
        self.browser_position = None
        self.browser_progress_at = self.started
        self.audio_log = stack.evidence / 'audio-probe.log'
        self.log = self.audio_log.open('w')
        self.audio_offset = 0
        self.engine_offset = (stack.root/'engine.log').stat().st_size
        self.metrics = dict(samples=0, elapsed_seconds=0, maximum_clock_lag_seconds=0,
                            max_rss_kib={}, audio_silence=[], resource_samples=[], issues=[])
        # Retain only the last two minutes of decoded, mono audio (about 2 MB).
        self.process = subprocess.Popen(['ffmpeg', '-nostdin', '-nostats', '-v', 'info', '-y',
            '-i', stack.icecast_url + '/' + stack.slug, '-map', '0:a:0',
            '-af', 'silencedetect=noise=-55dB:d=3', '-ac', '1', '-ar', '8000',
            # Flush the inner WAV muxer: its normal buffering can otherwise
            # make an active 16 KB/s decoder look stalled for over ten seconds.
            '-f', 'segment', '-segment_format_options', 'flush_packets=1',
            '-segment_time', '30', '-segment_wrap', '4',
            str(stack.evidence/'audio-%d.wav')], stdout=self.log, stderr=self.log)

    def check(self, condition, key, message, **details):
        """Keep a diagnostic shift running without turning findings into passes."""
        if condition:
            return
        if not self.collect_issues:
            raise AssertionError(message)
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        if key not in self.issues:
            self.issues[key] = dict(key=key, message=message, first_seen=now,
                                   first_elapsed=round(time.monotonic()-self.started, 2), count=0)
        issue = self.issues[key]
        issue.update(last_seen=now, details=details, count=issue['count']+1)
        self.metrics['issues'] = list(self.issues.values())
        with (self.stack.evidence/'programme-issues.jsonl').open('a') as output:
            output.write(json.dumps(issue)+'\n')

    @staticmethod
    def new_text(path, offset):
        with path.open() as source:
            source.seek(offset)
            text = source.read()
            return text, source.tell()

    @staticmethod
    def browser_rss(driver_pid):
        """Sum Chromium descendants, rather than mistaking driver RSS for the browser."""
        from pathlib import Path
        def children(pid):
            found = set()
            # ChromeDriver launches Chromium from a server thread, not its main
            # thread. Linux records children against the thread that created them.
            for path in Path(f'/proc/{pid}/task').glob('*/children'):
                try:
                    found.update(int(value) for value in path.read_text().split())
                except FileNotFoundError:
                    pass
            return list(found)
        pending = children(driver_pid)
        total = 0
        seen = set()
        while pending:
            pid = pending.pop()
            if pid in seen:
                continue
            seen.add(pid)
            pending.extend(children(pid))
            try:
                match = re.search(r'VmRSS:\s+(\d+)', Path(f'/proc/{pid}/status').read_text())
                if match:
                    total += int(match[1])
            except FileNotFoundError:
                pass  # Renderers can exit during navigation.
        return total

    def sample(self):
        self.metrics['elapsed_seconds'] = round(time.monotonic()-self.started, 2)
        self.metrics['samples'] += 1
        assert self.process.poll() is None, 'Continuous stream decoder exited'
        assert self.stack.engine.poll() is None, 'Liquidsoap exited'
        if time.monotonic() >= self.next_console:
            from tests.browser_evidence import drain_browser_console
            errors = drain_browser_console(self.stack)
            self.next_console = time.monotonic()+5
            self.check(not errors, 'browser_errors', 'Uncaught browser JavaScript error', errors=errors)
        monitor = self.stack.driver.execute_script('return {paused:FreoMonitor.audio.paused, position:FreoMonitor.audio.currentTime}')
        assert not monitor['paused'], 'Persistent browser monitor unexpectedly stopped'
        if self.browser_position is None or abs(monitor['position']-self.browser_position) > .01:
            self.browser_position = monitor['position']
            self.browser_progress_at = time.monotonic()
        self.metrics['browser_audio_seconds'] = round(monitor['position'], 2)
        assert time.monotonic()-self.browser_progress_at < 10, 'Browser monitor stopped advancing'
        recordings = list(self.stack.evidence.glob('audio-*.wav'))
        write_age = (time.time()-max(path.stat().st_mtime for path in recordings)
                     if recordings else time.monotonic()-self.started)
        self.metrics['last_audio_write_age_seconds'] = round(write_age, 2)
        assert write_age < 10, 'Stream decoder is alive but has stopped producing audio'
        audio, self.audio_offset = self.new_text(self.audio_log, self.audio_offset)
        silence_starts = re.findall(r'silence_start: ([\d.]+)', audio)
        self.metrics['audio_silence'].extend(silence_starts)
        for start in silence_starts:
            # The normal ring is overwritten after two minutes. Preserve a
            # bounded set of incident clips for later comparison with the music.
            if self.collect_issues and len(self.metrics['audio_silence']) <= 24:
                import shutil
                incident = self.stack.evidence/('silence-'+start)
                incident.mkdir(exist_ok=True)
                for recording in recordings:
                    shutil.copyfile(recording, incident/recording.name)
            self.check(False, 'silence:'+start, 'Decoded stream contained at least three seconds of silence',
                       stream_seconds=float(start))
        self.metrics.setdefault('silence_end_observations', []).extend(
            dict(stream_seconds=float(end), duration=float(duration))
            for end, duration in re.findall(r'silence_end: ([\d.]+) \| silence_duration: ([\d.]+)', audio))
        engine, self.engine_offset = self.new_text(self.stack.root/'engine.log', self.engine_offset)
        lag = [float(value) for value in re.findall(r'We must catchup ([\d.]+) seconds', engine)]
        self.metrics['maximum_clock_lag_seconds'] = max([self.metrics['maximum_clock_lag_seconds']] + lag)
        from app.models import LiveQueueSnapshot
        from app.services.playout_queue import mixer_state
        from datetime import datetime, timezone
        def observation():
            snapshot = LiveQueueSnapshot.query.first()
            seen = snapshot.observed_at.replace(tzinfo=snapshot.observed_at.tzinfo or timezone.utc)
            assert (datetime.now(timezone.utc)-seen).total_seconds() < 10, 'Worker observation became stale'
            assert not snapshot.error_code, snapshot.error_code
            return mixer_state(self.stack.slug)
        mixer = self.stack.query(observation)
        if not mixer['tone']:
            self.last_program = time.monotonic()
        fallback_seconds = time.monotonic()-self.last_program
        self.metrics['maximum_fallback_seconds'] = max(self.metrics.get('maximum_fallback_seconds', 0), round(fallback_seconds, 2))
        self.check(fallback_seconds < 5, 'fallback', 'Unexpected sustained fallback tone instead of scheduled music',
                   duration=round(fallback_seconds, 2), mixer=mixer)
        if time.monotonic() >= self.next_resources:
            self.next_resources = time.monotonic()+60
            from pathlib import Path
            sample = dict(at=self.metrics['elapsed_seconds'])
            for name, pid in [('engine', self.stack.engine.pid), ('test_worker_web', __import__('os').getpid()),
                              ('chromedriver', self.stack.driver.service.process.pid), ('decoder', self.process.pid)]:
                text = Path(f'/proc/{pid}/status').read_text()
                rss = int(re.search(r'VmRSS:\s+(\d+)', text)[1])
                sample[name] = rss
                self.metrics['max_rss_kib'][name] = max(self.metrics['max_rss_kib'].get(name, 0), rss)
            performance = {row['name']: row['value'] for row in
                self.stack.driver.execute_cdp_cmd('Performance.getMetrics', {})['metrics']}
            sample['browser'] = {key: performance[key] for key in
                ('JSHeapUsedSize', 'Nodes', 'Documents', 'JSEventListeners') if key in performance}
            sample['browser_tree_rss_kib'] = self.browser_rss(self.stack.driver.service.process.pid)
            assert sample['browser_tree_rss_kib'] > 0, 'Unable to observe Chromium process memory'
            self.metrics['max_rss_kib']['browser_tree'] = max(
                self.metrics['max_rss_kib'].get('browser_tree', 0), sample['browser_tree_rss_kib'])
            # Append the full history once per minute; keep the live JSON small
            # instead of rewriting days of samples every half second.
            with (self.stack.evidence/'resource-samples.jsonl').open('a') as history:
                history.write(json.dumps(sample)+'\n')
            self.metrics['resource_samples'].append(sample)
            self.metrics['resource_samples'] = self.metrics['resource_samples'][-60:]
        if time.monotonic() >= self.next_save:
            self.save()
            self.next_save = time.monotonic()+2
        self.check(self.metrics['maximum_clock_lag_seconds'] <= 10, 'clock_lag',
                   'Engine clock fell over ten seconds behind real time', seconds=self.metrics['maximum_clock_lag_seconds'])

    def save(self):
        target = self.stack.evidence/'soak-result.json'
        temporary = target.with_suffix('.tmp')
        temporary.write_text(json.dumps(self.metrics, indent=2))
        temporary.replace(target)

    def close(self):
        stop_process(self.process)
        self.log.close()
        self.save()
