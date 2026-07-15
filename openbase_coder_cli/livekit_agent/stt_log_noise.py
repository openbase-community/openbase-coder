"""Filter escalating AssemblyAI idle-session warnings down to one per pause.

During normal user silence the AssemblyAI plugin warns "no messages received
for 15s/30s/45s/…" every 15 seconds. The escalation carries no extra signal —
the counter simply resets when the user speaks again — and the spam has
misled real debugging by looking like a leaked second STT session. Keep the
first warning of each quiet stretch (idle=15s) and drop the escalations.
"""

import logging
import re

_IDLE_WARNING_PATTERN = re.compile(r"no messages received for (\d+)s")
_FIRST_IDLE_SECONDS = 15


class AssemblyAiIdleNoiseFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        match = _IDLE_WARNING_PATTERN.search(str(record.getMessage()))
        if not match:
            return True
        return int(match.group(1)) <= _FIRST_IDLE_SECONDS


def install_assemblyai_idle_noise_filter() -> AssemblyAiIdleNoiseFilter:
    noise_filter = AssemblyAiIdleNoiseFilter()
    logging.getLogger("livekit.plugins.assemblyai").addFilter(noise_filter)
    return noise_filter
