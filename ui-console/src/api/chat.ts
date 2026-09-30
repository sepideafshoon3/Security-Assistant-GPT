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
  | { type: "chunk"; text: string }
  | { type: "done"; conversation_id: string }
  | { type: "error"; message: string };

/**
 * POSTs to /chat and reads back a text/event-stream body, calling onEvent
 * once per parsed SSE frame as it arrives. Uses fetch + ReadableStream
 * rather than EventSource because EventSource can't send our auth header
 * or a POST body.
 *
 * opts.signal is accepted now (for Task 3's stop button) but nothing in
 * this app passes one yet — an aborted fetch will simply reject this
 * promise, which the caller's try/catch already handles.
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
          console.error("[streamChat] failed to parse SSE frame:", dataLine, err);
          continue;
        }
        onEvent(event);
      }
    }
  } finally {
    reader.releaseLock();
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
