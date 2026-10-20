import { Button } from "antd";
import { Link } from "react-router-dom";

const features = [
  {
    title: "本地加密优先",
    body: "AES-256-GCM + Argon2id，保险库与密钥默认只在你的电脑上。",
  },
  {
    title: "面向运维的条目",
    body: "登录、服务器、数据库、SSH 密钥、API 凭据与集群节点，一处管理。",
  },
  {
    title: "零知识同步",
    body: "可选云同步只上传密文；服务器看不到密码，也无法解开 .kpkey。",
  },
  {
    title: "跨平台桌面端",
    body: "Windows / macOS / Linux 同一套客户端，换电脑拷贝保险库即可。",
  },
];

export function HomePage() {
  return (
    <>
      <section className="kp-hero">
        <div className="kp-hero__inner">
          <div className="kp-hero__copy">
            <div className="kp-brand" style={{ fontSize: "1.4rem" }}>
              Keep Password
            </div>
            <h1>
              开发与运维的
              <br />
              <span style={{ whiteSpace: "nowrap" }}>本地密码库</span>
            </h1>
            <p className="lead">
              网站、服务器、数据库与 SSH 密钥加密保存在本机。需要时再开启零知识网络同步，数据仍然只有你能解开。
            </p>
            <div className="kp-hero-actions">
              <Link to="/download">
                <Button type="primary" size="large">
                  下载客户端
                </Button>
              </Link>
              <Link to="/register">
                <Button size="large">注册同步账号</Button>
              </Link>
            </div>
          </div>
          <div className="kp-hero__media">
            <img src="/hero.png" alt="Keep Password 客户端界面" width="100%" />
          </div>
        </div>
      </section>

      <section className="kp-section">
        <h2>为什么选它</h2>
        <p className="sub">少一层云厂商信任，多一份本机掌控。同步是增强，不是前提。</p>
        <div className="kp-feature-grid">
          {features.map((item) => (
            <article key={item.title} className="kp-feature">
              <h3>{item.title}</h3>
              <p>{item.body}</p>
            </article>
          ))}
        </div>
      </section>
    </>
  );
}
