import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

// /dashboard is the app; every other path is the marketing site. Each side is
// loaded on its own so their global stylesheets never meet on one page.
const root = createRoot(document.getElementById("root")!);
if (/^\/dashboard(\/|$)/.test(location.pathname)) {
  Promise.all([import("./App"), import("./style.css")]).then(([{ default: App }]) => root.render(<App />));
} else {
  Promise.all([import("./landing/App"), import("react-router-dom"), import("./landing/index.css")]).then(([{ default: Landing }, { BrowserRouter }]) =>
    root.render(<StrictMode><BrowserRouter><Landing /></BrowserRouter></StrictMode>));
}
