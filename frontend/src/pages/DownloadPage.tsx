import { useEffect, useState } from "react";
import { Alert, Button, Space, Typography } from "antd";
import axios from "axios";

const GITHUB = "https://github.com/a2king/keep-password/releases/latest";
const EDGE_STORE =
  "https://microsoftedge.microsoft.com/addons/detail/lbkhkkkmnbhnnmimhadmjappokdfkpgd";
const EDGE_STORE_ID = "0RDCKGQT5LVS";
const EDGE_CRX_ID = "lbkhkkkmnbhnnmimhadmjappokdfkpgd";

type LatestMirror = { filename: string | null; url?: string };

export function DownloadPage() {
  const [mirror, setMirror] = useState<LatestMirror | null>(null);

  useEffect(() => {
    axios
      .get<LatestMirror>("/api/admin/releases/latest")
      .then((r) => setMirror(r.data))
      .catch(() => setMirror({ filename: null }));
  }, []);

  return (
    <div className="kp-page">
      <h1>下载</h1>
      <Typography.Paragraph type="secondary">
        推荐从 GitHub Releases 获取最新安装包。官网通道由管理员上传，作为备用。
      </Typography.Paragraph>

      <div className="kp-card-panel" style={{ marginBottom: 16 }}>
        <Typography.Title level={4} style={{ marginTop: 0 }}>
          GitHub（首选）
        </Typography.Title>
        <Button type="primary" href={GITHUB} target="_blank" rel="noreferrer">
          打开最新 Release
        </Button>
      </div>

      <div className="kp-card-panel" style={{ marginBottom: 16 }}>
        <Typography.Title level={4} style={{ marginTop: 0 }}>
          Edge 浏览器扩展
        </Typography.Title>
        <Typography.Paragraph type="secondary" style={{ marginBottom: 12 }}>
          当前为私有上架，需通过商店页连接后才能安装。商店标识{" "}
          <Typography.Text code>{EDGE_STORE_ID}</Typography.Text>，CRX ID{" "}
          <Typography.Text code>{EDGE_CRX_ID}</Typography.Text>。
        </Typography.Paragraph>
        <Button type="primary" href={EDGE_STORE} target="_blank" rel="noreferrer">
          打开 Microsoft Edge 加载项
        </Button>
      </div>

      <div className="kp-card-panel">
        <Typography.Title level={4} style={{ marginTop: 0 }}>
          官网备用下载
        </Typography.Title>
        {mirror?.filename ? (
          <Space direction="vertical">
            <div>当前缓存：{mirror.filename}</div>
            <Button href={mirror.url || `/downloads/${mirror.filename}`}>下载</Button>
          </Space>
        ) : (
          <Alert type="info" showIcon message="管理员尚未上传备用安装包。" />
        )}
      </div>
    </div>
  );
}
