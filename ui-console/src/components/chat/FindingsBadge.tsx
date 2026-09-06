import { AlertTriangle, ShieldAlert, Wrench } from "lucide-react";
import { cn } from "../ui/utils";
import {
  extractFindings,
  hasNotableFindings,
  type Severity,
} from "../../utils/findings";

const SEVERITY_META: Record<
  Exclude<Severity, "clean">,
  { icon: typeof ShieldAlert; label: string; className: string }
> = {
  critical: {
    icon: ShieldAlert,
    label: "Critical finding",
    className:
      "bg-status-danger/10 text-status-danger-strong border-status-danger/30",
  },
  findings: {
    icon: AlertTriangle,
    label: "Has findings",
    className:
      "bg-status-warning/10 text-status-warning border-status-warning/30",
  },
};

interface FindingsBadgeProps {
  text: string;
}

export function FindingsBadge({ text }: FindingsBadgeProps) {
  const findings = extractFindings(text);
  if (!hasNotableFindings(findings)) return null;

  const severityMeta =
    findings.severity !== "clean" ? SEVERITY_META[findings.severity] : null;

  return (
    <div className="flex flex-wrap items-center gap-1.5 mb-1.5 px-1">
      {severityMeta && (
        <span
          className={cn(
            "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium",
            severityMeta.className,
          )}
        >
          <severityMeta.icon className="w-3 h-3" aria-hidden />
          {severityMeta.label}
        </span>
      )}
      {findings.tools.map((tool) => (
        <span
          key={tool}
          className="inline-flex items-center gap-1 rounded-full border border-border bg-surface-panel/80 px-2 py-0.5 text-[11px] font-mono text-fg-tertiary"
        >
          <Wrench className="w-3 h-3" aria-hidden />
          {tool}
        </span>
      ))}
      {findings.cves.map((cve) => (
        <span
          key={cve}
          className="inline-flex items-center rounded-full border border-border bg-surface-panel/80 px-2 py-0.5 text-[11px] font-mono text-fg-secondary"
        >
          {cve}
        </span>
      ))}
    </div>
  );
}
