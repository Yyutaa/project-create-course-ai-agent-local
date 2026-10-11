import { shouldPollRun } from "../src/features/run/run-polling.js";
import { authoritativeEffectiveChars } from "../src/features/run/quality-metrics.js";

function expect(value: boolean, message: string) {
  if (!value) throw new Error(message);
}

expect(
  shouldPollRun({ status: "FAILED", active_command: { status: "PENDING" } }) === true,
  "a queued continuation must keep polling after a failed run",
);
expect(
  shouldPollRun({ status: "FAILED", active_command: null }) === false,
  "an idle failed run can stop polling",
);
expect(shouldPollRun({ status: "RUNNING" }) === true, "a running run must keep polling");
expect(
  authoritativeEffectiveChars(13315, 8919) === 13315,
  "the quality snapshot must override a divergent client-side character estimate",
);
