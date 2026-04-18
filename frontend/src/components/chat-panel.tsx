"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { sendChatMessage } from "@/lib/api";
import type { ChatMessage } from "@/lib/types";

const initialMessages: ChatMessage[] = [
  {
    id: "welcome",
    role: "assistant",
    content:
      "Hi, I'm Sympl. Ask me about Moodle, Artemis, deadlines, or course material and I'll jump right in.",
  },
];

const thinkingStatuses = ["crawling", "searching", "thinking"];

type MockUser = {
  user: string;
  displayName: string;
};

export function ChatPanel() {
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  const [activeUser, setActiveUser] = useState<MockUser | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>(initialMessages);
  const [input, setInput] = useState("");
  const [conversationId, setConversationId] = useState<string | undefined>();
  const [isSending, setIsSending] = useState(false);
  const [thinkingStatusIndex, setThinkingStatusIndex] = useState(0);
  const [authError, setAuthError] = useState<string | null>(null);
  const [chatError, setChatError] = useState<string | null>(null);

  useEffect(() => {
    if (!isSending) {
      setThinkingStatusIndex(0);
      return;
    }

    const intervalId = window.setInterval(() => {
      setThinkingStatusIndex((current) => (current + 1) % thinkingStatuses.length);
    }, 1100);

    return () => window.clearInterval(intervalId);
  }, [isSending]);

  const canEnterChat = useMemo(() => {
    return displayName.trim().length > 1 && password.trim().length > 0;
  }, [displayName, password]);

  const canSubmit = useMemo(() => {
    return input.trim().length > 0 && activeUser !== null && !isSending;
  }, [activeUser, input, isSending]);

  function handleMockLogin(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const normalizedName = displayName.trim();
    const normalizedUser = normalizedName.toLowerCase().replace(/\s+/g, "-");

    if (!normalizedName || !password.trim()) {
      setAuthError("Enter your name and password to continue.");
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
      <section className="auth-shell" aria-label="Mock sign in">
        <div className="auth-hero">
          <p className="auth-kicker">Sympl</p>
          <h1>
            <span>Stop searching</span>
            <span>Start learning</span>
            <span>Sympl.</span>
          </h1>
          <p className="auth-copy">from students for students</p>
        </div>

        <div className="auth-card">
          <div className="auth-tabs" role="tablist" aria-label="Authentication">
            <button className="auth-tab auth-tab-active" type="button">
              Login
            </button>
            <button className="auth-tab" disabled type="button">
              Register
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
              <span>Password</span>
              <input
                onChange={(event) => setPassword(event.target.value)}
                placeholder="Password"
                type="password"
                value={password}
              />
            </label>

            <button className="primary-button" disabled={!canEnterChat} type="submit">
              Enter Chat
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
          Log out
        </button>
      </header>

      <div className="message-list" aria-live="polite">
        {messages.map((message) => (
          <article className={`message message-${message.role}`} key={message.id}>
            {message.role === "assistant" ? (
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={{
                  a: ({ children, href }) => (
                    <a href={href} rel="noreferrer" target="_blank">
                      {children}
                    </a>
                  ),
                }}
              >
                {message.content}
              </ReactMarkdown>
            ) : (
              <p>{message.content}</p>
            )}
          </article>
        ))}

        {isSending ? (
          <article className="message message-assistant message-thinking" aria-live="polite">
            <span className="thinking-dot" aria-hidden="true" />
            <span>{thinkingStatuses[thinkingStatusIndex]}</span>
          </article>
        ) : null}
      </div>

      <form className="composer composer-floating" onSubmit={handleSubmit}>
        <div className="input-row input-row-chatgpt">
          <textarea
            aria-label="Message"
            onChange={(event) => setInput(event.target.value)}
            placeholder="Ask about materials, deadlines, or course content..."
            value={input}
          />
          <button className="send-button" disabled={!canSubmit} type="submit">
            {isSending ? thinkingStatuses[thinkingStatusIndex] : "Send"}
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
