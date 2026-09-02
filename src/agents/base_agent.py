"""Abstract Base Class for all agents in the Multi-Agent system.

Every specialised agent (RAG, QA, etc.) MUST inherit from ``BaseAgent``
and implement its abstract methods.  The ``get_metadata()`` method is
critical for the Orchestrator's intent-classification step — its
``description`` field must be explicit enough for an LLM to correctly
match user intents to agent capabilities.

Usage:
    class MyAgent(BaseAgent):
        async def process_request(self, query, session_id):
            ...
        def get_metadata(self):
            ...
"""

from abc import ABC, abstractmethod


class BaseAgent(ABC):
    """Abstract base class that every agent must implement.

    Subclasses are required to provide:
      - ``process_request``: core logic for handling a user query.
      - ``get_metadata``: a dict describing the agent's capabilities so
        the Orchestrator can route requests accurately.
    """

    @abstractmethod
    async def process_request(self, query: str, session_id: str) -> str:
        """Process a user query and return a textual response.

        This is the main entry point called by the Orchestrator after
        intent classification selects this agent.

        Args:
            query: The end-user's natural-language question or command.
            session_id: Correlation ID for end-to-end request tracing.

        Returns:
            str: The agent's response text.
        """
        ...

    @abstractmethod
    def get_metadata(self) -> dict[str, str]:
        """Return metadata describing this agent's capabilities.

        The metadata **must** contain at minimum:
          - ``name``:  Short, unique agent identifier (e.g. ``"rag_agent"``).
          - ``description``: A concise, LLM-friendly description of what
            this agent does.  This text is fed directly into the
            Orchestrator's intent-classification prompt, so clarity is
            paramount.

        Returns:
            dict[str, str]: Agent metadata dictionary.
        """
        ...
