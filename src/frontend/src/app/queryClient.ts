import { MutationCache, QueryCache, QueryClient } from '@tanstack/react-query';
import { handleGlobalError, retryDelay, shouldRetry } from '../api/errorPolicy';

export function makeQueryClient(test = false) {
  return new QueryClient({
    queryCache: new QueryCache({ onError: handleGlobalError }),
    mutationCache: new MutationCache({ onError: handleGlobalError }),
    defaultOptions: {
      queries: { retry: test ? false : shouldRetry, retryDelay, refetchOnWindowFocus: false, staleTime: 5_000 },
    },
  });
}
