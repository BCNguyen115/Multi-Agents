/** The agents a person may pick, by the name the chat box uses for each mode, against the list their department's policy allows (`me.allowed_agents`; null = every agent). */
export const MODE_AGENT_ID: Record<string, string> = {
  'RAG Agent': 'rag_agent',
  'Data Agent': 'data_agent',
  'Search Agent': 'search_agent',
  'Database Agent': 'db_agent',
  'Coding Agent': 'coding_agent',
};

export const AGENT_MODES = Object.keys(MODE_AGENT_ID);

export function agentModeAllowed(allowed: string[] | null | undefined, mode: string): boolean {
  if (!allowed) return true;
  const id = MODE_AGENT_ID[mode];
  return id === undefined || allowed.includes(id);
}

/** The first mode the policy allows (the default for someone whose current mode was taken away); `fallback` when it allows none of them. */
export function firstAllowedMode(allowed: string[] | null | undefined, fallback: string): string {
  return AGENT_MODES.find((mode) => agentModeAllowed(allowed, mode)) ?? fallback;
}
