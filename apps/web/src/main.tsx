import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";

import { App } from "./App";
import { isApiError } from "./lib/api";
import { AuthProvider } from "./lib/auth";
import { CareContextProvider } from "./lib/careContext";
import { I18nProvider } from "./lib/i18n";
import { ThemeProvider } from "./lib/theme";
import "./styles/app.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 20_000,
      refetchOnWindowFocus: false,
      retry: (failureCount, error) => {
        if (isApiError(error) && error.status < 500) return false;
        return failureCount < 1;
      },
    },
  },
});

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
