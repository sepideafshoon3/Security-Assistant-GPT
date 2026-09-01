import { useEffect } from "react";
import { AlertTriangle, X, RotateCw } from "lucide-react";

interface ErrorBannerProps {
  message: string;
  onDismiss: () => void;
  onRetry?: () => void;
}

export function ErrorBanner({ message, onDismiss, onRetry }: ErrorBannerProps) {
  useEffect(() => {
    const t = setTimeout(onDismiss, 6000);
    return () => clearTimeout(t);
  }, [message, onDismiss]);

  return (
    <div
      role="alert"
      className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 flex items-center gap-3 max-w-md w-[calc(100%-3rem)] bg-red-950/90 backdrop-blur-xl border border-red-500/30 rounded-2xl px-4 py-3 shadow-[0_12px_40px_-8px_rgba(0,0,0,0.6),0_0_24px_-4px_rgba(239,68,68,0.25)] motion-safe:animate-in motion-safe:fade-in motion-safe:slide-in-from-bottom-4"
    >
      <AlertTriangle className="w-5 h-5 text-red-400 flex-shrink-0" aria-hidden />
      <p className="text-sm text-red-100 flex-1 min-w-0 break-words">{message}</p>
      {onRetry && (
        <button
          onClick={onRetry}
          aria-label="Retry"
          className="flex-shrink-0 text-red-300 hover:text-white transition-colors p-1.5 hover:bg-white/10 rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-300"
        >
          <RotateCw className="w-4 h-4" aria-hidden />
        </button>
      )}
      <button
        onClick={onDismiss}
        aria-label="Dismiss"
        className="flex-shrink-0 text-red-300 hover:text-white transition-colors p-1.5 hover:bg-white/10 rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-300"
      >
        <X className="w-4 h-4" aria-hidden />
      </button>
    </div>
  );
}