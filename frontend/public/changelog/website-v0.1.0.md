---
version: website v0.1.0
date: 2026-10-20
product: website
title: 官网与云同步服务端初版
source: https://github.com/a2king/keep-password-server/commit/a1dfa6754b8a4f4f4cd7b4be050421c7985e5fc1
---

依据本仓库 `VERSION` 与提交 `a1dfa67`（2026-10-20）。

- 账号注册、邮箱验证、绑定密钥下载
- 设备绑定与零知识保险库同步 API
- 管理看板与安装包上传
- Flask + React 官网，Docker Compose + Caddy 部署

同日提交 `045e4f1` 修复首次部署建表竞态，并处理上线前安全问题。随后同日还有官网首屏布局与移动端导航打磨。
