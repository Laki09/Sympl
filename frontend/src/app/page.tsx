import { ChatPanel } from "@/components/chat-panel";

const workflowItems = [
  "Frage erfassen",
  "Backend prueft Auth",
  "Dify Workflow starten",
  "Antwort anzeigen",
];

export default function Home() {
  return (
    <main className="app-shell">
      <section className="workspace">
        <div className="context-panel" aria-label="Projektstatus">
          <div>
            <p className="eyebrow">Sympl MVP</p>
            <h1>AI Workflow Frontend</h1>
            <p className="lead">
              Eine schlanke Oberflaeche fuer Nutzeranfragen, die spaeter ueber
              euer Backend an Dify und Cloud-Services weitergereicht werden.
            </p>
          </div>

          <div className="status-list" aria-label="Workflow">
            {workflowItems.map((item, index) => (
              <div className="status-item" key={item}>
                <span>{index + 1}</span>
                <p>{item}</p>
              </div>
            ))}
          </div>
        </div>

        <ChatPanel />
      </section>
    </main>
  );
}
