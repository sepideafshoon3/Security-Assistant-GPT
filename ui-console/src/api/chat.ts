// src/api/chat.ts
export interface BackendChatMessage {
  role: string;
  content: string;
}

export interface BackendChatResponse {
  conversation_id: string;
  reply?: string;
  messages?: BackendChatMessage[];
}

// همون base URL که برای /chat استفاده می‌کنی:
export const API_BASE =
  import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";

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
    headers: { "Content-Type": "application/json" },
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
  const res = await fetch(`${API_BASE}/conversations`);

  const text = await res.text();

  if (!res.ok) {
    throw new Error(
      `Failed to load conversations (${res.status}): ${text.slice(0, 200)}`
    );
  }

  // اگر باز هم HTML برگشته، اینجا سریع متوجه می‌شی
  try {
    const data = JSON.parse(text);
    return (data?.conversations as BackendConversationSummary[]) ?? [];
  } catch (err) {
    console.error("[fetchConversations] Non-JSON response:", text.slice(0, 500));
    throw new Error("Invalid JSON from /conversations");
  }
}
