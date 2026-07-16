"""Recognition of spoken control commands in transcribed user speech."""

EXIT_TO_DISPATCH_PHRASE = "exit to dispatch"
EXIT_TO_DISPATCH_PHRASES = {
    EXIT_TO_DISPATCH_PHRASE,
    "to dispatch",
    "two dispatch",
}


def _normalize_spoken_command(text: str) -> str:
    return " ".join(
        "".join(char.lower() if char.isalnum() else " " for char in text).split()
    )


def _is_exit_to_dispatch_command(text: str) -> bool:
    normalized = _normalize_spoken_command(text)
    return any(phrase in normalized for phrase in EXIT_TO_DISPATCH_PHRASES)
