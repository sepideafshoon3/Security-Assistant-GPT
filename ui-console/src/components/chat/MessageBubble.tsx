import type { Message } from "../../App";
import { Copy, Check, RotateCcw, Pencil, AlertCircle } from "lucide-react";
import { IconButton } from "../IconButton";
import { MessageContent } from "../MessageContent";
import { formatRelativeTime } from "../../utils/time";

interface MessageBubbleProps {
  message: Message;
  isCopied: boolean;
  onCopy: (id: string, text: string) => void;
  onResend: (id: string) => void;
  onEdit: (text: string) => void;
}

export function MessageBubble({ message, isCopied, onCopy, onResend, onEdit }: MessageBubbleProps) {
  const isUser = message.sender === "user";

  return (
    <div
      className={`group flex flex-col min-w-0 ${
        isUser ? "items-end" : "items-start"
      } motion-safe:animate-in motion-safe:fade-in motion-safe:slide-in-from-bottom-2 duration-300`}
    >
      <div
        className={`max-w-[70%] ${
          isUser
            ? "bg-indigo-500 text-white shadow-lg shadow-indigo-500/20"
            : "bg-white/5 backdrop-blur-md border border-white/10 text-gray-100 shadow-xl"
        } ${message.failed ? "ring-2 ring-red-500/60" : ""} min-w-0 break-words rounded-2xl px-5 py-3.5 transition-all`}
      >
        <span className="sr-only">{isUser ? "You said: " : "Assistant said: "}</span>
        <MessageContent text={message.text} />
      </div>

      {message.failed && (
        <div className="flex items-center gap-1.5 mt-1 px-1">
          <AlertCircle className="w-3.5 h-3.5 text-red-400" aria-hidden />
          <span className="text-xs text-red-400">Failed to send — hover to retry</span>
        </div>
      )}

      <div className="flex items-center gap-3 h-0 group-hover:h-5 group-focus-within:h-5 overflow-hidden transition-all duration-150 mt-1 px-1">
        <span className="text-xs text-slate-400">{formatRelativeTime(message.timestamp)}</span>
        {isUser && (
          <IconButton aria-label="Resend message" onClick={() => onResend(message.id)}>
            <RotateCcw className="w-3.5 h-3.5" aria-hidden />
          </IconButton>
        )}
        {isUser && (
          <IconButton aria-label="Edit message" onClick={() => onEdit(message.text)}>
            <Pencil className="w-3.5 h-3.5" aria-hidden />
          </IconButton>
        )}
        <IconButton aria-label="Copy message" onClick={() => onCopy(message.id, message.text)}>
          {isCopied ? <Check className="w-3.5 h-3.5" aria-hidden /> : <Copy className="w-3.5 h-3.5" aria-hidden />}
        </IconButton>
      </div>
    </div>
  );
}