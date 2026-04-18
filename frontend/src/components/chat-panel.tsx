"use client";

import { FormEvent, useMemo, useState } from "react";
import { sendChatMessage } from "@/lib/api";
import type { ChatMessage } from "@/lib/types";

const initialMessages: ChatMessage[] = [
  {
    id: "welcome",
    role: "assistant",
    content:
      "Hi, ich bin Sympl. Frag mich nach Moodle-, Artemis- oder Lerninhalten, und ich lege direkt los.",
  },
];

type MockUser = {
  user: string;
  displayName: string;
};

export function ChatPanel() {
  const [displayName, setDisplayName] = useState("");
  const [userId, setUserId] = useState("");
  const [activeUser, setActiveUser] = useState<MockUser | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>(initialMessages);
  const [input, setInput] = useState("");
  const [conversationId, setConversationId] = useState<string | undefined>();
  const [isSending, setIsSending] = useState(false);
  const [authError, setAuthError] = useState<string | null>(null);
  const [chatError, setChatError] = useState<string | null>(null);

  const canEnterChat = useMemo(() => {
    return displayName.trim().length > 1 || userId.trim().length > 1;
  }, [displayName, userId]);

  const canSubmit = useMemo(() => {
    return input.trim().length > 0 && activeUser !== null && !isSending;
  }, [activeUser, input, isSending]);

  function handleMockLogin(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const normalizedName = displayName.trim();
    const normalizedUser = userId.trim().toLowerCase() || normalizedName.toLowerCase().replace(/\s+/g, "-");

    if (!normalizedName && !normalizedUser) {
      setAuthError("Gib bitte mindestens einen Namen oder eine User ID ein.");
      return;
    }

    setActiveUser({
      user: normalizedUser || "demo-user",
      displayName: normalizedName || normalizedUser || "Demo User",
    });
    setAuthError(null);
    setChatError(null);
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const query = input.trim();

    if (!query || !activeUser) {
      return;
    }

    const userMessage: ChatMessage = {
      id: crypto.randomUUID(),
      role: "user",
      content: query,
    };

    setMessages((current) => [...current, userMessage]);
    setInput("");
    setIsSending(true);
    setChatError(null);

    try {
      const response = await sendChatMessage(query, conversationId, activeUser.user);
      setConversationId(response.conversationId);
      setMessages((current) => [
        ...current,
        {
          id: crypto.randomUUID(),
          role: "assistant",
          content: response.answer,
        },
      ]);
    } catch (unknownError) {
      setChatError(
        unknownError instanceof Error
          ? unknownError.message
          : "Die Anfrage konnte nicht verarbeitet werden.",
      );
    } finally {
      setIsSending(false);
    }
  }

  function handleLogout() {
    setActiveUser(null);
    setConversationId(undefined);
    setMessages(initialMessages);
    setInput("");
    setChatError(null);
  }

  if (!activeUser) {
    return (
      <section className="auth-shell" aria-label="Mock Anmeldung">
        <div className="auth-hero">
          <p className="auth-kicker">Sympl</p>
          <h1>Direkt rein in den Chat.</h1>
          <p className="auth-copy">
            Die Anmeldung ist aktuell nur ein Mock. Gib kurz deinen Namen oder eine User ID ein,
            dann landest du direkt im Chat.
          </p>
        </div>

        <div className="auth-card">
          <div className="auth-tabs" role="tablist" aria-label="Authentifizierung">
            <button className="auth-tab auth-tab-active" type="button">
              Mock Login
            </button>
            <button className="auth-tab" disabled type="button">
              Spaeter echt
            </button>
          </div>

          <form className="auth-form" onSubmit={handleMockLogin}>
            <label className="field">
              <span>Name</span>
              <input
                onChange={(event) => setDisplayName(event.target.value)}
                placeholder="Rufus"
                value={displayName}
              />
            </label>

            <label className="field">
              <span>User ID</span>
              <input
                onChange={(event) => setUserId(event.target.value)}
                placeholder="rufus"
                value={userId}
              />
            </label>

            <button className="primary-button" disabled={!canEnterChat} type="submit">
              In den Chat
            </button>
          </form>

          {authError ? <p className="auth-error">{authError}</p> : null}
        </div>
      </section>
    );
  }

  return (
    <section className="chat-layout" aria-label="Chat">
      <header className="chat-topbar">
        <div>
          <p className="chat-topbar-label">Sympl</p>
          <h2>{activeUser.displayName}</h2>
        </div>

        <button className="ghost-button" onClick={handleLogout} type="button">
          Abmelden
        </button>
      </header>

      <div className="message-list" aria-live="polite">
        {messages.map((message) => (
          <article className={`message message-${message.role}`} key={message.id}>
            <p>{message.content}</p>
          </article>
        ))}
      </div>

      <form className="composer composer-floating" onSubmit={handleSubmit}>
        <div className="input-row input-row-chatgpt">
          <textarea
            aria-label="Nachricht"
            onChange={(event) => setInput(event.target.value)}
            placeholder="Frage nach Materialien, Fristen oder Inhalten ..."
            value={input}
          />
          <button className="send-button" disabled={!canSubmit} type="submit">
            {isSending ? "Sendet..." : "Senden"}
          </button>
        </div>

        <div className="composer-meta">
          <span>{activeUser.user}</span>
          {chatError ? <span className="error-text">{chatError}</span> : <span>Backend: /api/chat</span>}
        </div>
      </form>
    </section>
  );
}
