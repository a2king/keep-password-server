import { useState } from "react";
import { Button, Form, Input, Typography, message } from "antd";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { forgotPassword, resetPassword } from "../api";

export function ForgotVerifyPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const initialEmail = (location.state as { email?: string } | null)?.email || "";
  const [loading, setLoading] = useState(false);
  const [resending, setResending] = useState(false);
  const [form] = Form.useForm();

  const onFinish = async (values: { email: string; code: string; newPassword: string; confirm: string }) => {
    if (values.newPassword !== values.confirm) {
      message.error("两次密码不一致");
      return;
    }
    setLoading(true);
    try {
      await resetPassword(values.email, values.code, values.newPassword);
      message.success("密码已重置，请登录");
      navigate("/login");
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { error?: string } } })?.response?.data?.error;
      message.error(msg || "重置失败");
    } finally {
      setLoading(false);
    }
  };

  const onResend = async () => {
    try {
      const email = (form.getFieldValue("email") || "").trim();
      if (!email) {
        message.warning("请先填写邮箱");
        return;
      }
      setResending(true);
      await forgotPassword(email);
      message.success("如果该邮箱已注册，将收到验证码");
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { error?: string } } })?.response?.data?.error;
      message.error(msg || "发送失败");
    } finally {
      setResending(false);
    }
  };

  return (
    <div className="kp-page" style={{ maxWidth: 480 }}>
      <h1>重置密码</h1>
      <Typography.Paragraph type="secondary">输入邮箱收到的 6 位验证码，并设置新的网站登录密码。</Typography.Paragraph>
      <p className="kp-auth-hint">仅重置网站登录，不影响本地保险库主密码。</p>
      <div className="kp-card-panel">
        <Form
          form={form}
          layout="vertical"
          onFinish={onFinish}
          requiredMark={false}
          initialValues={{ email: initialEmail }}
        >
          <Form.Item
            name="email"
            label="邮箱"
            rules={[{ required: true, type: "email", message: "请输入邮箱" }]}
          >
            <Input autoComplete="username" />
          </Form.Item>
          <Form.Item
            name="code"
            label="验证码"
            rules={[{ required: true, pattern: /^\d{6}$/, message: "请输入 6 位数字验证码" }]}
          >
            <Input maxLength={6} inputMode="numeric" autoComplete="one-time-code" />
          </Form.Item>
          <Form.Item
            name="newPassword"
            label="新密码"
            rules={[{ required: true, min: 12, message: "至少 12 位" }]}
          >
            <Input.Password autoComplete="new-password" />
          </Form.Item>
          <Form.Item name="confirm" label="确认新密码" rules={[{ required: true, message: "请再次输入密码" }]}>
            <Input.Password autoComplete="new-password" />
          </Form.Item>
          <Button type="primary" htmlType="submit" loading={loading} block>
            重置密码
          </Button>
          <Button style={{ marginTop: 12 }} onClick={onResend} loading={resending} block>
            重新发送验证码
          </Button>
        </Form>
      </div>
      <div className="kp-auth-footer">
        <Link to="/forgot">换个邮箱</Link>
        {" · "}
        <Link to="/login">返回登录</Link>
      </div>
    </div>
  );
}
