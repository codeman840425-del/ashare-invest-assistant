/**
 * 是否启用 MSW 示例数据：开发模式与 `--mode mock` 构建默认启用；
 * 联调真实后端时用 `VITE_USE_MOCK=false npm run dev`（配合 VITE_API_PROXY）关闭。
 */
export const IS_MOCK: boolean =
  (import.meta.env.DEV || import.meta.env.MODE === 'mock') && import.meta.env.VITE_USE_MOCK !== 'false';
