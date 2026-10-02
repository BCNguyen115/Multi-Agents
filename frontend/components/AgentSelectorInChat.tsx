'use client';

import React from 'react';
import { Cloud, Database, Globe } from 'lucide-react';
import { t, useLang } from '../lib/i18n';

interface AgentSelectorInChatProps {
  selectedAgent: string;
  onSelectAgent: (agentId: string) => void;
}

export function AgentSelectorInChat({
  selectedAgent,
  onSelectAgent,
}: AgentSelectorInChatProps) {
  const [lang] = useLang();
  const agents = [
    { id: 'RAG Agent', name: 'RAG Agent', icon: Cloud, desc: t(lang, 'agent.ragDescLong') },
    { id: 'Data Agent', name: 'Data Agent', icon: Database, desc: t(lang, 'agent.dataDescLong') },
    { id: 'Search Agent', name: 'Search Agent', icon: Globe, desc: t(lang, 'agent.searchDescLong') },
  ];

  return (
    <div className="px-6 py-2.5 border-b border-border bg-surface flex items-center justify-between sticky top-0 z-10">
      <div className="flex items-center gap-2">
        {agents.map((agent) => {
          const Icon = agent.icon;
          // exact id: 'Database Agent' must not light up 'Data Agent'
          const isActive = selectedAgent === agent.id;

          return (
            <button
              key={agent.id}
              type="button"
              aria-pressed={isActive}
              onClick={() => onSelectAgent(agent.id)}
              className={`flex items-center gap-2 px-3.5 py-1.5 text-xs font-medium rounded-xl transition-colors cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-primary/40 ${
                isActive
                  ? 'bg-accent-primary text-white font-semibold'
                  : 'bg-surface-raised hover:bg-surface-overlay text-foreground-secondary border border-border'
              }`}
              title={agent.desc}
            >
              <Icon className={`w-3.5 h-3.5 ${isActive ? 'text-white' : 'text-accent-primary'}`} aria-hidden="true" />
              <span>{agent.name}</span>
            </button>
          );
        })}
      </div>
      <div className="text-xs text-foreground-muted italic hidden sm:block">
        <span className="font-semibold text-foreground-secondary">{t(lang, 'agent.active', { agent: selectedAgent })}</span>
      </div>
    </div>
  );
}
