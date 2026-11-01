import { setupServer } from 'msw/node';
import { handlers } from './handlers';

/** Node（vitest）用的 MSW 服务 */
export const server = setupServer(...handlers);
