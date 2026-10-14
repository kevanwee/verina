/**
 * Connected-mode configuration.
 *
 * The public preview (/, /workbench, /workbench/intake) never reads this module's result as
 * "on": unless VERINA_CONNECTED is exactly "1" and every required variable is present and
 * valid, connected mode is off and every connected route answers 404.
 *
 * Variables are read from the object passed in, never through `process.env.NAME` member
 * expressions, so the bundler cannot inline a build-time value: a build without these
 * variables must still honour them when they are set at runtime.
 */

export type Env = Readonly<Record<string, string | undefined>>;

export type ConnectedConfig = {
  /** Fixed application origin; never derived from request forwarding headers. */
  readonly publicOrigin: string;
  /** Supabase project URL (public). No trailing slash. */
  readonly supabaseUrl: string;
  /** Supabase anon or publishable key (public by design, still only used server-side). */
  readonly supabaseAnonKey: string;
  /** Verina API origin plus optional base path, server-only. No trailing slash. */
  readonly apiBaseUrl: string;
  /** Mark auth cookies Secure. On unless running the development server. */
  readonly secureCookies: boolean;
};

export const ENV_KEYS = {
  publicOrigin: "VERINA_PUBLIC_ORIGIN",
  connected: "VERINA_CONNECTED",
  supabaseUrl: "NEXT_PUBLIC_SUPABASE_URL",
  supabaseAnonKey: "NEXT_PUBLIC_SUPABASE_ANON_KEY",
  apiBaseUrl: "VERINA_API_BASE_URL",
} as const;

const LOOPBACK_HOSTS = new Set(["localhost", "127.0.0.1", "[::1]"]);

/** https anywhere; plain http only for a loopback host (local API or local Supabase). */
function parseServiceUrl(raw: string | undefined): string | null {
  if (typeof raw !== "string") return null;
  const value = raw.trim();
  if (value.length === 0 || value.length > 2048) return null;
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    return null;
  }
  const secure = url.protocol === "https:";
  const loopbackHttp = url.protocol === "http:" && LOOPBACK_HOSTS.has(url.hostname);
  if (!secure && !loopbackHttp) return null;
  if (url.username || url.password || url.search || url.hash) return null;
  return `${url.origin}${url.pathname}`.replace(/\/+$/, "");
}

function parseKey(raw: string | undefined): string | null {
  if (typeof raw !== "string") return null;
  const value = raw.trim();
  // JWT-style anon keys and sb_publishable_ keys are printable ASCII without spaces.
  if (value.length < 20 || value.length > 4096 || !/^[\x21-\x7e]+$/.test(value)) return null;
  return value;
}

/**
 * Returns the connected configuration, or null when connected mode is off or incomplete.
 * Fails closed: a typo in any variable turns connected mode off rather than half on.
 */
export function readConnectedConfig(env: Env): ConnectedConfig | null {
  if (env[ENV_KEYS.connected] !== "1") return null;
  const supabaseUrl = parseServiceUrl(env[ENV_KEYS.supabaseUrl]);
  const supabaseAnonKey = parseKey(env[ENV_KEYS.supabaseAnonKey]);
  const apiBaseUrl = parseServiceUrl(env[ENV_KEYS.apiBaseUrl]);
  const parsedOrigin = parseServiceUrl(env[ENV_KEYS.publicOrigin]);
  const publicOrigin = parsedOrigin && new URL(parsedOrigin).pathname === "/" ? parsedOrigin : null;
  if (!supabaseUrl || !supabaseAnonKey || !apiBaseUrl || !publicOrigin) {
    warnIncomplete({ supabaseUrl, supabaseAnonKey, apiBaseUrl, publicOrigin });
    return null;
  }
  return {
    publicOrigin,
    supabaseUrl,
    supabaseAnonKey,
    apiBaseUrl,
    secureCookies: env.NODE_ENV !== "development",
  };
}

let warned = false;

/** Names only, never values. Logged once per process. */
function warnIncomplete(parts: Record<string, string | null>) {
  if (warned) return;
  warned = true;
  const names: Record<string, string> = {
    publicOrigin: ENV_KEYS.publicOrigin,
    supabaseUrl: ENV_KEYS.supabaseUrl,
    supabaseAnonKey: ENV_KEYS.supabaseAnonKey,
    apiBaseUrl: ENV_KEYS.apiBaseUrl,
  };
  const missing = Object.entries(parts)
    .filter(([, value]) => value === null)
    .map(([key]) => names[key]);
  console.warn(
    `[verina] ${ENV_KEYS.connected}=1 but connected mode stays off: missing or invalid ${missing.join(", ")}.`,
  );
}

/** Runtime configuration for this process. */
export function connectedConfig(): ConnectedConfig | null {
  return readConnectedConfig(process.env);
}
