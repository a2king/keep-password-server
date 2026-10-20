import ReactMarkdown from "react-markdown";

const md = `# 隐私政策与服务条款

## 隐私政策（摘要）

- 我们收集：注册邮箱、设备元数据、加密后的保险库文件与包裹后的密钥包、同步时间戳。
- 我们不收集：保险库明文、短密钥、未包裹的 \`.kpkey\`。
- 邮件仅用于验证、安全操作确认与必要通知。
- 你可以随时在个人中心注销账号，云端数据将被删除；本地客户端数据不受影响。

## 服务条款（摘要）

- 本服务按「现状」提供，用于个人同步加密备份。
- 请妥善保管 \`.kpkey\` 与官网密码；丢失可能导致无法恢复数据。
- 禁止滥用注册、攻击接口或上传违法内容。
- 我们可能因维护或安全原因暂停服务，并会尽量提前公告。

正式法律文本可在上线前由你替换为本页 Markdown。
`;

export function LegalPage() {
  return (
    <div className="kp-page">
      <div className="kp-markdown">
        <ReactMarkdown>{md}</ReactMarkdown>
      </div>
    </div>
  );
}
