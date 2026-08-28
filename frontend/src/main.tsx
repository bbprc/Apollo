import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import App from "./App";
import "./index.css";

const client = new QueryClient({
  defaultOptions: {
    queries: {
      // Nothing here goes stale on its own: a pick landing is what invalidates
      // the board, and the poll loop decides when that happened.
      refetchOnWindowFocus: false,
      staleTime: Infinity,
      retry: 1,
    },
  },
});

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>
  </React.StrictMode>,
);
