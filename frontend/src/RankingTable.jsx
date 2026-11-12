import React, { useMemo, useState } from "react";

const SORTS = {
  pagerank: "PageRank",
  in_degree: "入度（被引用）",
  out_degree: "出度（引用）",
  year: "年份",
};

export default function RankingTable({ graph, onSelectPaper }) {
  const [sortKey, setSortKey] = useState("pagerank");
  const [query, setQuery] = useState("");
  const [topic, setTopic] = useState("");
  const [author, setAuthor] = useState("");

  const nodes = graph?.ranking?.nodes ?? [];
  const topics = useMemo(
    () => Array.from(new Set(nodes.flatMap((n) => n.topics ?? []))).sort(),
    [nodes]
  );
  const authors = useMemo(
    () => Array.from(new Set(nodes.flatMap((n) => n.authors ?? []))).sort(),
    [nodes]
  );

  const rows = useMemo(() => {
    const filtered = nodes.filter((n) => {
      if (query && !`${n.title} ${n.id} ${(n.authors ?? []).join(" ")}`.toLowerCase().includes(query.toLowerCase())) {
        return false;
      }
      if (topic && !(n.topics ?? []).includes(topic)) return false;
      if (author && !(n.authors ?? []).includes(author)) return false;
      return true;
    });
    const sorted = [...filtered].sort((a, b) => {
      if (sortKey === "year") return (a.year ?? 0) - (b.year ?? 0) || a.id.localeCompare(b.id);
      return b[sortKey] - a[sortKey] || a.id.localeCompare(b.id);
    });
    return sorted;
  }, [nodes, query, topic, author, sortKey]);

  if (!graph) return null;

  return (
    <section className="panel-card">
      <div className="panel-head row">
        <h2>排名与明细</h2>
        <select value={sortKey} onChange={(e) => setSortKey(e.target.value)} aria-label="排序字段">
          {Object.entries(SORTS).map(([key, label]) => (
            <option key={key} value={key}>
              按{label}
            </option>
          ))}
        </select>
      </div>

      <div className="table-filters">
        <input
          type="search"
          placeholder="搜索标题 / 作者 / ID"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <select value={topic} onChange={(e) => setTopic(e.target.value)}>
          <option value="">全部主题</option>
          {topics.map((t) => (
            <option key={t} value={t}>{t}</option>
          ))}
        </select>
        <select value={author} onChange={(e) => setAuthor(e.target.value)}>
          <option value="">全部作者</option>
          {authors.map((a) => (
            <option key={a} value={a}>{a}</option>
          ))}
        </select>
      </div>

      <p className="hint">
        PageRank 状态：{graph.ranking.converged ? "已收敛" : "未收敛（达到最大迭代）"}
        · 迭代 {graph.ranking.iterations} 次 · 误差 {graph.ranking.error.toExponential(2)}
        · 阈值 {graph.ranking.threshold} · δ={graph.ranking.alpha}
      </p>

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th className="num">#</th>
              <th>论文</th>
              <th className="num">年份</th>
              <th className="num">被引用<br /><span className="th-sub">入度</span></th>
              <th className="num">引用<br /><span className="th-sub">出度</span></th>
              <th className="num">PageRank</th>
              <th>主题</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((n) => (
              <tr key={n.id} className={n.isolated ? "isolated-row" : ""}>
                <td className="num muted">{n.rank}</td>
                <td>
                  <button className="linklike" onClick={() => onSelectPaper?.(n.id)}>
                    {n.title}
                  </button>
                  <div className="muted small">{n.id}{n.isolated ? " · 孤立节点" : ""}</div>
                </td>
                <td className="num">{n.year ?? "—"}</td>
                <td className="num strong">{n.in_degree}</td>
                <td className="num">{n.out_degree}</td>
                <td className="num mono">{n.pagerank.toFixed(5)}</td>
                <td className="wrap">{n.topics.join("、")}</td>
              </tr>
            ))}
            {rows.length === 0 && (
              <tr><td colSpan={7} className="empty">没有符合条件的论文。</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {graph.meta?.excluded_edges?.length > 0 && (
        <div className="excluded-box">
          <h3>被排除的异常边（{graph.meta.excluded_edges.length}）</h3>
          <p className="hint">
            这些边因异常（自引用 / 引用未来年份论文）未纳入本次计算；可在筛选面板中选择纳入。
          </p>
          <ul>
            {graph.meta.excluded_edges.map((e) => (
              <li key={`${e.source_paper_id}-${e.target_paper_id}`}>
                {e.source_paper_id} → {e.target_paper_id} · {e.anomalies.join("、")} · 出现 {e.occurrence_count} 次
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
