"""Bounded cold-start budgets shared by installed engine lifecycle commands."""
import time


# Ubuntu 24.04's Liquidsoap 2.2 typechecks its standard library and station
# graph at every start. Use the same budget as the real two-engine acceptance
# test; a running process alone does not establish source readiness.
STARTUP_TIMEOUT = 120
VALIDATION_TIMEOUT = 120
COMMAND_TIMEOUT = VALIDATION_TIMEOUT + 30


def wait_ready(probe, *, timeout=STARTUP_TIMEOUT, interval=1):
    """Poll actual readiness until success or a monotonic, bounded deadline.

    Unexpected probe failures propagate. Callers retain their own cancellation
    and failure handling; elapsed wall-clock changes cannot extend the wait.
    """
    deadline = time.monotonic() + timeout
    while True:
        if probe():
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(interval, remaining))
