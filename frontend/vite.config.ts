import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";
import fs from "node:fs";
import path from "node:path";

const CHANGELOG_DIR = path.resolve(__dirname, "public/changelog");
const CHANGELOG_INDEX = path.join(CHANGELOG_DIR, "index.json");
const RELEASES_URL = "https://github.com/a2king/keep-password/releases";

type ChangelogMeta = {
  version: string;
  date: string;
  product: "client" | "website";
  title: string;
  file: string;
  source?: string;
  body: string;
};

function parseFrontmatter(file: string, raw: string): ChangelogMeta {
  const match = raw.match(/^---\r?\n([\s\S]*?)\r?\n---\r?\n?([\s\S]*)$/);
  if (!match) {
    throw new Error(`${file} 缺少 YAML frontmatter（--- 包裹的 version/date 等字段）`);
  }
  const meta: Record<string, string> = {};
  for (const line of match[1].split(/\r?\n/)) {
    if (!line.trim() || line.trim().startsWith("#")) continue;
    const idx = line.indexOf(":");
    if (idx === -1) continue;
    meta[line.slice(0, idx).trim()] = line.slice(idx + 1).trim().replace(/^["']|["']$/g, "");
  }
  const version = meta.version;
  const date = meta.date;
  if (!version || !date) {
    throw new Error(`${file} 的 frontmatter 需要 version 与 date`);
  }
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) {
    throw new Error(`${file} 的 date 必须是 YYYY-MM-DD，实际为 ${date}`);
  }
  const product = meta.product === "website" ? "website" : "client";
  return {
    version,
    date,
    product,
    title: meta.title || "",
    file,
    source: meta.source || undefined,
    body: match[2].trim(),
  };
}

function versionKey(version: string): number[] {
  return (version.match(/\d+/g) || []).map((n) => Number(n));
}

function compareVersionDesc(a: string, b: string): number {
  const left = versionKey(a);
  const right = versionKey(b);
  const len = Math.max(left.length, right.length);
  for (let i = 0; i < len; i += 1) {
    const d = (right[i] || 0) - (left[i] || 0);
    if (d) return d;
  }
  return b.localeCompare(a);
}

function writeChangelogIndex(): void {
  if (!fs.existsSync(CHANGELOG_DIR)) {
    throw new Error(`缺少更新日志目录: ${CHANGELOG_DIR}`);
  }
  const files = fs
    .readdirSync(CHANGELOG_DIR)
    .filter((name) => name.endsWith(".md") && name.toLowerCase() !== "readme.md")
    .sort();
  const entries = files.map((name) => {
    const raw = fs.readFileSync(path.join(CHANGELOG_DIR, name), "utf8");
    return parseFrontmatter(name, raw);
  });
  entries.sort((a, b) => {
    if (a.date !== b.date) return a.date < b.date ? 1 : -1;
    const byVersion = compareVersionDesc(a.version, b.version);
    if (byVersion) return byVersion;
    return a.file.localeCompare(b.file);
  });
  const payload = {
    releasesUrl: RELEASES_URL,
    entries,
  };
  fs.writeFileSync(CHANGELOG_INDEX, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
}

function changelogIndexPlugin(): Plugin {
  return {
    name: "kp-changelog-index",
    buildStart() {
      writeChangelogIndex();
    },
    configureServer() {
      writeChangelogIndex();
    },
    handleHotUpdate(ctx) {
      if (ctx.file.startsWith(CHANGELOG_DIR) && ctx.file.endsWith(".md")) {
        writeChangelogIndex();
      }
    },
  };
}

export default defineConfig({
  plugins: [react(), changelogIndexPlugin()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "src") },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:5000",
      "/downloads": "http://127.0.0.1:5000",
    },
  },
});
