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

/* --------- Streaming chat (SSE over fetch) --------- */

export type ChatStreamEvent =
  | { type: "start"; conversation_id: string }
  | { type: "snapshot"; text: string } // everything generated so far (sent on re-attach)
  | { type: "chunk"; text: string }
  | { type: "done"; conversation_id: string; stopped?: boolean }
  | { type: "error"; message: string };

/**
 * Reads an SSE response body, calling onEvent once per parsed frame.
 * Uses fetch + ReadableStream rather than EventSource because EventSource
 * can't send our auth header or a POST body.
 */
async function readSseStream(
  res: Response,
  onEvent: (event: ChatStreamEvent) => void,
): Promise<void> {
  if (!res.body) throw new Error("Response has no body");
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      // SSE frames are separated by a blank line. A read() chunk can land
      // mid-frame, so only consume complete frames and keep the remainder
      // buffered for the next read.
      let sepIndex: number;
      while ((sepIndex = buffer.indexOf("\n\n")) !== -1) {
        const rawFrame = buffer.slice(0, sepIndex);
        buffer = buffer.slice(sepIndex + 2);

        const dataLine = rawFrame.split("\n").find((line) => line.startsWith("data: "));
        if (!dataLine) continue;

        let event: ChatStreamEvent;
        try {
          event = JSON.parse(dataLine.slice("data: ".length));
        } catch (err) {
          console.error("[sse] failed to parse frame:", dataLine, err);
          continue;
        }
        onEvent(event);
      }
    }
  } finally {
    reader.releaseLock();
  }
}

/**
 * POSTs to /chat and follows the reply stream. NOTE: the backend generates
 * in a background task, so aborting `signal` (or refreshing the page) only
 * detaches this listener — it does NOT stop generation. Use
 * stopGeneration() for a real Stop.
 */
export async function streamChat(
  conversationId: string | null,
  text: string,
  onEvent: (event: ChatStreamEvent) => void,
  opts: { signal?: AbortSignal } = {},
): Promise<void> {
  const res = await fetch(`${API_BASE}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({
      conversation_id: conversationId,
      messages: [{ role: "user", content: text }],
    }),
    signal: opts.signal,
  });

  if (!res.ok || !res.body) {
    const body = await res.text().catch(() => "");
    throw new Error(`Chat request failed (${res.status}): ${body.slice(0, 200)}`);
  }
  await readSseStream(res, onEvent);
}

/**
 * Re-attaches to a generation that is still running on the server (e.g.
 * after a page refresh). Emits one "snapshot" event with the text so far,
 * then live "chunk" events until "done". Resolves false if nothing was
 * running (204).
 */
export async function attachToGeneration(
  conversationId: string,
  onEvent: (event: ChatStreamEvent) => void,
  opts: { signal?: AbortSignal } = {},
): Promise<boolean> {
  const res = await fetch(`${API_BASE}/conversations/${conversationId}/stream`, {
    headers: { ...authHeaders() },
    signal: opts.signal,
  });
  if (res.status === 204) return false;
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`Re-attach failed (${res.status}): ${body.slice(0, 200)}`);
  }
  await readSseStream(res, onEvent);
  return true;
}

/** Explicit Stop: tells the server to really end the generation. */
export async function stopGeneration(conversationId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/conversations/${conversationId}/stop`, {
    method: "POST",
    headers: { ...authHeaders() },
  });
  if (!res.ok) {
    throw new Error(`Stop failed (${res.status})`);
  }
}

/* --------- Generation status --------- */

export async function getGenerationStatus(conversationId: string): Promise<boolean> {
  const res = await fetch(`${API_BASE}/conversations/${conversationId}/generation-status`, {
    headers: { ...authHeaders() },
  });
  if (!res.ok) {
    // A transient failure here shouldn't trap the UI in a "still
    // generating" state forever — treat it as "not generating" and let
    // a normal reload/resend recover if something's actually wrong.
    return false;
  }
  try {
    const data = await res.json();
    return !!data.is_generating;
  } catch {
    return false;
  }
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
  project_id?: string | null;
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

export async function setConversationProject(conversationId: string, projectId: string | null) {
  const res = await fetch(`${API_BASE}/conversations/${conversationId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ project_id: projectId }),
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`Failed to update project (${res.status}): ${body.slice(0, 200)}`);
  }
}

/* --------- Projects --------- */

export interface BackendProject {
  id: string;
  name: string;
  created_at?: string;
  updated_at?: string;
}

export async function fetchProjects(): Promise<BackendProject[]> {
  const res = await fetch(`${API_BASE}/projects`, {
    headers: { ...authHeaders() },
  });
  const text = await res.text();
  if (!res.ok) {
    throw new Error(`Failed to load projects (${res.status}): ${text.slice(0, 200)}`);
  }
  try {
    const data = JSON.parse(text);
    return (data?.projects as BackendProject[]) ?? [];
  } catch (err) {
    console.error("[fetchProjects] Non-JSON response:", text.slice(0, 500), err);
    throw new Error("Invalid JSON from /projects");
  }
}

export async function createProject(name: string): Promise<BackendProject> {
  const res = await fetch(`${API_BASE}/projects`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ name }),
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`Failed to create project (${res.status}): ${body.slice(0, 200)}`);
  }
  return res.json();
}

export async function renameProject(projectId: string, name: string): Promise<BackendProject> {
  const res = await fetch(`${API_BASE}/projects/${projectId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ name }),
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`Failed to rename project (${res.status}): ${body.slice(0, 200)}`);
  }
  return res.json();
}

export async function deleteProject(projectId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/projects/${projectId}`, {
    method: "DELETE",
    headers: { ...authHeaders() },
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`Failed to delete project (${res.status}): ${body.slice(0, 200)}`);
  }
}
