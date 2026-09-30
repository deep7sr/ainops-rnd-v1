"""Redaction: secrets in device output become <redacted> before the output is stored, logged,
returned to a client or sent to an LLM. Applied to every output, whatever the command."""

import re

REDACTED = "<redacted>"

# Each pattern keeps its group 1 (the keyword) and replaces the value that follows it.
_KEYWORD_THEN_SECRET = [
    # Cisco IOS
    r"\b(?:password|secret)\s+(?:\d\s+)?",
    r"\bsnmp-server community\s+",
    r"\bkey\s+\d\s+",
    r"\b(?:tacacs-server|radius-server)\s+key\s+(?:\d\s+)?",
    r"\bcrypto isakmp key\s+",
    r"\bpre-shared-key\s+(?:ascii-text\s+|hexadecimal\s+)?",
    # Junos (text and JSON forms)
    r"\bencrypted-password\"?\s*[:\s]\s*\"?",
    r"\bauthentication-key\"?\s*[:\s]\s*\"?",
    r"\bcommunity\s+",
]
_PATTERNS = [
    re.compile(f"({keyword})[^\\s\"']+", re.IGNORECASE) for keyword in _KEYWORD_THEN_SECRET
]
# Junos "$9$..." and "$6$..." hashed/encrypted strings wherever they appear (also inside JSON).
_JUNOS_HASH = re.compile(r"\$[169]\$[^\s\"']+")


def redact(text: str) -> str:
    for pattern in _PATTERNS:
        text = pattern.sub(rf"\g<1>{REDACTED}", text)
    return _JUNOS_HASH.sub(REDACTED, text)
