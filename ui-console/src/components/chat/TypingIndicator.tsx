export function TypingIndicator() {
  return (
    <div className="flex flex-col min-w-0 items-start motion-safe:animate-in motion-safe:fade-in duration-200">
      <div className="max-w-[70%] bg-white/5 backdrop-blur-md border border-white/10 rounded-2xl px-5 py-3.5 shadow-xl">
        <div role="status" aria-label="Assistant is typing" className="flex items-center gap-1.5 h-2">
          <span className="w-2 h-2 rounded-full bg-fg-tertiary motion-safe:animate-bounce [animation-delay:-0.3s]" />
          <span className="w-2 h-2 rounded-full bg-fg-tertiary motion-safe:animate-bounce [animation-delay:-0.15s]" />
          <span className="w-2 h-2 rounded-full bg-fg-tertiary motion-safe:animate-bounce" />
        </div>
      </div>
    </div>
  );
}
