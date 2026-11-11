// Opt-in tracing only; inherits all original hooks, assertions and timeouts.
import { fileURLToPath } from 'node:url';
import original from '../../src/frontend/vite.config';

export default (env: Parameters<typeof original>[0]) => {
  const base = original(env);
  return {
    ...base,
    test: {
      ...base.test,
      setupFiles: [
        ...base.test.setupFiles,
        fileURLToPath(new URL('./frontend_timing.setup.ts', import.meta.url)),
      ],
    },
  };
};
