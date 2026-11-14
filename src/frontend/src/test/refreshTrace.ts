import { onTestFailed, onTestFinished, vi } from 'vitest';
import type { createMemoryRouter } from 'react-router';
import { server } from '../mocks/server';

/** Failure-only diagnostics for refresh tests: stages/statuses, never response bodies or headers. */
export function traceRefreshTest(label: string) {
  const started = performance.now();
  const events: { ms: number; event: string }[] = [];
  const mark = (event: string) => {
    if (events.length < 80) events.push({ ms: Math.round(performance.now() - started), event });
  };
  let router: ReturnType<typeof createMemoryRouter> | undefined;
  let unsubscribe: (() => void) | undefined;
  let initialPath: string | undefined;
  const resource = (request: Request) => {
    const path = new URL(request.url).pathname;
    if (path === '/api/v1/suggestions/refresh') return 'refresh';
    if (path === '/api/v1/suggestions') return 'suggestion-list';
    if (/^\/api\/v1\/suggestions\/[^/]+$/.test(path)) return 'suggestion-detail';
    if (/^\/api\/v1\/suggestions\/[^/]+\/tracking$/.test(path)) return 'suggestion-tracking';
    return null;
  };
  const requestStarted = ({ request }: { request: Request }) => {
    const name = resource(request);
    if (name) mark(`${request.method} ${name} started`);
  };
  const responseReceived = ({ request, response }: { request: Request; response: Response }) => {
    const name = resource(request);
    if (name) mark(`${request.method} ${name} ${response.status}`);
  };
  server.events.on('request:start', requestStarted);
  server.events.on('response:mocked', responseReceived);
  mark(`started; fakeTimers=${vi.isFakeTimers()}`);
  onTestFailed(() => {
    mark(`failed; fakeTimers=${vi.isFakeTimers()}`);
    console.error('REFRESH_TEST_TRACE', JSON.stringify({
      label,
      routeChanged: router ? router.state.location.pathname !== initialPath : null,
      navigation: router?.state.navigation.state ?? null,
      events,
    }));
  });
  onTestFinished(() => {
    unsubscribe?.();
    server.events.removeListener('request:start', requestStarted);
    server.events.removeListener('response:mocked', responseReceived);
  });
  return {
    mark,
    watchRouter(value: ReturnType<typeof createMemoryRouter>) {
      router = value;
      initialPath = value.state.location.pathname;
      unsubscribe = value.subscribe((state) => mark(`router ${state.navigation.state}; changed=${state.location.pathname !== initialPath}`));
    },
  };
}
