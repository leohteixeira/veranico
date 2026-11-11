import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import "./design/global.css";
import { EmbedMap, isEmbedPath } from "./embed/EmbedMap";

const root = document.getElementById("root");
if (root === null) {
  throw new Error("index.html has no #root element");
}

// Development only: with `VITE_API_MOCK=1` the client answers from the mock layer. The condition
// is constant in a production build, so the mock layer and its fixtures are not bundled.
if (import.meta.env.DEV && import.meta.env.VITE_API_MOCK === "1") {
  const { installMockApi } = await import("./mocks/fetch");
  installMockApi(window.location.search);
}

// Two routes do not need a router: the embed has its own path, everything else is the application.
createRoot(root).render(
  <StrictMode>{isEmbedPath(window.location.pathname) ? <EmbedMap /> : <App />}</StrictMode>,
);
