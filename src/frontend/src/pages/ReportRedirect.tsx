import { Navigate, useParams } from 'react-router';

/** 旧路径 /reports[/:date] → /daily-reports（遗留问题 #2） */
export function ReportRedirect() {
  const { date } = useParams();
  return <Navigate to={date ? `/daily-reports/${date}` : '/daily-reports'} replace />;
}
