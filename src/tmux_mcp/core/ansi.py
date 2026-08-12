"""Comprehensive ANSI and OSC escape sequence stripper utility."""

import re

# Regex patterns matching CSI, OSC, Title, and Keymode terminal sequences
_ANSI_CSI_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")
_ANSI_OSC_RE = re.compile(r"\x1B\][^\x07\x1B]*(?:\x07|\x1B\\)")
_ANSI_TITLE_RE = re.compile(r"\x1Bk[^\x1B]*\x1B\\")
_ANSI_MISC_RE = re.compile(r"\x1B[=>]")


def strip_ansi(text: str) -> str:
    """Remove CSI, OSC, Title, and Keymode ANSI escape codes from string."""
    text = _ANSI_CSI_RE.sub("", text)
    text = _ANSI_OSC_RE.sub("", text)
    text = _ANSI_TITLE_RE.sub("", text)
    text = _ANSI_MISC_RE.sub("", text)
    return text
