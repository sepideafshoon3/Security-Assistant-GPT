import { useState, useRef, useEffect } from "react";
import { Send, Plus, Paperclip, X, FileText } from "lucide-react";
import { cn } from "../ui/utils";

interface PendingAttachment {
  id: string;
  file: File;
  previewUrl?: string;
}

interface ChatInputProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: (e: React.FormEvent) => void;
  onKeyDown: (e: React.KeyboardEvent<HTMLTextAreaElement>) => void;
  onFocus: () => void;
  textareaRef: React.RefObject<HTMLTextAreaElement | null>;
  showHint: boolean;
  disabled?: boolean;
}

export function ChatInput({
  value,
  onChange,
  onSubmit,
  onKeyDown,
  onFocus,
  textareaRef,
  showHint,
  disabled,
}: ChatInputProps) {
  const [isAttachMenuOpen, setIsAttachMenuOpen] = useState(false);
  const attachMenuRef = useRef<HTMLDivElement | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [pendingAttachments, setPendingAttachments] = useState<
    PendingAttachment[]
  >([]);

  useEffect(() => {
    if (!isAttachMenuOpen) return;

    const handlePointerDown = (e: PointerEvent) => {
      if (!attachMenuRef.current?.contains(e.target as Node)) {
        setIsAttachMenuOpen(false);
      }
    };
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") setIsAttachMenuOpen(false);
    };

    document.addEventListener("pointerdown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [isAttachMenuOpen]);

  useEffect(() => {
    return () => {
      pendingAttachments.forEach((a) => {
        if (a.previewUrl) URL.revokeObjectURL(a.previewUrl);
      });
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const textarea = textareaRef.current;
    if (textarea) {
      textarea.style.height = "auto";
      const maxHeight = 200;
      textarea.style.height = `${Math.min(textarea.scrollHeight, maxHeight)}px`;
    }
  }, [value, textareaRef]);

  const handleFilesSelected = (files: FileList | null) => {
    if (!files) return;
    const next: PendingAttachment[] = Array.from(files).map((file) => ({
      id: `att-${Date.now()}-${Math.random().toString(36).slice(2)}`,
      file,
      previewUrl: file.type.startsWith("image/")
        ? URL.createObjectURL(file)
        : undefined,
    }));
    setPendingAttachments((prev) => [...prev, ...next]);
  };

  const removeAttachment = (id: string) => {
    setPendingAttachments((prev) => {
      const target = prev.find((a) => a.id === id);
      if (target?.previewUrl) URL.revokeObjectURL(target.previewUrl);
      return prev.filter((a) => a.id !== id);
    });
  };

  return (
    <div className="w-full">
      {pendingAttachments.length > 0 && (
        <div className="flex flex-wrap gap-2 mb-2 px-1">
          {pendingAttachments.map((att) => (
            <div
              key={att.id}
              className="relative flex items-center gap-2 bg-surface-panel/80 border border-white/10 rounded-xl px-2 py-1.5 pr-7"
            >
              {att.previewUrl ? (
                <img
                  src={att.previewUrl}
                  alt={att.file.name}
                  className="w-8 h-8 object-cover rounded-lg"
                />
              ) : (
                <FileText className="w-4 h-4 text-fg-tertiary" aria-hidden />
              )}
              <span className="text-xs text-fg-secondary max-w-[120px] truncate">
                {att.file.name}
              </span>
              <button
                type="button"
                onClick={() => removeAttachment(att.id)}
                aria-label={`Remove ${att.file.name}`}
                className="absolute right-1.5 top-1.5 text-fg-tertiary hover:text-fg-primary"
              >
                <X className="w-3 h-3" />
              </button>
            </div>
          ))}
        </div>
      )}

      <form
        onSubmit={onSubmit}
        className="flex items-center gap-3 rounded-3xl bg-surface-panel/80 backdrop-blur-xl p-2 pl-5 ring-1 ring-accent-hover/20 shadow-[0_0_0_1px_rgba(99,102,241,0.08),0_12px_40px_-8px_rgba(0,0,0,0.6),0_0_24px_-4px_rgba(99,102,241,0.25)] transition-shadow focus-within:ring-accent-hover/40 focus-within:shadow-[0_0_0_1px_rgba(99,102,241,0.15),0_12px_40px_-8px_rgba(0,0,0,0.6),0_0_32px_-2px_rgba(99,102,241,0.35)]"
      >
        <input
          ref={fileInputRef}
          type="file"
          multiple
          className="hidden"
          onChange={(e) => {
            handleFilesSelected(e.target.files);
            e.target.value = "";
          }}
        />
        <div ref={attachMenuRef} className="relative flex-shrink-0">
          <button
            type="button"
            onClick={() => setIsAttachMenuOpen((v) => !v)}
            aria-label="Add attachment"
            aria-expanded={isAttachMenuOpen}
            className={cn(
              "w-9 h-9 p-0 leading-none flex-shrink-0 inline-flex items-center justify-center rounded-full transition-all",
              isAttachMenuOpen
                ? "bg-white/10 text-fg-primary rotate-45"
                : "text-fg-tertiary hover:text-fg-primary hover:bg-white/5",
            )}
          >
            <Plus className="w-4 h-4 block" aria-hidden />
          </button>

          {isAttachMenuOpen && (
            <div
              role="menu"
              className="absolute bottom-full left-0 mb-2 w-48 bg-surface-panel/95 backdrop-blur-xl border border-white/10 rounded-2xl shadow-xl shadow-black/40 p-1.5 motion-safe:animate-in motion-safe:fade-in motion-safe:slide-in-from-bottom-2 duration-150"
            >
              <button
                type="button"
                role="menuitem"
                onClick={() => {
                  setIsAttachMenuOpen(false);
                  fileInputRef.current?.click();
                }}
                className="w-full flex items-center gap-2.5 text-left text-sm text-fg-primary hover:bg-white/5 rounded-xl px-3 py-2 transition-colors"
              >
                <Paperclip className="w-4 h-4 text-fg-tertiary" aria-hidden />
                Upload file
              </button>
            </div>
          )}
        </div>

        <div className="flex-1 relative">
          <label htmlFor="chat-input" className="sr-only">
            Message
          </label>
          <textarea
            id="chat-input"
            ref={textareaRef}
            value={value}
            onChange={(e) => onChange(e.target.value)}
            onKeyDown={onKeyDown}
            onFocus={onFocus}
            placeholder="Type a message..."
            aria-describedby="chat-input-hint"
            rows={1}
            disabled={disabled}
            className="w-full bg-transparent text-fg-primary placeholder-fg-faint focus:outline-none resize-none overflow-y-auto py-2.5 disabled:opacity-50"
            style={{ minHeight: "40px", maxHeight: "200px" }}
          />
          <span id="chat-input-hint" className="sr-only">
            Press Enter to send, Shift plus Enter for a new line.
          </span>
        </div>
        <button
          type="submit"
          disabled={!value.trim() || disabled}
          aria-label="Send message"
          className="w-11 h-11 mb-0.5 bg-accent rounded-full flex items-center justify-center hover:bg-accent-hover transition-all disabled:opacity-40 disabled:cursor-not-allowed shadow-[0_0_16px_-2px_var(--accent-glow)] flex-shrink-0 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-strong"
        >
          <Send className="w-4 h-4 text-white" aria-hidden />
        </button>
      </form>
      {showHint && (
        <p className="mt-2 text-xs text-center text-fg-faint">
          Shift+Enter for a new line
        </p>
      )}
    </div>
  );
}
