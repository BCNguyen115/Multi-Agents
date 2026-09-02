"""Telemetry & Privacy Control module.

Disables PostHog, LiteLLM, and mem0 analytics telemetry globally to avoid
multiple active PostHog client warnings and unnecessary network egress.
"""

import os
import logging
import warnings

logger: logging.Logger = logging.getLogger(__name__)

_TELEMETRY_DISABLED: bool = False


def disable_telemetry() -> None:
    """Disable PostHog, LiteLLM, and mem0 telemetry globally (singleton execution)."""
    global _TELEMETRY_DISABLED
    if _TELEMETRY_DISABLED:
        return

    os.environ["POSTHOG_DISABLED"] = "1"
    os.environ["LITELLM_TELEMETRY"] = "False"
    os.environ["MEM0_TELEMETRY"] = "False"
    os.environ["ANONYMIZED_TELEMETRY"] = "False"

    # Suppress PostHog duplicate client warnings
    warnings.filterwarnings(
        "ignore",
        message=".*Multiple active PostHog clients detected.*",
        category=UserWarning,
    )

    # Suppress HuggingFace Hub unauthenticated request warnings
    warnings.filterwarnings(
        "ignore",
        message=".*sending unauthenticated requests to the HF Hub.*",
    )
    warnings.filterwarnings(
        "ignore",
        message=".*unauthenticated requests to the HF Hub.*",
    )

    # Disable PostHog client if loaded
    try:
        import posthog  # type: ignore[import-untyped]
        posthog.disabled = True
    except Exception:
        pass

    _TELEMETRY_DISABLED = True
    logger.debug("Global telemetry disabled successfully.")
