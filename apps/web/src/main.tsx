import { QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";

import { App } from "./App";
import { AuthProvider } from "./lib/auth";
import { CareContextProvider } from "./lib/careContext";
import { I18nProvider } from "./lib/i18n";
import { queryClient } from "./lib/queryClient";
import { ThemeProvider } from "./lib/theme";
import "./styles/app.css";

const container = document.getElementById("root");
if (!container) throw new Error("Missing #root element");

createRoot(container).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <I18nProvider>
        <ThemeProvider>
          <AuthProvider>
            <CareContextProvider>
              <BrowserRouter>
                <App />
              </BrowserRouter>
            </CareContextProvider>
          </AuthProvider>
        </ThemeProvider>
      </I18nProvider>
    </QueryClientProvider>
  </StrictMode>,
);
