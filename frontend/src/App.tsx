import { useEffect, useState } from "react";

import { api } from "./api/client";

// Placeholder of the foundation milestone. The interface is built by plan 08.
export function App() {
  const [status, setStatus] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    void api.GET("/api/v1/regions").then(({ response }) => {
      if (!cancelled) {
        setStatus(response.status);
      }
    });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <main>
      <h1>Veranico</h1>
      <p>{status === null ? "Contacting the API…" : `GET /api/v1/regions answered ${status}.`}</p>
    </main>
  );
}
