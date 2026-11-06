import { useEffect, useState } from "react";
import { Alert, Spin, Typography } from "antd";
import ReactMarkdown from "react-markdown";
import { loadChangelog, type ChangelogEntry, type ChangelogIndex } from "../changelog";
import { CLIENT_RELEASES_URL } from "../site";

function productLabel(product: ChangelogEntry["product"]) {
  return product === "website" ? "官网 / 服务端" : "客户端";
}

export function ChangelogPage() {
  const [data, setData] = useState<ChangelogIndex | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    loadChangelog()
      .then((index) => {
        if (!cancelled) setData(index);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "更新日志暂时无法加载");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="kp-page kp-changelog">
      <h1>更新日志</h1>
      <Typography.Paragraph type="secondary">
        本页由仓库 <code>frontend/public/changelog/</code> 中的说明文件生成，不在浏览器里请求 GitHub
        API。完整发布包与校验信息见{" "}
        <a href={CLIENT_RELEASES_URL} target="_blank" rel="noreferrer">
          GitHub Releases
        </a>
        。
      </Typography.Paragraph>

      {error && <Alert type="error" showIcon message={error} />}
      {!error && !data && (
        <div className="kp-changelog-loading">
          <Spin />
        </div>
      )}
      {data && data.entries.length === 0 && (
        <Alert type="info" showIcon message="还没有更新日志条目。" />
      )}
      {data?.entries.map((entry) => (
        <article key={entry.file} className="kp-card-panel kp-changelog-entry">
          <header className="kp-changelog-head">
            <div>
              <h2>{entry.version}</h2>
              {entry.title && <p className="kp-changelog-title">{entry.title}</p>}
            </div>
            <div className="kp-changelog-meta">
              <time dateTime={entry.date}>{entry.date}</time>
              <span>{productLabel(entry.product)}</span>
            </div>
          </header>
          <div className="kp-markdown">
            <ReactMarkdown>{entry.body}</ReactMarkdown>
          </div>
          {entry.source && (
            <p className="kp-changelog-source">
              依据：{" "}
              <a href={entry.source} target="_blank" rel="noreferrer">
                {entry.source}
              </a>
            </p>
          )}
        </article>
      ))}
    </div>
  );
}
