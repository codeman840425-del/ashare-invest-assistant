import { Navigate } from 'react-router';
import { useSuggestions } from '../api/queries';
import { ErrorBox, Loading } from '../components/common';

/** /suggestions：跳到第一张当前候选信号卡（列表页在后续任务实现） */
export function SuggestionIndex() {
  const q = useSuggestions();
  if (q.isLoading) return <Loading />;
  if (q.isError) return <ErrorBox error={q.error} />;
  const first = q.data?.items[0];
  return first ? <Navigate to={`/suggestions/${first.id}`} replace /> : <div className="loading-box">暂无候选信号卡</div>;
}
