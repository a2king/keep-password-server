import { useState } from "react";
import { Button, Form, Input, Steps, Typography, message } from "antd";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { downloadTextFile, register, verifyEmail } from "../api";
import { useAuth } from "../auth";

export function RegisterPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const { refresh } = useAuth();
  const initialEmail = (location.state as { email?: string } | null)?.email || "";
  const initialStep = (location.state as { step?: string } | null)?.step === "verify" ? 1 : 0;
  const [step, setStep] = useState(initialStep);
  const [email, setEmail] = useState(initialEmail);
  const [loading, setLoading] = useState(false);

  const onRegister = async (values: { email: string; password: string; confirm: string }) => {
    if (values.password !== values.confirm) {
      message.error("两次密码不一致");
      return;
    }
    setLoading(true);
    try {
      await register(values.email, values.password);
      setEmail(values.email);
      setStep(1);
      message.success("验证码已发送（开发环境见服务器控制台）");
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { error?: string } } })?.response?.data?.error;
      message.error(msg || "注册失败");
    } finally {
      setLoading(false);
    }
  };

  const onVerify = async (values: { code: string }) => {
    setLoading(true);
    try {
      const data = await verifyEmail(email, values.code);
      downloadTextFile(data.filename, data.bindingKeyFile);
      await refresh();
      message.success("验证成功，已开始下载绑定密钥文件");
      setStep(2);
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { error?: string } } })?.response?.data?.error;
      message.error(msg || "验证失败");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="kp-page" style={{ maxWidth: 520 }}>
      <h1>注册</h1>
      <Typography.Paragraph type="secondary">
        已有账号？<Link to="/login">登录</Link>
      </Typography.Paragraph>
      <Steps
        current={step}
        items={[{ title: "填写资料" }, { title: "邮箱验证" }, { title: "完成" }]}
        style={{ marginBottom: 24 }}
      />
      <div className="kp-card-panel">
        {step === 0 && (
          <Form layout="vertical" onFinish={onRegister} requiredMark={false} initialValues={{ email }}>
            <Form.Item name="email" label="邮箱" rules={[{ required: true, type: "email" }]}>
              <Input />
            </Form.Item>
            <Form.Item
              name="password"
              label="长密码"
              rules={[{ required: true, min: 12, message: "至少 12 位" }]}
            >
              <Input.Password />
            </Form.Item>
            <Form.Item name="confirm" label="确认密码" rules={[{ required: true }]}>
              <Input.Password />
            </Form.Item>
            <Button type="primary" htmlType="submit" loading={loading} block>
              注册并发送验证码
            </Button>
          </Form>
        )}
        {step === 1 && (
          <Form layout="vertical" onFinish={onVerify} requiredMark={false}>
            <Typography.Paragraph>
              验证码已发送到 <strong>{email}</strong>
            </Typography.Paragraph>
            <Form.Item name="code" label="验证码" rules={[{ required: true, len: 6 }]}>
              <Input maxLength={6} />
            </Form.Item>
            <Button type="primary" htmlType="submit" loading={loading} block>
              验证并下载绑定密钥
            </Button>
          </Form>
        )}
        {step === 2 && (
          <>
            <Typography.Paragraph>
              请妥善保存刚下载的 <code>.kpbind</code> 文件。在客户端设置 → 云同步中用邮箱、密码、绑定密钥与验证码完成本机绑定。
            </Typography.Paragraph>
            <Button type="primary" onClick={() => navigate("/account")} block>
              进入个人中心
            </Button>
          </>
        )}
      </div>
    </div>
  );
}
