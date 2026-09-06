// src/utils/findings.ts
//
// Lightweight, client-side heuristics for surfacing security-relevant
// signal in plain-text assistant replies. This is intentionally text-based:
// the backend doesn't yet return structured scan results (see api-core's
// tool runners for semgrep/bandit/osv-scanner), so this reads the same
// kind of signal the sidebar's status dot already looks for and extends
// it into the chat itself. Once the backend returns structured findings,
// swap the regex-based extraction below for the real payload and keep
// the component API (Severity, Finding) the same.

export type Severity = "critical" | "findings" | "clean";

const CRITICAL_PATTERN = /\bcritical\b|\bcve-\d{4}-\d+\b|\brce\b/i;
const FINDINGS_PATTERN = /vulnerab|finding|semgrep|bandit|osv-scan/i;

const KNOWN_TOOLS = ["semgrep", "bandit", "osv-scanner", "osv-scan"] as const;
const CVE_ID_PATTERN = /\bCVE-\d{4}-\d{4,}\b/gi;

export interface Findings {
  severity: Severity;
  cves: string[];
  tools: string[];
}

/** Matches the sidebar's existing conversation-level status heuristic. */
export function deriveSeverity(text: string): Severity {
  const t = (text || "").toLowerCase();
  if (CRITICAL_PATTERN.test(t)) return "critical";
  if (FINDINGS_PATTERN.test(t)) return "findings";
  return "clean";
}

function extractCves(text: string): string[] {
  const matches = text.match(CVE_ID_PATTERN) ?? [];
  return Array.from(new Set(matches.map((m) => m.toUpperCase())));
}

function extractTools(text: string): string[] {
  const lower = text.toLowerCase();
  return KNOWN_TOOLS.filter((tool) => lower.includes(tool)).map((tool) =>
    tool === "osv-scan" ? "osv-scanner" : tool,
  );
}

/**
 * Pull out everything worth badging from a message's text. Returns
 * severity "clean" with empty arrays when nothing security-relevant
 * was detected — callers should treat that as "render nothing".
 */
export function extractFindings(text: string): Findings {
  return {
    severity: deriveSeverity(text),
    cves: extractCves(text),
    tools: Array.from(new Set(extractTools(text))),
  };
}

export function hasNotableFindings(findings: Findings): boolean {
  return (
    findings.severity !== "clean" ||
    findings.cves.length > 0 ||
    findings.tools.length > 0
  );
}
