import ReactMarkdown from "react-markdown";

const md = `# 使用文档

## 快速开始

1. 从[下载页](/download)安装客户端。
2. 创建本地保险库：设置短密钥并永久保存 \`.kpkey\`。
3. （可选）在官网注册账号，完成邮箱验证后下载绑定密钥 \`.kpbind\`。
4. 在客户端设置 → 云同步中登录并绑定设备。

## 云同步

- 本地文件变更后会自动上传加密保险库。
- 点「立即刷新」可主动检查并合并云端更新。
- 服务器只保存密文，无法解密条目内容。

## 浏览器扩展

Windows 上可安装浏览器扩展，配合短密钥确认后自动填充。macOS / Linux 的程序自动填充仍在完善中。

- **Microsoft Edge（已上架）**：[商店页](https://microsoftedge.microsoft.com/addons/detail/lbkhkkkmnbhnnmimhadmjappokdfkpgd)（商店标识 \`0RDCKGQT5LVS\`，CRX ID \`lbkhkkkmnbhnnmimhadmjappokdfkpgd\`）。当前为**私有**扩展，需连接后才能打开安装。
- 客户端「设置 → 浏览器扩展」也可打开同一商店页。
- 安装后仍需按扩展目录中的说明，注册 Native Messaging 宿主并与桌面端配对。

## 密钥说明

- \`.kpkey\`：保险库数据密钥，丢失则无法解密。
- \`.kpbind\`：设备绑定密钥，可在官网重新生成；旧文件立即失效，已绑定设备不受影响。
`;

export function DocsPage() {
  return (
    <div className="kp-page">
      <div className="kp-markdown">
        <ReactMarkdown>{md}</ReactMarkdown>
      </div>
    </div>
  );
}
