import axios from "axios";

const TOKEN_KEY = "kp_web_token";

export const api = axios.create({
  baseURL: "/api",
  timeout: 30000,
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem(TOKEN_KEY);
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

export function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string | null) {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

export type MeResponse = {
  email: string;
  isAdmin: boolean;
  vaultVersion: number;
  vaultSizeBytes: number;
  /** 云端密文所用加密密钥的编号，与客户端密钥文件名中的编号相同。尚未上传时为空。 */
  vaultKeyId?: string | null;
  keyVersion: number;
  devices: Array<{
    id: number;
    name: string;
    platform: string;
    clientVersion: string;
    createdAt: string;
    lastSeenAt: string;
  }>;
};

export type OverviewResponse = {
  totalUsers: number;
  verifiedUsers: number;
  activeDevices: number;
  dailyActiveUsers: number;
  weeklyActiveUsers: number;
  totalStorageBytes: number;
  registrationsLast30Days: Array<{ day: string; count: number }>;
  syncsLast30Days: Array<{ day: string; count: number }>;
};

export async function login(email: string, password: string, captcha?: { captchaId: string; captchaAnswer: string }) {
  const { data } = await api.post("/auth/login", { email, password, ...captcha });
  setToken(data.token);
  return data as { token: string; email: string; isAdmin: boolean };
}

export async function register(email: string, password: string) {
  const { data } = await api.post("/auth/register", { email, password });
  return data;
}

export async function resendVerify(email: string) {
  const { data } = await api.post("/auth/resend-verify", { email });
  return data as { ok: boolean };
}

export async function verifyEmail(email: string, code: string) {
  const { data } = await api.post("/auth/verify-email", { email, code });
  if (data.token) setToken(data.token);
  return data as {
    ok: boolean;
    token: string;
  };
}

/** 忘记密码：恒成功文案；有账号才发信（后端） */
export async function forgotPassword(email: string) {
  const { data } = await api.post("/auth/forgot", { email });
  return data as { ok: boolean; message?: string };
}

/** 用 6 位码重置网站登录密码 */
export async function resetPassword(email: string, code: string, newPassword: string) {
  const { data } = await api.post("/auth/reset", { email, code, newPassword });
  return data as { ok: boolean };
}

export async function fetchMe() {
  const { data } = await api.get<MeResponse>("/me");
  return data;
}

export async function fetchOverview() {
  const { data } = await api.get<OverviewResponse>("/admin/overview");
  return data;
}

export async function fetchCaptcha() {
  const { data } = await api.get<{ challengeId: string; question: string }>("/auth/captcha");
  return data;
}
