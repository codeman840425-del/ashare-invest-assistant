/** 终端分栏布局：拖拽后持久化到 localStorage；“恢复默认布局”写回这些默认值 */
export const LAYOUT_H_ID = 'ashare.terminal.h';
export const LAYOUT_V_ID = 'ashare.terminal.v';
export const DEFAULT_H = { left: 40, center: 36, right: 24 } as const;
export const DEFAULT_V = { main: 76, bottom: 24 } as const;
export const LAYOUT_STORAGE_KEYS = [LAYOUT_H_ID, LAYOUT_V_ID];

/** 清掉已保存的分栏布局（react-resizable-panels 的 key 带库前缀，这里按 id 子串匹配） */
export function clearSavedLayouts(storage: Storage = localStorage) {
  const keys: string[] = [];
  for (let i = 0; i < storage.length; i++) {
    const k = storage.key(i);
    if (k && LAYOUT_STORAGE_KEYS.some((id) => k.includes(id))) keys.push(k);
  }
  keys.forEach((k) => storage.removeItem(k));
}
