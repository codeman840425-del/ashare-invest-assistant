import { useEffect, useState } from 'react';

/** 极简 hash 路由：保证 dist 以 file:// 打开时也能跳转 */
export function useHashPath(): string {
  const get = () => (window.location.hash.replace(/^#/, '') || '/terminal');
  const [path, setPath] = useState(get);
  useEffect(() => {
    const on = () => setPath(get());
    window.addEventListener('hashchange', on);
    return () => window.removeEventListener('hashchange', on);
  }, []);
  return path;
}
export const go = (path: string) => {
  window.location.hash = path;
};
