import { useState } from "react";
import { ShieldCheck, Loader2 } from "lucide-react";

type Mode = "login" | "signup";

interface LoginPageProps {
  onLogin: (email: string, password: string) => Promise<unknown>;
  onSignup: (email: string, password: string) => Promise<unknown>;
}

export function LoginPage({ onLogin, onSignup }: LoginPageProps) {
  const [mode, setMode] = useState<Mode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    if (!email.trim() || !password) {
      setError("email & password");
      return;
    }

    setIsSubmitting(true);
    try {
      if (mode === "login") {
        await onLogin(email.trim(), password);
      } else {
        await onSignup(email.trim(), password);
      }
    } catch (err: any) {
      setError(err instanceof Error ? err.message : "something went wrong.");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="flex h-screen items-center justify-center bg-gradient-to-br from-white via-slate-50 to-white dark:from-slate-950 dark:via-slate-900 dark:to-slate-950 relative overflow-hidden px-4 transition-colors duration-300">
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_top_right,_var(--tw-gradient-stops))] from-cyan-100/40 dark:from-cyan-900/20 via-transparent to-transparent pointer-events-none" />
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_bottom_left,_var(--tw-gradient-stops))] from-green-100/40 dark:from-green-900/20 via-transparent to-transparent pointer-events-none" />

      <div className="w-full max-w-sm relative z-10 rounded-2xl border border-slate-200 dark:border-white/10 bg-white/80 dark:bg-black/40 backdrop-blur-xl shadow-xl shadow-cyan-500/10 p-6 sm:p-8">
        <div className="flex flex-col items-center text-center gap-2 mb-6">
          <div className="w-12 h-12 bg-gradient-to-br from-brand-cyan to-brand-green rounded-xl flex items-center justify-center shadow-lg shadow-brand-cyan/50 mb-1">
            <ShieldCheck className="w-6 h-6 text-black" aria-hidden />
          </div>
          <h1 className="text-lg text-slate-900 dark:text-gray-100">
            {mode === "login" ? "login" : "signup"}
          </h1>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            {mode === "login"
              ? "see your chats"
              : "wait a sec"}
          </p>
        </div>

        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <label
              htmlFor="email"
              className="text-sm text-slate-700 dark:text-slate-300"
            >
              ایمیل
            </label>
            <input
              id="email"
              type="email"
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@example.com"
              disabled={isSubmitting}
              className="h-9 w-full rounded-md border border-slate-200 dark:border-white/10 bg-white dark:bg-white/5 px-3 text-sm text-slate-900 dark:text-gray-100 outline-none focus-visible:ring-2 focus-visible:ring-accent-hover disabled:opacity-50"
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <label
              htmlFor="password"
              className="text-sm text-slate-700 dark:text-slate-300"
            >
             password
            </label>
            <input
              id="password"
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
              "login"
            ) : (
              "signup"
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
              ? "signup"
              : "login"}
          </button>
        </form>
      </div>
    </div>
  );
}