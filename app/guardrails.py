"""
guardrails.py
-------------
Stage 6: Safety Guardrails for the LLMOps Control Plane.

The "Is this allowed?" safety checkpoint in the API Gateway pipeline:
  1. INPUT GUARDRAIL  -- Scans prompts BEFORE sending to LLM providers.
                         Detects and blocks prompt-injection attacks and jailbreaks.
  2. OUTPUT GUARDRAIL -- Scans LLM replies BEFORE returning to callers.
                         Detects and redacts PII (SSNs, Credit Cards, Emails, Phone Numbers).

This module is PURE logic -- transparent pattern checks with zero network latency.
"""

import re

# --- Prompt Injection Patterns (Case-Insensitive) ----------------------------
PROMPT_INJECTION_PATTERNS = [
    (r"ignore (all )?(previous|prior) (instructions|directives|prompts)", "prompt_injection_ignore_instructions"),
    (r"disregard (all )?(previous|prior) (instructions|directives|prompts)", "prompt_injection_disregard_instructions"),
    (r"system (prompt )?override", "prompt_injection_system_override"),
    (r"you are now in (dan|jailbreak|developer) mode", "prompt_injection_jailbreak"),
    (r"bypass (all )?(safety|content) (filters|policies|protocols)", "prompt_injection_bypass_safety"),
    (r"reveal (your |the )?(system prompt|hidden instructions|secret key)", "prompt_injection_reveal_system_prompt"),
]

# --- PII Regex Patterns for Output Redaction --------------------------------
PII_PATTERNS = [
    ("SSN", r"\b\d{3}-\d{2}-\d{4}\b", "[REDACTED SSN]"),
    ("CREDIT_CARD", r"\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|3[47][0-9]{13}|6(?:011|5[0-9]{2})[0-9]{12})\b", "[REDACTED CREDIT_CARD]"),
    ("EMAIL", r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", "[REDACTED EMAIL]"),
    ("PHONE", r"\b(?:\+?1[-. ]?)?\(?\d{3}\)?[-. ]?\d{3}[-. ]?\d{4}\b", "[REDACTED PHONE]"),
]


def check_input_guardrails(messages: list[dict]) -> tuple[bool, str | None, str | None]:
    """Scan incoming conversation messages for prompt injection or jailbreak attempts.

    Returns: (is_safe: bool, violation_type: str | None, message: str | None)
    """
    for msg in messages:
        content = msg.get("content", "")
        if not content:
            continue

        for pattern, violation_type in PROMPT_INJECTION_PATTERNS:
            if re.search(pattern, content, re.IGNORECASE):
                return (
                    False,
                    violation_type,
                    f"Prompt injection attempt detected: matched pattern '{violation_type}'",
                )

    return True, None, None


def check_output_guardrails(text: str) -> tuple[bool, str, list[str]]:
    """Scan outgoing LLM generated text for PII leaks and redact sensitive values.

    Returns: (is_clean: bool, sanitized_text: str, detected_pii_types: list[str])
    """
    if not text:
        return True, text, []

    sanitized_text = text
    detected_pii: list[str] = []

    for pii_type, pattern, replacement in PII_PATTERNS:
        matches = re.findall(pattern, sanitized_text)
        if matches:
            detected_pii.append(pii_type)
            sanitized_text = re.sub(pattern, replacement, sanitized_text)

    is_clean = len(detected_pii) == 0
    return is_clean, sanitized_text, detected_pii
