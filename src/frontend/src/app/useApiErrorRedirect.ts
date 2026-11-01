import { useEffect, useRef } from 'react';
import { useLocation, useNavigate } from 'react-router';
import { useQueryClient } from '@tanstack/react-query';
import { onGlobalApiError } from '../api/errorPolicy';
import { clearEtagCache } from '../api/client';

/** 订阅全局 API 错误：401 AUTH_REQUIRED → /login?next=（评审 M2；v0.2.5 删除了同意门槛与开通引导页） */
export function useApiErrorRedirect() {
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
        if (action === 'login') {
          if (here.current.startsWith('/login')) return;
          clearEtagCache();
          qc.clear();
          navigate(`/login?next=${next}`, { replace: true });
        }
      }),
    [navigate, qc],
  );
}
