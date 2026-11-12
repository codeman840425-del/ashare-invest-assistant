import { RouterProvider, type RouterProviderProps } from 'react-router';

/** Test DOM assertions need urgent route commits; production keeps its normal transitions. */
export function TestRouterProvider({ router }: Pick<RouterProviderProps, 'router'>) {
  return <RouterProvider router={router} useTransitions={false} />;
}
