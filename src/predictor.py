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

    Returns a dict with predicted_multiplier/confidence/reasoning, or None
    (after printing a warning) if the API key is missing or the call fails -
    prediction errors must never block the capture loop.
    """
    if not os.environ.get("OPENAI_API_KEY"):
        print("Predictor: OPENAI_API_KEY not set - set it via the GUI's 'Set API Key' button, skipping prediction.")
        return None
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
        print(f"Predictor: API call failed: {e}")
        return None

    text = response.choices[0].message.content if response.choices else None
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None
