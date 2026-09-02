"""Security & Cryptography module — Internal Mutual Auth & Prompt Injection Defense.

Enterprise-grade implementation providing:
  1. Internal HMAC-SHA256 JWT Token signing and verification for inter-service
     communication with replay-attack protection (``jti``), expiry (``exp``),
     and not-before (``nbf``) claims per RFC 7519.
  2. Input moderation & Prompt Injection heuristic scanner with Unicode
     normalization, zero-width character stripping, and Base64 decode detection.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import re
import time
import unicodedata
import uuid
from typing import Any, Optional

from src.shared.logger import get_logger

logger: logging.Logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Internal Mutual Authentication (JWT / HMAC-SHA256)
# ---------------------------------------------------------------------------

def _get_jwt_secret(override: Optional[str] = None) -> str:
    """Resolve the JWT signing secret with a strict priority chain.

    Priority:
        1. Explicit ``override`` argument (used in tests).
        2. ``INTERNAL_JWT_SECRET`` environment variable.
        3. Raise ``RuntimeError`` — never fall back to a hardcoded value.

    Args:
        override: Optional explicit secret for unit-testing.

    Returns:
        str: The resolved secret key.

    Raises:
        RuntimeError: If no secret is configured.
    """
    if override:
        return override

    env_secret = os.environ.get("INTERNAL_JWT_SECRET", "")
    if env_secret:
        return env_secret

    # Attempt to load from pydantic settings (lazy import to avoid circular dep
    # at module level when security.py is imported from gateway startup).
    try:
        from src.config import settings as _cfg
        if _cfg.INTERNAL_JWT_SECRET:
            return _cfg.INTERNAL_JWT_SECRET
    except Exception:
        pass

    raise RuntimeError(
        "INTERNAL_JWT_SECRET is not configured. Set it via environment variable "
        "or .env file. Refusing to use a hardcoded fallback in production."
    )


def _urlsafe_b64encode(data: bytes) -> str:
    """Encode bytes to URL-safe base64 string without trailing padding."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("utf-8")


def _urlsafe_b64decode(data: str) -> bytes:
    """Decode URL-safe base64 string handling missing padding."""
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded.encode("utf-8"))


def generate_internal_token(
    service_name: str = "internal_service",
    secret_key: Optional[str] = None,
    expires_in_seconds: int = 3600,
) -> str:
    """Generate a signed internal JWT token for inter-service authentication.

    The token includes standard RFC 7519 claims:
      - ``iss``: Issuer (``multi_agent_system``).
      - ``sub``: Subject (the calling service name).
      - ``iat``: Issued-at timestamp.
      - ``exp``: Expiration timestamp.
      - ``nbf``: Not-before timestamp (equal to ``iat``).
      - ``jti``: Unique JWT ID (UUID4) for replay-attack prevention.

    Args:
        service_name: Identifier of the calling service.
        secret_key: Explicit secret key (for tests). Falls back to env config.
        expires_in_seconds: Lifetime of token in seconds.

    Returns:
        str: Encoded JWT token string (header.payload.signature).
    """
    secret = _get_jwt_secret(override=secret_key)
    now = int(time.time())

    header: dict[str, str] = {"alg": "HS256", "typ": "JWT"}
    payload: dict[str, Any] = {
        "iss": "multi_agent_system",
        "sub": service_name,
        "iat": now,
        "exp": now + expires_in_seconds,
        "nbf": now,
        "jti": uuid.uuid4().hex,
    }

    encoded_header = _urlsafe_b64encode(
        json.dumps(header, separators=(",", ":")).encode("utf-8")
    )
    encoded_payload = _urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
    )

    signing_input = f"{encoded_header}.{encoded_payload}".encode("utf-8")
    signature = hmac.new(
        secret.encode("utf-8"), signing_input, hashlib.sha256
    ).digest()
    encoded_signature = _urlsafe_b64encode(signature)

    return f"{encoded_header}.{encoded_payload}.{encoded_signature}"


def verify_internal_token(
    token: str,
    secret_key: Optional[str] = None,
) -> dict[str, Any]:
    """Verify an internal HMAC-SHA256 JWT token.

    Validates:
      - Token structure (3 dot-separated parts).
      - HMAC-SHA256 signature (constant-time comparison).
      - ``exp`` claim (token not expired).
      - ``nbf`` claim (token is active, allowing 30s clock skew).
      - ``jti`` claim existence (for upstream replay-attack auditing).

    Args:
        token: The JWT token string to verify.
        secret_key: Explicit secret key (for tests). Falls back to env config.

    Returns:
        dict[str, Any]: Decoded payload if valid.

    Raises:
        ValueError: If token is malformed, expired, not-yet-valid, or
                    signature verification fails.
    """
    secret = _get_jwt_secret(override=secret_key)
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("Malformed JWT token format: expected 3 dot-separated parts")

    encoded_header, encoded_payload, encoded_signature = parts

    # 1. Verify signature (constant-time comparison)
    signing_input = f"{encoded_header}.{encoded_payload}".encode("utf-8")
    expected_signature = hmac.new(
        secret.encode("utf-8"), signing_input, hashlib.sha256
    ).digest()
    actual_signature = _urlsafe_b64decode(encoded_signature)

    if not hmac.compare_digest(expected_signature, actual_signature):
        raise ValueError("Invalid JWT token signature")

    # 2. Decode payload
    try:
        payload: dict[str, Any] = json.loads(_urlsafe_b64decode(encoded_payload))
    except (json.JSONDecodeError, Exception) as exc:
        raise ValueError(f"Malformed JWT payload: {exc}") from exc

    now = int(time.time())
    clock_skew_tolerance = 30  # seconds

    # 3. Check expiration
    if payload.get("exp", 0) < now:
        raise ValueError("JWT token has expired")

    # 4. Check not-before (with clock skew tolerance)
    nbf = payload.get("nbf", 0)
    if nbf > now + clock_skew_tolerance:
        raise ValueError(f"JWT token not yet valid (nbf={nbf}, now={now})")

    # 5. Verify jti exists (actual replay-detection cache is an upstream concern)
    if "jti" not in payload:
        raise ValueError("JWT token missing required 'jti' claim")

    return payload


# ---------------------------------------------------------------------------
# Dedicated Input Moderation & Prompt Injection Defense
# ---------------------------------------------------------------------------

# Zero-width and invisible Unicode characters to strip before analysis
_INVISIBLE_CHARS_RE = re.compile(
    r"[\u200b\u200c\u200d\u200e\u200f\ufeff\u00ad\u2060\u2061\u2062\u2063\u2064"
    r"\u180e\u034f\u17b4\u17b5\ufff0-\ufff8]"
)

# Prompt injection & jailbreak attack patterns (compiled once at import)
_INJECTION_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # --- Direct instruction override ---
    (
        re.compile(
            r"\bignore\s+(?:all\s+)?(?:previous|prior|above)\s+(?:instructions?|prompts?|rules?)\b",
            re.IGNORECASE,
        ),
        "Ignore Previous Instructions Attempt",
    ),
    (
        re.compile(
            r"\bdisregard\s+(?:all\s+)?(?:rules?|constraints?|safety|prior\s+prompts?|guidelines?)\b",
            re.IGNORECASE,
        ),
        "Disregard Safety Constraints Attempt",
    ),
    (
        re.compile(
            r"\bforget\s+(?:all\s+)?(?:your\s+)?(?:rules?|instructions?|prompts?|guidelines?)\b",
            re.IGNORECASE,
        ),
        "Rule Erasure Attempt",
    ),
    # --- Jailbreak / persona hijack ---
    (
        re.compile(r"\bdan\s+mode\b|\bdo\s+anything\s+now\b", re.IGNORECASE),
        "DAN (Do Anything Now) Jailbreak Mode",
    ),
    (
        re.compile(r"\bjailbreak\b|\boverride\s+safety\b|\bbypass\s+guardrails?\b", re.IGNORECASE),
        "Explicit Safety Override Attempt",
    ),
    (
        re.compile(
            r"\bact\s+as\s+(?:an?\s+)?(?:unfiltered|uncensored|unrestricted)\b",
            re.IGNORECASE,
        ),
        "Unfiltered Persona Hijack Attempt",
    ),
    (
        re.compile(
            r"\b(?:you\s+are\s+now|pretend\s+(?:you\s+are|to\s+be)|roleplay\s+as)\s+",
            re.IGNORECASE,
        ),
        "Persona Override Attempt",
    ),
    # --- System prompt leakage ---
    (
        re.compile(
            r"\b(?:repeat|show|print|reveal|output|display|dump|leak|echo)\s+"
            r"(?:your\s+)?(?:system\s+)?(?:prompt|instructions?|rules?|guidelines?)\b",
            re.IGNORECASE,
        ),
        "System Prompt Leakage Attempt",
    ),
    (
        re.compile(
            r"\bwhat\s+(?:is|are)\s+your\s+(?:system\s+)?(?:prompt|instructions?|rules?)\b",
            re.IGNORECASE,
        ),
        "System Prompt Inquiry Attempt",
    ),
    # --- Multi-turn / delimiter injection ---
    (
        re.compile(
            r"\b(?:new\s+instructions?|system\s*:\s*|<\|system\|>|<<\s*SYS\s*>>|\[INST\])",
            re.IGNORECASE,
        ),
        "Delimiter / System Tag Injection",
    ),
]


def _normalize_for_safety_check(text: str) -> str:
    """Normalize user input to defeat common evasion techniques.

    Applies:
      1. Unicode NFKC normalization (folds homoglyphs, fullwidth chars, etc.).
      2. Stripping zero-width / invisible Unicode characters.
      3. Collapsing excessive whitespace.

    Args:
        text: Raw user input.

    Returns:
        str: Normalized text suitable for regex pattern matching.
    """
    # NFKC folds compatibility characters (e.g. fullwidth ASCII, ligatures)
    normalized = unicodedata.normalize("NFKC", text)
    # Strip zero-width and invisible characters
    normalized = _INVISIBLE_CHARS_RE.sub("", normalized)
    # Collapse whitespace
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def _detect_base64_injection(text: str) -> tuple[bool, str]:
    """Attempt to detect Base64-encoded prompt injection payloads.

    Looks for Base64-encoded segments ≥ 20 chars, decodes them, and
    recursively checks the decoded content against injection patterns.

    Args:
        text: Normalized user input text.

    Returns:
        tuple[bool, str]: (is_injection_found, label). Returns (False, "")
            if no Base64 injection detected.
    """
    # Match potential base64 segments (at least 20 chars, valid base64 alphabet)
    b64_candidates = re.findall(r"[A-Za-z0-9+/=]{20,}", text)
    for candidate in b64_candidates[:3]:  # Limit decode attempts for performance
        try:
            decoded = base64.b64decode(candidate, validate=True).decode("utf-8", errors="ignore")
            if len(decoded) < 8:
                continue
            # Check decoded content against injection patterns (non-recursive)
            for pattern, label in _INJECTION_PATTERNS:
                if pattern.search(decoded):
                    return True, f"Base64 Encoded {label}"
        except Exception:
            continue
    return False, ""


def inspect_prompt_safety(query: str) -> tuple[bool, str]:
    """Inspect user input query against prompt injection & jailbreak patterns.

    Processing pipeline:
      1. Unicode NFKC normalization + invisible character stripping.
      2. Regex pattern matching against known attack signatures.
      3. Base64 payload decode and recursive scan.

    Performance: Designed to complete in < 1ms for typical queries. All
    patterns are pre-compiled at module import time.

    Args:
        query: User natural language query text.

    Returns:
        tuple[bool, str]: ``(is_safe, violation_label)``.
            If safe, returns ``(True, "")``.
            If unsafe, returns ``(False, label_describing_violation)``.
    """
    if not query or not query.strip():
        return True, ""

    # Step 1: Normalize to defeat evasion
    normalized = _normalize_for_safety_check(query)

    # Step 2: Pattern matching on normalized text
    for pattern, label in _INJECTION_PATTERNS:
        if pattern.search(normalized):
            logger.warning(
                "Prompt Injection Attempt Blocked: label='%s' | query='%s'",
                label,
                query[:120],
                extra={"session_id": "SECURITY"},
            )
            return False, label

    # Step 3: Base64 decode detection
    is_b64_injection, b64_label = _detect_base64_injection(normalized)
    if is_b64_injection:
        logger.warning(
            "Base64 Prompt Injection Blocked: label='%s' | query='%s'",
            b64_label,
            query[:120],
            extra={"session_id": "SECURITY"},
        )
        return False, b64_label

    return True, ""
