import { useState } from "react";
import { Button, Input, Modal, Space, Table, Typography, message } from "antd";
import { api, downloadTextFile } from "../api";
import { useAuth } from "../auth";

export function AccountPage() {
  const { me, refresh, logout } = useAuth();
  const [busy, setBusy] = useState(false);

  if (!me) return null;

  const requestCode = async (purpose: string) => {
    await api.post("/me/request-code", { purpose });
    message.success("验证码已发送（开发环境见服务器控制台）");
  };

  const revokeDevice = (id: number) => {
    let code = "";
    Modal.confirm({
      title: "解绑设备",
      content: (
        <div>
          <Button style={{ marginBottom: 12 }} onClick={() => void requestCode("unbind_device")}>
            发送验证码
          </Button>
          <Input placeholder="邮箱验证码" onChange={(e) => (code = e.target.value)} />
        </div>
      ),
      onOk: async () => {
        await api.post(`/me/devices/${id}/revoke`, { code });
        message.success("已解绑");
        await refresh();
      },
    });
  };

  const regenKey = () => {
    let code = "";
    Modal.confirm({
      title: "重新生成绑定密钥",
      content: (
        <div>
          <Typography.Paragraph type="secondary">
            旧绑定密钥立即失效；已绑定设备可继续同步。
          </Typography.Paragraph>
          <Button style={{ marginBottom: 12 }} onClick={() => void requestCode("regen_binding_key")}>
            发送验证码
          </Button>
          <Input placeholder="邮箱验证码" onChange={(e) => (code = e.target.value)} />
        </div>
      ),
      onOk: async () => {
        const { data } = await api.post("/me/binding-key/regenerate", { code });
        downloadTextFile(data.filename, data.bindingKeyFile);
        message.success("新绑定密钥已下载");
        await refresh();
      },
    });
  };

  const deleteAccount = () => {
    let password = "";
    let code = "";
    Modal.confirm({
      title: "注销账号",
      okType: "danger",
      content: (
        <div>
          <Typography.Paragraph type="warning">将删除云端保险库与设备，本地客户端数据保留。</Typography.Paragraph>
          <Button style={{ marginBottom: 12 }} onClick={() => void requestCode("delete_account")}>
            发送验证码
          </Button>
          <Input.Password placeholder="官网密码" style={{ marginBottom: 8 }} onChange={(e) => (password = e.target.value)} />
          <Input placeholder="邮箱验证码" onChange={(e) => (code = e.target.value)} />
        </div>
      ),
      onOk: async () => {
        setBusy(true);
        try {
          await api.post("/me/delete", { password, code });
          message.success("账号已注销");
          logout();
        } finally {
          setBusy(false);
        }
      },
    });
  };

  return (
    <div className="kp-page">
      <h1>个人中心</h1>
      <div className="kp-card-panel" style={{ marginBottom: 20 }}>
        <Typography.Title level={4} style={{ marginTop: 0 }}>
          {me.email}
        </Typography.Title>
        <Typography.Paragraph type="secondary" style={{ marginBottom: 8 }}>
          绑定密钥指纹：{me.bindingKeyFingerprint || "—"}
          <br />
          云端保险库版本：{me.vaultVersion} · 大小 {me.vaultSizeBytes} 字节
          <br />
          密钥包：{me.hasWrappedKey ? "已上传" : "未上传"}
        </Typography.Paragraph>
        <Space>
          <Button onClick={regenKey}>重新生成绑定密钥</Button>
          <Button danger loading={busy} onClick={deleteAccount}>
            注销账号
          </Button>
        </Space>
      </div>

      <Typography.Title level={4}>已绑定设备</Typography.Title>
      <Table
        rowKey="id"
        dataSource={me.devices}
        pagination={false}
        columns={[
          { title: "名称", dataIndex: "name" },
          { title: "平台", dataIndex: "platform" },
          { title: "客户端", dataIndex: "clientVersion" },
          { title: "最近活跃", dataIndex: "lastSeenAt" },
          {
            title: "操作",
            render: (_, row) => (
              <Button size="small" danger onClick={() => revokeDevice(row.id)}>
                解绑
              </Button>
            ),
          },
        ]}
      />
    </div>
  );
}
