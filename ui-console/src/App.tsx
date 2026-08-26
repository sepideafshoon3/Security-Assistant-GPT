// src/App.tsx
import { useState, useEffect } from "react";
import { ConversationList } from "./components/ConversationList";
import { ChatArea } from "./components/ChatArea";
import {
  sendMessageToBackend,
  type BackendChatResponse,
  fetchConversations,
  type BackendConversationSummary,
} from "./api/chat";
export interface Message {
  id: string;
  text: string;
  sender: "user" | "contact";
  timestamp: Date;
}

export interface Conversation {
  id: string;
  title: string;
  lastMessage: string;
  timestamp: Date;
  messages: Message[];
}

/**
 * مپ کردن خلاصه‌ی کانورسیشن بک‌اند به مدل فرانت.
 */
function mapBackendConversationToConversation(
  summary: BackendConversationSummary
): Conversation {
  const ts = summary.last_updated ? new Date(summary.last_updated) : new Date();

  const messages: Message[] = (summary.last_messages || []).map((m, index) => ({
    id: `hist-${summary.conversation_id}-${index}`,
    text: m.content,
    sender: m.role === "user" ? "user" : "contact",
    timestamp: ts,
  }));

  const lastMessageText =
    messages[messages.length - 1]?.text || "No messages yet";

  return {
    id: summary.conversation_id,
    title: summary.theme || "Conversation",
    lastMessage: lastMessageText,
    timestamp: ts,
    messages,
  };
}

function mapBackendToMessages(resp: BackendChatResponse): Message[] {
  const now = Date.now();

  // Preferred: backend sends an array of messages
  if (
    resp.messages &&
    Array.isArray(resp.messages) &&
    resp.messages.length > 0
  ) {
    return resp.messages.map((m, index) => ({
      id: `m-${now}-${index}`,
      text: m.content,
      sender: m.role === "user" ? "user" : "contact",
      timestamp: new Date(),
    }));
  }

  // Fallback: current backend only sends a single "reply" string
  if (resp.reply) {
    return [
      {
        id: `m-${now}-0`,
        text: resp.reply,
        sender: "contact",
        timestamp: new Date(),
      },
    ];
  }

  // No messages in response
  return [];
}

export default function App() {
  // حالا چند کانورسیشن رو تو state نگه می‌داریم، نه فقط یکی.
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [selectedConversationId, setSelectedConversationId] = useState<
    string | null
  >(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const selectedConversation = conversations.find(
    (c) => c.id === selectedConversationId
  );

  // --- on mount: لیست کانورسیشن‌ها رو از بک‌اند بگیر ---
  useEffect(() => {
    const load = async () => {
      setIsLoading(true);
      setError(null);
      try {
        const backendConvs = await fetchConversations();
        const mapped = backendConvs.map(mapBackendConversationToConversation);
        setConversations(mapped);
        if (mapped.length > 0) {
          setSelectedConversationId(mapped[0].id);
        }
      } catch (e: any) {
        console.error(e);
        setError(e?.message || "Failed to load conversations");
      } finally {
        setIsLoading(false);
      }
    };

    load();
  }, []);

  // "New Chat" button: فقط کانورسیشن جدید شروع کن؛ قبلی‌ها رو پاک نکن.
  const handleNewConversation = () => {
    setError(null);
    setIsLoading(false);
    setSelectedConversationId(null);
  };

  // SEND MESSAGE: handles both new and existing conversations.
  const handleSendMessage = async (text: string) => {
    const trimmed = text.trim();
    if (!trimmed) return;

    setError(null);

    const now = new Date();
    const userMessage: Message = {
      id: `m-${Date.now()}`,
      text: trimmed,
      sender: "user",
      timestamp: now,
    };

    const current = selectedConversation;

    // ===== NEW CONVERSATION BRANCH =====
    if (!current) {
      const tempId = `tmp-${Date.now()}`;

      // Optimistic: show user message immediately with a temporary conversation
      const tempConv: Conversation = {
        id: tempId,
        title: "New Conversation",
        lastMessage: trimmed,
        timestamp: now,
        messages: [userMessage],
      };

      // قبلی‌ها رو نگه دار، این جدید رو اضافه کن
      setConversations((prev) => [...prev, tempConv]);
      setSelectedConversationId(tempId);

      setIsLoading(true);
      try {
        const resp = await sendMessageToBackend(null, trimmed);

        const backendMessages = mapBackendToMessages(resp);
        const assistantMessages = backendMessages.filter(
          (m) => m.sender === "contact"
        );
        const lastAssistantText =
          assistantMessages[assistantMessages.length - 1]?.text || trimmed;

        const finalConv: Conversation = {
          id: resp.conversation_id,
          title: "Mr Robot Chat",
          lastMessage: lastAssistantText,
          timestamp: new Date(),
          messages: [userMessage, ...assistantMessages],
        };

        setConversations((prev) => {
          // temp کانورسیشن رو بردار و تا جاش نسخه نهایی رو بگذار
          const others = prev.filter((c) => c.id !== tempId);
          return [...others, finalConv];
        });
        setSelectedConversationId(resp.conversation_id);
      } catch (e: any) {
        console.error(e);
        setError(e?.message || "Failed to send message");
      } finally {
        setIsLoading(false);
      }

      return;
    }

    // ===== EXISTING CONVERSATION BRANCH =====

    // Optimistic update: add user message immediately
    setConversations((prev) =>
      prev.map((conv) =>
        conv.id === current.id
          ? {
              ...conv,
              messages: [...conv.messages, userMessage],
              lastMessage: trimmed,
              timestamp: now,
            }
          : conv
      )
    );

    setIsLoading(true);
    try {
      const resp = await sendMessageToBackend(current.id, trimmed);

      const backendMessages = mapBackendToMessages(resp);
      const assistantMessages = backendMessages.filter(
        (m) => m.sender === "contact"
      );
      const lastAssistantText =
        assistantMessages[assistantMessages.length - 1]?.text ||
        current.lastMessage;

      setConversations((prev) =>
        prev.map((conv) =>
          conv.id === current.id
            ? {
                ...conv,
                id: resp.conversation_id, // در صورت تغییر id از سمت بک‌اند
                messages: [...conv.messages, ...assistantMessages],
                lastMessage: lastAssistantText,
                timestamp: new Date(),
              }
            : conv
        )
      );
      setSelectedConversationId(resp.conversation_id);
    } catch (e: any) {
      console.error(e);
      setError(e?.message || "Failed to send message");
    } finally {
      setIsLoading(false);
    }
  };

  const handleSelectConversation = (conversationId: string) => {
    setSelectedConversationId(conversationId);
  };

  return (
    <div className="flex h-screen bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950 text-gray-100 relative overflow-hidden">
      {/* Background Effects */}
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_top_right,_var(--tw-gradient-stops))] from-cyan-900/20 via-transparent to-transparent pointer-events-none" />
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_bottom_left,_var(--tw-gradient-stops))] from-green-900/20 via-transparent to-transparent pointer-events-none" />

      {/* Header */}
      <div className="fixed top-0 left-0 right-0 h-16 bg-black/40 backdrop-blur-xl border-b border-white/10 z-10 flex items-center px-6 shadow-lg shadow-cyan-500/5">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 bg-gradient-to-br from-cyan-400 via-cyan-500 to-green-500 rounded-xl flex items-center justify-center shadow-lg shadow-cyan-500/50">
            <span className="text-black">MR</span>
          </div>
          <h1 className="text-cyan-400 tracking-wider bg-gradient-to-r from-cyan-400 to-green-400 bg-clip-text text-transparent">
            MR_ROBOT://CHAT
          </h1>
        </div>

        {/* Optional loading/error indicator */}
        <div className="ml-auto flex items-center gap-4 text-xs">
          {isLoading && (
            <span className="text-cyan-300 animate-pulse">thinking…</span>
          )}
          {error && (
            <span className="text-red-400 max-w-xs truncate">{error}</span>
          )}
        </div>
      </div>

      {/* Main Content */}
      <div className="flex w-full pt-16 relative z-0">
        {/* Sidebar */}
        <ConversationList
          conversations={conversations}
          selectedConversationId={selectedConversationId ?? ""}
          onSelectConversation={handleSelectConversation}
          onNewConversation={handleNewConversation}
        />

        {/* Chat Area */}
        <ChatArea
          conversation={selectedConversation || null}
          onSendMessage={handleSendMessage}
        />
      </div>
    </div>
  );
}
