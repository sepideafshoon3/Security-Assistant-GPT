// src/App.tsx
import { PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { useState, useEffect } from "react";
import { ConversationList } from "./components/ConversationList";
import { ChatArea } from "./components/ChatArea";
import { ErrorBanner } from "./components/ErrorBanner";
import {
  sendMessageToBackend,
  type BackendChatResponse,
  fetchConversations,
  type BackendConversationSummary,
  getFriendlyErrorMessage,
} from "./api/chat";
export interface Message {
  id: string;
  text: string;
  sender: "user" | "contact";
  timestamp: Date;
  failed?: boolean;
}

export interface Conversation {
  id: string;
  title: string;
  lastMessage: string;
  timestamp: Date;
  messages: Message[];
  status?: "clean" | "findings" | "critical"; 
}

function deriveStatus(text: string): Conversation["status"] {
  const t = (text || "").toLowerCase();
  if (/\bcritical\b|\bcve-\d{4}-\d+\b|\brce\b/.test(t)) return "critical";
  if (/vulnerab|finding|semgrep|bandit|osv-scan/.test(t)) return "findings";
  return "clean";
}


function mapBackendConversationToConversation(
  summary: BackendConversationSummary,
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
    status: deriveStatus(`${summary.theme || ""} ${lastMessageText}`),
  };
}

function mapBackendToMessages(resp: BackendChatResponse): Message[] {
  const now = Date.now();


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

  return [];
}

export default function App() {

  const [isSidebarOpen, setIsSidebarOpen] = useState(true);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [selectedConversationId, setSelectedConversationId] = useState<
    string | null
  >(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [errorRetry, setErrorRetry] = useState<(() => void) | null>(null);
  const selectedConversation = conversations.find(
    (c) => c.id === selectedConversationId,
  );

  const [processingConversationIds, setProcessingConversationIds] = useState<
    Set<string>
  >(new Set());

  const markProcessing = (id: string) =>
    setProcessingConversationIds((prev) => new Set(prev).add(id));

  const unmarkProcessing = (id: string) =>
    setProcessingConversationIds((prev) => {
      const next = new Set(prev);
      next.delete(id);
      return next;
    });

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
        setError(getFriendlyErrorMessage(e));
        setErrorRetry(() => load);
      } finally {
        setIsLoading(false);
      }
    };

    load();
  }, []);

  const handleNewConversation = () => {
    setError(null);
    setErrorRetry(null);
    setIsLoading(false);
    setSelectedConversationId(null);
  };

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

    if (!current) {
      const tempId = `tmp-${Date.now()}`;

      const tempConv: Conversation = {
        id: tempId,
        title: "New Conversation",
        lastMessage: trimmed,
        timestamp: now,
        messages: [userMessage],
      };

      setConversations((prev) => [...prev, tempConv]);
      setSelectedConversationId(tempId);
      markProcessing(tempId);

      setIsLoading(true);
      try {
        const resp = await sendMessageToBackend(null, trimmed);

        const backendMessages = mapBackendToMessages(resp);
        const assistantMessages = backendMessages.filter(
          (m) => m.sender === "contact",
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
          const others = prev.filter((c) => c.id !== tempId);
          return [...others, finalConv];
        });
        setSelectedConversationId(resp.conversation_id);
      } catch (e: any) {
        console.error(e);
        const friendly = getFriendlyErrorMessage(e);
        setError(friendly);
        setErrorRetry(() => () => handleSendMessage(trimmed));
        setConversations((prev) =>
          prev.map((c) =>
            c.id === tempId
              ? {
                  ...c,
                  messages: c.messages.map((m) =>
                    m.id === userMessage.id ? { ...m, failed: true } : m,
                  ),
                }
              : c,
          ),
        );
      } finally {
        setIsLoading(false);
        unmarkProcessing(tempId);
      }

      return;
    }


    setConversations((prev) =>
      prev.map((conv) =>
        conv.id === current.id
          ? {
              ...conv,
              messages: [...conv.messages, userMessage],
              lastMessage: trimmed,
              timestamp: now,
            }
          : conv,
      ),
    );

    markProcessing(current.id);
    setIsLoading(true);
    try {
      const resp = await sendMessageToBackend(current.id, trimmed);

      const backendMessages = mapBackendToMessages(resp);
      const assistantMessages = backendMessages.filter(
        (m) => m.sender === "contact",
      );
      const lastAssistantText =
        assistantMessages[assistantMessages.length - 1]?.text ||
        current.lastMessage;

      setConversations((prev) =>
        prev.map((conv) =>
          conv.id === current.id
            ? {
                ...conv,
                id: resp.conversation_id,
                messages: [...conv.messages, ...assistantMessages],
                lastMessage: lastAssistantText,
                timestamp: new Date(),
              }
            : conv,
        ),
      );
      setSelectedConversationId(resp.conversation_id);
    } catch (e: any) {
      console.error(e);
      const friendly = getFriendlyErrorMessage(e);
      setError(friendly);
      setErrorRetry(() => () => handleSendMessage(trimmed));
      setConversations((prev) =>
        prev.map((c) =>
          c.id === current.id
            ? {
                ...c,
                messages: c.messages.map((m) =>
                  m.id === userMessage.id ? { ...m, failed: true } : m,
                ),
              }
            : c,
        ),
      );
    } finally {
      setIsLoading(false);
      unmarkProcessing(current.id);
    }
  };
  const handleSelectConversation = (conversationId: string) => {
    setSelectedConversationId(conversationId);
  };

  const handleResendMessage = (messageId: string) => {
    const conv = selectedConversation;
    if (!conv) return;

    const target = conv.messages.find((m) => m.id === messageId);
    if (!target) return;

    setConversations((prev) =>
      prev.map((c) =>
        c.id === conv.id
          ? { ...c, messages: c.messages.filter((m) => m.id !== messageId) }
          : c,
      ),
    );

    handleSendMessage(target.text);
  };

  return (
    <div className="flex h-screen bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950 text-gray-100 relative overflow-hidden">
      {/* Background Effects */}
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_top_right,_var(--tw-gradient-stops))] from-cyan-900/20 via-transparent to-transparent pointer-events-none" />
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_bottom_left,_var(--tw-gradient-stops))] from-green-900/20 via-transparent to-transparent pointer-events-none" />

      {/* Header */}
      <div className="fixed top-0 left-0 right-0 h-16 bg-black/40 backdrop-blur-xl border-b border-white/10 z-10 flex items-center px-6 shadow-lg shadow-cyan-500/5">
        <button
          onClick={() => setIsSidebarOpen((v) => !v)}
          aria-label={isSidebarOpen ? "Close sidebar" : "Open sidebar"}
          className="mr-3 text-slate-400 hover:text-slate-200 transition-colors p-2 hover:bg-white/5 rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400"
        >
          {isSidebarOpen ? (
            <PanelLeftClose className="w-5 h-5" aria-hidden />
          ) : (
            <PanelLeftOpen className="w-5 h-5" aria-hidden />
          )}
        </button>
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 bg-gradient-to-br from-cyan-400 via-cyan-500 to-green-500 rounded-xl flex items-center justify-center shadow-lg shadow-cyan-500/50">
            <span className="text-black">MR</span>
          </div>
          <h1 className="text-cyan-400 tracking-wider bg-gradient-to-r from-cyan-400 to-green-400 bg-clip-text text-transparent">
            MR_ROBOT://CHAT
          </h1>
        </div>

        {/* Loading indicator (errors now shown via ErrorBanner below) */}
        <div className="ml-auto flex items-center gap-4 text-xs" />
      </div>

      {/* Main Content */}
      <div className="flex w-full pt-16 relative z-0">
        {/* Sidebar */}
        <ConversationList
          isOpen={isSidebarOpen}
          conversations={conversations}
          selectedConversationId={selectedConversationId ?? ""}
          onSelectConversation={handleSelectConversation}
          onNewConversation={handleNewConversation}
          processingConversationIds={processingConversationIds}
        />

        {/* Chat Area */}
        <ChatArea
          conversation={selectedConversation || null}
          onSendMessage={handleSendMessage}
          onResendMessage={handleResendMessage}
          isLoading={isLoading}
        />
      </div>

      {error && (
        <ErrorBanner
          message={error}
          onDismiss={() => {
            setError(null);
            setErrorRetry(null);
          }}
          onRetry={
            errorRetry
              ? () => {
                  const retry = errorRetry;
                  setError(null);
                  setErrorRetry(null);
                  retry();
                }
              : undefined
          }
        />
      )}
    </div>
  );
}
