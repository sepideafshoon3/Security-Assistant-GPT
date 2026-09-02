import { ChevronDown } from "lucide-react";

interface ScrollToBottomButtonProps {
  visible: boolean;
  onClick: () => void;
}

export function ScrollToBottomButton({ visible, onClick }: ScrollToBottomButtonProps) {
  if (!visible) return null;
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label="Scroll to latest message"
      className="absolute bottom-28 left-1/2 -translate-x-1/2 z-10 w-9 h-9 rounded-full bg-slate-800/90 backdrop-blur-xl border border-white/10 text-slate-300 hover:text-white hover:bg-slate-700/90 shadow-lg flex items-center justify-center transition-all motion-safe:animate-in motion-safe:fade-in focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400"
    >
      <ChevronDown className="w-4 h-4" aria-hidden />
    </button>
  );
}