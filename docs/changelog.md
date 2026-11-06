# 更新日志维护

官网 `/changelog` 只读取本仓库静态文件，**不会在运行时调用 GitHub API**。

## 怎么加一条

1. 在 `frontend/public/changelog/` 新增一个 Markdown 文件，文件名建议：
   - 客户端发布：`client-v0.9.0.md`
   - 官网 / 服务端：`website-v0.1.0.md` 或 `website-2026-11-06.md`
2. 文件开头必须有 frontmatter：

```markdown
---
version: v0.9.0
date: 2026-11-05
product: client
title: 一句话标题
source: https://github.com/a2king/keep-password/releases/tag/v0.9.0
---

- 变更说明
```

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `version` | 是 | 展示用版本号 |
| `date` | 是 | `YYYY-MM-DD`，取 GitHub Release 发布日或 git 提交日 |
| `product` | 否 | `client`（默认）或 `website` |
| `title` | 否 | 列表副标题 |
| `source` | 否 | 依据链接，客户端用 GitHub Release |

3. 保存后执行 `cd frontend && npm run build`（或 `npm run dev`）。Vite 会扫描该目录，生成 `index.json`（已 gitignore，不要手改、不要提交）。
4. 只写有依据的版本：GitHub Releases（https://github.com/a2king/keep-password/releases）或本仓库 git 记录。不要编造日期或功能。
5. 页面文案不要写 Edge 商店标识、CRX ID、产品 ID 等内部编号。

`README.md` 不要当作版本条目。构建时会忽略它。
