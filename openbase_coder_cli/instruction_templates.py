from __future__ import annotations

from openbase_coder_cli.services.console_settings import (
    get_dangerous_confirmation_phrase,
)

DANGEROUS_CONFIRMATION_PHRASE_TOKEN = "${dangerous_confirmation_phrase}"


def has_instruction_template_tokens(text: str) -> bool:
    return DANGEROUS_CONFIRMATION_PHRASE_TOKEN in text


def render_instruction_template(text: str) -> str:
    return text.replace(
        DANGEROUS_CONFIRMATION_PHRASE_TOKEN,
        get_dangerous_confirmation_phrase(),
    )


def text_matches_instruction_template(text: str, template: str) -> bool:
    parts = template.split(DANGEROUS_CONFIRMATION_PHRASE_TOKEN)
    if len(parts) == 1:
        return text == template

    position = 0
    for index, part in enumerate(parts):
        if not part:
            continue
        next_position = text.find(part, position)
        if next_position == -1:
            return False
        if index == 0 and next_position != 0:
            return False
        position = next_position + len(part)

    final_part = parts[-1]
    return not final_part or text.endswith(final_part)
