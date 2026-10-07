import { PanelLeftClose, PanelLeftOpen, ShieldCheck, Loader2 } from "lucide-react";
import { useState, useEffect, useRef } from "react";
import { ConversationList } from "./components/ConversationList";
import { ChatArea } from "./components/ChatArea";
import { ErrorBanner } from "./components/ErrorBanner";
import { LoginModal } from "./components/LoginModal";
import { useTheme } from "./hooks/useTheme";
import { useAuth } from "./hooks/useAuth";
import { useIsMobile } from "./components/ui/use-mobile";
import { deriveSeverity } from "./utils/findings";
import {
  streamChat,
  attachToGeneration,
  stopGeneration,
  getActiveGenerationIds,
  getGenerationStatus,
  fetchConversations,
  type BackendConversationSummary,
  getFriendlyErrorMessage,
  deleteConversation,
  renameConversation,
  setConversationPinned,
  setConversationProject,
  fetchProjects,
  createProject,
  renameProject,
  deleteProject,
  type BackendProject,
} from "./api/chat";

export interface Project {
  id: string;
  name: string;
}
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
  status?: "clean" | "findings" | "critical"; // TODO: source from backend scan results
  pinned?: boolean;
  projectId?: string | null;
}

function deriveStatus(text: string): Conversation["status"] {
  return deriveSeverity(text);
}

function mapBackendConversationToConversation(summary: BackendConversationSummary): Conversation {
  const fallbackTs = summary.last_updated ? new Date(summary.last_updated) : new Date();

  const messages: Message[] = (summary.last_messages || []).map((m, index) => ({
    id: `hist-${summary.conversation_id}-${index}`,
    text: m.content,
    sender: m.role === "user" ? "user" : "contact",
    timestamp: m.created_at ? new Date(m.created_at) : fallbackTs,
  }));

  const lastMessageText = messages[messages.length - 1]?.text || "No messages yet";

  return {
    id: summary.conversation_id,
    title: summary.theme || "Conversation",
    lastMessage: lastMessageText,
    timestamp: fallbackTs,
    messages,
    status: deriveStatus(`${summary.theme || ""} ${lastMessageText}`),
    pinned: summary.pinned,
    projectId: summary.project_id ?? null,
  };
}

function mapBackendProjectToProject(p: BackendProject): Project {
  return { id: p.id, name: p.name };
}

export default function App() {
  const auth = useAuth();
  const [authModal, setAuthModal] = useState<{ open: boolean; mode: "login" | "signup" }>({
    open: false,
    mode: "login",
  });
  const { theme, toggleTheme } = useTheme();
  const isMobile = useIsMobile();
  const [isSidebarOpen, setIsSidebarOpen] = useState(
    () => typeof window !== "undefined" && window.innerWidth >= 768,
  );

  // Keep the sidebar's open/closed default sensible as the viewport crosses
  // the mobile breakpoint (e.g. rotating a tablet, resizing a window).
  const [hasAdjustedForBreakpoint, setHasAdjustedForBreakpoint] = useState(false);
  useEffect(() => {
    if (hasAdjustedForBreakpoint) return;
    setIsSidebarOpen(!isMobile);
    setHasAdjustedForBreakpoint(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isMobile]);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedConversationId, setSelectedConversationId] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [errorRetry, setErrorRetry] = useState<(() => void) | null>(null);
  const selectedConversation = conversations.find((c) => c.id === selectedConversationId);
  const [processingConversationIds, setProcessingConversationIds] = useState<Set<string>>(
    new Set(),
  );
  // Keyed by whatever conversation id is "live" at the time (see the id
  // swap in handleSendMessage for a brand-new conversation) — lets the
  // Stop button abort the right in-flight stream even if more than one
  // conversation is generating at once.
  const streamControllersRef = useRef<Map<string, AbortController>>(new Map());
  // Mirrors processingConversationIds but read synchronously (no React
  // batching delay) from reattachToGeneration's guard below — see its
  // comment for why the state version alone isn't reliable there.
  const locallyStreamingRef = useRef<Set<string>>(new Set());

  // Real Stop = tell the server. Generation runs in a backend task that
  // survives disconnects (refresh, closed tab), so aborting the fetch alone
  // would only hide the reply while the model keeps running. On success the
  // open stream ends by itself with a "done" event; the local abort is only
  // a fallback if the stop request itself fails.
  const handleStopGenerating = (conversationId: string) => {
    stopGeneration(conversationId).catch((e) => {
      console.error("[stop] request failed, detaching locally", e);
      streamControllersRef.current.get(conversationId)?.abort();
    });
  };

  // After a refresh: if the server is still generating a reply for this
  // conversation, re-attach — show what's been produced so far and keep
  // streaming the rest live, then swap in the persisted version.
  const reattachToGeneration = async (conversationId: string) => {
    // Guard against double subscription: if this tab is already live-
    // streaming this conversation via handleSendMessage's own streamChat
    // (e.g. the load effect re-firing mid-send — Fast Refresh during dev
    // is the common trigger, but a stray re-render could do it too), a
    // second subscriber here would render a second, independently-growing
    // copy of the same reply until the next fetchConversations reconciles
    // them. A ref (not state) because this must be correct the instant
    // the effect runs, with no render/commit delay.
    if (locallyStreamingRef.current.has(conversationId)) return;
    if (!(await getGenerationStatus(conversationId))) return;
    markProcessing(conversationId);

    const resumedId = `m-${Date.now()}-assistant-resumed`;
    let text = "";
    const showText = () => {
      if (!text) return;
      setConversations((prev) =>
        prev.map((conv) => {
          if (conv.id !== conversationId) return conv;
          const exists = conv.messages.some((m) => m.id === resumedId);
          return {
            ...conv,
            lastMessage: text,
            messages: exists
              ? conv.messages.map((m) => (m.id === resumedId ? { ...m, text } : m))
              : [
                  ...conv.messages,
                  {
                    id: resumedId,
                    text,
                    sender: "contact" as const,
                    timestamp: new Date(),
                  },
                ],
          };
        }),
      );
    };

    try {
      await attachToGeneration(conversationId, (event) => {
        if (event.type === "snapshot") {
          text = event.text;
          showText();
        } else if (event.type === "chunk") {
          text += event.text;
          showText();
        }
      });
    } catch (e) {
      console.error("[reattach] failed", e);
    } finally {
      unmarkProcessing(conversationId);
      try {
        const refreshed = await fetchConversations();
        const summary = refreshed.find((c) => c.conversation_id === conversationId);
        if (summary) {
          const fresh = mapBackendConversationToConversation(summary);
          setConversations((prev) => prev.map((c) => (c.id === conversationId ? fresh : c)));
        }
      } catch (e) {
        console.error("[reattach] refresh failed", e);
      }
    }
  };

  const markProcessing = (id: string) =>
    setProcessingConversationIds((prev) => new Set(prev).add(id));

  const unmarkProcessing = (id: string) =>
    setProcessingConversationIds((prev) => {
      const next = new Set(prev);
      next.delete(id);
      return next;
    });

  useEffect(() => {
    if (!auth.isCheckingSession && !auth.isAuthenticated) {
      setAuthModal((s) => (s.open ? s : { open: true, mode: "login" }));
    }
  }, [auth.isCheckingSession, auth.isAuthenticated]);

  useEffect(() => {
    if (!auth.isAuthenticated) {
      // Wipe any previously-loaded user's data immediately on logout --
      // otherwise it stays visible underneath the login modal, since the
      // app shell renders dimmed behind it rather than unmounting.
      setConversations([]);
      setProjects([]);
      setSelectedConversationId(null);
      setError(null);
      setErrorRetry(null);
      return;
    }

    const load = async () => {
      setIsLoading(true);
      setError(null);
      try {
        const [backendConvs, backendProjects] = await Promise.all([
          fetchConversations(),
          fetchProjects().catch((e) => {
            // Projects are a nice-to-have for the sidebar; don't let a
            // failure here block the conversation list from loading.
            console.error(e);
            return [] as BackendProject[];
          }),
        ]);
        setProjects(backendProjects.map(mapBackendProjectToProject));

        // Clear out abandoned empty chats (e.g. a conversation row that got
        // created but never received a message, such as a request that was
        // interrupted before it could persist anything).
        const empty = backendConvs.filter((c) => c.num_messages === 0);
        const nonEmpty = backendConvs.filter((c) => c.num_messages > 0);
        if (empty.length > 0) {
          await Promise.allSettled(empty.map((c) => deleteConversation(c.conversation_id)));
        }

        const mapped = nonEmpty.map(mapBackendConversationToConversation);
        setConversations(mapped);

        if (mapped.length > 0) {
          setSelectedConversationId(mapped[0].id);
        }

        // A refresh no longer kills generation (it runs in a backend
        // task), so re-attach to every conversation that's still mid-reply.
        // One request names them all; asking per conversation meant N
        // requests on every load. (reattachToGeneration itself skips anything
        // this tab is already live-streaming — see its guard.)
        const generating = new Set(await getActiveGenerationIds());
        mapped
          .filter((conv) => generating.has(conv.id))
          .forEach((conv) => {
            void reattachToGeneration(conv.id);
          });
      } catch (e) {
        console.error(e);
        setError(getFriendlyErrorMessage(e));
        setErrorRetry(() => load);
      } finally {
        setIsLoading(false);
      }
    };

    load();
    // Only re-run on auth changes; reattachToGeneration only uses stable setState helpers.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [auth.isAuthenticated]);
  const handleNewConversation = () => {
    setError(null);
    setErrorRetry(null);
    setIsLoading(false);
    setSelectedConversationId(null);
  };

  const handleDeleteConversation = async (conversationId: string) => {
    // Optimistic removal — revert if the request fails.
    const previous = conversations;
    setConversations((prev) => prev.filter((c) => c.id !== conversationId));
    if (selectedConversationId === conversationId) {
      setSelectedConversationId(null);
    }

    try {
      await deleteConversation(conversationId);
    } catch (e) {
      console.error(e);
      setConversations(previous);
      if (selectedConversationId === conversationId) {
        setSelectedConversationId(conversationId);
      }
      setError(getFriendlyErrorMessage(e));
    }
  };

  const handleRenameConversation = async (conversationId: string, title: string) => {
    const trimmed = title.trim();
    if (!trimmed) return;

    const previous = conversations;
    setConversations((prev) =>
      prev.map((c) => (c.id === conversationId ? { ...c, title: trimmed } : c)),
    );

    try {
      await renameConversation(conversationId, trimmed);
    } catch (e) {
      console.error(e);
      setConversations(previous);
      setError(getFriendlyErrorMessage(e));
    }
  };

  const handlePinConversation = async (conversationId: string) => {
    const target = conversations.find((c) => c.id === conversationId);
    const next = !target?.pinned;
    setConversations((prev) =>
      prev.map((c) => (c.id === conversationId ? { ...c, pinned: next } : c)),
    );
    try {
      await setConversationPinned(conversationId, next);
    } catch (err) {
      console.error(err);
      setConversations((prev) =>
        prev.map((c) => (c.id === conversationId ? { ...c, pinned: !next } : c)),
      );
      setError("Couldn't update pin — try again.");
    }
  };

  const handleSetConversationProject = async (conversationId: string, projectId: string | null) => {
    const previous = conversations;
    setConversations((prev) =>
      prev.map((c) => (c.id === conversationId ? { ...c, projectId } : c)),
    );
    try {
      await setConversationProject(conversationId, projectId);
    } catch (e) {
      console.error(e);
      setConversations(previous);
      setError("Couldn't update project — try again.");
    }
  };

  const handleCreateProject = async (name: string): Promise<Project | null> => {
    const trimmed = name.trim();
    if (!trimmed) return null;
    try {
      const created = await createProject(trimmed);
      const project = mapBackendProjectToProject(created);
      setProjects((prev) => [...prev, project]);
      return project;
    } catch (e) {
      console.error(e);
      setError("Couldn't create project — try again.");
      return null;
    }
  };

  const handleRenameProject = async (projectId: string, name: string) => {
    const trimmed = name.trim();
    if (!trimmed) return;
    const previous = projects;
    setProjects((prev) => prev.map((p) => (p.id === projectId ? { ...p, name: trimmed } : p)));
    try {
      await renameProject(projectId, trimmed);
    } catch (e) {
      console.error(e);
      setProjects(previous);
      setError("Couldn't rename project — try again.");
    }
  };

  const handleDeleteProject = async (projectId: string) => {
    const previousProjects = projects;
    const previousConversations = conversations;
    setProjects((prev) => prev.filter((p) => p.id !== projectId));
    // The backend un-files conversations (project_id -> null) rather than
    // deleting them, so mirror that locally.
    setConversations((prev) =>
      prev.map((c) => (c.projectId === projectId ? { ...c, projectId: null } : c)),
    );
    try {
      await deleteProject(projectId);
    } catch (e) {
      console.error(e);
      setProjects(previousProjects);
      setConversations(previousConversations);
      setError("Couldn't delete project — try again.");
    }
  };

  const handleSendMessage = async (text: string) => {
    const trimmed = text.trim();
    if (!trimmed) return;

    if (!auth.isAuthenticated) {
      setAuthModal({ open: true, mode: "login" });
      return;
    }

    setError(null);

    const now = new Date();
    const userMessage: Message = {
      id: `m-${Date.now()}`,
      text: trimmed,
      sender: "user",
      timestamp: now,
    };

    const current = selectedConversation;
    const isNewConversation = !current;
    const localId = current?.id ?? `tmp-${Date.now()}`;
    // Mutable across the whole send: starts as localId, and for a brand
    // new conversation gets swapped to the backend's real id as soon as
    // the "start" SSE frame arrives (before any text has streamed in).
    let activeId = localId;

    if (isNewConversation) {
      const tempConv: Conversation = {
        id: localId,
        title: "New Conversation",
        lastMessage: trimmed,
        timestamp: now,
        messages: [userMessage],
      };
      setConversations((prev) => [...prev, tempConv]);
      setSelectedConversationId(localId);
    } else {
      setConversations((prev) =>
        prev.map((conv) =>
          conv.id === localId
            ? {
                ...conv,
                messages: [...conv.messages, userMessage],
                lastMessage: trimmed,
                timestamp: now,
              }
            : conv,
        ),
      );
    }

    markProcessing(localId);
    locallyStreamingRef.current.add(localId);
    setIsLoading(true);

    const controller = new AbortController();
    streamControllersRef.current.set(localId, controller);

    const assistantMessageId = `m-${Date.now()}-assistant`;
    let assistantInserted = false;
    let assistantText = "";

    const appendAssistantChunk = (piece: string) => {
      assistantText += piece;
      setConversations((prev) =>
        prev.map((conv) => {
          if (conv.id !== activeId) return conv;
          if (!assistantInserted) {
            return {
              ...conv,
              messages: [
                ...conv.messages,
                {
                  id: assistantMessageId,
                  text: assistantText,
                  sender: "contact" as const,
                  timestamp: new Date(),
                },
              ],
              lastMessage: assistantText,
            };
          }
          return {
            ...conv,
            messages: conv.messages.map((m) =>
              m.id === assistantMessageId ? { ...m, text: assistantText } : m,
            ),
            lastMessage: assistantText,
          };
        }),
      );
      assistantInserted = true;
    };

    try {
      await streamChat(
        current?.id ?? null,
        trimmed,
        (event) => {
          if (event.type === "start") {
            if (isNewConversation) {
              const realId = event.conversation_id;
              setConversations((prev) =>
                prev.map((conv) => (conv.id === localId ? { ...conv, id: realId } : conv)),
              );
              setSelectedConversationId(realId);
              markProcessing(realId);
              unmarkProcessing(localId);
              locallyStreamingRef.current.delete(localId);
              locallyStreamingRef.current.add(realId);
              const existingController = streamControllersRef.current.get(localId);
              if (existingController) {
                streamControllersRef.current.delete(localId);
                streamControllersRef.current.set(realId, existingController);
              }
              activeId = realId;
            }
          } else if (event.type === "chunk") {
            appendAssistantChunk(event.text);
          } else if (event.type === "error") {
            throw new Error(event.message);
          }
          // "done" needs no handling here — the try block below falls
          // through once streamChat's promise resolves.
        },
        { signal: controller.signal },
      );

      setIsLoading(false);

      if (isNewConversation) {
        // Pick up the auto-generated title now that the backend has had a
        // chance to set one (see _maybe_generate_title on the backend).
        const refreshed = await fetchConversations();
        const finalSummary = refreshed.find((c) => c.conversation_id === activeId);
        if (finalSummary) {
          const finalConv = mapBackendConversationToConversation(finalSummary);
          setConversations((prev) => prev.map((conv) => (conv.id === activeId ? finalConv : conv)));
        }
      }
    } catch (e) {
      setIsLoading(false);
      const isAbort = e instanceof DOMException && e.name === "AbortError";
      if (isAbort) {
        // Stopped on purpose — the partial reply already on screen (from
        // chunks received before the abort) stays as-is, no error banner,
        // no "failed" mark on the user's message.
      } else {
        console.error(e);
        const friendly = getFriendlyErrorMessage(e);
        setError(friendly);
        setErrorRetry(() => () => handleSendMessage(trimmed));
        setConversations((prev) =>
          prev.map((c) =>
            c.id === activeId
              ? {
                  ...c,
                  messages: c.messages.map((m) =>
                    m.id === userMessage.id ? { ...m, failed: true } : m,
                  ),
                }
              : c,
          ),
        );
      }
    } finally {
      unmarkProcessing(localId);
      if (activeId !== localId) unmarkProcessing(activeId);
      streamControllersRef.current.delete(localId);
      streamControllersRef.current.delete(activeId);
      locallyStreamingRef.current.delete(localId);
      locallyStreamingRef.current.delete(activeId);
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
        c.id === conv.id ? { ...c, messages: c.messages.filter((m) => m.id !== messageId) } : c,
      ),
    );

    handleSendMessage(target.text);
  };

  if (auth.isCheckingSession) {
    return (
      <div className="flex h-screen items-center justify-center bg-white dark:bg-slate-950">
        <Loader2 className="w-6 h-6 animate-spin text-muted-foreground" aria-hidden />
      </div>
    );
  }

  // No early return for guests: the shell below renders for everyone,
  // and the login modal overlays it (see bottom of the JSX). This is what
  // lets a logged-out visitor see the app dimmed behind the dialog instead
  // of a blank page, the way ChatGPT's logged-out state works.

  return (
    <div className="flex h-screen bg-gradient-to-br from-white via-slate-50 to-white text-slate-900 dark:from-slate-950 dark:via-slate-900 dark:to-slate-950 dark:text-gray-100 relative overflow-hidden transition-colors duration-300">
      {/* Background Effects */}
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_top_right,_var(--tw-gradient-stops))] from-cyan-100/40 dark:from-cyan-900/20 via-transparent to-transparent pointer-events-none" />
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_bottom_left,_var(--tw-gradient-stops))] from-green-100/40 dark:from-green-900/20 via-transparent to-transparent pointer-events-none" />

      {/* Header */}
      <div className="fixed top-0 left-0 right-0 h-16 bg-white/70 dark:bg-black/40 backdrop-blur-xl border-b border-slate-200 dark:border-white/10 z-50 flex items-center px-3 sm:px-6 shadow-lg shadow-cyan-500/5">
        <button
          onClick={() => setIsSidebarOpen((v) => !v)}
          aria-label={isSidebarOpen ? "Close sidebar" : "Open sidebar"}
          className="mr-2 sm:mr-3 text-slate-500 hover:text-slate-900 dark:text-slate-400 dark:hover:text-slate-200 transition-colors p-2 hover:bg-black/5 dark:hover:bg-white/5 rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-hover shrink-0"
        >
          {isSidebarOpen ? (
            <PanelLeftClose className="w-5 h-5" aria-hidden />
          ) : (
            <PanelLeftOpen className="w-5 h-5" aria-hidden />
          )}
        </button>
        <div className="flex items-center gap-2 sm:gap-3 min-w-0">
          <div className="w-9 h-9 sm:w-10 sm:h-10 shrink-0 bg-gradient-to-br from-brand-cyan to-brand-green rounded-xl flex items-center justify-center shadow-lg shadow-brand-cyan/50">
            <ShieldCheck className="w-5 h-5 text-black" aria-hidden />
          </div>
          <h1 className="truncate tracking-wider bg-gradient-to-r from-brand-cyan to-brand-green bg-clip-text text-transparent text-sm sm:text-base">
            Security Assistant
          </h1>
        </div>

        <div className="ml-auto flex items-center gap-2 text-xs">
          {!auth.isAuthenticated && !auth.isCheckingSession && (
            <>
              <button
                onClick={() => setAuthModal({ open: true, mode: "login" })}
                className="h-8 px-3.5 rounded-full text-slate-700 dark:text-slate-200 text-sm hover:bg-black/5 dark:hover:bg-white/10 transition-colors"
              >
                Log in
              </button>
              <button
                onClick={() => setAuthModal({ open: true, mode: "signup" })}
                className="h-8 px-3.5 rounded-full bg-slate-900 dark:bg-white text-white dark:text-slate-900 text-sm hover:opacity-90 transition-opacity"
              >
                Sign up for free
              </button>
            </>
          )}
        </div>
      </div>

      {/* Main Content */}
      <div className="flex w-full pt-16 relative z-0">
        <ConversationList
          isOpen={isSidebarOpen}
          isMobile={isMobile}
          onClose={() => setIsSidebarOpen(false)}
          conversations={conversations}
          projects={projects}
          selectedConversationId={selectedConversationId ?? ""}
          onSelectConversation={handleSelectConversation}
          onNewConversation={handleNewConversation}
          processingConversationIds={processingConversationIds}
          isLoadingConversations={isLoading && conversations.length === 0}
          theme={theme}
          toggleTheme={toggleTheme}
          userEmail={auth.user?.email ?? null}
          onLogout={auth.logout}
          onDeleteConversation={handleDeleteConversation}
          onRenameConversation={handleRenameConversation}
          onPinConversation={handlePinConversation}
          onSetConversationProject={handleSetConversationProject}
          onCreateProject={handleCreateProject}
          onRenameProject={handleRenameProject}
          onDeleteProject={handleDeleteProject}
          onLoginClick={() => setAuthModal({ open: true, mode: "login" })}
        />

        <ChatArea
          conversation={selectedConversation || null}
          projects={projects}
          onSendMessage={handleSendMessage}
          onResendMessage={handleResendMessage}
          onDeleteConversation={handleDeleteConversation}
          onRenameConversation={handleRenameConversation}
          onPinConversation={handlePinConversation}
          onSetConversationProject={handleSetConversationProject}
          onCreateProject={handleCreateProject}
          onStopGenerating={handleStopGenerating}
          isLoading={
            !!selectedConversationId && processingConversationIds.has(selectedConversationId)
          }
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

      <LoginModal
        isOpen={authModal.open}
        initialMode={authModal.mode}
        onClose={() => setAuthModal((s) => ({ ...s, open: false }))}
        onLogin={auth.login}
        onSignup={auth.signup}
      />
    </div>
  );
}
