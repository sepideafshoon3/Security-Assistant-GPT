import type { Conversation } from '../App';
import { Search, Plus } from 'lucide-react';

interface ConversationListProps {
  conversations: Conversation[];
  selectedConversationId: string;
  onSelectConversation: (id: string) => void;
  onNewConversation: () => void;
}

export function ConversationList({ conversations, selectedConversationId, onSelectConversation, onNewConversation }: ConversationListProps) {
  const formatTime = (date: Date) => {
    const now = new Date();
    const diff = now.getTime() - date.getTime();
    const minutes = Math.floor(diff / 60000);
    const hours = Math.floor(diff / 3600000);
    const days = Math.floor(diff / 86400000);

    if (minutes < 60) return `${minutes}m`;
    if (hours < 24) return `${hours}h`;
    return `${days}d`;
  };

  return (
    <div className="w-80 bg-black/20 backdrop-blur-xl border-r border-white/10 flex flex-col shadow-2xl">
      {/* Search & New Chat */}
      <div className="p-4 border-b border-white/10 space-y-3">
        <button
          onClick={onNewConversation}
          className="w-full bg-gradient-to-r from-cyan-500 to-green-500 hover:from-cyan-400 hover:to-green-400 rounded-xl py-2.5 flex items-center justify-center gap-2 transition-all shadow-lg shadow-cyan-500/50 hover:shadow-cyan-500/70 hover:scale-[1.02]"
        >
          <Plus className="w-5 h-5 text-black" />
          <span className="text-black">New Chat</span>
        </button>
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-cyan-400/70" />
          <input
            type="text"
            placeholder="Search conversations..."
            className="w-full bg-white/5 backdrop-blur-sm border border-white/10 rounded-xl pl-10 pr-4 py-2.5 text-sm text-gray-200 placeholder-gray-500 focus:outline-none focus:border-cyan-400/50 focus:ring-2 focus:ring-cyan-400/20 focus:bg-white/10 transition-all"
          />
        </div>
      </div>

      {/* Conversations */}
      <div className="flex-1 overflow-y-auto">
        {conversations.map((conversation) => (
          <button
            key={conversation.id}
            onClick={() => onSelectConversation(conversation.id)}
            className={`w-full p-4 border-b border-white/5 hover:bg-white/5 transition-all text-left group ${
              selectedConversationId === conversation.id 
                ? 'bg-gradient-to-r from-cyan-500/20 to-green-500/20 backdrop-blur-sm border-l-2 border-l-cyan-400 shadow-lg shadow-cyan-500/10' 
                : ''
            }`}
          >
            <div className="flex items-center justify-between mb-2">
              <h3 className="text-gray-100 truncate group-hover:text-cyan-300 transition-colors">{conversation.title}</h3>
              <span className="text-xs text-cyan-400/60 ml-2">{formatTime(conversation.timestamp)}</span>
            </div>
            <p className="text-sm text-gray-400 truncate">{conversation.lastMessage}</p>
            <div className="text-xs font-mono text-green-400/40 mt-1 group-hover:text-green-400/60 transition-colors">
              {conversation.id}
            </div>
          </button>
        ))}
      </div>

      {/* Footer */}
      <div className="p-4 border-t border-white/10 bg-black/20 backdrop-blur-sm">
        <div className="text-xs text-center text-cyan-400/60 font-mono flex items-center justify-center gap-2">
          <span className="animate-pulse text-green-400">●</span> 
        </div>
      </div>
    </div>
  );
}
