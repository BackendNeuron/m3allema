// Talking to the local M3allema server: the access token, REST calls, and the
// WebSocket URL.

const TOKEN_KEY = "m3allema-token";

/** Read the token from the URL once, keep it for this tab, and hide it from the address bar. */
function readToken(): string {
  const params = new URLSearchParams(window.location.search);
  const fromUrl = params.get("token");
  if (fromUrl) {
    sessionStorage.setItem(TOKEN_KEY, fromUrl);
    window.history.replaceState(null, "", window.location.pathname);
    return fromUrl;
  }
  return sessionStorage.getItem(TOKEN_KEY) ?? "";
}

export const token = readToken();

export async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(path, { headers: { "X-M3allema-Token": token } });
  if (!response.ok) throw new Error(`${path} failed (${response.status})`);
  return (await response.json()) as T;
}

export function socketUrl(): string {
  const scheme = window.location.protocol === "https:" ? "wss" : "ws";
  return `${scheme}://${window.location.host}/api/ws?token=${encodeURIComponent(token)}`;
}

export const money = (value: number | null | undefined): string =>
  value == null ? "unknown" : `$${value.toFixed(4)}`;

export async function postJson<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(path, {
    method: "POST",
    headers: { "X-M3allema-Token": token, "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`${path} failed (${response.status}): ${detail.slice(0, 300)}`);
  }
  return (await response.json()) as T;
}
