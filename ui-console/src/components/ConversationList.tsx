import { useState, useMemo } from "react";
import type { Conversation } from "../App";
import { Search, Plus, Sun, Moon, X } from "lucide-react";
import { cn } from "./ui/utils";

interface ConversationListProps {
  conversations: Conversation[];
  selectedConversationId: string;
  onSelectConversation: (id: string) => void;
  onNewConversation: () => void;
  isOpen: boolean;
  isMobile: boolean;
  onClose: () => void;
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
    fill: "bg-status-success",
    ring: "ring-2 ring-status-success/30",
    border: "border-status-success/60",
    label: "No open findings",
  },
  findings: {
    fill: "bg-status-warning",
    ring: "ring-2 ring-status-warning/30",
    border: "border-status-warning/60",
    label: "Has findings",
  },
  critical: {
    fill: "bg-status-danger",
    ring: "ring-2 ring-status-danger/30",
    border: "border-status-danger/60",
    label: "Critical finding",
  },
};

export function ConversationList({
  conversations,
  selectedConversationId,
  onSelectConversation,
  onNewConversation,
  isOpen,
  isMobile,
  onClose,
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

  const handleSelect = (id: string) => {
    onSelectConversation(id);
    if (isMobile) onClose();
  };

  const handleNew = () => {
    onNewConversation();
    if (isMobile) onClose();
  };

  return (
    <>
      {/* Mobile backdrop: tapping outside the drawer closes it */}
      {isMobile && (
        <div
          onClick={onClose}
          aria-hidden
          className={cn(
            "fixed inset-0 top-16 z-20 bg-black/50 backdrop-blur-sm transition-opacity duration-300",
            isOpen ? "opacity-100" : "opacity-0 pointer-events-none",
          )}
        />
      )}

      <nav
        aria-label="Conversations"
        aria-hidden={!isOpen}
        className={cn(
          "bg-surface-deep/95 md:bg-surface-deep/60 backdrop-blur-xl border-border overflow-hidden transition-all duration-300 ease-in-out",
          isMobile
            ? cn(
                "fixed top-16 bottom-0 left-0 z-30 w-[85vw] max-w-80 border-r shadow-2xl shadow-black/40",
                isOpen ? "translate-x-0" : "-translate-x-full",
              )
            : cn(
                "flex-shrink-0 relative",
                isOpen ? "w-80 border-r" : "w-0 border-r-0",
              ),
        )}
      >
        <div className="w-[85vw] max-w-80 md:w-80 h-full flex flex-col">
          {/* New chat + search */}
          <div className="p-4 border-b border-border space-y-3">
            <div className="flex items-center justify-between gap-2 md:hidden">
              <span className="text-sm text-fg-secondary font-medium">
                Conversations
              </span>
              <button
                onClick={onClose}
                aria-label="Close sidebar"
                className="text-fg-tertiary hover:text-fg-primary p-1.5 rounded-lg hover:bg-secondary transition-colors"
              >
                <X className="w-4 h-4" aria-hidden />
              </button>
            </div>
            <button
              onClick={handleNew}
              className="w-full bg-accent hover:bg-accent-hover rounded-lg py-2.5 flex items-center justify-center gap-2 transition-colors"
            >
              <Plus className="w-4 h-4 text-white" />
              <span className="text-white text-sm font-medium">New Review</span>
            </button>
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-fg-faint" />
              <input
                type="text"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search conversations..."
                className="w-full bg-input-background border border-border rounded-lg pl-9 pr-3 py-2.5 text-sm text-fg-secondary placeholder-fg-faint focus:outline-none focus:border-accent-hover/50 focus:ring-1 focus:ring-accent-hover/30 transition-colors"
              />
            </div>
          </div>

          {/* Conversations */}
          <div className="flex-1 overflow-y-auto">
            {filtered.length === 0 && (
              <p className="text-sm text-fg-faint text-center mt-8">
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
                  onClick={() => handleSelect(conversation.id)}
                  title={isActive ? "Agent is working..." : status.label}
                  className={cn(
                    "w-full p-4 border-b border-border/60 hover:bg-secondary transition-colors text-left",
                    isSelected &&
                      "bg-accent-soft border-l-2 border-l-accent-hover",
                  )}
                >
                  <div className="flex items-center gap-2 mb-1.5">
                    <span
                      className={cn(
                        "w-2 h-2 rounded-full shrink-0 transition-all duration-300",
                        isActive
                          ? cn(status.fill, status.ring, "animate-pulse")
                          : cn("bg-transparent border-2", status.border),
                      )}
                      aria-hidden
                    />
                    <h3 className="text-fg-primary text-sm truncate flex-1">
                      {conversation.title}
                    </h3>
                    <span className="text-xs text-fg-faint shrink-0">
                      {formatTime(conversation.timestamp)}
                    </span>
                  </div>
                  <p className="text-sm text-fg-tertiary truncate pl-4">
                    {conversation.lastMessage}
                  </p>
                </button>
              );
            })}
          </div>

          {/* Footer. Note: the rest of this sidebar is unconditionally dark
            (bg-surface-deep/60 etc.), but this row still carries light/dark
            pairs from before that change — pre-existing, left as-is here. */}
          <div className="p-3 border-t border-border flex items-center justify-between">
            <div className="text-xs text-fg-faint">
              {conversations.length} conversation
              {conversations.length === 1 ? "" : "s"}
            </div>
            <button
              onClick={toggleTheme}
              aria-label={
                theme === "dark"
                  ? "Switch to light mode"
                  : "Switch to dark mode"
              }
              className="relative w-8 h-8 text-fg-tertiary hover:text-fg-primary transition-colors hover:bg-secondary rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-hover"
            >
              <Sun
                className={cn(
                  "w-4 h-4 absolute inset-0 m-auto transition-all duration-300",
                  theme === "dark"
                    ? "opacity-100 rotate-0 scale-100"
                    : "opacity-0 -rotate-90 scale-50",
                )}
                aria-hidden
              />
              <Moon
                className={cn(
                  "w-4 h-4 absolute inset-0 m-auto transition-all duration-300",
                  theme === "dark"
                    ? "opacity-0 rotate-90 scale-50"
                    : "opacity-100 rotate-0 scale-100",
                )}
                aria-hidden
              />
            </button>
          </div>
        </div>
      </nav>
    </>
  );
}
