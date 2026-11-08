import { useRef, useState } from 'react';

/** 密码仅短暂存在于 DOM 和本次请求；React state 只记录是否非空。 */
export function useTransientPassword() {
  const ref = useRef<HTMLInputElement>(null);
  const [filled, setFilled] = useState(false);
  function clear() {
    if (ref.current) ref.current.value = '';
    setFilled(false);
  }
  function take() {
    const value = ref.current?.value ?? '';
    clear();
    return value;
  }
  return { ref, filled, clear, take, onChange: () => setFilled(!!ref.current?.value) };
}
