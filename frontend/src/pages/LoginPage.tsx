import { useState } from "react";
import { Alert, Button, Form, Input, Typography, message } from "antd";
import { Link, useNavigate } from "react-router-dom";
import { fetchCaptcha, login } from "../api";
import { useAuth } from "../auth";

export function LoginPage() {
  const navigate = useNavigate();
  const { refresh } = useAuth();
  const [captchaRequired, setCaptchaRequired] = useState(false);
  const [captcha, setCaptcha] = useState<{ challengeId: string; question: string } | null>(null);
  const [loading, setLoading] = useState(false);

  const loadCaptcha = async () => {
    const c = await fetchCaptcha();
    setCaptcha(c);
    setCaptchaRequired(true);
  };

  const onFinish = async (values: { email: string; password: string; captchaAnswer?: string }) => {
    setLoading(true);
    try {
      await login(
        values.email,
        values.password,
        captchaRequired && captcha
          ? { captchaId: captcha.challengeId, captchaAnswer: values.captchaAnswer || "" }
          : undefined,
      );
      await refresh();
      message.success("登录成功");
      navigate("/account");
    } catch (err: unknown) {
      const data = (err as { response?: { data?: { error?: string; captchaRequired?: boolean; needVerify?: boolean } } })
        ?.response?.data;
      if (data?.needVerify) {
        message.warning("请先完成邮箱验证");
        navigate("/register", { state: { email: values.email, step: "verify" } });
        return;
      }
      if (data?.captchaRequired) {
        await loadCaptcha();
      }
      message.error(data?.error || "登录失败");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="kp-page" style={{ maxWidth: 480 }}>
      <h1>登录</h1>
      <Typography.Paragraph type="secondary">
        使用官网邮箱与长密码。还没有账号？<Link to="/register">注册</Link>
      </Typography.Paragraph>
      <div className="kp-card-panel">
        <Form layout="vertical" onFinish={onFinish} requiredMark={false}>
          <Form.Item name="email" label="邮箱" rules={[{ required: true, type: "email", message: "请输入邮箱" }]}>
            <Input autoComplete="username" />
          </Form.Item>
          <Form.Item name="password" label="密码" rules={[{ required: true, message: "请输入密码" }]}>
            <Input.Password autoComplete="current-password" />
          </Form.Item>
          {captchaRequired && captcha && (
            <>
              <Alert type="info" showIcon message={`验证码题目：${captcha.question}`} style={{ marginBottom: 12 }} />
              <Form.Item name="captchaAnswer" label="答案" rules={[{ required: true, message: "请填写答案" }]}>
                <Input />
              </Form.Item>
            </>
          )}
          <Button type="primary" htmlType="submit" loading={loading} block>
            登录
          </Button>
        </Form>
      </div>
    </div>
  );
}
