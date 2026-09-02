"""Agent Versioning & Prompt Snapshots module — CI/CD Rollback Manager.

Provides thread-safe snapshot management and atomic rollback capabilities
when Langfuse / eval metrics detect a quality score drop exceeding 15%.

Key improvements over the initial implementation:
  - Thread-safe mutations via ``threading.Lock``.
  - Atomic rollback (poisoned snapshot removed from history).
  - UUID-based snapshot IDs (no timestamp collisions).
  - Semantic version validation (``vX.Y.Z`` with optional pre-release).
  - Optional JSON-file persistence for crash recovery.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

from src.shared.logger import get_logger

logger: logging.Logger = get_logger(__name__)

# Regex for validating semantic version strings (vX.Y.Z with optional pre-release)
_SEMVER_RE = re.compile(
    r"^v?(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)"
    r"(?:-(?P<prerelease>[a-zA-Z0-9]+(?:\.[a-zA-Z0-9]+)*))?$"
)

# Default directory for persistent snapshot storage
_DEFAULT_SNAPSHOT_DIR = os.path.join("data", "snapshots")


def _validate_semver(version: str) -> str:
    """Validate and normalize a semantic version string.

    Accepts formats: ``v1.0.0``, ``1.0.0``, ``v1.2.0-rc1``, ``v2.0.0-beta.1``.

    Args:
        version: Version string to validate.

    Returns:
        str: Normalized version string with 'v' prefix.

    Raises:
        ValueError: If the version string does not match semver format.
    """
    match = _SEMVER_RE.match(version)
    if not match:
        raise ValueError(
            f"Invalid semantic version '{version}'. "
            f"Expected format: vX.Y.Z or vX.Y.Z-prerelease (e.g., v1.0.0, v1.2.0-rc1)"
        )
    # Normalize to always have 'v' prefix
    if not version.startswith("v"):
        return f"v{version}"
    return version


@dataclass
class AgentSnapshot:
    """Dataclass representing a static versioned snapshot of an Agent's state.

    Attributes:
        snapshot_id: Unique snapshot identifier (UUID-based).
        agent_name: Target agent name.
        prompt_version: Semantic version string (e.g. 'v1.0.0').
        llm_model: Underlying LLM model identifier.
        registered_tools: List of active MCP tools attached to agent.
        quality_baseline: Baseline quality score (0.0 to 1.0).
        created_at: ISO timestamp of snapshot creation.
    """

    snapshot_id: str
    agent_name: str
    prompt_version: str
    llm_model: str
    registered_tools: list[str] = field(default_factory=list)
    quality_baseline: float = 0.90
    created_at: str = field(default_factory=lambda: "")

    def __post_init__(self) -> None:
        """Set creation timestamp if not already set."""
        if not self.created_at:
            import time
            self.created_at = time.strftime("%Y-%m-%dT%H:%M:%S%z")


class SnapshotManager:
    """Manages agent prompt/model snapshots and handles automated CI/CD rollback.

    Thread-safe: All mutations are guarded by an internal lock to prevent
    race conditions from concurrent request handlers.

    Attributes:
        _snapshots: Dict mapping agent_name → list of historical AgentSnapshots.
        _active_snapshot: Dict mapping agent_name → current active AgentSnapshot.
        _lock: Threading lock for safe concurrent access.
        _persist_dir: Optional directory for JSON persistence.
    """

    def __init__(self, persist_dir: Optional[str] = None) -> None:
        """Initialise snapshot store.

        Args:
            persist_dir: Optional directory path for JSON file persistence.
                         Pass ``None`` to use in-memory only (default).
        """
        self._snapshots: dict[str, list[AgentSnapshot]] = {}
        self._active_snapshot: dict[str, AgentSnapshot] = {}
        self._lock = threading.Lock()
        self._persist_dir: Optional[str] = persist_dir

        if persist_dir:
            Path(persist_dir).mkdir(parents=True, exist_ok=True)
            self._load_from_disk()

    def create_snapshot(
        self,
        agent_name: str,
        prompt_version: str,
        llm_model: str,
        registered_tools: Optional[list[str]] = None,
        quality_baseline: float = 0.90,
    ) -> AgentSnapshot:
        """Create and record a new versioned snapshot for an agent.

        Thread-safe. Validates semantic version format before creating.

        Args:
            agent_name: Name of the agent.
            prompt_version: Semantic version (e.g. 'v1.0.0', 'v1.2.0-rc1').
            llm_model: LLM model string.
            registered_tools: MCP tools assigned.
            quality_baseline: Expected evaluation baseline score (0.0 to 1.0).

        Returns:
            AgentSnapshot: The created snapshot.

        Raises:
            ValueError: If ``prompt_version`` is not valid semver or
                        ``quality_baseline`` is out of range.
        """
        # Validate inputs
        normalized_version = _validate_semver(prompt_version)

        if not (0.0 <= quality_baseline <= 1.0):
            raise ValueError(
                f"quality_baseline must be between 0.0 and 1.0, got {quality_baseline}"
            )

        if not agent_name or not agent_name.strip():
            raise ValueError("agent_name must be a non-empty string")

        snapshot_id = f"{agent_name}_{normalized_version}_{uuid.uuid4().hex[:12]}"
        snapshot = AgentSnapshot(
            snapshot_id=snapshot_id,
            agent_name=agent_name.strip(),
            prompt_version=normalized_version,
            llm_model=llm_model,
            registered_tools=registered_tools or [],
            quality_baseline=quality_baseline,
        )

        with self._lock:
            if agent_name not in self._snapshots:
                self._snapshots[agent_name] = []

            self._snapshots[agent_name].append(snapshot)
            self._active_snapshot[agent_name] = snapshot
            self._save_to_disk_locked(agent_name)

        logger.info(
            "Created agent snapshot: id=%s | version=%s | baseline=%.2f",
            snapshot_id,
            normalized_version,
            quality_baseline,
            extra={"session_id": "SYSTEM"},
        )
        return snapshot

    def get_active_snapshot(self, agent_name: str) -> Optional[AgentSnapshot]:
        """Retrieve the currently active snapshot for an agent (thread-safe)."""
        with self._lock:
            return self._active_snapshot.get(agent_name)

    def get_snapshot_history(self, agent_name: str) -> list[AgentSnapshot]:
        """Retrieve the full snapshot history for an agent (thread-safe copy)."""
        with self._lock:
            return list(self._snapshots.get(agent_name, []))

    def evaluate_quality_and_rollback(
        self, agent_name: str, current_quality_score: float
    ) -> tuple[bool, Optional[AgentSnapshot], str]:
        """Check quality score against baseline and atomically rollback if dropped > 15%.

        Atomicity guarantee: If rollback is triggered, the poisoned (current)
        snapshot is removed from history, and the previous safe snapshot becomes
        active. This prevents repeated rollbacks from oscillating between bad states.

        Args:
            agent_name: Target agent name.
            current_quality_score: Measured quality score (0.0 - 1.0).

        Returns:
            tuple[bool, Optional[AgentSnapshot], str]:
                ``(rolled_back, active_snapshot, reason_message)``
        """
        with self._lock:
            active = self._active_snapshot.get(agent_name)
            if active is None:
                return False, None, "No active snapshot found for agent"

            baseline = active.quality_baseline
            if baseline <= 0:
                return False, active, "Baseline score is 0; skipping check"

            drop_percent = (baseline - current_quality_score) / baseline

            if drop_percent > 0.15:  # Quality dropped by > 15%
                history = self._snapshots.get(agent_name, [])
                if len(history) > 1:
                    # Atomic rollback: remove the poisoned snapshot, restore previous
                    poisoned = history.pop()  # Remove the bad snapshot from history
                    previous_safe = history[-1]
                    self._active_snapshot[agent_name] = previous_safe
                    self._save_to_disk_locked(agent_name)

                    msg = (
                        f"AUTOMATED ROLLBACK TRIGGERED: Agent '{agent_name}' quality "
                        f"score dropped by {drop_percent:.1%} "
                        f"(current={current_quality_score:.2f}, baseline={baseline:.2f}). "
                        f"Removed poisoned snapshot '{poisoned.snapshot_id}' and restored "
                        f"'{previous_safe.snapshot_id}' (version {previous_safe.prompt_version})."
                    )
                    logger.warning(msg, extra={"session_id": "SYSTEM"})
                    return True, previous_safe, msg
                else:
                    msg = (
                        f"QUALITY DROP WARNING: Agent '{agent_name}' score dropped "
                        f"by {drop_percent:.1%}, but no previous snapshot is available "
                        f"for rollback."
                    )
                    logger.warning(msg, extra={"session_id": "SYSTEM"})
                    return False, active, msg

            return (
                False,
                active,
                f"Quality check passed (score={current_quality_score:.2f}, "
                f"baseline={baseline:.2f})",
            )

    # ------------------------------------------------------------------
    # Persistence (optional)
    # ------------------------------------------------------------------

    def _save_to_disk_locked(self, agent_name: str) -> None:
        """Persist snapshots for a given agent to a JSON file.

        Must be called with ``self._lock`` held.

        Args:
            agent_name: Agent whose snapshots to persist.
        """
        if not self._persist_dir:
            return

        filepath = os.path.join(self._persist_dir, f"{agent_name}_snapshots.json")
        data = {
            "agent_name": agent_name,
            "active_snapshot_id": (
                self._active_snapshot[agent_name].snapshot_id
                if agent_name in self._active_snapshot
                else None
            ),
            "snapshots": [asdict(s) for s in self._snapshots.get(agent_name, [])],
        }

        try:
            tmp_path = filepath + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            # Atomic rename (on most OSes) to prevent partial writes
            os.replace(tmp_path, filepath)
        except OSError as exc:
            logger.warning(
                "Failed to persist snapshots for '%s': %s",
                agent_name,
                exc,
                extra={"session_id": "SYSTEM"},
            )

    def _load_from_disk(self) -> None:
        """Load all persisted snapshots from the persist directory.

        Called once during ``__init__`` if ``persist_dir`` is set.
        """
        if not self._persist_dir or not os.path.isdir(self._persist_dir):
            return

        for filename in os.listdir(self._persist_dir):
            if not filename.endswith("_snapshots.json"):
                continue

            filepath = os.path.join(self._persist_dir, filename)
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)

                agent_name = data["agent_name"]
                snapshots = [
                    AgentSnapshot(**snap_data) for snap_data in data.get("snapshots", [])
                ]
                active_id = data.get("active_snapshot_id")

                self._snapshots[agent_name] = snapshots

                # Restore active snapshot
                active = None
                for s in snapshots:
                    if s.snapshot_id == active_id:
                        active = s
                        break
                if active:
                    self._active_snapshot[agent_name] = active
                elif snapshots:
                    self._active_snapshot[agent_name] = snapshots[-1]

                logger.info(
                    "Loaded %d snapshots for agent '%s' from disk",
                    len(snapshots),
                    agent_name,
                    extra={"session_id": "SYSTEM"},
                )
            except Exception as exc:
                logger.warning(
                    "Failed to load snapshots from '%s': %s",
                    filepath,
                    exc,
                    extra={"session_id": "SYSTEM"},
                )
