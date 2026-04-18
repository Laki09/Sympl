"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { createUserAccount, fetchUsers, sendChatMessage } from "@/lib/api";
import type { ChatMessage, ServiceCredentialPayload, UserAccountSummary } from "@/lib/types";

const initialMessages: ChatMessage[] = [
  {
    id: "welcome",
    role: "assistant",
    content:
      "Hi, ich bin Sympl. Frag mich nach Moodle-, Artemis- oder Lerninhalten, und ich lege direkt los.",
  },
];

type AuthMode = "login" | "register";

type RegisterFormState = {
  user: string;
  displayName: string;
  moodleUsername: string;
  moodlePassword: string;
  artemisUsername: string;
  artemisPassword: string;
};

export function ChatPanel() {
  const [authMode, setAuthMode] = useState<AuthMode>("login");
  const [accounts, setAccounts] = useState<UserAccountSummary[]>([]);
  const [selectedLoginUser, setSelectedLoginUser] = useState("");
  const [activeUser, setActiveUser] = useState<UserAccountSummary | null>(null);
  const [registerForm, setRegisterForm] = useState<RegisterFormState>({

    user: "",
    displayName: "",
    moodleUsername: "",
    moodlePassword: "",
    artemisUsername: "",
    artemisPassword: "",
  });
  const [messages, setMessages] = useState<ChatMessage[]>(initialMessages);
  const [input, setInput] = useState("");
  const [conversationId, setConversationId] = useState<string | undefined>();
  const [isLoadingAccounts, setIsLoadingAccounts] = useState(false);
  const [isCreatingAccount, setIsCreatingAccount] = useState(false);
  const [isSending, setIsSending] = useState(false);
  const [authError, setAuthError] = useState<string | null>(null);
  const [chatError, setChatError] = useState<string | null>(null);

  const canLogin = useMemo(() => selectedLoginUser.trim().length > 0, [selectedLoginUser]);
  const canRegister = useMemo(() => {
    return (
      registerForm.user.trim().length > 1 &&
      registerForm.displayName.trim().length > 1 &&
      !isCreatingAccount
    );
  }, [isCreatingAccount, registerForm.displayName, registerForm.user]);
  const canSubmit = useMemo(() => {
    return input.trim().length > 0 && activeUser !== null && !isSending;
  }, [activeUser, input, isSending]);

  useEffect(() => {
    async function loadAccounts() {
      setIsLoadingAccounts(true);
      setAuthError(null);

      try {
        const response = await fetchUsers();
        setAccounts(response.users);
        setSelectedLoginUser((current) => current || response.users[0]?.user || "");
      } catch (unknownError) {
        setAuthError(
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

  function handleLogin(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const account = accounts.find((entry) => entry.user === selectedLoginUser.trim());
    if (!account) {
      setAuthError("Bitte waehle einen vorhandenen Account aus.");
      return;
    }

    setActiveUser(account);
    setAuthError(null);
    setChatError(null);
  }

  async function handleRegister(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (!canRegister) {
      return;
    }

    setIsCreatingAccount(true);
    setAuthError(null);

    try {
      const services: ServiceCredentialPayload[] = [];

      if (registerForm.moodleUsername.trim() && registerForm.moodlePassword.trim()) {
        services.push({
          serviceKey: "moodle",
          label: "Moodle",
          username: registerForm.moodleUsername.trim(),
          password: registerForm.moodlePassword,
        });
      }

      if (registerForm.artemisUsername.trim() && registerForm.artemisPassword.trim()) {
        services.push({
          serviceKey: "artemis",
          label: "Artemis",
          username: registerForm.artemisUsername.trim(),
          password: registerForm.artemisPassword,
        });
      }

      await createUserAccount({
        user: registerForm.user.trim(),
        displayName: registerForm.displayName.trim(),
        services,
      });

      const nextAccount: UserAccountSummary = {
        user: registerForm.user.trim().toLowerCase(),
        displayName: registerForm.displayName.trim(),
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
      };

      setAccounts((current) =>
        [...current, nextAccount].sort((left, right) => left.displayName.localeCompare(right.displayName)),
      );
      setSelectedLoginUser(nextAccount.user);
      setActiveUser(nextAccount);
      setRegisterForm({
        user: "",
        displayName: "",
        moodleUsername: "",
        moodlePassword: "",
        artemisUsername: "",
        artemisPassword: "",
      });
    } catch (unknownError) {
      setAuthError(
        unknownError instanceof Error
          ? unknownError.message
          : "Der Account konnte nicht erstellt werden.",
      );
    } finally {
      setIsCreatingAccount(false);
    }
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
      <section className="auth-shell" aria-label="Anmeldung">
        <div className="auth-hero">
          <p className="auth-kicker">Sympl</p>
          <h1>Dein Lern-Chat mit Moodle und Artemis im Hintergrund.</h1>
          <p className="auth-copy">
            Melde dich mit einem bestehenden Account an oder registriere dich einmal mit den
            wichtigsten Hochschulzugangsdaten.
          </p>
        </div>

        <div className="auth-card">
          <div className="auth-tabs" role="tablist" aria-label="Authentifizierung">
            <button
              className={authMode === "login" ? "auth-tab auth-tab-active" : "auth-tab"}
              onClick={() => setAuthMode("login")}
              type="button"
            >
              Anmelden
            </button>
            <button
              className={authMode === "register" ? "auth-tab auth-tab-active" : "auth-tab"}
              onClick={() => setAuthMode("register")}
              type="button"
            >
              Registrieren
            </button>
          </div>

          {authMode === "login" ? (
            <form className="auth-form" onSubmit={handleLogin}>
              <label className="field">
                <span>Account</span>
                <select
                  onChange={(event) => setSelectedLoginUser(event.target.value)}
                  value={selectedLoginUser}
                >
                  <option value="">Account auswaehlen</option>
                  {accounts.map((account) => (
                    <option key={account.user} value={account.user}>
                      {account.displayName} ({account.user})
                    </option>
                  ))}
                </select>
              </label>

              <button className="primary-button" disabled={!canLogin || isLoadingAccounts} type="submit">
                {isLoadingAccounts ? "Laedt..." : "In den Chat"}
              </button>
            </form>
          ) : (
            <form className="auth-form" onSubmit={handleRegister}>
              <div className="auth-grid">
                <label className="field">
                  <span>User ID</span>
                  <input
                    onChange={(event) =>
                      setRegisterForm((current) => ({ ...current, user: event.target.value }))
                    }
                    placeholder="rufus"
                    value={registerForm.user}
                  />
                </label>

                <label className="field">
                  <span>Name</span>
                  <input
                    onChange={(event) =>
                      setRegisterForm((current) => ({ ...current, displayName: event.target.value }))
                    }
                    placeholder="Rufus"
                    value={registerForm.displayName}
                  />
                </label>

                <label className="field">
                  <span>Moodle Username</span>
                  <input
                    onChange={(event) =>
                      setRegisterForm((current) => ({
                        ...current,
                        moodleUsername: event.target.value,
                      }))
                    }
                    placeholder="s1234567"
                    value={registerForm.moodleUsername}
                  />
                </label>

                <label className="field">
                  <span>Moodle Passwort</span>
                  <input
                    onChange={(event) =>
                      setRegisterForm((current) => ({
                        ...current,
                        moodlePassword: event.target.value,
                      }))
                    }
                    placeholder="Passwort"
                    type="password"
                    value={registerForm.moodlePassword}
                  />
                </label>

                <label className="field">
                  <span>Artemis Username</span>
                  <input
                    onChange={(event) =>
                      setRegisterForm((current) => ({
                        ...current,
                        artemisUsername: event.target.value,
                      }))
                    }
                    placeholder="s1234567"
                    value={registerForm.artemisUsername}
                  />
                </label>

                <label className="field">
                  <span>Artemis Passwort</span>
                  <input
                    onChange={(event) =>
                      setRegisterForm((current) => ({
                        ...current,
                        artemisPassword: event.target.value,
                      }))
                    }
                    placeholder="Passwort"
                    type="password"
                    value={registerForm.artemisPassword}
                  />
                </label>
              </div>

              <button className="primary-button" disabled={!canRegister} type="submit">
                {isCreatingAccount ? "Erstellt..." : "Account erstellen"}
              </button>
            </form>
          )}

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
