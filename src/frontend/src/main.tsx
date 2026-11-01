import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { RouterProvider, createBrowserRouter } from 'react-router';
import 'dayjs/locale/zh-cn';
import dayjs from 'dayjs';
import { AppProviders } from './app/AppProviders';
import { makeQueryClient } from './app/queryClient';
import { routes } from './app/routes';
import { IS_MOCK } from './lib/env';
import './styles.css';

dayjs.locale('zh-cn');

async function enableMocks() {
  // 生产构建（mode=production）里这段在编译期整体剔除：dist/ 不含 MSW 与示例数据
  if (import.meta.env.MODE === 'production' || !IS_MOCK) return;
  // 仅开发/示例构建：MSW Service Worker 拦截 /api/v1/*，返回按契约 v0.2.3 构造的示例数据
  const { network } = await import('virtual:msw');
  const { handlers } = await import('./mocks/handlers');
  network.configure({ handlers });
  await network.enable();
}

void enableMocks().then(() => {
  const router = createBrowserRouter(routes);
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <AppProviders client={makeQueryClient()}>
        <RouterProvider router={router} />
      </AppProviders>
    </StrictMode>,
  );
});
