import ReactMarkdown from "react-markdown";

const md = `# 更新日志

## 服务端 0.1.0

- 账号注册、邮箱验证、绑定密钥下载
- 设备绑定与零知识保险库同步 API
- 管理看板与安装包上传

## 客户端（配合版本）

- 本地密钥格式（短密钥 + \`.kpkey\`）
- 条目时间戳与冲突合并
- 设置页云同步绑定 / 刷新 / 断开
`;

export function ChangelogPage() {
  return (
    <div className="kp-page">
      <div className="kp-markdown">
        <ReactMarkdown>{md}</ReactMarkdown>
      </div>
    </div>
  );
}
