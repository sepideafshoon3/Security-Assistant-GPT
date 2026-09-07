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

export const API_BASE =
  import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";

function authHeaders(): Record<string, string> {
  const token = localStorage.getItem("sa_access_token");
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export async function sendMessageToBackend(
  conversationId: string | null,
  text: string
): Promise<BackendChatResponse> {
  const payload = {
    conversation_id: conversationId,
    messages: [{ role: "user", content: text }],
  };

  const res = await fetch(`${API_BASE}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(payload),
  });

  if (!res.ok) {
    const body = await res.text();
    throw new Error(
      `Chat request failed (${res.status}): ${body.slice(0, 200)}`
    );
  }

  return res.json();
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
}

export async function fetchConversations(): Promise<BackendConversationSummary[]> {
  const res = await fetch(`${API_BASE}/conversations`, {
    headers: { ...authHeaders() },
  });

  const text = await res.text();

  if (!res.ok) {
    throw new Error(
      `Failed to load conversations (${res.status}): ${text.slice(0, 200)}`
    );
  }

  try {
    const data = JSON.parse(text);
    return (data?.conversations as BackendConversationSummary[]) ?? [];
  } catch (err) {
    console.error("[fetchConversations] Non-JSON response:", text.slice(0, 500));
    throw new Error("Invalid JSON from /conversations");
  }
}