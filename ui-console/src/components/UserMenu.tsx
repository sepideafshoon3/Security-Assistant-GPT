import { useEffect, useRef, useState } from "react";
import { ChevronDown, LogOut } from "lucide-react";
import { cn } from "./ui/utils";

interface UserMenuProps {
  email: string;
  plan?: string;
  onLogout: () => void;
}

export function UserMenu({ email, plan = "Free", onLogout }: UserMenuProps) {
  const [isOpen, setIsOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  const displayName = email.split("@")[0] || email;
  const initial = displayName.charAt(0).toUpperCase();

  useEffect(() => {
    if (!isOpen) return;

    const handleClickOutside = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    };
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === "Escape") setIsOpen(false);
    };

    document.addEventListener("mousedown", handleClickOutside);
    document.addEventListener("keydown", handleEscape);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
      document.removeEventListener("keydown", handleEscape);
    };
  }, [isOpen]);

  return (
    <div ref={rootRef} className="relative">
      {isOpen && (
        <div
          role="menu"
          className="absolute bottom-full left-0 right-0 mb-2 rounded-lg border border-border bg-popover shadow-xl shadow-black/20 overflow-hidden"
        >
          <button
            role="menuitem"
            onClick={() => {
              setIsOpen(false);
              onLogout();
            }}
            className="w-full flex items-center gap-2.5 px-3 py-2.5 text-sm text-fg-secondary hover:bg-secondary transition-colors text-left"
          >
            <LogOut className="w-4 h-4" aria-hidden />
            logout
          </button>
        </div>
      )}

      <button
        onClick={() => setIsOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={isOpen}
        className={cn(
          "w-full flex items-center gap-2 px-2 py-1.5 rounded-lg hover:bg-secondary transition-colors text-left",
          isOpen && "bg-secondary",
        )}
      >
        <div className="w-7 h-7 shrink-0 rounded-full bg-gradient-to-br from-brand-cyan to-brand-green flex items-center justify-center text-black text-xs font-medium">
          {initial}
        </div>
        <div className="min-w-0 flex-1 flex items-baseline gap-1 text-sm">
          <span className="text-fg-primary truncate">{displayName}</span>
          <span className="text-fg-faint shrink-0">· {plan}</span>
        </div>
        <ChevronDown
          className={cn(
            "w-3.5 h-3.5 text-fg-faint shrink-0 transition-transform duration-200",
            isOpen && "rotate-180",
          )}
          aria-hidden
        />
      </button>
    </div>
  );
}