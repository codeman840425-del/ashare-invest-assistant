import { clearSavedLayouts, DEFAULT_H, DEFAULT_V, LAYOUT_H_ID, LAYOUT_V_ID } from './layout';

describe('终端分栏布局', () => {
  it('默认比例各自合计 100%', () => {
    expect(Object.values(DEFAULT_H).reduce((a, b) => a + b, 0)).toBe(100);
    expect(Object.values(DEFAULT_V).reduce((a, b) => a + b, 0)).toBe(100);
  });
  it('clearSavedLayouts 只清终端布局键，不动其他 localStorage', () => {
    localStorage.setItem(`react-resizable-panels:${LAYOUT_H_ID}`, '{"left":60,"center":20,"right":20}');
    localStorage.setItem(`react-resizable-panels:${LAYOUT_V_ID}`, '{"main":50,"bottom":50}');
    localStorage.setItem('other.key', 'keep');
    clearSavedLayouts();
    expect(localStorage.getItem(`react-resizable-panels:${LAYOUT_H_ID}`)).toBeNull();
    expect(localStorage.getItem(`react-resizable-panels:${LAYOUT_V_ID}`)).toBeNull();
    expect(localStorage.getItem('other.key')).toBe('keep');
  });
});
