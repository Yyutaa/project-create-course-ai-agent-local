const REFRESH_DELAY_MS = 150;

export function subscribeRun(
  runId: string,
  onChange: () => void,
  onConnection: (connected: boolean) => void,
): () => void {
  const source = new EventSource(`/api/v0/runs/${encodeURIComponent(runId)}/stream`);
  let refreshTimer: ReturnType<typeof setTimeout> | null = null;
  source.addEventListener("run.changed", () => {
    if (refreshTimer !== null) return;
    refreshTimer = setTimeout(() => {
      refreshTimer = null;
      onChange();
    }, REFRESH_DELAY_MS);
  });
  source.onopen = () => onConnection(true);
  source.onerror = () => onConnection(false);
  return () => {
    source.close();
    if (refreshTimer !== null) clearTimeout(refreshTimer);
  };
}
