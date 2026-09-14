"""AI-based next-multiplier prediction using the OpenAI API.

Crash-style multiplier games are typically provably-fair / RNG-based, so past
rounds carry no real statistical signal about the next one. This module still
asks the model for a best-effort estimate as requested, but every prediction is
logged alongside the actual outcome (see runner.run_detection) so real
accuracy is visible over time rather than assumed.
"""

from __future__ import annotations

import json
import os

import openai

from . import config

# The key can come from an existing OPENAI_API_KEY env var (e.g. set by the
# shell), but the primary path is the GUI's "Set API Key" dialog, which
# persists it via src.config so it's remembered across runs without needing
# .env.
if not os.environ.get("OPENAI_API_KEY"):
    _persisted_key = config.load_api_key()
    if _persisted_key:
        os.environ["OPENAI_API_KEY"] = _persisted_key

DEFAULT_MODEL = "gpt-5"

# Offered in the GUI's model dropdown; the box is editable so any other
# chat-completions-compatible model id can be typed in too.
MODEL_OPTIONS = ["gpt-5", "gpt-5-mini", "gpt-4.1", "gpt-4o", "gpt-4o-mini"]

_SCHEMA = {
    "type": "object",
    "properties": {
        "predicted_multiplier": {"type": "number"},
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
        "reasoning": {"type": "string"},
    },
    "required": ["predicted_multiplier", "confidence", "reasoning"],
    "additionalProperties": False,
}

DEFAULT_SYSTEM_PROMPT = (
    "You analyze a history of crash-game round multipliers, given as "
    "(timestamp, multiplier) pairs in chronological order, and produce a "
    "best-effort estimate for the next round.\n\n"
    "Consider two kinds of signal:\n"
    "1. Value-based: descriptive statistics of the recent multipliers - prefer "
    "the median (or a trimmed mean) over the raw mean, since crash multipliers "
    "are heavy-tailed and rare large multipliers skew the average; note the "
    "spread (e.g. stddev or IQR) and the empirical frequency of exceeding "
    "common thresholds like 2x or 5x.\n"
    "2. Time-based: the timestamps themselves - look at elapsed time between "
    "consecutive rounds (round cadence/pace) and the time of day, and note "
    "whether the current round is arriving faster/slower than the recent "
    "pace, or whether this time of day has shown a different multiplier "
    "distribution than the rest of the sample.\n\n"
    "Weigh both kinds of signal in your estimate, but be calibrated: if the "
    "sample is small or the patterns are weak/inconsistent, say so and keep "
    "confidence 'low'. Only raise confidence if a pattern (value-based or "
    "time-based) is clearly present and holds up across a reasonably large, "
    "consistent sample. In your reasoning, name the specific statistic(s) or "
    "time pattern you used."
)

_client: openai.OpenAI | None = None


def _error(short: str, detail: str) -> dict:
    """Package a failure so callers can show it instead of a bare '-'."""
    print(f"Predictor unavailable: {short} - {detail.splitlines()[0]}")
    return {"error": short, "error_detail": detail}


def _describe(e: openai.OpenAIError) -> dict:
    """Turn an SDK exception into something a non-developer can act on."""
    body = getattr(e, "body", None) or {}
    code = body.get("code") or ""
    status = getattr(e, "status_code", None)

    if code == "credit_balance_exhausted" or body.get("type") == "insufficient_quota":
        return _error(
            "no API credits",
            "The OpenAI account has no credits remaining.\n\n"
            "Add credits at:\n"
            "https://platform.openai.com/settings/organization/billing/\n\n"
            "The key itself is valid - only billing is blocking predictions.",
        )
    if isinstance(e, openai.AuthenticationError) or status == 401:
        return _error(
            "API key rejected",
            "The OpenAI API key was rejected (HTTP 401).\n\n"
            "Check it with the 'Set API Key' button.",
        )
    if isinstance(e, openai.APIConnectionError):
        return _error(
            "cannot reach API",
            f"Could not reach the OpenAI API - check the network connection.\n\n{e}",
        )
    if isinstance(e, openai.NotFoundError) or status == 404:
        return _error(
            "unknown model",
            f"The selected model was not found, or this account cannot use it.\n\n{e}",
        )
    if isinstance(e, openai.RateLimitError) or status == 429:
        return _error("rate limited", f"The API is rate limiting requests.\n\n{e}")
    return _error(f"API error{f' ({status})' if status else ''}", str(e))


def _get_client() -> openai.OpenAI:
    global _client
    if _client is None:
        _client = openai.OpenAI()
    return _client


def has_api_key() -> bool:
    return bool(os.environ.get("OPENAI_API_KEY"))


def set_api_key(key: str) -> None:
    """Set the API key from the GUI, persist it, and drop any cached client
    so the next prediction call picks up the new key."""
    global _client
    key = (key or "").strip()
    if key:
        os.environ["OPENAI_API_KEY"] = key
    else:
        os.environ.pop("OPENAI_API_KEY", None)
    config.save_api_key(key)
    _client = None


def predict_next(
    history: list[float],
    timestamps: list[str] | None = None,
    system_prompt: str | None = None,
    model: str | None = None,
) -> dict | None:
    """
    Ask the model to estimate the next round's multiplier given recent history.

    timestamps, if given, must be the same length as history (one ISO timestamp
    per round, oldest to newest) and is passed along purely as context - it is
    not a predictive feature, since round timing carries no signal for an
    RNG-based game (see DEFAULT_SYSTEM_PROMPT).

    system_prompt overrides DEFAULT_SYSTEM_PROMPT when given (e.g. from the GUI's
    editable prompt box), letting the instructions be tuned without a code change.
    model overrides DEFAULT_MODEL when given (e.g. from the GUI's model dropdown).

    Returns one of:
      - a dict with predicted_multiplier/confidence/reasoning, on success;
      - a dict with "error" (a short reason, for the GUI's prediction line) and
        "error_detail" (the full text, for the response pane), if the key is
        missing or the call fails;
      - None if there is nothing to predict yet (no history).

    Failures are always reported this way rather than raised - a prediction
    error must never block the capture loop - but the reason is carried back
    instead of discarded, so the GUI can say why it has no prediction.
    """
    if not os.environ.get("OPENAI_API_KEY"):
        return _error(
            "no API key set",
            "No OpenAI API key is set.\n\nUse the 'Set API Key' button to add one.",
        )
    if not history:
        return None

    recent = history[-50:]
    if timestamps and len(timestamps) == len(history):
        recent_ts = timestamps[-50:]
        recent_pairs = list(zip(recent_ts, recent))
        content = (
            "Recent multiplier history, oldest to newest, as "
            f"(timestamp, multiplier) pairs: {recent_pairs}"
        )
    else:
        content = f"Recent multiplier history (oldest to newest): {recent}"

    try:
        response = _get_client().chat.completions.create(
            model=model or DEFAULT_MODEL,
            messages=[
                {"role": "system", "content": system_prompt or DEFAULT_SYSTEM_PROMPT},
                {"role": "user", "content": content},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "multiplier_prediction",
                    "schema": _SCHEMA,
                    "strict": True,
                },
            },
        )
    except openai.OpenAIError as e:
        return _describe(e)

    text = response.choices[0].message.content if response.choices else None
    if not text:
        return _error("empty response", "The model returned an empty response.")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return _error(
            "unreadable response",
            f"The model's reply was not valid JSON:\n\n{text[:500]}",
        )
