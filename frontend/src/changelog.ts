export type ChangelogProduct = "client" | "website";

export type ChangelogEntry = {
  version: string;
  date: string;
  product: ChangelogProduct;
  title: string;
  file: string;
  source?: string;
  body: string;
};

export type ChangelogIndex = {
  releasesUrl: string;
  entries: ChangelogEntry[];
};

export async function loadChangelog(): Promise<ChangelogIndex> {
  const res = await fetch("/changelog/index.json", { cache: "no-cache" });
  if (!res.ok) {
    throw new Error("更新日志暂时无法加载");
  }
  return (await res.json()) as ChangelogIndex;
}
