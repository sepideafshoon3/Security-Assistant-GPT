export interface BackendChatMessage {
  role: string;
  content: string;
}

export interface BackendChatResponse {
  conversation_id: string;
  reply?: string;
  messages?: BackendChatMessage[];
}

export function getFriendlyErrorMessage(err: unknown): string {
  if (err instanceof TypeError && /fetch/i.test(err.message)) {
    return "Can't reach the server. Is the backend running?";
  }
  if (err instanceof Error) {
    return err.message;
  }
  return "Something went wrong.";
}

export const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";

function authHeaders(): Record<string, string> {
  const token = localStorage.getItem("sa_access_token");
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export interface JobStartResponse {
  conversation_id: string;
  job_id: string;
  status: "running";
}

export interface JobStatusResponse {
  job_id: string;
  conversation_id: string;
  status: "running" | "done" | "error";
  reply?: string;
  error?: string;
}

export async function startChatJob(
  conversationId: string | null,
  text: string,
): Promise<JobStartResponse> {
  const res = await fetch(`${API_BASE}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({
      conversation_id: conversationId,
      messages: [{ role: "user", content: text }],
    }),
  });

  if (!res.ok) {
    const body = await res.text();
    throw new Error(`Chat request failed (${res.status}): ${body.slice(0, 200)}`);
  }

  return res.json();
}

export async function pollChatJob(jobId: string): Promise<JobStatusResponse> {
  const res = await fetch(`${API_BASE}/chat/jobs/${jobId}`, {
    headers: { ...authHeaders() },
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`Job lookup failed (${res.status}): ${body.slice(0, 200)}`);
  }
  return res.json();
}

export async function waitForChatJob(
  jobId: string,
  opts: { signal?: AbortSignal; maxWaitMs?: number } = {},
): Promise<JobStatusResponse> {
  const { signal, maxWaitMs = 10 * 60 * 1000 } = opts; // 10 min hard ceiling
  const startedAt = Date.now();

  while (true) {
    if (signal?.aborted) {
      throw new DOMException("Polling aborted", "AbortError");
    }
    if (Date.now() - startedAt > maxWaitMs) {
      return {
        job_id: jobId,
        conversation_id: "",
        status: "error",
        error: "Timed out waiting for a response.",
      };
    }
    const status = await pollChatJob(jobId);
    if (status.status !== "running") return status;
    await new Promise((r) => setTimeout(r, 1500));
  }
}

export async function getActiveJob(conversationId: string): Promise<string | null> {
  const res = await fetch(`${API_BASE}/conversations/${conversationId}/active-job`, {
    headers: { ...authHeaders() },
  });
  if (!res.ok) return null;
  const data = await res.json();
  return data.job_id ?? null;
}

/* --------- Conversation list --------- */

export interface BackendHistoryMessage {
  role: string;
  content: string;
  created_at?: string;
}

export interface BackendConversationSummary {
  conversation_id: string;
  theme: string;
  keywords?: string[];
  num_messages: number;
  last_updated?: string;
  last_messages: BackendHistoryMessage[];
  pinned: boolean;
}

export async function fetchConversations(): Promise<BackendConversationSummary[]> {
  const res = await fetch(`${API_BASE}/conversations`, {
    headers: { ...authHeaders() },
  });

  const text = await res.text();

  if (!res.ok) {
    throw new Error(`Failed to load conversations (${res.status}): ${text.slice(0, 200)}`);
  }

  try {
    const data = JSON.parse(text);
    return (data?.conversations as BackendConversationSummary[]) ?? [];
  } catch (err) {
    console.error("[fetchConversations] Non-JSON response:", text.slice(0, 500), err);
    throw new Error("Invalid JSON from /conversations");
  }
}

export async function deleteConversation(conversationId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/conversations/${conversationId}`, {
    method: "DELETE",
    headers: { ...authHeaders() },
  });

  if (!res.ok) {
    const body = await res.text();
    throw new Error(`Failed to delete conversation (${res.status}): ${body.slice(0, 200)}`);
  }
}

export async function renameConversation(
  conversationId: string,
  title: string,
): Promise<{ conversation_id: string; theme: string; last_updated?: string }> {
  const res = await fetch(`${API_BASE}/conversations/${conversationId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ title }),
  });

  if (!res.ok) {
    const body = await res.text();
    throw new Error(`Failed to rename conversation (${res.status}): ${body.slice(0, 200)}`);
  }

  return res.json();
}

export async function setConversationPinned(conversationId: string, pinned: boolean) {
  const res = await fetch(`${API_BASE}/conversations/${conversationId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ pinned }),
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`Failed to update pin (${res.status}): ${body.slice(0, 200)}`);
  }
}
