// Optional aggregate timing telemetry; never logs headers, bodies or query values.
import { appendFileSync, mkdirSync } from 'node:fs';
import { join } from 'node:path';
import { monitorEventLoopDelay, performance } from 'node:perf_hooks';
import { afterAll, afterEach, beforeAll, beforeEach } from '../../src/frontend/node_modules/vitest/dist/index.js';
import { getConfig } from '../../src/frontend/node_modules/@testing-library/dom/dist/config.js';
import { server } from '../../src/frontend/src/mocks/server';

const directory = process.env.AIA_TIMING_TRACE_DIR;
if (!directory) throw new Error('AIA_TIMING_TRACE_DIR must point to an external evidence directory');
mkdirSync(directory, { recursive: true });
const histogram = monitorEventLoopDelay({ resolution: 10 });
let test = '';
let start = 0;
const requests = new Map<string, { path: string; started: number }>();
const write = (event: Record<string, unknown>) => appendFileSync(
  join(directory, `worker-${process.pid}.jsonl`),
  `${JSON.stringify({ test, since_test_ms: Math.round(performance.now() - start), ...event })}\n`,
);
const requestStart = ({ request, requestId }: { request: Request; requestId: string }) => {
  const path = new URL(request.url).pathname;
  requests.set(requestId, { path, started: performance.now() });
  write({ kind: 'request', path });
};
const responseMocked = ({ requestId }: { requestId: string }) => {
  const pending = requests.get(requestId);
  if (pending) write({ kind: 'mocked', path: pending.path, elapsed_ms: Math.round(performance.now() - pending.started) });
  requests.delete(requestId);
};

beforeAll(() => {
  server.events.on('request:start', requestStart);
  server.events.on('response:mocked', responseMocked);
  histogram.enable();
});
beforeEach((context) => {
  test = context.task.name;
  start = performance.now();
  histogram.reset();
  write({ kind: 'begin', async_util_timeout_ms: getConfig().asyncUtilTimeout });
});
afterEach(() => {
  write({
    kind: 'end',
    event_loop_max_ms: Math.round(histogram.max / 1e6),
    pending_paths: [...requests.values()].map((value) => value.path),
    present_testids: ['stock-head', 'profile-panel', 'tab-factors', 'tab-financials'].filter(
      (id) => document.querySelector(`[data-testid="${id}"]`),
    ),
  });
});
afterAll(() => {
  histogram.disable();
  server.events.removeListener('request:start', requestStart);
  server.events.removeListener('response:mocked', responseMocked);
});
