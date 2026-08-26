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
        <div className="text-xs font-mono text-cyan-400/80 mb-1">
          SESSION_ID:{" "}
          <span className="text-green-400">
            {conversation ? conversation.id : "pending"}
          </span>
        </div>
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
                <span
                  className={`text-xs font-mono ${
                    message.sender === "user"
                      ? "text-black/50"
                      : "text-green-400/50"
                  }`}
                >
                  #{message.id}
                </span>
              </div>
            </div>
          </div>
        ))}
        <div ref={messagesEndRef} />
      </div>

      {/* Input Area */}
      <div className="p-6 bg-black/30 backdrop-blur-xl border-t border-white/10 shadow-2xl">
        <form onSubmit={handleSubmit} className="flex items-end gap-4">
          <div className="flex-1 relative">
            <textarea
              ref={textareaRef}
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Type a message... (Shift+Enter for new line)"
              rows={1}
              className="w-full bg-white/5 backdrop-blur-sm border border-white/10 rounded-2xl px-6 py-3.5 text-gray-100 placeholder-gray-500 focus:outline-none focus:border-cyan-400/50 focus:ring-2 focus:ring-cyan-400/20 focus:bg-white/10 transition-all shadow-lg resize-none overflow-y-auto"
              style={{ minHeight: "52px", maxHeight: "200px" }}
            />
          </div>
          <button
            type="submit"
            disabled={!inputValue.trim()}
            className="w-12 h-12 bg-gradient-to-br from-cyan-400 via-cyan-500 to-green-500 rounded-2xl flex items-center justify-center hover:from-cyan-300 hover:to-green-400 transition-all disabled:opacity-50 disabled:cursor-not-allowed shadow-lg shadow-cyan-500/50 hover:shadow-cyan-500/70 hover:scale-105 flex-shrink-0"
          >
            <Send className="w-5 h-5 text-black" />
          </button>
        </form>
        <div className="mt-3 text-xs text-center font-mono flex items-center justify-center gap-2">
          <span className="animate-pulse text-cyan-400">▶</span>
          <span className="bg-gradient-to-r from-cyan-400 to-green-400 bg-clip-text text-transparent">
          </span>
        </div>
      </div>
    </div>
  );
}
