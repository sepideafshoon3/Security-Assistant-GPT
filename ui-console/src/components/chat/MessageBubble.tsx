import type { Message } from "../../App";
import { Copy, Check, RotateCcw, Pencil, AlertCircle } from "lucide-react";
import { IconButton } from "../IconButton";
import { MessageContent } from "../MessageContent";
import { FindingsBadge } from "./FindingsBadge";
import { formatRelativeTime } from "../../utils/time";
import { cn } from "../ui/utils";

interface MessageBubbleProps {
  message: Message;
  isCopied: boolean;
  onCopy: (id: string, text: string) => void;
  onResend: (id: string) => void;
  onEdit: (text: string) => void;
  disabled?: boolean;
}

export function MessageBubble({
  message,
  isCopied,
  onCopy,
  onResend,
  onEdit,
  disabled,
}: MessageBubbleProps) {
  const isUser = message.sender === "user";

  return (
    <div
      className={cn(
        "group flex flex-col min-w-0",
        isUser ? "items-end" : "items-start",
        "motion-safe:animate-in motion-safe:fade-in motion-safe:slide-in-from-bottom-2 duration-300",
      )}
    >
      {!isUser && <FindingsBadge text={message.text} />}
      <div
        className={cn(
          "max-w-[88%] sm:max-w-[70%] min-w-0 break-words rounded-2xl px-4 sm:px-5 py-3.5 backdrop-blur-xl transition-all",
          isUser
            ? "bg-accent/70 text-white border border-white/20 shadow-[inset_0_1px_0_rgba(255,255,255,0.25),0_8px_24px_-6px_var(--accent-glow)]"
            : "bg-gradient-to-br from-white/85 to-surface-deep/90 dark:from-transparent dark:to-transparent dark:bg-white/[0.07] backdrop-blur-xl backdrop-saturate-150 border border-black/[0.06] dark:border-white/15 text-fg-primary shadow-[inset_0_1px_0_rgba(255,255,255,0.6),0_1px_2px_rgba(15,23,42,0.04),0_8px_24px_-8px_rgba(15,23,42,0.12)] dark:shadow-[inset_0_1px_0_rgba(255,255,255,0.1),0_0_0_1px_rgba(255,255,255,0.03),0_8px_24px_-6px_rgba(0,0,0,0.5),0_0_20px_-6px_var(--accent-glow)]",
          message.failed && "ring-2 ring-status-danger/60",
        )}
      >
        <span className="sr-only">{isUser ? "You said: " : "Assistant said: "}</span>
        <MessageContent text={message.text} />
      </div>

      {message.failed && (
        <div className="flex items-center gap-1.5 mt-1 px-1">
          <AlertCircle className="w-3.5 h-3.5 text-status-danger-strong" aria-hidden />
          <span className="text-xs text-status-danger-strong">Failed to send — hover to retry</span>
        </div>
      )}

      <div className="flex items-center gap-3 h-0 group-hover:h-5 group-focus-within:h-5 overflow-hidden transition-all duration-150 mt-1 px-1">
        <span className="text-xs text-fg-faint">{formatRelativeTime(message.timestamp)}</span>
        {isUser && (
          <IconButton
            aria-label="Resend message"
            onClick={() => onResend(message.id)}
            disabled={disabled}
          >
            <RotateCcw className="w-3.5 h-3.5" aria-hidden />
          </IconButton>
        )}
        {isUser && (
          <IconButton
            aria-label="Edit message"
            onClick={() => onEdit(message.text)}
            disabled={disabled}
          >
            <Pencil className="w-3.5 h-3.5" aria-hidden />
          </IconButton>
        )}
        <IconButton aria-label="Copy message" onClick={() => onCopy(message.id, message.text)}>
          {isCopied ? (
            <Check className="w-3.5 h-3.5" aria-hidden />
          ) : (
            <Copy className="w-3.5 h-3.5" aria-hidden />
          )}
        </IconButton>
      </div>
    </div>
  );
}
