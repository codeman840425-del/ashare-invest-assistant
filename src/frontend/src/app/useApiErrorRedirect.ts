import { useEffect, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router';
import { useQueryClient } from '@tanstack/react-query';
import { onGlobalApiError } from '../api/errorPolicy';
import { clearEtagCache } from '../api/client';

/**
 * 订阅全局 API 错误：401 AUTH_REQUIRED → /login?next=（评审 M2；v0.2.5 删除了同意门槛与开通引导页）；
 * 403 CSRF_FAILED → 返回 true，由外壳显示“请刷新页面”提示（契约 v0.2.9 #30 ④：提示刷新，不自动重试）
 */
export function useApiErrorRedirect(): { csrfExpired: boolean; dismissCsrf: () => void } {
  const [csrfExpired, setCsrfExpired] = useState(false);
  const navigate = useNavigate();
  const qc = useQueryClient();
  const loc = useLocation();
  const here = useRef('');
  useEffect(() => {
    here.current = loc.pathname + loc.search;
  }, [loc.pathname, loc.search]);
  useEffect(
    () =>
      onGlobalApiError((action) => {
        const next = encodeURIComponent(here.current);
        if (action === 'csrf') {
          setCsrfExpired(true);
          return;
        }
        if (action === 'login') {
          if (here.current.startsWith('/login')) return;
          clearEtagCache();
          qc.clear();
          navigate(`/login?next=${next}`, { replace: true });
        }
      }),
    [navigate, qc],
  );
  return { csrfExpired, dismissCsrf: () => setCsrfExpired(false) };
}
