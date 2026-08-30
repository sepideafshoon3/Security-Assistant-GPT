import { useState, useRef, useEffect } from "react";
import type { Conversation } from "../App";
import { Send, MoreVertical, Trash2 } from "lucide-react";
import { MessageContent } from "./MessageContent";

interface ChatAreaProps {
  conversation: Conversation | null;
  onSendMessage: (text: string) => void;
}

export function ChatArea({ conversation, onSendMessage }: ChatAreaProps) {
  const [inputValue, setInputValue] = useState("");
  const messagesEndRef = useRef<HTMLDivElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
    // trigger scroll when conversation changes or message count changes
  }, [conversation?.id, conversation?.messages?.length]);

  // Auto-resize textarea based on content
  useEffect(() => {
    const textarea = textareaRef.current;
    if (textarea) {
      // Reset height to auto to get the correct scrollHeight
      textarea.style.height = "auto";
      // Set the height to scrollHeight, with a max limit
      const maxHeight = 200; // Maximum height in pixels
      const newHeight = Math.min(textarea.scrollHeight, maxHeight);
      textarea.style.height = `${newHeight}px`;
    }
  }, [inputValue]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = inputValue.trim();
    if (!trimmed) return;

    // IMPORTANT: allow sending even if conversation === null
    // App will decide whether this starts a new conversation or continues one.
    onSendMessage(trimmed);
    setInputValue("");
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    // Submit on Enter without Shift key
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
    // Shift+Enter will naturally create a new line
  };

  const formatMessageTime = (date: Date) => {
    return date.toLocaleTimeString("en-US", {
      hour: "2-digit",
      minute: "2-digit",
    });
  };

  const messages = conversation?.messages ?? [];

  return (
    <div className="flex-1 flex flex-col bg-black/10 backdrop-blur-xl">
      {/* Chat Header */}
      <div className="h-16 bg-black/30 backdrop-blur-xl border-b border-white/10 flex items-center justify-between px-6 shadow-lg">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 bg-gradient-to-br from-cyan-400 via-cyan-500 to-green-500 rounded-xl flex items-center justify-center shadow-lg shadow-cyan-500/50">
            <span className="text-black">AI</span>
          </div>
          <div>
            <h2 className="text-gray-100 bg-gradient-to-r from-cyan-300 to-green-300 bg-clip-text text-transparent">
              Mr. Robot AI
            </h2>
            <p className="text-xs text-green-400 flex items-center gap-1">
              <span className="animate-pulse">●</span>{" "}
              {conversation ? "Active" : "Waiting for first message"}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-4">
          {/* Wire these later if you want: clear, options, etc. */}
          <button className="text-cyan-400 hover:text-cyan-300 transition-colors p-2 hover:bg-white/5 rounded-lg">
            <Trash2 className="w-5 h-5" />
          </button>
          <button className="text-cyan-400 hover:text-cyan-300 transition-colors p-2 hover:bg-white/5 rounded-lg">
            <MoreVertical className="w-5 h-5" />
          </button>
        </div>
      </div>

      {/* Conversation Info */}
      <div className="px-6 py-3 bg-gradient-to-r from-black/20 to-black/30 backdrop-blur-sm border-b border-white/10">
        {/* <div className="text-xs font-mono text-cyan-400/80 mb-1">
          SESSION_ID:{" "}
          <span className="text-green-400">
            {conversation ? conversation.id : "pending"}
          </span>
        </div> */}
        <div className="text-sm text-gray-300">
          {conversation ? conversation.title : "New Conversation"}
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto overflow-x-hidden p-6 space-y-4">
        {messages.length === 0 && (
          <div className="flex h-full items-center justify-center">
            <div className="text-center text-gray-500 text-sm">
              <p className="mb-1">No messages yet.</p>
              <p>Type your first prompt below to start a new session.</p>
            </div>
          </div>
        )}

        {messages.map((message) => (
          <div
            key={message.id}
            className={`flex min-w-0 ${
              message.sender === "user" ? "justify-end" : "justify-start"
            } animate-in fade-in slide-in-from-bottom-2 duration-300`}
          >
            <div
              className={`max-w-[70%] w-[90vh] ${
                message.sender === "user"
                  ? "bg-gradient-to-br from-cyan-500 to-green-500 text-black shadow-lg shadow-cyan-500/30"
                  : "bg-white/5 backdrop-blur-md border border-white/10 text-gray-100 shadow-xl"
              } min-w-0 break-words rounded-2xl px-5 py-3.5 transition-all hover:scale-[1.01]`}
            >
              <MessageContent text={message.text} />
              <div className="flex items-center gap-2 mt-2 pt-2 border-t border-white/10">
                <span
                  className={`text-xs ${
                    message.sender === "user"
                      ? "text-black/70"
                      : "text-cyan-400/70"
                  }`}
                >
                  {formatMessageTime(message.timestamp)}
                </span>
                {/* <span
                  className={`text-xs font-mono ${
                    message.sender === "user"
                      ? "text-black/50"
                      : "text-green-400/50"
                  }`}
                >
                  #{message.id}
                </span> */}
              </div>
            </div>
          </div>
        ))}
        <div ref={messagesEndRef} />
      </div>

      {/* Input Area — floating */}
      <div className="relative px-6 pb-6 pt-2">
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
        <p className="mt-2 text-xs text-center text-slate-500">
          Shift+Enter for a new line
        </p>
      </div>
    </div>
  );
}
