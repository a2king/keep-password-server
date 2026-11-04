import { useState } from "react";
import { Button, Form, Input, Typography, message } from "antd";
import { Link, useNavigate } from "react-router-dom";
import { forgotPassword } from "../api";

export function ForgotPage() {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(false);

  const onFinish = async (values: { email: string }) => {
    setLoading(true);
    try {
      await forgotPassword(values.email);
      message.success("如果该邮箱已注册，将收到验证码");
      navigate("/forgot/verify", { state: { email: values.email } });
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { error?: string } } })?.response?.data?.error;
      message.error(msg || "请求失败，请稍后再试");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="kp-page" style={{ maxWidth: 480 }}>
      <h1>忘记密码</h1>
      <Typography.Paragraph type="secondary">
        通过邮箱验证码重置<strong>网站登录密码</strong>。
      </Typography.Paragraph>
      <p className="kp-auth-hint">仅重置网站登录，不影响本地保险库主密码。</p>
      <div className="kp-card-panel">
        <Form layout="vertical" onFinish={onFinish} requiredMark={false}>
          <Form.Item name="email" label="邮箱" rules={[{ required: true, type: "email", message: "请输入邮箱" }]}>
            <Input autoComplete="username" />
          </Form.Item>
          <Button type="primary" htmlType="submit" loading={loading} block>
            发送验证码
          </Button>
        </Form>
      </div>
      <div className="kp-auth-footer">
        <Link to="/login">返回登录</Link>
      </div>
    </div>
  );
}
