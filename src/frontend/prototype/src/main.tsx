import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { App as AntApp, ConfigProvider, theme } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import 'dayjs/locale/zh-cn';
import App from './App';
import './styles.css';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ConfigProvider
      locale={zhCN}
      theme={{
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
        },
      }}
    >
      <AntApp>
        <App />
      </AntApp>
    </ConfigProvider>
  </StrictMode>,
);
