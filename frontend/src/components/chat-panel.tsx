"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import {
  createUserAccount,
  deleteServiceCredential,
  fetchServiceCredentials,
  fetchUsers,
  saveServiceCredential,
  sendChatMessage,
} from "@/lib/api";
import type {
  ChatMessage,
  ServiceCredentialPayload,
  StoredServiceCredential,
  UserAccountSummary,
} from "@/lib/types";

const initialMessages: ChatMessage[] = [
  {
    id: "welcome",
    role: "assistant",
    content:
      "Hi, ich bin die Sympl-Oberflaeche. Lege einmal deinen Account an und ich nutze die gespeicherten Zugaenge fuer weitere Anfragen.",
  },
];

type AccountFormState = {
  user: string;
  displayName: string;
  moodleUsername: string;
  moodlePassword: string;
  artemisUsername: string;
  artemisPassword: string;
};

const emptyExtraServiceForm: ServiceCredentialPayload = {
  serviceKey: "",
  label: "",
  username: "",
  password: "",
  notes: "",
};

export function ChatPanel() {
  const [messages, setMessages] = useState<ChatMessage[]>(initialMessages);
  const [input, setInput] = useState("");
  const [conversationId, setConversationId] = useState<string | undefined>();
  const [accounts, setAccounts] = useState<UserAccountSummary[]>([]);
  const [selectedUser, setSelectedUser] = useState("demo-user");
  const [services, setServices] = useState<StoredServiceCredential[]>([]);
  const [accountForm, setAccountForm] = useState<AccountFormState>({
    user: "",
    displayName: "",
    moodleUsername: "",
    moodlePassword: "",
    artemisUsername: "",
    artemisPassword: "",
  });
  const [extraServiceForm, setExtraServiceForm] =
    useState<ServiceCredentialPayload>(emptyExtraServiceForm);
  const [isSending, setIsSending] = useState(false);
  const [isLoadingAccounts, setIsLoadingAccounts] = useState(false);
  const [isLoadingServices, setIsLoadingServices] = useState(false);
  const [isCreatingAccount, setIsCreatingAccount] = useState(false);
  const [isSavingService, setIsSavingService] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [accountError, setAccountError] = useState<string | null>(null);
  const [serviceError, setServiceError] = useState<string | null>(null);

  const canSubmit = useMemo(() => {
    return input.trim().length > 0 && selectedUser.trim().length > 0 && !isSending;
  }, [input, isSending, selectedUser]);

  const canCreateAccount = useMemo(() => {
    return (
      accountForm.user.trim().length > 1 &&
      accountForm.displayName.trim().length > 1 &&
      !isCreatingAccount
    );
  }, [accountForm.displayName, accountForm.user, isCreatingAccount]);

  const canSaveExtraService = useMemo(() => {
    return (
      selectedUser.trim().length > 0 &&
      extraServiceForm.serviceKey.trim().length > 1 &&
      extraServiceForm.label.trim().length > 1 &&
      extraServiceForm.username.trim().length > 0 &&
      extraServiceForm.password.trim().length > 0 &&
      !isSavingService
    );
  }, [extraServiceForm, isSavingService, selectedUser]);

  useEffect(() => {
    async function loadAccounts() {
      setIsLoadingAccounts(true);
      setAccountError(null);

      try {
        const response = await fetchUsers();
        setAccounts(response.users);
        setSelectedUser((current) => current || response.users[0]?.user || "demo-user");
      } catch (unknownError) {
        setAccountError(
          unknownError instanceof Error
            ? unknownError.message
            : "Die Accounts konnten nicht geladen werden.",
        );
      } finally {
        setIsLoadingAccounts(false);
      }
    }

    void loadAccounts();
  }, []);

  useEffect(() => {
    const normalizedUser = selectedUser.trim();

    if (!normalizedUser) {
      setServices([]);
      return;
    }

    async function loadServices() {
      setIsLoadingServices(true);
      setServiceError(null);

      try {
        const response = await fetchServiceCredentials(normalizedUser);
        setServices(response.services);
      } catch (unknownError) {
        setServiceError(
          unknownError instanceof Error
            ? unknownError.message
            : "Die gespeicherten Services konnten nicht geladen werden.",
        );
      } finally {
        setIsLoadingServices(false);
      }
    }

    void loadServices();
  }, [selectedUser]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const query = input.trim();

    if (!query || !selectedUser.trim()) {
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
      const response = await sendChatMessage(query, conversationId, selectedUser.trim());
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

  async function handleCreateAccount(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (!canCreateAccount) {
      return;
    }

    setIsCreatingAccount(true);
    setAccountError(null);

    try {
      const services: ServiceCredentialPayload[] = [];

      if (accountForm.moodleUsername.trim() && accountForm.moodlePassword.trim()) {
        services.push({
          serviceKey: "moodle",
          label: "Moodle",
          username: accountForm.moodleUsername.trim(),
          password: accountForm.moodlePassword,
        });
      }

      if (accountForm.artemisUsername.trim() && accountForm.artemisPassword.trim()) {
        services.push({
          serviceKey: "artemis",
          label: "Artemis",
          username: accountForm.artemisUsername.trim(),
          password: accountForm.artemisPassword,
        });
      }

      await createUserAccount({
        user: accountForm.user.trim(),
        displayName: accountForm.displayName.trim(),
        services,
      });

      const nextAccount: UserAccountSummary = {
        user: accountForm.user.trim().toLowerCase(),
        displayName: accountForm.displayName.trim(),
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
      };

      setAccounts((current) => [...current, nextAccount].sort((left, right) => left.displayName.localeCompare(right.displayName)));
      setSelectedUser(nextAccount.user);
      setAccountForm({
        user: "",
        displayName: "",
        moodleUsername: "",
        moodlePassword: "",
        artemisUsername: "",
        artemisPassword: "",
      });
    } catch (unknownError) {
      setAccountError(
        unknownError instanceof Error
          ? unknownError.message
          : "Der Account konnte nicht erstellt werden.",
      );
    } finally {
      setIsCreatingAccount(false);
    }
  }

  async function handleExtraServiceSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (!canSaveExtraService) {
      return;
    }

    setIsSavingService(true);
    setServiceError(null);

    try {
      const savedService = await saveServiceCredential(selectedUser.trim(), {
        serviceKey: extraServiceForm.serviceKey.trim(),
        label: extraServiceForm.label.trim(),
        username: extraServiceForm.username.trim(),
        password: extraServiceForm.password,
        notes: extraServiceForm.notes?.trim() || undefined,
      });

      setServices((current) => {
        const next = current.filter((service) => service.serviceKey !== savedService.serviceKey);
        return [...next, savedService].sort((left, right) => left.label.localeCompare(right.label));
      });
      setExtraServiceForm(emptyExtraServiceForm);
    } catch (unknownError) {
      setServiceError(
        unknownError instanceof Error
          ? unknownError.message
          : "Der zusaetzliche Service konnte nicht gespeichert werden.",
      );
    } finally {
      setIsSavingService(false);
    }
  }

  async function handleDeleteService(serviceKey: string) {
    if (!selectedUser.trim()) {
      return;
    }

    setServiceError(null);

    try {
      await deleteServiceCredential(selectedUser.trim(), serviceKey);
      setServices((current) => current.filter((service) => service.serviceKey !== serviceKey));
    } catch (unknownError) {
      setServiceError(
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

      <section className="credential-panel" aria-label="Account und Zugaenge">
        <div className="credential-panel-header">
          <div>
            <h3>Account und Zugaenge</h3>
            <p>
              Moodle und Artemis werden direkt bei der Account-Erstellung gespeichert. Weitere
              Services kannst du spaeter ergaenzen, ohne die Login-Links manuell einzutragen.
            </p>
          </div>
        </div>

        <form className="credential-form" onSubmit={handleCreateAccount}>
          <div className="credential-grid">
            <label className="field">
              <span>User ID</span>
              <input
                onChange={(event) =>
                  setAccountForm((current) => ({ ...current, user: event.target.value }))
                }
                placeholder="rufus"
                value={accountForm.user}
              />
            </label>

            <label className="field">
              <span>Anzeigename</span>
              <input
                onChange={(event) =>
                  setAccountForm((current) => ({ ...current, displayName: event.target.value }))
                }
                placeholder="Rufus"
                value={accountForm.displayName}
              />
            </label>

            <label className="field">
              <span>Moodle Username</span>
              <input
                onChange={(event) =>
                  setAccountForm((current) => ({ ...current, moodleUsername: event.target.value }))
                }
                placeholder="s1234567"
                value={accountForm.moodleUsername}
              />
            </label>

            <label className="field">
              <span>Moodle Passwort</span>
              <input
                onChange={(event) =>
                  setAccountForm((current) => ({ ...current, moodlePassword: event.target.value }))
                }
                placeholder="Passwort"
                type="password"
                value={accountForm.moodlePassword}
              />
            </label>

            <label className="field">
              <span>Artemis Username</span>
              <input
                onChange={(event) =>
                  setAccountForm((current) => ({ ...current, artemisUsername: event.target.value }))
                }
                placeholder="s1234567"
                value={accountForm.artemisUsername}
              />
            </label>

            <label className="field">
              <span>Artemis Passwort</span>
              <input
                onChange={(event) =>
                  setAccountForm((current) => ({ ...current, artemisPassword: event.target.value }))
                }
                placeholder="Passwort"
                type="password"
                value={accountForm.artemisPassword}
              />
            </label>
          </div>

          <div className="credential-actions">
            <button className="secondary-button" disabled={!canCreateAccount} type="submit">
              {isCreatingAccount ? "Erstellt..." : "Account erstellen"}
            </button>
            <span>
              {isLoadingAccounts
                ? "Accounts werden geladen..."
                : `${accounts.length} Accounts vorhanden`}
            </span>
          </div>
        </form>

        <div className="account-toolbar">
          <label className="field">
            <span>Aktiver Account</span>
            <select
              onChange={(event) => setSelectedUser(event.target.value)}
              value={selectedUser}
            >
              <option value="demo-user">Demo User</option>
              {accounts.map((account) => (
                <option key={account.user} value={account.user}>
                  {account.displayName} ({account.user})
                </option>
              ))}
            </select>
          </label>
        </div>

        <form className="credential-form" onSubmit={handleExtraServiceSubmit}>
          <div className="credential-grid">
            <label className="field">
              <span>Weiterer Service Key</span>
              <input
                onChange={(event) =>
                  setExtraServiceForm((current) => ({ ...current, serviceKey: event.target.value }))
                }
                placeholder="bibliothek"
                value={extraServiceForm.serviceKey}
              />
            </label>

            <label className="field">
              <span>Name</span>
              <input
                onChange={(event) =>
                  setExtraServiceForm((current) => ({ ...current, label: event.target.value }))
                }
                placeholder="Bibliothek"
                value={extraServiceForm.label}
              />
            </label>

            <label className="field">
              <span>Username</span>
              <input
                onChange={(event) =>
                  setExtraServiceForm((current) => ({ ...current, username: event.target.value }))
                }
                placeholder="login"
                value={extraServiceForm.username}
              />
            </label>

            <label className="field">
              <span>Passwort</span>
              <input
                onChange={(event) =>
                  setExtraServiceForm((current) => ({ ...current, password: event.target.value }))
                }
                placeholder="Passwort"
                type="password"
                value={extraServiceForm.password}
              />
            </label>
          </div>

          <label className="field">
            <span>Notiz</span>
            <input
              onChange={(event) =>
                setExtraServiceForm((current) => ({ ...current, notes: event.target.value }))
              }
              placeholder="Optional, z. B. 2FA-Hinweis"
              value={extraServiceForm.notes}
            />
          </label>

          <div className="credential-actions">
            <button className="secondary-button" disabled={!canSaveExtraService} type="submit">
              {isSavingService ? "Speichert..." : "Weiteren Service speichern"}
            </button>
            <span>
              {isLoadingServices
                ? "Services werden geladen..."
                : `${services.length} Services fuer ${selectedUser || "keinen Account"} gespeichert`}
            </span>
          </div>
        </form>

        <div className="service-list" aria-live="polite">
          {services.map((service) => (
            <article className="service-card" key={service.serviceKey}>
              <div>
                <strong>{service.label}</strong>
                <p>Service Key: {service.serviceKey}</p>
                <p>Login: {service.username}</p>
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
              Fuer diesen Account sind noch keine Services gespeichert.
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
          {error || accountError || serviceError ? (
            <span className="error-text">{error ?? accountError ?? serviceError}</span>
          ) : (
            <span>Backend: /api/chat</span>
          )}
        </div>
      </form>
    </section>
  );
}
