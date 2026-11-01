import type { ReactNode } from 'react';
import { useMe } from '../api/queries';
import { Loading } from '../components/common';
import { NotFoundPage } from '../pages/PlaceholderPage';

/** /admin/* 只对 role=admin 渲染；其他人（含 /me 失败）一律显示 404，与契约 §1.3 后端行为一致（评审 M4） */
export function AdminGate({ children }: { children: ReactNode }) {
  const me = useMe();
  if (me.isPending) return <Loading />;
  if (me.data?.role !== 'admin') return <NotFoundPage />;
  return <>{children}</>;
}
