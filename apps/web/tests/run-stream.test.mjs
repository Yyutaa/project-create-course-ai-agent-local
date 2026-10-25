import test from "node:test";
import assert from "node:assert/strict";

import { subscribeRun } from "../src/run-stream.ts";

test("run stream coalesces changes, reports connection and closes cleanly", async () => {
  const original = globalThis.EventSource;
  const seen = [];
  class FakeEventSource {
    constructor(url) { this.url = url; this.listeners = new Map(); FakeEventSource.current = this; }
    addEventListener(name, callback) { this.listeners.set(name, callback); }
    close() { this.closed = true; }
  }
  globalThis.EventSource = FakeEventSource;
  try {
    const close = subscribeRun("run/1", () => seen.push("refresh"),
      (connected) => seen.push(connected));
    const source = FakeEventSource.current;
    assert.equal(source.url, "/api/v0/runs/run%2F1/stream");
    source.onopen();
    source.listeners.get("run.changed")();
    source.listeners.get("run.changed")();
    source.listeners.get("run.changed")();
    assert.deepEqual(seen, [true]);
    await new Promise((resolve) => setTimeout(resolve, 180));
    assert.deepEqual(seen, [true, "refresh"]);
    source.onerror();
    assert.deepEqual(seen, [true, "refresh", false]);
    close();
    assert.equal(source.closed, true);
  } finally {
    globalThis.EventSource = original;
  }
});
