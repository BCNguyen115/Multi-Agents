'use client';

import React from 'react';
import { Cloud, Database, Globe } from 'lucide-react';

interface AgentSelectorInChatProps {
  selectedAgent: string;
  onSelectAgent: (agentId: string) => void;
}

export function AgentSelectorInChat({
  selectedAgent,
  onSelectAgent,
}: AgentSelectorInChatProps) {
  const agents = [
    { id: 'RAG Agent', name: 'RAG Agent', icon: Cloud, desc: 'Tra cứu hợp đồng & tài liệu' },
    { id: 'Data Agent', name: 'Data Agent', icon: Database, desc: 'Phân tích CSV & Tạo Dashboard' },
    { id: 'Search Agent', name: 'Search Agent', icon: Globe, desc: 'Tìm kiếm web thời gian thực' },
  ];

  return (
    <div className="px-6 py-2.5 border-b border-border bg-surface/80 backdrop-blur-sm flex items-center justify-between sticky top-0 z-10">
      <div className="flex items-center gap-2">
        {agents.map((agent) => {
          const Icon = agent.icon;
          const isActive =
            selectedAgent === agent.id ||
            selectedAgent.includes(agent.name.split(' ')[0]) ||
            selectedAgent.toLowerCase().includes(agent.id.toLowerCase().split(' ')[0]);

          return (
            <button
              key={agent.id}
              onClick={() => onSelectAgent(agent.id)}
              className={`flex items-center gap-2 px-3.5 py-1.5 text-xs font-medium rounded-xl transition-all cursor-pointer ${
                isActive
                  ? 'bg-accent-primary text-white ring-2 ring-accent-primary/30 font-semibold shadow-xs'
                  : 'bg-surface-raised hover:bg-surface-overlay text-foreground-secondary border border-border'
              }`}
              title={agent.desc}
            >
              <Icon className={`w-3.5 h-3.5 ${isActive ? 'text-white' : 'text-accent-primary'}`} />
              <span>{agent.name}</span>
            </button>
          );
        })}
      </div>
      <div className="text-[11px] text-foreground-muted italic hidden sm:block">
        Active: <span className="font-semibold text-foreground-secondary">{selectedAgent}</span>
      </div>
    </div>
  );
}
