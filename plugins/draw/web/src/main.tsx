import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { ConfigProvider, App as AntApp } from 'antd';
import './api'; // 先裝好帶 token 的 fetch
import App from './App';
import { antdTheme, applyPalette } from './theme';
import './styles.css';

// Excalidraw 手寫字型走它預設的 CDN(字型含中文共 ~14MB,不塞進 plugin);離線時退回系統字型。

applyPalette();

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ConfigProvider theme={antdTheme}>
      <AntApp>
        <App />
      </AntApp>
    </ConfigProvider>
  </StrictMode>,
);
