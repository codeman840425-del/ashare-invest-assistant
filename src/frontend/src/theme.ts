import { theme, type ThemeConfig } from 'antd';

/** 深色 + 紧凑主题（与 T-F00 原型一致）。红涨绿跌颜色见 styles.css 的 --up/--down。 */
export const UP_COLOR = '#f5384a';
export const DOWN_COLOR = '#1fb36b';

export const appTheme: ThemeConfig = {
  algorithm: [theme.darkAlgorithm, theme.compactAlgorithm],
  token: {
    colorPrimary: '#3b82f6',
    colorBgBase: '#0b0f15',
    colorBgContainer: '#0f141c',
    colorBorder: '#232c3a',
    colorBorderSecondary: '#1c2430',
    borderRadius: 3,
    fontSize: 12,
    fontFamily: '-apple-system, "PingFang SC", "Microsoft YaHei", "Noto Sans CJK SC", "Segoe UI", sans-serif',
  },
  components: {
    Table: { headerBg: '#121925', rowHoverBg: '#16202e', cellPaddingBlockSM: 3, cellPaddingInlineSM: 6 },
    Tabs: { horizontalItemPadding: '5px 4px', horizontalMargin: '0' },
  },
};
