"""VocalBridge voice dispatch integration.

When the voice dispatch provider is set to ``vocalbridge``, calls connect to
a hosted VocalBridge voice agent (LiveKit Cloud) instead of the local LiveKit
stack. VocalBridge handles speech; domain questions are delegated back to
this machine over the room data channel (``query_agent``/``agent_response``),
where a deliberately restricted dispatcher agent answers them.
"""
