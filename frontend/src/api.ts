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
  bindingKeyFingerprint?: string;
  bindingKeyCreatedAt?: string;
  vaultVersion: number;
  vaultSizeBytes: number;
  hasWrappedKey: boolean;
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

export async function verifyEmail(email: string, code: string) {
  const { data } = await api.post("/auth/verify-email", { email, code });
  if (data.token) setToken(data.token);
  return data as {
    ok: boolean;
    fingerprint: string;
    filename: string;
    bindingKeyFile: string;
    token: string;
  };
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

export function downloadTextFile(filename: string, content: string) {
  const blob = new Blob([content], { type: "application/json;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
