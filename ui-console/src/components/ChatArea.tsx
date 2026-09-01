import { useState, useRef, useEffect, useLayoutEffect } from "react";
import type { Conversation } from "../App";
import {
  Send,
  MoreVertical,
  Trash2,
  Copy,
  Check,
  RotateCcw,
  Pencil,
} from "lucide-react";
import { MessageContent } from "./MessageContent";

interface ChatAreaProps {
  conversation: Conversation | null;
  onSendMessage: (text: string) => void;
  onResendMessage: (messageId: string) => void;
}

const GREETINGS: Record<
  "morning" | "afternoon" | "evening" | "night",
  { title: string; subtitle: string }[]
> = {
  morning: [
    { title: "Good morning ☀️", subtitle: "What are we breaking today?" },
    {
      title: "Morning, dev",
      subtitle: "Coffee's brewing — so is the next finding.",
    },
    {
      title: "Rise and grep",
      subtitle: "Let's see what yesterday's build left behind.",
    },
  ],
  afternoon: [
    {
      title: "Good afternoon",
      subtitle: "Mid-day check — any weird logs yet?",
    },
    { title: "Hey", subtitle: "Let's find something worth patching." },
    { title: "Afternoon", subtitle: "Paste a repo, a diff, or just say hi." },
  ],
  evening: [
    {
      title: "Good evening",
      subtitle: "Wrapping up, or just getting started?",
    },
    { title: "Evening", subtitle: 'Prime time for "just one more commit."' },
    { title: "Hey there", subtitle: "What's on the review queue tonight?" },
  ],
  night: [
    {
      title: "Late-night vibe coding? 🌙",
      subtitle: "Respect. What are we hunting for?",
    },
    {
      title: "Found a bug at 2am?",
      subtitle: "Classic. Let's squash it together.",
    },
    {
      title: "Still up?",
      subtitle: "The best findings show up after midnight.",
    },
    {
      title: "3am and debugging",
      subtitle: "A tale as old as time. What's broken?",
    },
  ],
};

function getTimeBand(hour: number): keyof typeof GREETINGS {
  if (hour >= 5 && hour < 12) return "morning";
  if (hour >= 12 && hour < 17) return "afternoon";
  if (hour >= 17 && hour < 22) return "evening";
  return "night";
}

function pickGreeting() {
  const band = getTimeBand(new Date().getHours());
  const pool = GREETINGS[band];
  return pool[Math.floor(Math.random() * pool.length)];
}

function formatRelativeTime(date: Date) {
  const now = new Date();
  const startOfToday = new Date(
    now.getFullYear(),
    now.getMonth(),
    now.getDate(),
  );
  const startOfDate = new Date(
    date.getFullYear(),
    date.getMonth(),
    date.getDate(),
  );
  const dayDiff = Math.round(
    (startOfToday.getTime() - startOfDate.getTime()) / 86400000,
  );
  const time = date.toLocaleTimeString("en-US", {
    hour: "2-digit",
    minute: "2-digit",
  });

  if (dayDiff <= 0) return `Today, ${time}`;
  if (dayDiff === 1) return `Yesterday, ${time}`;
  if (dayDiff < 7) return `${dayDiff} days ago`;
  return date.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

export function ChatArea({
  conversation,
  onSendMessage,
  onResendMessage,
}: ChatAreaProps) {
  const [inputValue, setInputValue] = useState("");
  const [greeting] = useState(pickGreeting);
  const [copiedMessageId, setCopiedMessageId] = useState<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const inputWrapperRef = useRef<HTMLDivElement | null>(null);
  const prevRectRef = useRef<DOMRect | null>(null);

  const messages = conversation?.messages ?? [];

  const [hasStarted, setHasStarted] = useState(messages.length > 0);

  useEffect(() => {
    setHasStarted((conversation?.messages?.length ?? 0) > 0);
    prevRectRef.current = null;
  }, [conversation?.id]);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [conversation?.id, messages.length]);

  useEffect(() => {
    const textarea = textareaRef.current;
    if (textarea) {
      textarea.style.height = "auto";
      const maxHeight = 200;
      textarea.style.height = `${Math.min(textarea.scrollHeight, maxHeight)}px`;
    }
  }, [inputValue]);

  const triggerStart = () => {
    if (hasStarted) return;
    if (inputWrapperRef.current) {
      prevRectRef.current = inputWrapperRef.current.getBoundingClientRect();
    }
    setHasStarted(true);
  };

  useLayoutEffect(() => {
    const el = inputWrapperRef.current;
    if (!el || !prevRectRef.current) return;

    const prev = prevRectRef.current;
    const next = el.getBoundingClientRect();
    const dx = prev.left - next.left;
    const dy = prev.top - next.top;

    prevRectRef.current = null;

    if (!dx && !dy) return;

    el.style.transition = "none";
    el.style.transform = `translate(${dx}px, ${dy}px)`;
    el.getBoundingClientRect();

    requestAnimationFrame(() => {
      el.style.transition = "transform 480ms cubic-bezier(0.22, 1, 0.36, 1)";
      el.style.transform = "translate(0, 0)";
    });
  }, [hasStarted]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = inputValue.trim();
    if (!trimmed) return;
    triggerStart();
    onSendMessage(trimmed);
    setInputValue("");
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  };

  const handleCopy = async (id: string, text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopiedMessageId(id);
      setTimeout(() => {
        setCopiedMessageId((cur) => (cur === id ? null : cur));
      }, 1500);
    } catch (err) {
      console.error("Copy failed", err);
    }
  };

  const handleEditClick = (text: string) => {
  triggerStart(); 
  setInputValue(text);

  requestAnimationFrame(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.focus();
    const len = el.value.length;
    el.setSelectionRange(len, len);
    el.scrollIntoView({ behavior: "smooth", block: "center" });
  });
};

  return (
    <main className="flex-1 flex flex-col bg-black/10 backdrop-blur-xl">
      {/* Chat Header */}
      <div className="h-16 bg-black/30 backdrop-blur-xl border-b border-white/10 flex items-center justify-between px-6 shadow-lg">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 bg-indigo-500 rounded-xl flex items-center justify-center shadow-lg shadow-indigo-500/20">
            <span className="text-white">AI</span>
          </div>
          <div>
            <h2 className="text-slate-100">Security Assistant</h2>
            <p className="text-xs text-emerald-400 flex items-center gap-1">
              <span className="motion-safe:animate-pulse" aria-hidden>
                ●
              </span>
              {conversation ? "Active" : "Waiting for first message"}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            aria-label="Delete conversation"
            className="text-slate-400 hover:text-slate-200 transition-colors p-2 hover:bg-white/5 rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400"
          >
            <Trash2 className="w-5 h-5" aria-hidden />
          </button>
          <button
            aria-label="More options"
            className="text-slate-400 hover:text-slate-200 transition-colors p-2 hover:bg-white/5 rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400"
          >
            <MoreVertical className="w-5 h-5" aria-hidden />
          </button>
        </div>
      </div>

      {/* Messages + floating input host */}
      <div className="relative flex-1 overflow-hidden">
        <div
          role="log"
          aria-live="polite"
          aria-relevant="additions"
          aria-label="Conversation messages"
          className="absolute inset-0 overflow-y-auto overflow-x-hidden p-6 pb-28 space-y-4"
        >
          {messages.map((message) => (
            <div
              key={message.id}
              className={`group flex flex-col min-w-0 ${
                message.sender === "user" ? "items-end" : "items-start"
              } motion-safe:animate-in motion-safe:fade-in motion-safe:slide-in-from-bottom-2 duration-300`}
            >
              {/* Bubble — unaffected by hover, keeps its own fixed padding/shape */}
              <div
                className={`max-w-[70%] ${
                  message.sender === "user"
                    ? "bg-indigo-500 text-white shadow-lg shadow-indigo-500/20"
                    : "bg-white/5 backdrop-blur-md border border-white/10 text-gray-100 shadow-xl"
                } min-w-0 break-words rounded-2xl px-5 py-3.5 transition-all`}
              >
                <span className="sr-only">
                  {message.sender === "user"
                    ? "You said: "
                    : "Assistant said: "}
                </span>
                <MessageContent text={message.text} />
              </div>

              {/* Hover/focus-revealed meta row — separate, sits below/outside the bubble */}
              <div className="flex items-center gap-3 h-0 group-hover:h-5 group-focus-within:h-5 overflow-hidden transition-all duration-150 mt-1 px-1">
                <span className="text-xs text-slate-400">
                  {formatRelativeTime(message.timestamp)}
                </span>
                {message.sender === "user" && (
                  <button
                    type="button"
                    onClick={() => onResendMessage(message.id)}
                    aria-label="Resend message"
                    className="text-slate-400 hover:text-slate-200 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-300 rounded"
                  >
                    <RotateCcw className="w-3.5 h-3.5" aria-hidden />
                  </button>
                )}
                {message.sender === "user" && (
                  <button
                    type="button"
                    onClick={() => handleEditClick(message.text)}
                    aria-label="Edit message"
                    className="text-slate-400 hover:text-slate-200 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-300 rounded"
                  >
                    <Pencil className="w-3.5 h-3.5" aria-hidden />
                  </button>
                )}
                <button
                  onClick={() => handleCopy(message.id, message.text)}
                  aria-label="Copy message"
                  className="text-slate-400 hover:text-slate-200 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-300 rounded"
                >
                  {copiedMessageId === message.id ? (
                    <Check className="w-3.5 h-3.5" aria-hidden />
                  ) : (
                    <Copy className="w-3.5 h-3.5" aria-hidden />
                  )}
                </button>
              </div>
            </div>
          ))}
          <div ref={messagesEndRef} />
        </div>

        {/* Greeting + input, stacked as one column */}
        <div
          className={`absolute inset-x-0 top-0 bottom-0 flex flex-col items-center px-6 pointer-events-none ${
            hasStarted ? "justify-end pb-6" : "justify-center pb-24"
          }`}
        >
          {!hasStarted && (
            <div className="text-center max-w-md mb-6 motion-safe:animate-in motion-safe:fade-in duration-500">
              <h2 className="text-2xl text-slate-100 mb-2">{greeting.title}</h2>
              <p className="text-slate-400">{greeting.subtitle}</p>
            </div>
          )}

          <div
            ref={inputWrapperRef}
            className="w-full max-w-2xl pointer-events-auto"
          >
            <form
              onSubmit={handleSubmit}
              className="flex items-end gap-3 rounded-3xl bg-slate-900/80 backdrop-blur-xl p-2 pl-5 ring-1 ring-indigo-400/20 shadow-[0_0_0_1px_rgba(99,102,241,0.08),0_12px_40px_-8px_rgba(0,0,0,0.6),0_0_24px_-4px_rgba(99,102,241,0.25)] transition-shadow focus-within:ring-indigo-400/40 focus-within:shadow-[0_0_0_1px_rgba(99,102,241,0.15),0_12px_40px_-8px_rgba(0,0,0,0.6),0_0_32px_-2px_rgba(99,102,241,0.35)]"
            >
              <div className="flex-1 relative">
                <label htmlFor="chat-input" className="sr-only">
                  Message
                </label>
                <textarea
                  id="chat-input"
                  ref={textareaRef}
                  value={inputValue}
                  onChange={(e) => setInputValue(e.target.value)}
                  onKeyDown={handleKeyDown}
                  onFocus={triggerStart}
                  placeholder="Type a message..."
                  aria-describedby="chat-input-hint"
                  rows={1}
                  className="w-full bg-transparent text-gray-100 placeholder-gray-500 focus:outline-none resize-none overflow-y-auto py-2.5"
                  style={{ minHeight: "40px", maxHeight: "200px" }}
                />
                <span id="chat-input-hint" className="sr-only">
                  Press Enter to send, Shift plus Enter for a new line.
                </span>
              </div>
              <button
                type="submit"
                disabled={!inputValue.trim()}
                aria-label="Send message"
                className="w-11 h-11 mb-0.5 bg-indigo-500 rounded-full flex items-center justify-center hover:bg-indigo-400 transition-all disabled:opacity-40 disabled:cursor-not-allowed shadow-[0_0_16px_-2px_rgba(99,102,241,0.6)] flex-shrink-0 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-300"
              >
                <Send className="w-4 h-4 text-white" aria-hidden />
              </button>
            </form>
            {hasStarted && (
              <p className="mt-2 text-xs text-center text-slate-500">
                Shift+Enter for a new line
              </p>
            )}
          </div>
        </div>
      </div>
    </main>
  );
}
