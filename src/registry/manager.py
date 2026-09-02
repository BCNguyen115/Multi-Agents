"""Agent Registry — Register Validation Gate, look up, and list agent instances.

The ``AgentRegistry`` is the central phone-book that the Orchestrator
queries to find a suitable agent for a given intent.

Enterprise Features:
  - **Register Validation Gate**: Automatic overlap detection (>80% similarity
    threshold) to prevent agent ambiguity in Planner Node intent classification.
  - **API Probe Testing**: Functional probe that calls ``process_request``
    with a timeout to verify the agent's async interface contract.
  - **Metadata Schema Enforcement**: Rejects registration when required
    fields (``name``, ``description``) are missing or empty.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import math
import re
from collections import Counter
from typing import Optional

from src.agents.base_agent import BaseAgent
from src.shared.logger import get_logger

logger: logging.Logger = get_logger(__name__)

# Minimum description length below which similarity comparison is skipped.
# Very short descriptions produce unreliable cosine similarity scores.
_MIN_DESCRIPTION_LENGTH: int = 10

# Timeout in seconds for the async API probe test.
_PROBE_TIMEOUT_SECONDS: float = 3.0


def _compute_cosine_similarity(text1: str, text2: str) -> float:
    """Compute cosine similarity between two text strings using word frequency vectors.

    Uses a lightweight bag-of-words approach to avoid adding heavy NLP
    dependencies (TF-IDF, sentence-transformers) to the registry's hot path.

    Args:
        text1: First text string.
        text2: Second text string.

    Returns:
        float: Cosine similarity score between 0.0 and 1.0.
               Returns 0.0 if either text is empty or yields no word tokens.
    """
    words1 = re.findall(r"\w+", text1.lower())
    words2 = re.findall(r"\w+", text2.lower())

    if not words1 or not words2:
        return 0.0

    vec1 = Counter(words1)
    vec2 = Counter(words2)

    intersection = set(vec1.keys()) & set(vec2.keys())
    numerator = sum(vec1[x] * vec2[x] for x in intersection)

    sum1 = sum(v ** 2 for v in vec1.values())
    sum2 = sum(v ** 2 for v in vec2.values())
    denominator = math.sqrt(sum1) * math.sqrt(sum2)

    if denominator == 0.0:
        return 0.0
    return float(numerator / denominator)


class AgentRegistry:
    """In-memory registry for managing ``BaseAgent`` instances with Validation Gate.

    Attributes:
        _agents: Internal mapping from agent name → agent instance.
        _similarity_threshold: Maximum allowed description similarity (0.80 = 80%).
    """

    def __init__(self, similarity_threshold: float = 0.80) -> None:
        """Initialise registry with configurable validation gate threshold."""
        self._agents: dict[str, BaseAgent] = {}
        self.similarity_threshold: float = similarity_threshold

    # ------------------------------------------------------------------
    # Registration with Validation Gate
    # ------------------------------------------------------------------

    async def register_async(self, agent: BaseAgent, validate: bool = True) -> None:
        """Register an agent instance with mandatory Validation Gate checks (async).

        This is the preferred registration method when called from an async
        context (e.g., ``lifespan`` startup). It runs a real functional probe
        with ``asyncio.wait_for`` timeout protection.

        Args:
            agent: An instance of a ``BaseAgent`` subclass.
            validate: Whether to run overlap detection and probe tests.

        Raises:
            ValueError: If metadata is invalid, overlap > threshold, or probe fails.
            TypeError: If agent does not conform to ``BaseAgent`` interface.
        """
        metadata = self._extract_and_validate_metadata(agent)
        name: str = metadata["name"]
        description: str = metadata["description"]

        if validate:
            self._check_description_overlap(name, description)
            await self._probe_test_async(agent, name)

        self._commit_registration(agent, name, description)

    def register(self, agent: BaseAgent, validate: bool = True) -> None:
        """Register an agent instance synchronously (backward-compatible).

        Performs metadata validation and overlap detection but runs a
        lightweight synchronous probe (interface check only, no actual call)
        to avoid requiring an event loop at startup time.

        Args:
            agent: An instance of a ``BaseAgent`` subclass.
            validate: Whether to run overlap detection and probe tests.

        Raises:
            ValueError: If metadata is invalid, overlap > threshold, or probe fails.
            TypeError: If agent does not conform to ``BaseAgent`` interface.
        """
        metadata = self._extract_and_validate_metadata(agent)
        name: str = metadata["name"]
        description: str = metadata["description"]

        if validate:
            self._check_description_overlap(name, description)
            self._probe_test_sync(agent, name)

        self._commit_registration(agent, name, description)

    # ------------------------------------------------------------------
    # Validation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_and_validate_metadata(agent: BaseAgent) -> dict[str, str]:
        """Extract and validate required metadata fields from an agent.

        Args:
            agent: Agent to extract metadata from.

        Returns:
            dict[str, str]: Validated metadata with ``name`` and ``description``.

        Raises:
            TypeError: If ``get_metadata()`` doesn't return a dict.
            ValueError: If required fields are missing or empty.
        """
        try:
            metadata = agent.get_metadata()
        except Exception as exc:
            raise TypeError(
                f"Agent.get_metadata() raised an exception: {exc}"
            ) from exc

        if not isinstance(metadata, dict):
            raise TypeError(
                f"Agent.get_metadata() must return a dict, got {type(metadata).__name__}"
            )

        name = metadata.get("name", "")
        if not name or not isinstance(name, str) or not name.strip():
            raise ValueError(
                f"Agent metadata must contain a non-empty 'name' string. Got: {metadata!r}"
            )

        description = metadata.get("description", "")
        if not description or not isinstance(description, str) or not description.strip():
            raise ValueError(
                f"Agent '{name}' metadata must contain a non-empty 'description' string. "
                f"An empty description would bypass the Validation Gate overlap check."
            )

        return {"name": name.strip(), "description": description.strip()}

    def _check_description_overlap(self, name: str, description: str) -> None:
        """Check new agent description against existing agents for overlap.

        Skips comparison when either description is shorter than
        ``_MIN_DESCRIPTION_LENGTH`` characters (cosine similarity is unreliable
        on very short texts).

        Args:
            name: Name of the agent being registered.
            description: Description of the agent being registered.

        Raises:
            ValueError: If overlap with any existing agent exceeds threshold.
        """
        if len(description) < _MIN_DESCRIPTION_LENGTH:
            logger.debug(
                "Skipping overlap check for '%s': description too short (%d chars)",
                name,
                len(description),
            )
            return

        for existing_name, existing_agent in self._agents.items():
            if existing_name == name:
                continue

            existing_desc = existing_agent.get_metadata().get("description", "")
            if len(existing_desc) < _MIN_DESCRIPTION_LENGTH:
                continue

            sim = _compute_cosine_similarity(description, existing_desc)
            if sim > self.similarity_threshold:
                raise ValueError(
                    f"Agent registration rejected: description similarity between "
                    f"'{name}' and existing agent '{existing_name}' is {sim:.1%}, "
                    f"which exceeds the maximum allowed threshold of "
                    f"{self.similarity_threshold:.0%}."
                )

    async def _probe_test_async(self, agent: BaseAgent, name: str) -> None:
        """Run a real async functional probe on the agent with timeout.

        Calls ``agent.process_request("__probe_test__", "SYSTEM_PROBE")``
        with a hard timeout of ``_PROBE_TIMEOUT_SECONDS`` to verify:
          1. The method is callable and is an async coroutine.
          2. It returns within the timeout window.
          3. It returns a string (non-None).

        Args:
            agent: Agent instance to probe.
            name: Agent name (for error messages).

        Raises:
            ValueError: If the probe fails for any reason.
        """
        if not hasattr(agent, "process_request") or not callable(agent.process_request):
            raise ValueError(f"Agent '{name}' must implement callable process_request()")

        if not inspect.iscoroutinefunction(agent.process_request):
            raise ValueError(
                f"Agent '{name}' process_request() must be an async coroutine method"
            )

        try:
            result = await asyncio.wait_for(
                agent.process_request("__probe_test__", "SYSTEM_PROBE"),
                timeout=_PROBE_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            raise ValueError(
                f"Agent '{name}' probe test timed out after {_PROBE_TIMEOUT_SECONDS}s. "
                f"The agent's process_request() must respond within the timeout window."
            )
        except Exception as exc:
            raise ValueError(
                f"Agent '{name}' probe test raised an exception: {exc}"
            ) from exc

        if not isinstance(result, str):
            raise ValueError(
                f"Agent '{name}' process_request() must return a str, "
                f"got {type(result).__name__}"
            )

    @staticmethod
    def _probe_test_sync(agent: BaseAgent, name: str) -> None:
        """Run a lightweight synchronous probe (interface check only).

        Verifies that the agent has a callable async ``process_request`` method
        without actually invoking it. Used by the synchronous ``register()``
        method when no event loop is available.

        Args:
            agent: Agent instance to probe.
            name: Agent name (for error messages).

        Raises:
            ValueError: If interface check fails.
        """
        if not hasattr(agent, "process_request") or not callable(agent.process_request):
            raise ValueError(f"Agent '{name}' must implement callable process_request()")

        if not inspect.iscoroutinefunction(agent.process_request):
            raise ValueError(
                f"Agent '{name}' process_request() must be an async coroutine method"
            )

    def _commit_registration(
        self, agent: BaseAgent, name: str, description: str
    ) -> None:
        """Commit agent to the registry after all validation passes.

        Args:
            agent: Validated agent instance.
            name: Agent name key.
            description: Agent description (for logging).
        """
        if name in self._agents:
            logger.warning(
                "Overwriting existing agent registration: %s",
                name,
                extra={"session_id": "SYSTEM"},
            )

        self._agents[name] = agent
        logger.info(
            "Agent registered successfully [Validation Gate PASSED]: name=%s | description=%s",
            name,
            description[:80],
            extra={"session_id": "SYSTEM"},
        )

    # ------------------------------------------------------------------
    # Lookup & Listing
    # ------------------------------------------------------------------

    def lookup(self, name: str) -> Optional[BaseAgent]:
        """Look up an agent by its registered name."""
        agent: Optional[BaseAgent] = self._agents.get(name)
        if agent is None:
            logger.warning(
                "Agent lookup miss: name=%s",
                name,
                extra={"session_id": "SYSTEM"},
            )
        return agent

    def list_agents(self) -> list[dict[str, str]]:
        """Return metadata for every registered agent."""
        return [agent.get_metadata() for agent in self._agents.values()]

    def __len__(self) -> int:
        """Return the number of registered agents."""
        return len(self._agents)
