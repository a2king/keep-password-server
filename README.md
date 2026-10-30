# Keep Password Server

版本 **v0.1.0**。Keep Password 官网与云同步后台：Flask API + React 前端，Docker Compose + Caddy 部署。

## 本地开发（API）

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env   # 或 cp
flask --app wsgi run --debug --port 5000
```

## 本地开发（官网前端）

```bash
cd frontend
npm install
npm run dev
```

开发服务器：`http://127.0.0.1:5173`（`/api` 代理到 Flask `:5000`）。

生产构建输出到 `frontend/dist`，由 Caddy 提供静态文件。

首次或空库可执行：

```bash
flask --app wsgi init-db
```

冒烟测试：

```bash
cd backend
python scripts/smoke_api.py
# 等价：PYTHONPATH=. python scripts/smoke_api.py
```

授予管理员：

```bash
set SET_ADMIN_EMAIL=you@example.com
flask --app wsgi set-admin
```

生产 Docker 入口会先 `python -m app.dbutil` 再以 `--preload` 启动 gunicorn，避免多 worker 竞态建表。在反向代理后请设置 `TRUST_PROXY=true`。

## 已实现 API（阶段 2）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/auth/register` | 注册 |
| POST | `/api/auth/verify-email` | 邮箱验证并下载绑定密钥 |
| POST | `/api/auth/login` | 登录（失败限速 + 验证码） |
| POST | `/api/auth/forgot-password` / `reset-password` | 重置密码 |
| GET | `/api/me` | 个人中心 |
| POST | `/api/me/devices/:id/revoke` | 解绑设备 |
| POST | `/api/me/binding-key/regenerate` | 重新生成绑定密钥 |
| POST | `/api/me/delete` | 注销账号 |
| POST | `/api/sync/device/bind` | 设备绑定 |
| GET/PUT | `/api/sync/vault` | 下载/上传加密保险库（版本冲突 409） |
| GET/PUT | `/api/sync/wrapped-key` | 官网密码包裹的 `.kpkey` |
| GET | `/api/admin/overview` | 管理看板数据 |

服务器只存加密 blob，无法解密保险库内容。

## 部署

域名只改 `deploy/domains.env`（由 `deploy/domains.env.example` 复制）。Caddy 和 API 都会读这一份。

当前约定：

- 官网：`www.keep-password.work`，裸域跳到 www
- 客户端：`https://api.keep-password.work`（不要加 `/api`，路径里已经有）
- 过渡期把旧主机追加到 `SITE_HOSTS` / `API_HOSTS`，两个域名同时可用
- 收尾时把 `REDIRECT_TO_CANONICAL=true`，旧官网跳到 `CANONICAL_HOST`。API 主机不跳转，旧客户端还能连

`backend/.env` 里的密钥、数据库和 SMTP 照旧。生产环境 `domains.env` 会把 `TRUST_PROXY` 和 `PUBLIC_BASE_URL` 盖掉。

```bash
copy deploy\domains.env.example deploy\domains.env
docker compose up -d --build
```

客户端默认地址在 `SyncDefaults.ProductionBaseUrls`，按同样的顺序排列。开发可用 `KEEP_PASSWORD_SYNC_URL` 或逗号分隔的 `KEEP_PASSWORD_SYNC_URLS` 覆盖。已经绑定过的设备仍用当时保存的地址。
