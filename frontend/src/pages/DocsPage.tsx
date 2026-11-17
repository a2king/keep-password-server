import ReactMarkdown from "react-markdown";
import { EDGE_STORE_URL } from "../site";

const md = `# 使用文档

## 快速开始

1. 从[下载页](/download)安装客户端。
2. 创建本地保险库：设置短密钥并永久保存加密密钥 \`.kpkey\`。
3. （可选）在官网注册账号并完成邮箱验证。
4. 在客户端「设置 → 云同步」中填写邮箱、网站密码和邮件验证码，绑定本机。

## 换电脑

1. 在新电脑安装客户端，创建保险库时选择「使用已有加密密钥」，选中原来的 \`.kpkey\`，再设置本机短密钥。
2. 在「设置 → 云同步」中绑定本机，云端数据会自动下载合并。
3. 如果创建时用了新密钥，绑定后按提示选择原来的 \`.kpkey\` 即可恢复同步。

## 云同步

- 本地文件变更后会自动上传加密保险库。
- 点「立即刷新」可主动检查并合并云端更新。
- 服务器只保存密文，无法解密条目内容。

## 浏览器扩展

Windows 上可安装浏览器扩展，配合短密钥确认后自动填充。macOS / Linux 的程序自动填充仍在完善中。

- **Microsoft Edge**：[Microsoft Edge 加载项](${EDGE_STORE_URL})。当前为私有扩展，需连接后才能打开安装。
- 客户端「设置 → 浏览器扩展」也可打开同一商店页。
- 安装后仍需按扩展目录中的说明，注册 Native Messaging 宿主并与桌面端配对。

## 密钥说明

- \`.kpkey\`：保险库数据密钥，换电脑时需要。服务器不保存它，丢失后无法解密云端数据。
- 文件名里的编号（如 \`83BD38E247B7\`）与个人中心显示的「云端加密密钥编号」一致，用来确认该带哪一份。
- 丢失 \`.kpkey\` 但还有一台能解锁的电脑时，可在客户端「设置 → 加密密钥」中重新导出。
- 1.0.1 起不再需要 \`.kpbind\` 绑定密钥文件，旧文件可以删除。
`;

export function DocsPage() {
  return (
    <div className="kp-page">
      <div className="kp-card-panel">
        <div className="kp-markdown">
          <ReactMarkdown>{md}</ReactMarkdown>
        </div>
      </div>
    </div>
  );
}
