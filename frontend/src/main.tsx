import React from "react";
import ReactDOM from "react-dom/client";
import { PersistQueryClientProvider } from "@tanstack/react-query-persist-client";
import { App } from "./App";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { makeQueryClient } from "./lib/queryClient";
import { persistOptions } from "./lib/queryPersist";
import "./styles/tokens.css";
import "./styles/base.css";
import "./styles/header3.css";
import "./styles/anim.css";

const queryClient = makeQueryClient();

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    {/* Backstop: pega erros no próprio shell/roteador; o Layout tem outro
        boundary por rota que preserva o shell quando só a página falha. */}
    <ErrorBoundary>
      {/* Hidrata o cache do IndexedDB antes do 1º render: a página abre com o
          último dado conhecido em vez de skeleton, e revalida em seguida. */}
      <PersistQueryClientProvider client={queryClient} persistOptions={persistOptions}>
        <App />
      </PersistQueryClientProvider>
    </ErrorBoundary>
  </React.StrictMode>,
);
