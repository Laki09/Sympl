"use client";

import { FormEvent, useMemo, useState } from "react";
import { sendChatMessage } from "@/lib/api";
import type { ChatMessage } from "@/lib/types";

const initialMessages: ChatMessage[] = [
  {
    id: "welcome",
    role: "assistant",
    content:
      "Hi, ich bin die Sympl-Oberflaeche. Stell eine Frage und ich sende sie an euer Backend, sobald die API steht.",
  },
];

export function ChatPanel() {
  const [messages, setMessages] = useState<ChatMessage[]>(initialMessages);
  const [input, setInput] = useState("");
  const [conversationId, setConversationId] = useState<string | undefined>();
  const [isSending, setIsSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const canSubmit = useMemo(() => input.trim().length > 0 && !isSending, [input, isSending]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const query = input.trim();

    if (!query) {
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
    setError(null);

    try {
      const response = await sendChatMessage(query, conversationId);
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
      setError(
        unknownError instanceof Error
          ? unknownError.message
          : "Die Anfrage konnte nicht verarbeitet werden.",
      );
    } finally {
      setIsSending(false);
    }
  }

  return (
    <section className="chat-panel" aria-label="Chat">
      <header className="chat-header">
        <div>
          <h2>Assistant</h2>
          <p>{"Frontend -> Backend -> Dify"}</p>
        </div>
        <span className="connection-pill">Backend API</span>
      </header>

      <div className="message-list" aria-live="polite">
        {messages.map((message) => (
          <article className={`message message-${message.role}`} key={message.id}>
            <p>{message.content}</p>
          </article>
        ))}
      </div>

      <form className="composer" onSubmit={handleSubmit}>
        <div className="input-row">
          <textarea
            aria-label="Nachricht"
            onChange={(event) => setInput(event.target.value)}
            placeholder="Was soll Sympl fuer dich klaeren?"
            value={input}
          />
          <button className="send-button" disabled={!canSubmit} type="submit">
            {isSending ? "Sendet..." : "Senden"}
          </button>
        </div>

        <div className="composer-meta">
          <span>{input.trim().length} Zeichen</span>
          {error ? <span className="error-text">{error}</span> : <span>Backend: /api/chat</span>}
        </div>
      </form>
    </section>
  );
}
