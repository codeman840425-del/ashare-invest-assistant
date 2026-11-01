import { QueryClient } from '@tanstack/react-query';

export function makeQueryClient(test = false) {
  return new QueryClient({
    defaultOptions: { queries: { retry: test ? false : 1, refetchOnWindowFocus: false, staleTime: 5_000 } },
  });
}

