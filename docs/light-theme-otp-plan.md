# 整站浅色 + 忘记密码 OTP — 改动说明

## 视觉
- 全局 CSS 变量改为浅色：页底 `#F7F7F5`、卡片 `#FFFFFF`、描边 `#E8E8E6`、正文 `#1A1A1A`
- Ant Design `ConfigProvider` 改为 `defaultAlgorithm`，主色炭黑 `#1A1A1A`（不用 ChatGPT 绿）
- 气质：大留白、轻描边、少阴影

## 忘记密码
- 路由：`/forgot` → `/forgot/verify`
- 登录页增加「忘记密码」
- 文案：「仅重置网站登录，不影响本地保险库主密码」
- API：`POST /api/auth/forgot`、`POST /api/auth/reset`（兼容旧路径 `forgot-password` / `reset-password`）
- 验证码：6 位数字，15 分钟，单次；限流约 1/min、5/h（email hash + IP）
- 存储：复用现有 `email_tokens`（purpose=`reset`，码只存哈希）；另增 `auth_throttles` 限流表
- 重置成功后作废设备会话（`devices.revoked_at`），清除云端 wrapped key

## Edge
- 保留商店按钮 / 链接；页面文案不再展示商店标识或 CRX ID

## SMTP
- 仍走 `backend/app/mail.py` + 环境变量 `SMTP_*` / `MAIL_DEV_CONSOLE`
- 未配置 SMTP 时开发模式打印到控制台，不写死密钥

## 文件清单
- `frontend/src/styles.css`、`main.tsx`、`App.tsx`、`api.ts`
- `frontend/src/pages/LoginPage.tsx`、`ForgotPage.tsx`、`ForgotVerifyPage.tsx`
- `backend/app/api/auth.py`、`tokens.py`、`models.py`、`config.py`
- `docs/light-theme-otp-plan.md`（本文件）

## 本地验收
```bash
# 前端
cd frontend && npm run build

# 后端（开发）
cd backend && .venv\Scripts\python -m flask --app wsgi run
# 或按仓库 README
```
打开首页 / 下载 / 文档 / 登录 / 注册 / forgot / forgot/verify，确认浅色且 Edge 入口仍在。
