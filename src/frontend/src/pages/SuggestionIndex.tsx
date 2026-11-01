import { Navigate, useSearchParams } from 'react-router';
import { useSuggestions } from '../api/queries';
import { ErrorBox, Loading } from '../components/common';
import { PlaceholderPage } from './PlaceholderPage';

/**
 * /suggestions：跳到第一张当前候选信号卡（列表页在后续任务实现）。
 * 带 ?status=（如 /today“查看全部”的 status=invalidated）时不跳转，先由占位页接住筛选参数。
 */
export function SuggestionIndex() {
  const [params] = useSearchParams();
  return params.get('status') ? <PlaceholderPage title="候选信号卡列表" /> : <FirstSuggestion />;
}

function FirstSuggestion() {
  const q = useSuggestions();
  if (q.isLoading) return <Loading />;
  if (q.isError) return <ErrorBox error={q.error} />;
  const first = q.data?.items[0];
  return first ? <Navigate to={`/suggestions/${first.id}`} replace /> : <div className="loading-box">暂无候选信号卡</div>;
}
