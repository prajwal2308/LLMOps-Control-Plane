"""
providers.py
------------
A "provider" is anything that can answer an LLM request: OpenAI, Anthropic, a
local model, etc. The rest of the app doesn't care WHICH one -- it just calls
`generate(...)` and gets back text + token counts. That's the abstraction that
lets a gateway/control-plane route across many providers.

Two providers here:
  - MockProvider: needs NO api key. Returns a canned answer with fake token
    counts so you can run and see the whole system work immediately.
  - AnthropicProvider: makes a REAL call to Anthropic when you add an API key.

Error Taxonomy:
  - ClientError (HTTP 4xx): Bad request, invalid key, schema error -> Non-retryable.
  - ProviderError (HTTP 5xx / Network): Server crash, timeout, connection drop -> Failover-eligible.
"""

import os
import time
import httpx


class ClientError(Exception):
    """Client/User error (HTTP 4xx). NON-RETRYABLE. Should fail fast immediately."""
    pass


class ProviderError(Exception):
    """Provider/Infrastructure error (HTTP 5xx / Timeout). RETRYABLE & Failover-eligible."""
    pass


# --- Approximate prices in USD *per token* (NOT per million). --------------
PRICE_TABLE = {
    "mock-model":                (0.0,        0.0),          # free, it's fake
    "claude-3-5-haiku-20241022": (0.80e-6,    4.00e-6),      # ~$0.80 / $4.00 per M
    "claude-sonnet-4-20250514":  (3.00e-6,   15.00e-6),      # ~$3 / $15 per M
}


def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Look up the model's price and compute the dollar cost of this call."""
    in_price, out_price = PRICE_TABLE.get(model, (0.0, 0.0))
    return prompt_tokens * in_price + completion_tokens * out_price


class MockProvider:
    """A fake provider so the whole platform runs with zero setup / no keys."""

    name = "mock"

    def generate(self, model: str, messages: list[dict]) -> tuple[str, int, int]:
        # Echo something deterministic so tests are predictable.
        last_user_msg = messages[-1]["content"] if messages else ""
        text = f"[mock reply] you said: {last_user_msg}"

        # Pretend token counts: ~1 token per 4 characters is a rough industry rule.
        prompt_tokens = max(1, sum(len(m["content"]) for m in messages) // 4)
        completion_tokens = max(1, len(text) // 4)
        return text, prompt_tokens, completion_tokens


class AnthropicProvider:
    """Real calls to Anthropic's API. Used only when ANTHROPIC_API_KEY is set."""

    name = "anthropic"
    BASE_URL = "https://api.anthropic.com/v1/messages"

    def __init__(self) -> None:
        self.api_key = os.environ.get("ANTHROPIC_API_KEY", "")

    def generate(self, model: str, messages: list[dict]) -> tuple[str, int, int]:
        if not self.api_key:
            raise ProviderError("ANTHROPIC_API_KEY is not set")

        payload = {"model": model, "max_tokens": 1024, "messages": messages}
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        try:
            resp = httpx.post(self.BASE_URL, json=payload, headers=headers, timeout=60)
            resp.raise_for_status()
            data = resp.json()
            text = data["content"][0]["text"]
            usage = data.get("usage", {})
            prompt_tokens = usage.get("input_tokens", 0)
            completion_tokens = usage.get("output_tokens", 0)
            return text, prompt_tokens, completion_tokens
        except httpx.HTTPStatusError as err:
            status_code = err.response.status_code
            if 400 <= status_code < 500:
                raise ClientError(f"HTTP {status_code} User Error: {err.response.text}") from err
            else:
                raise ProviderError(f"HTTP {status_code} Provider Outage: {err.response.text}") from err
        except (httpx.TimeoutException, httpx.RequestError) as err:
            raise ProviderError(f"Network Connection Failure: {err}") from err


_PROVIDERS = {
    "mock": MockProvider(),
    "anthropic": AnthropicProvider(),
}


def get_provider(name: str):
    """Return the provider object for a given name, or raise if unknown."""
    if name not in _PROVIDERS:
        raise ClientError(f"unknown provider '{name}' (have: {list(_PROVIDERS)})")
    return _PROVIDERS[name]
