"""Call language model APIs via OpenRouter SDK with retry and backoff."""

import os
import random
import time
from dataclasses import dataclass

from openrouter import OpenRouter
from openrouter.errors import (
    BadGatewayResponseError,
    InternalServerResponseError,
    ServiceUnavailableResponseError,
    TooManyRequestsResponseError,
    ProviderOverloadedResponseError,
)

_client = None

_RETRYABLE_ERRORS = (
    BadGatewayResponseError,
    InternalServerResponseError,
    ServiceUnavailableResponseError,
    TooManyRequestsResponseError,
    ProviderOverloadedResponseError,
)


@dataclass
class ApiResponse:
    content: str
    tokens_input: int
    tokens_output: int
    model: str
    system_fingerprint: str
    duration_seconds: float


def _get_client() -> OpenRouter:
    global _client
    if _client is None:
        _client = OpenRouter(
            api_key=os.environ["OPENROUTER_API_KEY"],
        )
    return _client


def call_api(
    model: str,
    prompt: str,
    temperature: float,
    max_retries: int = 3,
    backoff_base: float = 2.0,
    max_tokens: int = 65536,
    seed: int | None = None,
) -> ApiResponse:
    client = _get_client()
    last_error = None

    for attempt in range(max_retries + 1):
        t0 = time.monotonic()
        try:
            kwargs = dict(
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            if seed is not None:
                kwargs["seed"] = seed

            result = client.chat.send(**kwargs)
            duration = time.monotonic() - t0

            choice = result.choices[0]
            content = choice.message.content
            # content may be a string or a list; normalise to string
            if isinstance(content, list):
                content = "".join(
                    part.text if hasattr(part, "text") else str(part)
                    for part in content
                )
            elif content is None:
                content = ""

            usage = result.usage
            fingerprint = getattr(result, "system_fingerprint", None)
            return ApiResponse(
                content=content,
                tokens_input=int(usage.prompt_tokens) if usage else 0,
                tokens_output=int(usage.completion_tokens) if usage else 0,
                model=result.model or model,
                system_fingerprint=fingerprint if fingerprint else "",
                duration_seconds=duration,
            )
        except KeyboardInterrupt:
            raise
        except _RETRYABLE_ERRORS as e:
            last_error = e
            if attempt < max_retries:
                time.sleep(backoff_base ** attempt + random.uniform(0, 1))
                continue
            raise
        except Exception as e:
            # Non-retryable errors (auth, not found, bad request, etc.)
            raise

    raise last_error
