import { useEffect, useState } from "react";
import { Alert, Button, Card, Col, Row, Statistic, Typography, Upload, message } from "antd";
import { Navigate } from "react-router-dom";
import { fetchOverview, getToken, type OverviewResponse } from "../api";
import { useAuth } from "../auth";

function formatBytes(n: number) {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(2)} MB`;
}

export function AdminPage() {
  const { me } = useAuth();
  const [data, setData] = useState<OverviewResponse | null>(null);

  useEffect(() => {
    if (!me?.isAdmin) return;
    fetchOverview()
      .then(setData)
      .catch(() => message.error("加载看板失败"));
  }, [me]);

  if (!me) return null;
  if (!me.isAdmin) return <Navigate to="/account" replace />;

  return (
    <div className="kp-page">
      <h1>管理后台</h1>
      <Typography.Paragraph type="secondary">只展示使用统计，不包含任何保险库明文。</Typography.Paragraph>

      {!data ? (
        <Alert message="加载中…" />
      ) : (
        <>
          <Row gutter={[16, 16]}>
            <Col xs={12} md={8}>
              <Card>
                <Statistic title="注册用户" value={data.totalUsers} />
              </Card>
            </Col>
            <Col xs={12} md={8}>
              <Card>
                <Statistic title="已验证邮箱" value={data.verifiedUsers} />
              </Card>
            </Col>
            <Col xs={12} md={8}>
              <Card>
                <Statistic title="活跃设备" value={data.activeDevices} />
              </Card>
            </Col>
            <Col xs={12} md={8}>
              <Card>
                <Statistic title="日活" value={data.dailyActiveUsers} />
              </Card>
            </Col>
            <Col xs={12} md={8}>
              <Card>
                <Statistic title="周活" value={data.weeklyActiveUsers} />
              </Card>
            </Col>
            <Col xs={12} md={8}>
              <Card>
                <Statistic title="存储占用" value={formatBytes(data.totalStorageBytes)} />
              </Card>
            </Col>
          </Row>

          <Card title="近 30 日注册" style={{ marginTop: 20 }}>
            <Typography.Paragraph style={{ marginBottom: 0 }}>
              {data.registrationsLast30Days.length === 0
                ? "暂无数据"
                : data.registrationsLast30Days.map((x) => `${x.day}: ${x.count}`).join(" · ")}
            </Typography.Paragraph>
          </Card>
          <Card title="近 30 日同步次数" style={{ marginTop: 16 }}>
            <Typography.Paragraph style={{ marginBottom: 0 }}>
              {data.syncsLast30Days.length === 0
                ? "暂无数据"
                : data.syncsLast30Days.map((x) => `${x.day}: ${x.count}`).join(" · ")}
            </Typography.Paragraph>
          </Card>
        </>
      )}

      <Card title="上传客户端安装包（官网备用通道）" style={{ marginTop: 20 }}>
        <Upload
          name="file"
          action="/api/admin/releases/upload"
          headers={{ Authorization: `Bearer ${getToken() || ""}` }}
          maxCount={1}
          onChange={(info) => {
            if (info.file.status === "done") message.success("上传成功");
            if (info.file.status === "error") message.error("上传失败");
          }}
        >
          <Button type="primary">选择文件上传</Button>
        </Upload>
      </Card>
    </div>
  );
}
