import { useEffect } from 'react';
import { AppShell } from './components/AppShell';
import { useHashPath } from './router';
import { Terminal } from './pages/Terminal';
import { SuggestionDetail } from './pages/SuggestionDetail';
import { DailyReport } from './pages/DailyReport';
import { Placeholder } from './pages/Placeholder';

export default function App() {
  const path = useHashPath();
  useEffect(() => {
    document.querySelector('.content')?.scrollTo(0, 0);
  }, [path]);
  const [, seg, param] = path.split('/');
  let page;
  if (seg === 'terminal' || seg === '') page = <Terminal />;
  else if (seg === 'suggestions') page = <SuggestionDetail key={param ?? ''} param={param ? decodeURIComponent(param) : undefined} />;
  else if (seg === 'reports') page = <DailyReport date={param} />;
  else page = <Placeholder path={path} />;
  return <AppShell path={path}>{page}</AppShell>;
}
