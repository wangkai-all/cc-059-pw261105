import React, { useMemo, useState } from "react";

/**
 * Author view: "which papers are being cited, by author".
 * Citations received = sum of each paper's in-degree for that author's papers.
 * Ranked horizontal bars, one hue (sequential), exact values in the column
 * beside each bar; a table below keeps every number reachable without hovering.
 */
export default function AuthorView({ graph }) {
  const [selected, setSelected] = useState(null);
  const nodes = graph?.ranking?.nodes ?? [];

  const rows = useMemo(() => {
    const byAuthor = new Map();
    for (const node of nodes) {
      for (const author of node.authors ?? []) {
        const entry = byAuthor.get(author) ?? {
          author,
          citations: 0,
          papers: [],
          topics: new Set(),
          years: [],
        };
        entry.citations += node.in_degree;
        entry.papers.push(node);
        for (const topic of node.topics ?? []) entry.topics.add(topic);
        if (node.year != null) entry.years.push(node.year);
        byAuthor.set(author, entry);
      }
    }
    return [...byAuthor.values()]
      .map((entry) => ({
        ...entry,
        topics: [...entry.topics].sort(),
        years: entry.years.sort((a, b) => a - b),
        papers: entry.papers.sort((a, b) => b.in_degree - a.in_degree),
      }))
      .sort((a, b) => b.citations - a.citations || a.author.localeCompare(b.author));
  }, [nodes]);

  if (!graph) return null;
  if (rows.length === 0) {
    return (
      <section className="panel-card wide">
        <h2>作者视角</h2>
        <p className="empty">当前筛选下没有作者数据。</p>
      </section>
    );
  }

  const max = Math.max(1, ...rows.map((r) => r.citations));
  const active = selected ? rows.find((r) => r.author === selected) : null;

  return (
    <section className="panel-card wide">
      <div className="panel-head row">
        <div>
          <h2>作者视角 · 被引用</h2>
          <p className="hint">
            条长表示该作者名下论文收到的引用总数（每条边只计一次；多作者论文对每位作者各计一次）。
            点击作者查看其论文明细。
          </p>
        </div>
        {active && (
          <button className="ghost small" onClick={() => setSelected(null)}>
            取消选择
          </button>
        )}
      </div>

      <div className="author-chart" aria-label="作者被引用排名">
        {rows.map((row) => {
          const width = (row.citations / max) * 100;
          const meta = `${row.papers.length} 篇 · ${
            row.years.length ? `${row.years[0]}–${row.years.at(-1)}` : "无年份"
          } · ${row.topics.join("、") || "无主题"}`;
          return (
            <button
              key={row.author}
              className={active && active.author !== row.author ? "author-row dim" : "author-row"}
              onClick={() => setSelected((cur) => (cur === row.author ? null : row.author))}
              title={meta}
              aria-label={`${row.author}，被引用 ${row.citations} 次，${meta}`}
            >
              <span className="author-name">{row.author}</span>
              <span className="author-track">
                <span className="author-bar" style={{ width: `${Math.max(width, 1)}%` }} />
              </span>
              <span className="author-value">{row.citations}</span>
            </button>
          );
        })}
      </div>

      {active && (
        <div className="author-detail">
          <h3>{active.author} 的论文</h3>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>论文</th>
                  <th className="num">年份</th>
                  <th className="num">被引用（入度）</th>
                  <th>主题</th>
                </tr>
              </thead>
              <tbody>
                {active.papers.map((p) => (
                  <tr key={p.id}>
                    <td>
                      {p.title}
                      <div className="muted small">{p.id}</div>
                    </td>
                    <td className="num">{p.year ?? "—"}</td>
                    <td className="num strong">{p.in_degree}</td>
                    <td className="wrap">{p.topics.join("、")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <details className="author-table">
        <summary>表格视图</summary>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>作者</th>
                <th className="num">被引用合计</th>
                <th className="num">论文数</th>
                <th className="num">年份</th>
                <th>主题</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.author}>
                  <td>{r.author}</td>
                  <td className="num strong">{r.citations}</td>
                  <td className="num">{r.papers.length}</td>
                  <td className="num">
                    {r.years.length ? `${r.years[0]}–${r.years[r.years.length - 1]}` : "—"}
                  </td>
                  <td className="wrap">{r.topics.join("、")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </section>
  );
}
