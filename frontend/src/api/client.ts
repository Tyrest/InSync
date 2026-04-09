import { getBaseUrl } from "../config/baseUrl";

const base = getBaseUrl();

/** Full URL for the login route (respects Vite ``BASE_URL`` / subpath deploys). */
export function getLoginUrl(): string {
  const prefix = base === "/" ? "" : base;
  const path = `${prefix}/login`;
  return `${window.location.origin}${path}`;
}

/** Clear session and go to login (full navigation so Zustand rehydrates from storage). */
export function redirectToLogin(): void {
  localStorage.removeItem("token");
  window.location.assign(getLoginUrl());
}

/** Parse FastAPI-style JSON errors into a single line for UI. */
export function formatApiError(err: unknown): string {
  if (!(err instanceof Error)) {
    return String(err);
  }
  const text = err.message.trim();
  if (!text.startsWith("{")) {
    return text;
  }
  try {
    const body = JSON.parse(text) as { detail?: unknown };
    const { detail } = body;
    if (typeof detail === "string") {
      return detail;
    }
    if (Array.isArray(detail)) {
      return detail
        .map((item) => {
          if (item && typeof item === "object" && "msg" in item) {
            return String((item as { msg: string }).msg);
          }
          return JSON.stringify(item);
        })
        .join("; ");
    }
  } catch {
    /* not JSON */
  }
  return text;
}

export async function apiFetch<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = localStorage.getItem("token");
  const headers = new Headers(options.headers);
  headers.set("Content-Type", "application/json");
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  const response = await fetch(`${base.replace(/\/$/, "")}/api${path}`, {
    ...options,
    headers,
  });
  if (!response.ok) {
    if (response.status === 401 && path !== "/auth/login") {
      redirectToLogin();
    }
    throw new Error(await response.text());
  }
  return (await response.json()) as T;
}
