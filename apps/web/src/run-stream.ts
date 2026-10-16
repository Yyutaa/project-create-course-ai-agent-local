export function subscribeRun(
  runId: string,
  onChange: () => void,
  onConnection: (connected: boolean) => void,
): () => void {
  const source = new EventSource(`/api/v0/runs/${encodeURIComponent(runId)}/stream`);
  source.addEventListener("run.changed", onChange);
  source.onopen = () => onConnection(true);
  source.onerror = () => onConnection(false);
  return () => source.close();
}
