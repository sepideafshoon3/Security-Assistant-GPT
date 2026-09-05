import { useState, useRef, useEffect, useLayoutEffect } from "react";
import type { Conversation } from "../App";
import { Trash2, MoreVertical } from "lucide-react";
import { Greeting } from "./chat/Greeting";
import { MessageBubble } from "./chat/MessageBubble";
import { TypingIndicator } from "./chat/TypingIndicator";
import { ScrollToBottomButton } from "./chat/ScrollToBottomButton";
import { ChatInput } from "./chat/ChatInput";
import { cn } from "./ui/utils";

interface ChatAreaProps {
  conversation: Conversation | null;
  onSendMessage: (text: string) => void;
  onResendMessage: (messageId: string) => void;
  isLoading?: boolean;
}

export function ChatArea({ conversation, onSendMessage, onResendMessage, isLoading }: ChatAreaProps) {
  const [inputValue, setInputValue] = useState("");
  const [copiedMessageId, setCopiedMessageId] = useState<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement | null>(null);
  const messagesContainerRef = useRef<HTMLDivElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const inputWrapperRef = useRef<HTMLDivElement | null>(null);
  const prevRectRef = useRef<DOMRect | null>(null);
  const [showScrollButton, setShowScrollButton] = useState(false);

  const messages = conversation?.messages ?? [];
  const [hasStarted, setHasStarted] = useState(messages.length > 0);

  useEffect(() => {
    setHasStarted((conversation?.messages?.length ?? 0) > 0);
    prevRectRef.current = null;
    setShowScrollButton(false);
  }, [conversation?.id]);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  const handleMessagesScroll = () => {
    const el = messagesContainerRef.current;
    if (!el) return;
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    setShowScrollButton(distanceFromBottom > 150);
  };

  useEffect(() => {
    scrollToBottom();
  }, [conversation?.id, messages.length, isLoading]);

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
      <div className="h-16 bg-black/30 backdrop-blur-xl border-b border-white/10 flex items-center justify-between px-6 shadow-lg">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 bg-accent rounded-xl flex items-center justify-center shadow-lg shadow-accent/20">
            <span className="text-white">AI</span>
          </div>
          <div>
            <h2 className="text-fg-primary">Security Assistant</h2>
            <p className="text-xs text-status-success flex items-center gap-1">
              <span className="motion-safe:animate-pulse" aria-hidden>●</span>
              {conversation ? "Active" : "Waiting for first message"}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            aria-label="Delete conversation"
            className="text-fg-tertiary hover:text-fg-primary transition-colors p-2 hover:bg-white/5 rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-hover"
          >
            <Trash2 className="w-5 h-5" aria-hidden />
          </button>
          <button
            aria-label="More options"
            className="text-fg-tertiary hover:text-fg-primary transition-colors p-2 hover:bg-white/5 rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-hover"
          >
            <MoreVertical className="w-5 h-5" aria-hidden />
          </button>
        </div>
      </div>

      <div className="relative flex-1 overflow-hidden">
        <div
          ref={messagesContainerRef}
          onScroll={handleMessagesScroll}
          role="log"
          aria-live="polite"
          aria-relevant="additions"
          aria-label="Conversation messages"
          className="absolute inset-0 overflow-y-auto overflow-x-hidden p-6 pb-28 space-y-4"
        >
          {messages.map((message) => (
            <MessageBubble
              key={message.id}
              message={message}
              isCopied={copiedMessageId === message.id}
              onCopy={handleCopy}
              onResend={onResendMessage}
              onEdit={handleEditClick}
              disabled={isLoading}
            />
          ))}

          {isLoading && conversation && <TypingIndicator />}

          <div ref={messagesEndRef} />
        </div>

        <ScrollToBottomButton
          visible={showScrollButton}
          onClick={() => {
            scrollToBottom();
            setShowScrollButton(false);
          }}
        />

        <div
          className={cn(
            "absolute inset-x-0 top-0 bottom-0 flex flex-col items-center px-6 pointer-events-none",
            hasStarted ? "justify-end pb-6" : "justify-center pb-24",
          )}
        >
          {!hasStarted && <Greeting />}

          <div ref={inputWrapperRef} className="w-full max-w-2xl pointer-events-auto">
            <ChatInput
              value={inputValue}
              onChange={setInputValue}
              onSubmit={handleSubmit}
              onKeyDown={handleKeyDown}
              onFocus={triggerStart}
              textareaRef={textareaRef}
              showHint={hasStarted}
            />
          </div>
        </div>
      </div>
    </main>
  );
}