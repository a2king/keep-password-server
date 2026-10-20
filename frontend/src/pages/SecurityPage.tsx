import ReactMarkdown from "react-markdown";

const md = `# 安全设计

## 本地保险库

- 数据密钥：256 位随机密钥，以 \`.kpkey\` 形式由你保管。
- 载荷加密：AES-256-GCM。
- 本机解锁：短密钥 + 设备绑定的快速解锁材料（Windows 上经 DPAPI 保护）。

## 零知识同步

1. 客户端用官网密码在本地派生密钥，包裹 \`.kpkey\` 后上传（服务器无法解开）。
2. 保险库文件始终以密文上传/下载。
3. 冲突时在客户端按条目 \`UpdatedAt\` 合并，再写回云端。

## 账号安全

- 官网密码至少 12 位，服务端 Argon2id 存储。
- 登录失败限速，多次失败后要求算术验证码。
- 解绑设备、重新生成绑定密钥、注销账号均需邮箱验证码确认。

我们承诺：管理员后台只看使用统计，永远看不到你的保险库明文。
`;

export function SecurityPage() {
  return (
    <div className="kp-page">
      <div className="kp-markdown">
        <ReactMarkdown>{md}</ReactMarkdown>
      </div>
    </div>
  );
}
