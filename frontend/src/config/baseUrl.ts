const runtimeBase = (window as { __BASE_URL__?: string }).__BASE_URL__;
const fallbackBase = import.meta.env.BASE_URL;

function normalizeBase(value: string | undefined): string {
  const trimmed = (value ?? "").trim();
  if (!trimmed || trimmed === "/") {
    return "/";
  }
  const withLeadingSlash = trimmed.startsWith("/") ? trimmed : `/${trimmed}`;
  return withLeadingSlash.endsWith("/") ? withLeadingSlash.slice(0, -1) : withLeadingSlash;
}

export function getBaseUrl(): string {
  return normalizeBase(runtimeBase ?? fallbackBase);
}
