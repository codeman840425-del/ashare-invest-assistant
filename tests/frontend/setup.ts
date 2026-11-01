// vitest 全局 setup（T-T01）
import '@testing-library/jest-dom/vitest';
import { afterEach, vi } from 'vitest';

// jsdom 没有 matchMedia；默认模拟深色主题（plan §2.4：深色交易终端风格，仅桌面）
if (!window.matchMedia) {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: (query: string) => ({
      matches: query.includes('prefers-color-scheme: dark'),
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }),
  });
}

// 禁止测试中真实联网：任何未 mock 的 fetch 直接失败
const blockedFetch = vi.fn(async (input: unknown) => {
  throw new Error(`前端单测禁止真实网络请求：${String(input)}`);
});

afterEach(() => {
  document.body.innerHTML = '';
});

globalThis.fetch = blockedFetch as unknown as typeof fetch;
