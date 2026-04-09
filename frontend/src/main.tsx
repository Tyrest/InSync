import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { getBaseUrl } from "./config/baseUrl";
import "./index.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter basename={getBaseUrl()}>
      <App />
    </BrowserRouter>
  </React.StrictMode>,
);
