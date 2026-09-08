// src/components/LoginModal.tsx
import { useEffect, useState } from "react";
import { ShieldCheck, Loader2, X } from "lucide-react";

type Mode = "login" | "signup";

interface LoginModalProps {
  isOpen: boolean;
  onClose: () => void;
  onLogin: (email: string, password: string) => Promise<unknown>;
  onSignup: (email: string, password: string) => Promise<unknown>;
  initialMode?: Mode;
}

export function LoginModal({
  isOpen,
  onClose,
  onLogin,
  onSignup,
  initialMode = "login",
}: LoginModalProps) {
  const [mode, setMode] = useState<Mode>(initialMode);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Reset the form each time the modal is (re)opened, and sync the
  // requested initial mode (e.g. "Sign up" vs "Log in" trigger buttons).
  useEffect(() => {
    if (isOpen) {
      setMode(initialMode);
      setEmail("");
      setPassword("");
      setError(null);
      setIsSubmitting(false);
    }
  }, [isOpen, initialMode]);

  // Esc to close + lock background scroll while the modal is open.
  useEffect(() => {
    if (!isOpen) return;

    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handleEscape);

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    return () => {
      document.removeEventListener("keydown", handleEscape);
      document.body.style.overflow = previousOverflow;
    };
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    if (!email.trim() || !password) {
      setError("ایمیل و رمز عبور را وارد کنید.");
      return;
    }

    setIsSubmitting(true);
    try {
      if (mode === "login") {
        await onLogin(email.trim(), password);
      } else {
        await onSignup(email.trim(), password);
      }
      // On success, the parent's auth state flips and this modal's parent
      // branch stops rendering — no explicit onClose() needed, but calling
      // it is harmless and keeps state tidy if the parent tree changes.
      onClose();
    } catch (err: any) {
      setError(err instanceof Error ? err.message : "خطایی پیش آمد.");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="login-modal-title"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm px-4"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="w-full max-w-sm relative rounded-2xl border border-slate-200 dark:border-white/10 bg-white dark:bg-slate-950 shadow-2xl shadow-black/40 p-6 sm:p-8">
        <button
          type="button"
          onClick={onClose}
          aria-label="بستن"
          className="absolute top-3 left-3 p-1.5 rounded-lg text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 hover:bg-black/5 dark:hover:bg-white/10 transition-colors"
        >
          <X className="w-4 h-4" aria-hidden />
        </button>

        <div className="flex flex-col items-center text-center gap-2 mb-6">
          <div className="w-12 h-12 bg-gradient-to-br from-brand-cyan to-brand-green rounded-xl flex items-center justify-center shadow-lg shadow-brand-cyan/50 mb-1">
            <ShieldCheck className="w-6 h-6 text-black" aria-hidden />
          </div>
          <h1
            id="login-modal-title"
            className="text-lg text-slate-900 dark:text-gray-100"
          >
            {mode === "login" ? "ورود به حساب" : "ساخت حساب جدید"}
          </h1>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            {mode === "login"
              ? "برای دیدن گفتگوهای ذخیره‌شده‌ات وارد شو."
              : "چند ثانیه‌ای طول می‌کشد."}
          </p>
        </div>

        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <label
              htmlFor="modal-email"
              className="text-sm text-slate-700 dark:text-slate-300"
            >
              ایمیل
            </label>
            <input
              id="modal-email"
              type="email"
              autoComplete="email"
              autoFocus
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@example.com"
              disabled={isSubmitting}
              className="h-9 w-full rounded-md border border-slate-200 dark:border-white/10 bg-white dark:bg-white/5 px-3 text-sm text-slate-900 dark:text-gray-100 outline-none focus-visible:ring-2 focus-visible:ring-accent-hover disabled:opacity-50"
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <label
              htmlFor="modal-password"
              className="text-sm text-slate-700 dark:text-slate-300"
            >
              رمز عبور
            </label>
            <input
              id="modal-password"
              type="password"
              autoComplete={mode === "login" ? "current-password" : "new-password"}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
              disabled={isSubmitting}
              className="h-9 w-full rounded-md border border-slate-200 dark:border-white/10 bg-white dark:bg-white/5 px-3 text-sm text-slate-900 dark:text-gray-100 outline-none focus-visible:ring-2 focus-visible:ring-accent-hover disabled:opacity-50"
            />
          </div>

          {error && (
            <p className="text-sm text-red-500 dark:text-red-400" role="alert">
              {error}
            </p>
          )}

          <button
            type="submit"
            disabled={isSubmitting}
            className="mt-2 h-9 w-full rounded-md bg-gradient-to-r from-brand-cyan to-brand-green text-black text-sm font-medium flex items-center justify-center gap-2 hover:opacity-90 transition-opacity disabled:opacity-50 disabled:pointer-events-none"
          >
            {isSubmitting ? (
              <Loader2 className="w-4 h-4 animate-spin" aria-hidden />
            ) : mode === "login" ? (
              "ورود"
            ) : (
              "ثبت‌نام"
            )}
          </button>

          <button
            type="button"
            className="text-sm text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200 transition-colors"
            onClick={() => {
              setError(null);
              setMode((m) => (m === "login" ? "signup" : "login"));
            }}
          >
            {mode === "login"
              ? "حساب نداری؟ ثبت‌نام کن"
              : "قبلاً حساب ساختی؟ وارد شو"}
          </button>
        </form>
      </div>
    </div>
  );
}