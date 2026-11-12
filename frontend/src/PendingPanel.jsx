import React, { useState } from "react";

export default function PendingPanel({ pending, onLink, onUnlink, onChanged }) {
  const [search, setSearch] = useState({});

  if (!pending.length) {
    return (
      <section className="panel-card wide">
        <h2>待确认引用</h2>
        <p className="empty">当前没有待确认的引用记录。所有 DOI 精确匹配或已人工关联。</p>
      </section>
    );
  }

  return (
    <section className="panel-card wide">
      <div className="panel-head">
        <h2>待确认引用（{pending.length}）</h2>
        <p className="hint">
          这些记录没有可匹配的 DOI。标题候选仅供人工确认，系统不会自动建立关联；
          无法匹配的记录会一直保留在此列表，原始文献不会丢失。
        </p>
      </div>
      <div className="pending-list">
        {pending.map((item) => (
          <article key={item.id} className="pending-card">
            <header>
              <div>
                <strong>{item.title || "（无标题）"}</strong>
                <span className="muted">
                  {item.year ?? "年份未知"} · 引用者 {item.source.id}「{item.source.title}」
                </span>
              </div>
              <span className="badge">第 {item.line_no} 行</span>
            </header>
            {item.doi_norm && <p className="hint">DOI：{item.doi_norm}（未能唯一匹配）</p>}
            {item.raw?.context && <p className="quote">“{item.raw.context}”</p>}

            <div className="candidates">
              <span className="chip-label">标题候选</span>
              {item.candidates.length === 0 && <span className="hint">没有相似标题</span>}
              {item.candidates.map((c) => (
                <div key={c.paper_id} className="candidate-row">
                  <div>
                    <strong>{c.title}</strong>
                    <span className="muted">
                      {c.paper_id} · {c.year ?? "年份未知"} · 评分 {Math.round(c.score)}
                    </span>
                    {c.reasons?.length > 0 && (
                      <ul className="reasons">
                        {c.reasons.map((r) => (
                          <li key={r}>{r}</li>
                        ))}
                      </ul>
                    )}
                  </div>
                  <button className="primary small" onClick={() => onLink(item.id, c.paper_id)}>
                    确认关联
                  </button>
                </div>
              ))}
            </div>

            <div className="manual-search">
              <input
                type="text"
                placeholder="按标题或论文 ID 搜索目标"
                value={search[item.id] ?? ""}
                onChange={(e) => setSearch((s) => ({ ...s, [item.id]: e.target.value }))}
              />
              <ManualSearch
                refId={item.id}
                query={search[item.id] ?? ""}
                onLink={onLink}
              />
            </div>

            {item.raw && (
              <details className="raw-json">
                <summary>原始引用记录</summary>
                <pre>{JSON.stringify(item.raw, null, 2)}</pre>
              </details>
            )}
          </article>
        ))}
      </div>
    </section>
  );
}

function ManualSearch({ refId, query, onLink }) {
  const [results, setResults] = React.useState([]);
  const [loading, setLoading] = React.useState(false);

  const run = async () => {
    setLoading(true);
    try {
      const res = await fetch(
        `/api/references/search?ref_id=${refId}${query ? `&q=${encodeURIComponent(query)}` : ""}`
      ).then((r) => r.json());
      setResults(res.candidates ?? []);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <button className="secondary" onClick={run} disabled={loading}>
        {loading ? "搜索中…" : "搜索"}
      </button>
      {results.length > 0 && (
        <ul className="search-results">
          {results.map((r) => (
            <li key={r.paper_id}>
              <span>
                <strong>{r.title}</strong>
                <span className="muted"> {r.paper_id} · {r.year ?? "年份未知"}</span>
              </span>
              <button className="ghost small" onClick={() => onLink(refId, r.paper_id)}>
                关联
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
