import { useState, useMemo } from "react";
import type { Conversation } from "../App";
import { Search, Plus } from "lucide-react";
import { Sun, Moon } from "lucide-react";


interface ConversationListProps {
  conversations: Conversation[];
  selectedConversationId: string;
  onSelectConversation: (id: string) => void;
  onNewConversation: () => void;
  isOpen: boolean;
  processingConversationIds: Set<string>;
  theme: "light" | "dark";
  toggleTheme: () => void;
}

type ConversationStatus = NonNullable<Conversation["status"]>;

const STATUS_STYLES: Record<
  ConversationStatus,
  { fill: string; ring: string; border: string; label: string }
> = {
  clean: {
    fill: "bg-emerald-500",
    ring: "ring-2 ring-emerald-500/30",
    border: "border-emerald-500/60",
    label: "No open findings",
  },
  findings: {
    fill: "bg-amber-500",
    ring: "ring-2 ring-amber-500/30",
    border: "border-amber-500/60",
    label: "Has findings",
  },
  critical: {
    fill: "bg-red-500",
    ring: "ring-2 ring-red-500/30",
    border: "border-red-500/60",
    label: "Critical finding",
  },
};

export function ConversationList({
  conversations,
  selectedConversationId,
  onSelectConversation,
  onNewConversation,
  isOpen,
  processingConversationIds,
  theme,
  toggleTheme,
}: ConversationListProps) {
  const [query, setQuery] = useState("");

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return conversations
      .filter(
        (c) =>
          !q ||
          c.title.toLowerCase().includes(q) ||
          c.lastMessage.toLowerCase().includes(q),
      )
      .sort((a, b) => b.timestamp.getTime() - a.timestamp.getTime());
  }, [conversations, query]);

  const formatTime = (date: Date) => {
    const now = new Date();
    const diff = now.getTime() - date.getTime();
    const minutes = Math.floor(diff / 60000);
    const hours = Math.floor(diff / 3600000);
    const days = Math.floor(diff / 86400000);

    if (minutes < 1) return "Just now";
    if (minutes < 60) return `${minutes}m`;
    if (hours < 24) return `${hours}h`;
    return `${days}d`;
  };

  return (
    <nav
      aria-label="Conversations"
      aria-hidden={!isOpen}
      className={`bg-slate-950/60 backdrop-blur-xl border-white/10 flex-shrink-0 overflow-hidden transition-all duration-300 ease-in-out ${
        isOpen ? "w-80 border-r" : "w-0 border-r-0"
      }`}
    >
      <div className="w-80 h-full flex flex-col">
        {/* New chat + search */}
        <div className="p-4 border-b border-white/10 space-y-3">
          <button
            onClick={onNewConversation}
            className="w-full bg-indigo-500 hover:bg-indigo-400 rounded-lg py-2.5 flex items-center justify-center gap-2 transition-colors"
          >
            <Plus className="w-4 h-4 text-white" />
            <span className="text-white text-sm font-medium">New Review</span>
          </button>
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search conversations..."
              className="w-full bg-white/5 border border-white/10 rounded-lg pl-9 pr-3 py-2.5 text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:border-indigo-400/50 focus:ring-1 focus:ring-indigo-400/30 transition-colors"
            />
          </div>
        </div>

        {/* Conversations */}
        <div className="flex-1 overflow-y-auto">
          {filtered.length === 0 && (
            <p className="text-sm text-slate-500 text-center mt-8">
              No conversations found
            </p>
          )}
          {filtered.map((conversation) => {
            const status = STATUS_STYLES[conversation.status ?? "clean"];
            const isSelected = selectedConversationId === conversation.id;
            const isActive = processingConversationIds.has(conversation.id);
            return (
              <button
                key={conversation.id}
                onClick={() => onSelectConversation(conversation.id)}
                title={isActive ? "Agent is working..." : status.label}
                className={`w-full p-4 border-b border-white/5 hover:bg-white/5 transition-colors text-left ${
                  isSelected
                    ? "bg-indigo-500/10 border-l-2 border-l-indigo-400"
                    : ""
                }`}
              >
                <div className="flex items-center gap-2 mb-1.5">
                  <span
                    className={`w-2 h-2 rounded-full shrink-0 transition-all duration-300 ${
                      isActive
                        ? `${status.fill} ${status.ring} animate-pulse`
                        : `bg-transparent border-2 ${status.border}`
                    }`}
                    aria-hidden
                  />
                  <h3 className="text-slate-100 text-sm truncate flex-1">
                    {conversation.title}
                  </h3>
                  <span className="text-xs text-slate-500 shrink-0">
                    {formatTime(conversation.timestamp)}
                  </span>
                </div>
                <p className="text-sm text-slate-400 truncate pl-4">
                  {conversation.lastMessage}
                </p>
              </button>
            );
          })}
        </div>

        {/* Footer */}
        <div className="p-3 border-t border-slate-200 dark:border-white/10 flex items-center justify-between">
          <div className="text-xs text-slate-400 dark:text-slate-500">
            {conversations.length} conversation
            {conversations.length === 1 ? "" : "s"}
          </div>
          <button
            onClick={toggleTheme}
            aria-label={
              theme === "dark" ? "Switch to light mode" : "Switch to dark mode"
            }
            className="relative w-8 h-8 text-slate-500 hover:text-slate-900 dark:text-slate-400 dark:hover:text-slate-200 transition-colors hover:bg-black/5 dark:hover:bg-white/5 rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400"
          >
            <Sun
              className={`w-4 h-4 absolute inset-0 m-auto transition-all duration-300 ${
                theme === "dark"
                  ? "opacity-100 rotate-0 scale-100"
                  : "opacity-0 -rotate-90 scale-50"
              }`}
              aria-hidden
            />
            <Moon
              className={`w-4 h-4 absolute inset-0 m-auto transition-all duration-300 ${
                theme === "dark"
                  ? "opacity-0 rotate-90 scale-50"
                  : "opacity-100 rotate-0 scale-100"
              }`}
              aria-hidden
            />
          </button>
        </div>
      </div>
    </nav>
  );
}
