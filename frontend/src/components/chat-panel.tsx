"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import {
  deleteServiceCredential,
  fetchServiceCredentials,
  saveServiceCredential,
  sendChatMessage,
} from "@/lib/api";
import type { ChatMessage, ServiceCredentialPayload, StoredServiceCredential } from "@/lib/types";

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
  const [userId, setUserId] = useState("demo-user");
  const [isSending, setIsSending] = useState(false);
  const [isSavingCredential, setIsSavingCredential] = useState(false);
  const [isLoadingServices, setIsLoadingServices] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [credentialError, setCredentialError] = useState<string | null>(null);
  const [services, setServices] = useState<StoredServiceCredential[]>([]);
  const [serviceForm, setServiceForm] = useState<ServiceCredentialPayload>({
    serviceKey: "moodle",
    label: "Moodle",
    baseUrl: "",
    loginUrl: "",
    username: "",
    password: "",
    notes: "",
  });

  const canSubmit = useMemo(() => input.trim().length > 0 && !isSending, [input, isSending]);
  const canSaveCredential = useMemo(() => {
    return (
      userId.trim().length > 0 &&
      serviceForm.serviceKey.trim().length > 1 &&
      serviceForm.label.trim().length > 1 &&
      serviceForm.baseUrl.trim().length > 2 &&
      serviceForm.username.trim().length > 0 &&
      serviceForm.password.trim().length > 0 &&
      !isSavingCredential
    );
  }, [isSavingCredential, serviceForm, userId]);

  useEffect(() => {
    const normalizedUser = userId.trim();

    if (!normalizedUser) {
      setServices([]);
      return;
    }

    async function loadServices() {
      setIsLoadingServices(true);
      setCredentialError(null);

      try {
        const response = await fetchServiceCredentials(normalizedUser);
        setServices(response.services);
      } catch (unknownError) {
        setCredentialError(
          unknownError instanceof Error
            ? unknownError.message
            : "Die gespeicherten Services konnten nicht geladen werden.",
        );
      } finally {
        setIsLoadingServices(false);
      }
    }

    void loadServices();
  }, [userId]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const query = input.trim();
    const normalizedUser = userId.trim();

    if (!query || !normalizedUser) {
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
      const response = await sendChatMessage(query, conversationId, normalizedUser);
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

  async function handleCredentialSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalizedUser = userId.trim();

    if (!normalizedUser || !canSaveCredential) {
      return;
    }

    setIsSavingCredential(true);
    setCredentialError(null);

    try {
      const savedService = await saveServiceCredential(normalizedUser, {
        serviceKey: serviceForm.serviceKey.trim(),
        label: serviceForm.label.trim(),
        baseUrl: serviceForm.baseUrl.trim(),
        loginUrl: serviceForm.loginUrl?.trim() || undefined,
        username: serviceForm.username.trim(),
        password: serviceForm.password,
        notes: serviceForm.notes?.trim() || undefined,
      });

      setServices((current) => {
        const next = current.filter((service) => service.serviceKey !== savedService.serviceKey);
        return [...next, savedService].sort((left, right) => left.label.localeCompare(right.label));
      });
      setServiceForm((current) => ({
        ...current,
        password: "",
        notes: "",
      }));
    } catch (unknownError) {
      setCredentialError(
        unknownError instanceof Error
          ? unknownError.message
          : "Die Zugangsdaten konnten nicht gespeichert werden.",
      );
    } finally {
      setIsSavingCredential(false);
    }
  }

  async function handleDeleteService(serviceKey: string) {
    const normalizedUser = userId.trim();

    if (!normalizedUser) {
      return;
    }

    setCredentialError(null);

    try {
      await deleteServiceCredential(normalizedUser, serviceKey);
      setServices((current) => current.filter((service) => service.serviceKey !== serviceKey));
    } catch (unknownError) {
      setCredentialError(
        unknownError instanceof Error
          ? unknownError.message
          : "Der Service konnte nicht entfernt werden.",
      );
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

      <section className="credential-panel" aria-label="Service-Zugaenge">
        <div className="credential-panel-header">
          <div>
            <h3>Zugaenge pro User</h3>
            <p>Moodle und weitere Portale werden pro Nutzer gespeichert und bei jedem Prompt mitgesendet.</p>
          </div>
        </div>

        <form className="credential-form" onSubmit={handleCredentialSubmit}>
          <label className="field">
            <span>User ID</span>
            <input
              onChange={(event) => setUserId(event.target.value)}
              placeholder="demo-user"
              value={userId}
            />
          </label>

          <div className="credential-grid">
            <label className="field">
              <span>Service Key</span>
              <input
                onChange={(event) =>
                  setServiceForm((current) => ({ ...current, serviceKey: event.target.value }))
                }
                placeholder="moodle"
                value={serviceForm.serviceKey}
              />
            </label>

            <label className="field">
              <span>Name</span>
              <input
                onChange={(event) =>
                  setServiceForm((current) => ({ ...current, label: event.target.value }))
                }
                placeholder="Moodle"
                value={serviceForm.label}
              />
            </label>

            <label className="field">
              <span>Basis-URL</span>
              <input
                onChange={(event) =>
                  setServiceForm((current) => ({ ...current, baseUrl: event.target.value }))
                }
                placeholder="https://moodle.example.edu"
                value={serviceForm.baseUrl}
              />
            </label>

            <label className="field">
              <span>Login-URL</span>
              <input
                onChange={(event) =>
                  setServiceForm((current) => ({ ...current, loginUrl: event.target.value }))
                }
                placeholder="https://moodle.example.edu/login"
                value={serviceForm.loginUrl}
              />
            </label>

            <label className="field">
              <span>Username</span>
              <input
                onChange={(event) =>
                  setServiceForm((current) => ({ ...current, username: event.target.value }))
                }
                placeholder="s1234567"
                value={serviceForm.username}
              />
            </label>

            <label className="field">
              <span>Passwort</span>
              <input
                onChange={(event) =>
                  setServiceForm((current) => ({ ...current, password: event.target.value }))
                }
                placeholder="Passwort"
                type="password"
                value={serviceForm.password}
              />
            </label>
          </div>

          <label className="field">
            <span>Notiz</span>
            <input
              onChange={(event) =>
                setServiceForm((current) => ({ ...current, notes: event.target.value }))
              }
              placeholder="Optional, z. B. Kursraum oder 2FA-Hinweis"
              value={serviceForm.notes}
            />
          </label>

          <div className="credential-actions">
            <button className="secondary-button" disabled={!canSaveCredential} type="submit">
              {isSavingCredential ? "Speichert..." : "Zugang speichern"}
            </button>
            <span>
              {isLoadingServices
                ? "Gespeicherte Services werden geladen..."
                : `${services.length} Services fuer ${userId.trim() || "keinen User"} gespeichert`}
            </span>
          </div>
        </form>

        <div className="service-list" aria-live="polite">
          {services.map((service) => (
            <article className="service-card" key={service.serviceKey}>
              <div>
                <strong>{service.label}</strong>
                <p>{service.baseUrl}</p>
                <p>
                  Login: {service.username}
                  {service.loginUrl ? ` | ${service.loginUrl}` : ""}
                </p>
              </div>
              <button
                className="ghost-button"
                onClick={() => void handleDeleteService(service.serviceKey)}
                type="button"
              >
                Entfernen
              </button>
            </article>
          ))}

          {services.length === 0 && !isLoadingServices ? (
            <p className="empty-state">
              Noch keine Services gespeichert. Du kannst hier Moodle und spaeter weitere Portale
              wie Artemis oder Bibliotheksseiten hinterlegen.
            </p>
          ) : null}
        </div>
      </section>

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
          {error || credentialError ? (
            <span className="error-text">{error ?? credentialError}</span>
          ) : (
            <span>Backend: /api/chat</span>
          )}
        </div>
      </form>
    </section>
  );
}
