// Pending write keys live only in the browser session until the API accepts them.
type SessionStore = Pick<Storage, "getItem" | "setItem" | "removeItem">;

function slotKey(slot: string): string {
  return `course-agent:pending:${slot}`;
}

export function pendingKey(store: SessionStore, slot: string, body: string): string {
  const key = slotKey(slot);
  const pending = store.getItem(key);
  if (pending) {
    try {
      const parsed = JSON.parse(pending) as { body: string; key: string };
      if (parsed.body === body && parsed.key) return parsed.key;
    } catch { /* Replace an invalid pending value. */ }
  }
  const fresh = crypto.randomUUID();
  store.setItem(key, JSON.stringify({ body, key: fresh }));
  return fresh;
}

export function clearPendingKey(store: SessionStore, slot: string): void {
  store.removeItem(slotKey(slot));
}
