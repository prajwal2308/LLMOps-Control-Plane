"""
routing.py
----------
Stage 4: deciding WHICH provider/model should handle a request, and in what
order to try backups if one fails.

This module is PURE logic — no network calls, no database, no timing. That makes
it trivial to test on its own, and it keeps main.py (which does the actual calls,
timing, and telemetry) clean. This mirrors how telemetry.py hides storage and
providers.py hides model backends: each file owns one concern.

Two ideas live here:
  1. ROUTING   — pick a provider/model based on the request (cheap model for
                 simple prompts, stronger model for complex ones).
  2. FAILOVER  — an ordered list of backups to try if the first choice errors,
                 so a provider outage doesn't take the whole request down.

main.py walks the ordered list this module returns, trying each until one works.
"""

import random

# --- Tiers: map a "size" of task to a (provider, model). --------------------
# Swap these for whatever providers/models you actually have. When you add an
# OpenAI or local Ollama provider, this is the only place you change.
CHEAP_TIER  = ("mock", "mock-model")                      # fast/cheap: simple prompts
STRONG_TIER = ("anthropic", "claude-3-5-haiku-20241022")  # stronger: complex prompts


# --- Failover order: what to try if the chosen provider fails. --------------
# These are appended AFTER the primary choice. The last entry should be
# something that almost always works so a demo degrades gracefully instead of
# hard-failing. In real production you might instead fail loudly, page someone,
# or route to a second *paid* provider — that's a deliberate design choice.
FAILOVER_FALLBACKS = [
    ("anthropic", "claude-3-5-haiku-20241022"),
    ("mock", "mock-model"),
]

# Prompts longer than this (in characters) are treated as "complex" and routed
# to the strong tier. A crude heuristic on purpose — a fine-tuned classifier
# could make this decision far better later (a natural future upgrade, and a
# good place to add real ML to the project).
COMPLEXITY_CHAR_THRESHOLD = 280


def estimate_complexity(messages: list[dict]) -> str:
    """Return 'complex' for long prompts, 'simple' otherwise.

    Length is a rough proxy for difficulty: short asks ('hi', 'what's 2+2')
    are usually simple; long, detailed prompts usually need a stronger model.
    """
    total_chars = sum(len(m.get("content", "")) for m in messages)
    return "complex" if total_chars > COMPLEXITY_CHAR_THRESHOLD else "simple"


def _default_model_for(provider: str) -> str:
    """If a caller names a provider but not a model, pick a sensible default."""
    if provider == "anthropic":
        return STRONG_TIER[1]
    return CHEAP_TIER[1]


def build_attempt_plan(
    provider: str | None,
    model: str | None,
    messages: list[dict],
) -> list[tuple[str, str]]:
    """Return an ordered list of (provider, model) attempts to try in sequence.

    Rules:
      - If the caller explicitly named a provider, honor that choice FIRST,
        then append the failover backups.
      - If no provider was named, ROUTE by complexity (cheap vs strong tier),
        then append the failover backups.
    Duplicate (provider, model) pairs are removed while preserving order, so we
    never pointlessly try the same thing twice.
    """
    plan: list[tuple[str, str]] = []

    if provider:
        # Explicit choice wins as the primary attempt.
        plan.append((provider, model or _default_model_for(provider)))
    else:
        # Auto-route by how hard the prompt looks.
        tier = STRONG_TIER if estimate_complexity(messages) == "complex" else CHEAP_TIER
        tier_provider, tier_model = tier
        plan.append((tier_provider, model or tier_model))

    # Append the failover backups after the primary choice.
    plan.extend(FAILOVER_FALLBACKS)

    # De-duplicate while preserving order.
    seen: set[tuple[str, str]] = set()
    deduped: list[tuple[str, str]] = []
    for pair in plan:
        if pair not in seen:
            seen.add(pair)
            deduped.append(pair)
    return deduped


def calculate_backoff_with_jitter(
    attempt_index: int,
    base: float = 0.1,
    max_cap: float = 2.0,
) -> float:
    """Calculate exponential backoff with full jitter (AWS Architecture pattern).

    Formula: T = random.uniform(0, min(max_cap, base * (2 ** attempt_index)))
    `attempt_index` is 0-indexed count of prior failure attempts.
    """
    temp = min(max_cap, base * (2 ** attempt_index))
    return random.uniform(0, temp)

