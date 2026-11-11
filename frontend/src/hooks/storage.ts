/**
 * What the application keeps in the browser.
 *
 * Local storage holds three things and nothing else: the conversation identifier (here), the theme
 * preference (`design/theme.ts`) and the locale preference (`i18n/index.ts`). The allowance code
 * stays in session storage. The API key secret is never stored: it lives in component memory.
 */

export const CONVERSATION_STORAGE_KEY = "veranico.conversation";
export const ALLOWANCE_CODE_STORAGE_KEY = "veranico.allowance_code";

function read(storage: () => Storage, key: string): string | null {
  try {
    return storage().getItem(key);
  } catch {
    return null;
  }
}

function write(storage: () => Storage, key: string, value: string | null): void {
  try {
    if (value === null) storage().removeItem(key);
    else storage().setItem(key, value);
  } catch {
    // Storage is unavailable (private mode, a third-party frame): the page still works.
  }
}

export function storedConversationId(): string | null {
  return read(() => window.localStorage, CONVERSATION_STORAGE_KEY);
}

export function storeConversationId(conversationId: string | null): void {
  write(() => window.localStorage, CONVERSATION_STORAGE_KEY, conversationId);
}

/**
 * The allowance code of this session. It arrives as `?code=` on the application URL, is kept for
 * the session, and is sent only on `POST /chat` and `GET /allowance`. It is never logged or shown.
 */
export function allowanceCode(): string | null {
  const fromUrl = new URLSearchParams(window.location.search).get("code");
  if (fromUrl !== null && fromUrl !== "") {
    write(() => window.sessionStorage, ALLOWANCE_CODE_STORAGE_KEY, fromUrl);
    return fromUrl;
  }
  return read(() => window.sessionStorage, ALLOWANCE_CODE_STORAGE_KEY);
}

/** The header that carries the code; no code, no header. */
export function allowanceHeader(): { "Veranico-Allowance-Code"?: string } {
  const code = allowanceCode();
  return code === null ? {} : { "Veranico-Allowance-Code": code };
}
