import { useState } from "react";
import { Button } from "antd";
import { Link } from "react-router-dom";
import { motion, useReducedMotion } from "motion/react";

const features = [
  {
    title: "本地加密",
    body: "AES-256，数据不出本机",
    icon: (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <rect x="5" y="11" width="14" height="9" rx="2" fill="none" stroke="currentColor" strokeWidth="1.6" />
        <path d="M8 11V8a4 4 0 0 1 8 0v3" fill="none" stroke="currentColor" strokeWidth="1.6" />
      </svg>
    ),
  },
  {
    title: "运维条目",
    body: "服务器、数据库、SSH 一处管",
    icon: (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <rect x="3" y="4" width="18" height="6" rx="1.5" fill="none" stroke="currentColor" strokeWidth="1.6" />
        <rect x="3" y="14" width="18" height="6" rx="1.5" fill="none" stroke="currentColor" strokeWidth="1.6" />
        <circle cx="7" cy="7" r="0.8" fill="currentColor" />
        <circle cx="7" cy="17" r="0.8" fill="currentColor" />
      </svg>
    ),
  },
  {
    title: "零知识同步",
    body: "只上传密文，服务端解不开",
    icon: (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M7 18h10a4 4 0 0 0 .4-8 6 6 0 0 0-11.5-1.6A3.5 3.5 0 0 0 7 18z" fill="none" stroke="currentColor" strokeWidth="1.6" />
        <path d="M12 11v4M10.5 13.5 12 15l1.5-1.5" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
      </svg>
    ),
  },
  {
    title: "安全审计",
    body: "弱密码与泄露检查",
    icon: (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M12 3 5 6v6c0 4.2 2.8 7.2 7 8.5 4.2-1.3 7-4.3 7-8.5V6l-7-3z" fill="none" stroke="currentColor" strokeWidth="1.6" />
        <path d="m9 12 2 2 4-4" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
      </svg>
    ),
  },
];

function reveal(reduce: boolean | null) {
  if (reduce) {
    return {
      initial: { opacity: 1 },
      animate: { opacity: 1 },
      transition: { duration: 0 },
    };
  }
  return {
    initial: { opacity: 0, y: 20 },
    whileInView: { opacity: 1, y: 0 },
    viewport: { once: true, amount: 0.25 },
    transition: { duration: 0.5, ease: "easeOut" as const },
  };
}

export function HomePage() {
  const reduce = useReducedMotion();
  const [videoOk, setVideoOk] = useState(true);

  return (
    <>
      <motion.section className="kp-hero" {...reveal(reduce)}>
        <div className="kp-hero__inner">
          <div className="kp-hero__copy">
            <p className="kp-eyebrow">开源 · 本地加密 · 零知识同步</p>
            <h1>
              开发与运维的
              <br />
              <span className="kp-nowrap">本地密码库</span>
            </h1>
            <p className="lead">网站、服务器、数据库、SSH 密钥，全部加密存在你自己的电脑上</p>
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
            <div className="kp-hero__tilt">
              {videoOk ? (
                <video
                  autoPlay
                  muted
                  loop
                  playsInline
                  poster="/hero.webp"
                  width={1024}
                  height={602}
                  onError={() => setVideoOk(false)}
                >
                  <source src="/demo.webm" type="video/webm" />
                </video>
              ) : (
                <picture>
                  <source srcSet="/hero.webp" type="image/webp" />
                  <img src="/hero.png" alt="Keep Password 客户端界面" width={1408} height={964} />
                </picture>
              )}
            </div>
          </div>
        </div>
      </motion.section>

      <motion.section className="kp-section" {...reveal(reduce)}>
        <h2>为什么选它</h2>
        <div className="kp-feature-grid">
          {features.map((item) => (
            <article key={item.title} className="kp-feature-card">
              <div className="kp-feature-icon">{item.icon}</div>
              <h3>{item.title}</h3>
              <p>{item.body}</p>
            </article>
          ))}
        </div>
        <Link className="kp-more" to="/security">
          了解安全设计 →
        </Link>
      </motion.section>
    </>
  );
}
