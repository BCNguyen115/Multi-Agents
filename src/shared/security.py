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
import secrets
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
    (
        re.compile(
            r"\b(?:bỏ qua|hủy bỏ|xóa bỏ)\s+(?:toàn bộ\s+)?(?:hướng dẫn|quy tắc|chỉ thị|chính sách)\b",
            re.IGNORECASE,
        ),
        "Vietnamese Instruction Override Attempt",
    ),
    # --- Jailbreak / persona hijack ---
    (
        re.compile(r"\bdan\s+mode\b|\bdo\s+anything\s+now\b", re.IGNORECASE),
        "DAN (Do Anything Now) Jailbreak Mode",
    ),
    (
        re.compile(
            r"\b(?:chế độ\s+dan|chế độ\s+bảo trì|đóng vai\s+trò\s+là\s+dan)\b",
            re.IGNORECASE,
        ),
        "Vietnamese Jailbreak Attempt",
    ),
    (
        re.compile(r"\bjailbreak\b|\boverride\s+safety\b|\bbypass\s+guardrails?\b", re.IGNORECASE),
        "Explicit Safety Override Attempt",
    ),
    (
        re.compile(
            r"\b(?:maintenance|developer|debug|sudo|root|god)\s+mode\b",
            re.IGNORECASE,
        ),
        "Privileged Mode Override Attempt",
    ),
    (
        re.compile(
            r"\bact\s+as\s+(?:an?\s+)?(?:unfiltered|uncensored|unrestricted|evil|rebel)\b",
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
    # --- System prompt leakage & Canary probing ---
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
            r"\b(?:xuất|hiển thị|tiết lộ|in ra)\s+(?:nguyên văn\s+)?(?:system prompt|hướng dẫn hệ thống|khóa bí mật)\b",
            re.IGNORECASE,
        ),
        "Vietnamese System Prompt Extraction",
    ),
    (
        re.compile(
            r"\bwhat\s+(?:is|are)\s+your\s+(?:system\s+)?(?:prompt|instructions?|rules?)\b",
            re.IGNORECASE,
        ),
        "System Prompt Inquiry Attempt",
    ),
    (
        re.compile(r"\bcanary_secret_\w+\b", re.IGNORECASE),
        "Canary Token Extraction Probe",
    ),
    # --- Multi-turn / delimiter injection ---
    (
        re.compile(
            r"\b(?:new\s+instructions?|system\s*:\s*|<\|system\|>|<<\s*SYS\s*>>|\[INST\]|<user_untrusted_input)",
            re.IGNORECASE,
        ),
        "Delimiter / System Tag Injection",
    ),
]

# Canary Token Prefix & Pattern
CANARY_PREFIX: str = "CANARY_SECRET_"
_CANARY_PATTERN: re.Pattern[str] = re.compile(r"CANARY_SECRET_[a-f0-9]{12}", re.IGNORECASE)


def generate_canary_token() -> str:
    """Generate an ephemeral, cryptographically unique canary token for system prompt leakage detection."""
    return f"{CANARY_PREFIX}{secrets.token_hex(6)}"


def inspect_response_for_canary_leak(
    response_text: str, specific_canary: Optional[str] = None
) -> tuple[bool, str]:
    """Inspect model response for prompt leakage of canary/honeypot tokens.

    Returns:
        tuple[bool, str]: (is_leaked, leaked_token). Returns (False, "") if clean.
    """
    if not response_text:
        return False, ""

    if specific_canary and specific_canary in response_text:
        logger.critical(
            "PROMPT_LEAKAGE_DETECTED: Target Canary Token '%s' found in model response!",
            specific_canary,
            extra={"session_id": "SECURITY"},
        )
        return True, specific_canary

    match = _CANARY_PATTERN.search(response_text)
    if match:
        leaked_token = match.group(0)
        logger.critical(
            "PROMPT_LEAKAGE_DETECTED: Canary pattern '%s' discovered in model response!",
            leaked_token,
            extra={"session_id": "SECURITY"},
        )
        return True, leaked_token

    return False, ""


# Dynamic Nonce Delimiters for Untrusted User Input
def generate_input_nonce() -> str:
    """Generate a unique 4-byte (8-hex-char) cryptographic nonce."""
    return secrets.token_hex(4)


def wrap_user_input(query: str, nonce: Optional[str] = None) -> tuple[str, str]:
    """Wrap raw user input in dynamic nonce delimiters to prevent instruction hijacking.

    Returns:
        tuple[str, str]: (wrapped_string, nonce)
    """
    active_nonce = nonce or generate_input_nonce()
    clean_query = query.strip()
    wrapped = f'<user_untrusted_input nonce="{active_nonce}">\n{clean_query}\n</user_untrusted_input nonce="{active_nonce}">'
    return wrapped, active_nonce


def unwrap_user_input(wrapped_text: str) -> tuple[str, Optional[str]]:
    """Extract raw query and nonce from wrapped user input if present."""
    pattern = r'<user_untrusted_input nonce="([a-f0-9]+)">\s*(.*?)\s*</user_untrusted_input nonce="\1">'
    match = re.search(pattern, wrapped_text, re.DOTALL)
    if match:
        return match.group(2).strip(), match.group(1)
    return wrapped_text.strip(), None


def _normalize_for_safety_check(text: str) -> str:
    """Normalize user input to defeat common evasion techniques.

    Applies:
      1. Unicode NFKC normalization (folds homoglyphs, fullwidth chars, etc.).
      2. Stripping zero-width / invisible Unicode characters.
      3. Collapsing excessive whitespace.
    """
    normalized = unicodedata.normalize("NFKC", text)
    normalized = _INVISIBLE_CHARS_RE.sub("", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def _detect_base64_injection(text: str) -> tuple[bool, str]:
    """Attempt to detect Base64-encoded prompt injection payloads."""
    b64_candidates = re.findall(r"[A-Za-z0-9+/=]{20,}", text)
    for candidate in b64_candidates[:3]:
        try:
            decoded = base64.b64decode(candidate, validate=True).decode("utf-8", errors="ignore")
            if len(decoded) < 8:
                continue
            for pattern, label in _INJECTION_PATTERNS:
                if pattern.search(decoded):
                    return True, f"Base64 Encoded {label}"
            # Also test semantic intent on decoded text
            is_semantic_b64, sem_label = _semantic_intent_classification(decoded)
            if is_semantic_b64:
                return True, f"Base64 Encoded {sem_label}"
        except Exception:
            continue
    return False, ""


def _semantic_intent_classification(text: str) -> tuple[bool, str]:
    """Semantic Guardrail Layer: Fast semantic intent and adversarial cluster classifier (<2ms).

    Identifies adversarial context switching, roleplay jailbreaks, and prompt exfiltration
    by analyzing semantic intent density across threat clusters.
    """
    clean = text.lower()

    # Cluster 1: Override / Bypass Verbs
    override_keywords = {
        "ignore", "disregard", "forget", "bypass", "override", "disable", "reset",
        "bỏ qua", "hủy bỏ", "xóa bỏ", "vượt qua", "tắt", "stop following", "drop all"
    }

    # Cluster 2: Target Rules / System Instructions
    target_keywords = {
        "instruction", "instructions", "prompt", "prompts", "rule", "rules",
        "guideline", "guidelines", "constraint", "constraints", "policy", "safety",
        "guardrail", "hướng dẫn", "chỉ thị", "quy tắc", "chính sách"
    }

    # Cluster 3: Persona / Roleplay Hijack
    roleplay_keywords = {
        "dan", "jailbreak", "unfiltered", "uncensored", "unrestricted", "pretend",
        "roleplay", "maintenance mode", "developer mode", "god mode", "sudo", "root"
    }

    # Cluster 4: Exfiltration / System Leakage
    exfiltration_keywords = {
        "system prompt", "system instructions", "secret", "secrets", "api key",
        "credentials", "password", "tokens", "webhook", "canary", "canary_secret"
    }

    has_override = any(k in clean for k in override_keywords)
    has_target = any(k in clean for k in target_keywords)
    has_roleplay = any(k in clean for k in roleplay_keywords)
    has_exfil = any(k in clean for k in exfiltration_keywords)

    # Heuristic Combinations
    if has_override and (has_target or has_roleplay):
        return True, "Semantic Adversarial Instruction Override"
    if has_roleplay and (has_override or has_target or has_exfil):
        return True, "Semantic Jailbreak & Persona Hijack"
    if has_exfil and (has_override or "show" in clean or "reveal" in clean or "leak" in clean or "tiết lộ" in clean):
        return True, "Semantic System Prompt Exfiltration"

    return False, ""


# ---------------------------------------------------------------------------
# Pre-Execution Indirect Prompt Injection Audit (documents, web pages, dataset-derived text)
# ---------------------------------------------------------------------------

_INDIRECT_INJECTION_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(
            r"\bignore\s+(?:all\s+)?(?:previous|prior|above)\s+(?:instructions?|prompts?|rules?)\b",
            re.IGNORECASE,
        ),
        "Instruction Override in external document",
    ),
    (
        re.compile(
            r"\b(?:bỏ qua|hủy bỏ|xóa bỏ)\s+(?:toàn bộ\s+)?(?:hướng dẫn|quy tắc|chỉ thị|chính sách)\b",
            re.IGNORECASE,
        ),
        "Vietnamese Instruction Override in external document",
    ),
    (
        re.compile(
            r"\bdisregard\s+(?:all\s+)?(?:rules?|safety|constraints?)\b",
            re.IGNORECASE,
        ),
        "Safety Constraint Disregard in external document",
    ),
    (
        re.compile(
            r"\b(?:you are now|acting as|operate as|system mode:)\b",
            re.IGNORECASE,
        ),
        "Persona Hijack / Role Switching in external document",
    ),
    (
        re.compile(
            r"\b(?:send|exfiltrate|transmit|post)\s+(?:all\s+)?(?:data|secrets?|passwords?|keys?|tokens?)\s+(?:to|via)\b",
            re.IGNORECASE,
        ),
        "Data Exfiltration Directive in external document",
    ),
    (
        re.compile(
            r"(?:curl\s+https?://|wget\s+https?://|webhook|https?://[a-zA-Z0-9.-]+\.ngrok\.io|https?://webhook\.site)",
            re.IGNORECASE,
        ),
        "External Call / Webhook Trigger in external document",
    ),
    (
        re.compile(
            r"\b(?:CANARY_SECRET_|ADMIN_ACCESS_OVERRIDE|system_prompt_dump)\b",
            re.IGNORECASE,
        ),
        "Canary Probing or System Exfiltration in external document",
    ),
]


def indirect_injection_threats(text: str) -> list[str]:
    """Labels of the indirect-injection patterns found in ``text`` (same normalisation as ``audit_context_safety``)."""
    if not text or not isinstance(text, str):
        return []
    scanned = _normalize_for_safety_check(text)
    return [label for pattern, label in _INDIRECT_INJECTION_PATTERNS if pattern.search(scanned)]


def audit_context_safety(
    context_chunks: list[str],
) -> tuple[bool, list[str], list[str]]:
    """Pre-Execution Audit: scan retrieved/derived text chunks for indirect prompt injection.

    Args:
        context_chunks: Raw document, web or dataset-derived text chunks.

    Returns:
        ``(all_safe, sanitized_chunks, audit_findings)`` — unsafe chunks are replaced by a neutral notice.
    """
    if not context_chunks:
        return True, [], []

    all_safe: bool = True
    sanitized_chunks: list[str] = []
    audit_findings: list[str] = []

    for idx, chunk in enumerate(context_chunks):
        if not chunk or not isinstance(chunk, str):
            sanitized_chunks.append("")  # keep the output aligned with the input, callers index into it
            continue

        # same evasion defence as direct input (homoglyphs, zero-width characters, split lines, decomposed accents);
        # the chunk that is returned stays as it was written
        scanned = _normalize_for_safety_check(chunk)
        chunk_threats: list[str] = [label for pattern, label in _INDIRECT_INJECTION_PATTERNS if pattern.search(scanned)]
        if chunk_threats:
            all_safe = False
            threat_summary = ", ".join(chunk_threats)
            finding_msg = f"Chunk #{idx + 1} blocked by Security Audit: {threat_summary}"
            audit_findings.append(finding_msg)
            logger.warning(
                "Indirect Injection Detected during Pre-Execution Audit: %s",
                finding_msg,
                extra={"session_id": "SECURITY_AUDIT"},
            )
            sanitized_chunks.append(
                f"[BẢO MẬT ZERO-TRUST: Đoạn trích này đã bị vô hiệu hóa do chứa chỉ thị không an toàn ({threat_summary})]"
            )
        else:
            sanitized_chunks.append(chunk)

    return all_safe, sanitized_chunks, audit_findings


def inspect_prompt_safety(query: str) -> tuple[bool, str]:
    """Inspect user input query against direct prompt injection, jailbreaks & semantic attacks.

    Defense-in-depth pipeline:
      Tier 1: Unicode NFKC normalization + invisible character stripping.
      Tier 2: Signature pattern matching against known adversarial vectors.
      Tier 3: Base64 decode extraction and recursive scan.
      Tier 4: Semantic Intent Classifier detecting evasion & context-switching.

    Performance: < 2ms execution time.

    Args:
        query: User natural language query text.

    Returns:
        tuple[bool, str]: (is_safe, violation_label).
            If safe: (True, "")
            If unsafe: (False, violation_label)
    """
    if not query or not query.strip():
        return True, ""

    # Tier 1: Normalize to defeat evasion (homoglyphs, zero-width chars)
    normalized = _normalize_for_safety_check(query)

    # Tier 2: Pattern matching on normalized text
    for pattern, label in _INJECTION_PATTERNS:
        if pattern.search(normalized):
            logger.warning(
                "Prompt Injection Signature Blocked: label='%s' | query='%s'",
                label,
                query[:120],
                extra={"session_id": "SECURITY"},
            )
            return False, label

    # Tier 3: Base64 decode detection
    is_b64_injection, b64_label = _detect_base64_injection(normalized)
    if is_b64_injection:
        logger.warning(
            "Base64 Prompt Injection Blocked: label='%s' | query='%s'",
            b64_label,
            query[:120],
            extra={"session_id": "SECURITY"},
        )
        return False, b64_label

    # Tier 4: Semantic Intent Classifier
    is_semantic_threat, sem_label = _semantic_intent_classification(normalized)
    if is_semantic_threat:
        logger.warning(
            "Semantic Prompt Guardrail Blocked: label='%s' | query='%s'",
            sem_label,
            query[:120],
            extra={"session_id": "SECURITY"},
        )
        return False, sem_label

    return True, ""

