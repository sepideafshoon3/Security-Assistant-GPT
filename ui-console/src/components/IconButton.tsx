import { forwardRef } from "react";
import type { ButtonHTMLAttributes } from "react";
import { cn } from "./ui/utils";

type IconButtonProps = ButtonHTMLAttributes<HTMLButtonElement>;

export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(
  ({ className, disabled, ...props }, ref) => (
    <button
      ref={ref}
      type="button"
      disabled={disabled}
      className={cn(
        "text-fg-tertiary hover:text-fg-primary transition-colors rounded",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-strong",
        disabled && "opacity-30 pointer-events-none",
        className,
      )}
      {...props}
    />
  ),
);
IconButton.displayName = "IconButton";
