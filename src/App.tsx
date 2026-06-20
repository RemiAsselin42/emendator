import { useEffect, useState } from "react";
import { fetchHealth, type HealthResponse } from "./lib/api";

export default function App() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchHealth()
      .then(setHealth)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  return (
    <main className="container">
      <h1>Emendator</h1>
      <p className="tagline">Fabric modpack conflict analyzer</p>

      <section className="status">
        <h2>Backend</h2>
        {health ? (
          <p className="ok">
            {health.status} · profile {health.profile}
          </p>
        ) : error ? (
          <p className="err">unreachable: {error}</p>
        ) : (
          <p>connecting…</p>
        )}
      </section>
    </main>
  );
}
