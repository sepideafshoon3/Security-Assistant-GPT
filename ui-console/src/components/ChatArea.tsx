import { useState, useRef, useEffect, useLayoutEffect } from "react";
import type { Conversation } from "../App";
import {
  ShieldCheck,
  MoreHorizontal,
  Pin,
  PinOff,
  Pencil,
  Trash2,
  FolderPlus,
  Users,
  Share2,
} from "lucide-react";
import { Greeting } from "./chat/Greeting";
import { MessageBubble } from "./chat/MessageBubble";
import { TypingIndicator } from "./chat/TypingIndicator";
import { ScrollToBottomButton } from "./chat/ScrollToBottomButton";
import { ChatInput } from "./chat/ChatInput";
import { cn } from "./ui/utils";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "./ui/dropdown-menu";
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogHeader,
  AlertDialogFooter,
  AlertDialogTitle,
  AlertDialogDescription,
  AlertDialogAction,
  AlertDialogCancel,
} from "./ui/alert-dialog";

interface ChatAreaProps {
  conversation: Conversation | null;
  onSendMessage: (text: string) => void;
  onResendMessage: (messageId: string) => void;
  onDeleteConversation: (id: string) => void;
  onRenameConversation: (id: string, title: string) => void;
  onPinConversation: (id: string) => void;
  isLoading?: boolean;
}

export function ChatArea({
  conversation,
  onSendMessage,
  onResendMessage,
  onDeleteConversation,
  onRenameConversation,
  onPinConversation,
  isLoading,
}: ChatAreaProps) {
  const [inputValue, setInputValue] = useState("");
  const [isEditingTitle, setIsEditingTitle] = useState(false);
  const [titleValue, setTitleValue] = useState("");
  const [pendingDelete, setPendingDelete] = useState(false);
  const titleInputRef = useRef<HTMLInputElement>(null);

  const [copiedMessageId, setCopiedMessageId] = useState<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement | null>(null);
  const messagesContainerRef = useRef<HTMLDivElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const inputWrapperRef = useRef<HTMLDivElement | null>(null);
  const prevRectRef = useRef<DOMRect | null>(null);
  const [showScrollButton, setShowScrollButton] = useState(false);
  // Tracks the input bar's live height (it grows with multi-line text) so
  // the message list's bottom clearance can track it exactly, instead of a
  // guessed constant that breaks once the input grows past it.
  const [inputBarHeight, setInputBarHeight] = useState(0);

  const messages = conversation?.messages ?? [];
  const [hasStarted, setHasStarted] = useState(messages.length > 0);

  useEffect(() => {
    setHasStarted((conversation?.messages?.length ?? 0) > 0);
    prevRectRef.current = null;
    setShowScrollButton(false);
    // Selecting a different conversation should always cancel any in-progress
    // rename — otherwise a stale edit could get committed onto the wrong chat.
    setIsEditingTitle(false);
  }, [conversation?.id]);

  useEffect(() => {
    if (isEditingTitle) titleInputRef.current?.focus();
  }, [isEditingTitle]);

  useLayoutEffect(() => {
    const el = inputWrapperRef.current;
    if (!el) return;

    setInputBarHeight(el.getBoundingClientRect().height);
    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (entry) setInputBarHeight(entry.contentRect.height);
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const startTitleEdit = () => {
    if (!conversation) return;
    setTitleValue(conversation.title);
    setIsEditingTitle(true);
  };

  const commitTitleEdit = () => {
    if (!conversation) return;
    const trimmed = titleValue.trim();
    if (trimmed && trimmed !== conversation.title) {
      onRenameConversation(conversation.id, trimmed);
    }
    setIsEditingTitle(false);
  };

  const cancelTitleEdit = () => {
    setIsEditingTitle(false);
    setTitleValue("");
  };

  const scrollToBottom = () => {
    // block: "start" (the default) is correct here, not "end" — the target
    // is a 0-height marker right after the last message, followed only by
    // this container's bottom padding. "end" aligns the marker's bottom
    // edge to the viewport's bottom edge, which scrolls just *short* of
    // the real max — exactly enough to hide that padding and let the
    // floating input overlap the last line of the message. "start" clamps
    // to the true max scroll, which is what actually leaves the padding
    // (the gap above the input) visible.
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
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
    <>
      <main className="flex-1 flex flex-col bg-background relative">
        <div className="h-16 bg-surface-elevated/80 backdrop-blur-xl border-b border-border flex items-center justify-between px-3 sm:px-6 shadow-sm gap-2">
          <div className="flex items-center gap-2 sm:gap-3 min-w-0">
            <div className="w-9 h-9 sm:w-10 sm:h-10 shrink-0 bg-accent rounded-xl flex items-center justify-center shadow-lg shadow-accent/20">
              <ShieldCheck className="w-5 h-5 text-white" aria-hidden />
            </div>
            <div className="min-w-0 flex-1">
              {isEditingTitle && conversation ? (
                <div className="flex items-center gap-1.5">
                  <input
                    ref={titleInputRef}
                    value={titleValue}
                    onChange={(e) => setTitleValue(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") {
                        e.preventDefault();
                        commitTitleEdit();
                      } else if (e.key === "Escape") {
                        e.preventDefault();
                        cancelTitleEdit();
                      }
                    }}
                    onBlur={commitTitleEdit}
                    className="flex-1 min-w-0 bg-input-background border border-accent-hover/50 rounded px-1.5 py-0.5 text-fg-primary outline-none focus:ring-1 focus:ring-accent-hover/40"
                  />
                  <button
                    onClick={commitTitleEdit}
                    aria-label="Save name"
                    className="p-1 rounded text-fg-tertiary hover:text-fg-primary hover:bg-secondary transition-colors shrink-0"
                  >
                    {/* <Check className="w-4 h-4" aria-hidden /> */}
                  </button>
                </div>
              ) : (
                <h2
                  onDoubleClick={startTitleEdit}
                  title={conversation ? "Double-click to rename" : undefined}
                  className={cn("text-fg-primary truncate", conversation && "cursor-text")}
                >
                  {conversation ? conversation.title : "New chat"}
                </h2>
              )}
              <p className="text-xs text-status-success flex items-center gap-1 truncate">
                <span className="motion-safe:animate-pulse shrink-0" aria-hidden>
                  ●
                </span>
                <span className="truncate">
                  {conversation ? "Active" : "Waiting for first message"}
                </span>
              </p>
            </div>
          </div>

          {conversation && (
            <div className="flex items-center gap-1 sm:gap-2 shrink-0">
              <button
                aria-label="Share conversation"
                disabled
                title="Coming soon"
                className="text-fg-tertiary hover:text-fg-primary transition-colors p-2 hover:bg-secondary rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-hover disabled:opacity-40 disabled:hover:bg-transparent disabled:hover:text-fg-tertiary disabled:cursor-not-allowed"
              >
                <Share2 className="w-5 h-5" aria-hidden />
              </button>

              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <button
                    aria-label="More options"
                    className="text-fg-tertiary hover:text-fg-primary transition-colors p-2 hover:bg-secondary rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-hover"
                  >
                    <MoreHorizontal className="w-5 h-5" aria-hidden />
                  </button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="w-44">
                  <DropdownMenuItem onSelect={() => onPinConversation(conversation.id)}>
                    {conversation.pinned ? (
                      <PinOff className="w-3.5 h-3.5" aria-hidden />
                    ) : (
                      <Pin className="w-3.5 h-3.5" aria-hidden />
                    )}
                    {conversation.pinned ? "Unpin" : "Pin"}
                  </DropdownMenuItem>
                  <DropdownMenuItem onSelect={startTitleEdit}>
                    <Pencil className="w-3.5 h-3.5" aria-hidden />
                    Rename
                  </DropdownMenuItem>
                  <DropdownMenuItem variant="destructive" onSelect={() => setPendingDelete(true)}>
                    <Trash2 className="w-3.5 h-3.5" aria-hidden />
                    Delete
                  </DropdownMenuItem>
                  <DropdownMenuSeparator />
                  {/* Same as the sidebar menu: no project/group data model or
                   share-link endpoint on the backend yet. */}
                  <DropdownMenuItem disabled title="Coming soon">
                    <FolderPlus className="w-3.5 h-3.5" aria-hidden />
                    Add to project
                  </DropdownMenuItem>
                  <DropdownMenuItem disabled title="Coming soon">
                    <Users className="w-3.5 h-3.5" aria-hidden />
                    Add to group
                  </DropdownMenuItem>
                  <DropdownMenuItem disabled title="Coming soon">
                    <Share2 className="w-3.5 h-3.5" aria-hidden />
                    Share
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
          )}
        </div>

        <div className="relative flex-1 overflow-hidden">
          <div
            ref={messagesContainerRef}
            onScroll={handleMessagesScroll}
            role="log"
            aria-live="polite"
            aria-relevant="additions"
            aria-label="Conversation messages"
            className="absolute inset-0 overflow-y-auto overflow-x-hidden p-3 sm:p-6 space-y-4"
            style={{
              // Real input height + its own 24px (pb-6) offset from the
              // floor + a bit of breathing room, so the last message always
              // clears the floating input — including while it's grown
              // tall from a multi-line draft.
              paddingBottom: inputBarHeight ? inputBarHeight + 24 + 20 : 160,
            }}
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
              "absolute inset-x-0 top-0 bottom-0 flex flex-col items-center px-3 sm:px-6 pointer-events-none",
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

      <AlertDialog open={pendingDelete} onOpenChange={setPendingDelete}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete this conversation?</AlertDialogTitle>
            <AlertDialogDescription>
              {conversation
                ? `"${conversation.title}" and all of its messages will be permanently deleted. This can't be undone.`
                : "This conversation and all of its messages will be permanently deleted. This can't be undone."}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel onClick={() => setPendingDelete(false)}>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                if (conversation) onDeleteConversation(conversation.id);
                setPendingDelete(false);
              }}
              className="bg-status-danger text-white hover:bg-status-danger/90"
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
