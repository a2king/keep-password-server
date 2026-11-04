import React from "react";
import ReactDOM from "react-dom/client";
import { ConfigProvider, theme } from "antd";
import zhCN from "antd/locale/zh_CN";
import App from "./App";
import { AuthProvider } from "./auth";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ConfigProvider
      locale={zhCN}
      button={{ autoInsertSpace: false }}
      theme={{
        algorithm: theme.defaultAlgorithm,
        token: {
          colorPrimary: "#1A1A1A",
          colorBgBase: "#F7F7F5",
          colorBgContainer: "#FFFFFF",
          colorBorder: "#E8E8E6",
          colorText: "#1A1A1A",
          colorTextSecondary: "#5A5A58",
          fontFamily: "'IBM Plex Sans', system-ui, sans-serif",
          borderRadius: 10,
        },
      }}
    >
      <AuthProvider>
        <App />
      </AuthProvider>
    </ConfigProvider>
  </React.StrictMode>,
);
