import { forwardRef } from "react";
import type { ButtonHTMLAttributes } from "react";

type IconButtonProps = ButtonHTMLAttributes<HTMLButtonElement>;

export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(
  ({ className = "", ...props }, ref) => (
    <button
      ref={ref}
      type="button"
      className={`text-slate-400 hover:text-slate-200 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-300 rounded ${className}`}
      {...props}
    />
  ),
);
IconButton.displayName = "IconButton";