# Freo 1.0.2-rc.1 — healthy muted microphone correction

Extended 1.0.1 acceptance found that a healthy muted live microphone caused the
complete-program blank detector to enable the station safety carrier after
three seconds. Microphone speech was muted, but listeners heard the carrier.
The deployed test measured carrier RMS 0.0776; an isolated full-program regression
reproduced it at RMS 0.05655. This behavior was not covered by the earlier
microphone tests, which measured only the microphone tone component.

Suppress the carrier only while the microphone is active, its input is ready
and its worker-renewed lease is valid. Report the same audible carrier state in
engine observations. Existing source-loss, expired-lease and ordinary empty
program fallback remain enforced. The schema, dependencies, APIs and recovery
implementation are unchanged from 1.0.1.

The new regression keeps actual RTP connected with zero-valued audio beyond the
blank timeout, measures the whole rendered program, checks on-air health and
carrier observations, then unmutes and verifies the real microphone tone resumes.
Earlier noisy-host test failures are retained separately; the original three
engine cases passed unchanged on the quieter disposable VM.

This is a test candidate. Existing signed 1.0.0, 1.0.1-rc.1 and 1.0.1 artifacts
stay immutable. Physical iPhone/Android, Safari and USB microphone checks require
actual hardware; Chromium touch/viewport emulation does not certify them.
Exact candidate hashes and extended acceptance results accompany the signed kit.
