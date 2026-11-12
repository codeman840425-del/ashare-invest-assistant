import { act, render, screen } from '@testing-library/react';
import { flushSync } from 'react-dom';
import { createMemoryRouter, useParams } from 'react-router';
import { TestRouterProvider } from './TestRouterProvider';

function RouteView() {
  return <div data-testid="committed-route">{useParams().id}</div>;
}

it('test router commits destination DOM with the completed router update', () => {
  const router = createMemoryRouter([{ path: '/detail/:id', element: <RouteView /> }], { initialEntries: ['/detail/old'] });
  render(<TestRouterProvider router={router} />);
  expect(screen.getByTestId('committed-route')).toHaveTextContent('old');
  act(() => {
    flushSync(() => { void router.navigate('/detail/new'); });
    expect(router.state.navigation.state).toBe('idle');
    expect(router.state.location.pathname).toBe('/detail/new');
    expect(screen.getByTestId('committed-route')).toHaveTextContent('new');
  });
});
