import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import "./design/global.css";
import { EmbedMap, isEmbedPath } from "./embed/EmbedMap";

const root = document.getElementById("root");
if (root === null) {
  throw new Error("index.html has no #root element");
}

// Two routes do not need a router: the embed has its own path, everything else is the application.
createRoot(root).render(
  <StrictMode>{isEmbedPath(window.location.pathname) ? <EmbedMap /> : <App />}</StrictMode>,
);
