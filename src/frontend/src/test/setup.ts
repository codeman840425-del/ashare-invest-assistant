import '@testing-library/jest-dom/vitest';
import { afterAll, afterEach, beforeAll, vi } from 'vitest';
import { cleanup, configure } from '@testing-library/react';
import { server } from '../mocks/server';
import { resetMockState } from '../mocks/handlers';
import { clearEtagCache } from '../api/client';

// jsdom 缺少的浏览器 API（antd / AG Grid / react-resizable-panels 需要）
if (!window.matchMedia) {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: (query: string) => ({
      matches: false, media: query, onchange: null,
      addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn(), dispatchEvent: vi.fn(),
    }),
  });
}
class RO {
  observe() {}
  unobserve() {}
  disconnect() {}
}
if (!('ResizeObserver' in window)) Object.defineProperty(window, 'ResizeObserver', { writable: true, value: RO });
if (!('ResizeObserver' in globalThis)) Object.defineProperty(globalThis, 'ResizeObserver', { writable: true, value: RO });
const gcs = window.getComputedStyle.bind(window);
window.getComputedStyle = (el: Element, pseudo?: string | null) => gcs(el, pseudo ? undefined : pseudo);

// 评审 7afbc06 m5：findBy / waitFor 默认 1000ms 在高负载下不够（t-f03、t-f08、t-f13、t-a09 偶发超时），统一放宽
configure({ asyncUtilTimeout: 5000 });

// 测试中所有 /api/v1 请求都由 msw/node 拦截；未处理的请求直接报错，确保不出网
beforeAll(() => server.listen({ onUnhandledFrame: 'error' }));
afterEach(() => {
  cleanup();
  server.resetHandlers();
  resetMockState();
  clearEtagCache();
  localStorage.clear();
});
afterAll(() => server.close());
