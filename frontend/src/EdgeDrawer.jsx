import React from "react";

const ANOMALY_LABELS = {
  self_citation: "自引用",
  future_year: "引用未来年份论文",
};

export default function EdgeDrawer({ selection, onClose, onUnlink, onOpenEdge, side = false }) {
  if (!selection) {
    return (
      <p className="empty small">
        点击图中的一条边或一条被排除的异常边，这里会显示原始参考文献与关联记录。
      </p>
    );
  }

  const { edge, references } = selection;

  return (
    <aside className={side ? "drawer side" : "drawer"} aria-label="边明细">
      <header>
        <div>
          <h2>
            {edge.source_paper_id} → {edge.target_paper_id}
          </h2>
          <p className="muted">
            {edge.source_paper?.title} → {edge.target_paper?.title}
          </p>
        </div>
        <button className="ghost" onClick={onClose} aria-label="关闭">
          ✕
        </button>
      </header>

      <dl className="edge-meta">
        <dt>方向</dt><dd>引用者 → 被引用者</dd>
        <dt>出现次数</dt><dd>{edge.occurrence_count}</dd>
        <dt>异常</dt>
        <dd>
          {edge.anomalies?.length
            ? edge.anomalies.map((a) => ANOMALY_LABELS[a] ?? a).join("、")
            : "无"}
        </dd>
        <dt>被引用论文</dt>
        <dd>
          {edge.target_paper?.year ?? "年份未知"} · {(edge.target_paper?.topics ?? []).join("、")}
        </dd>
        <dt>引用者论文</dt>
        <dd>
          {edge.source_paper?.year ?? "年份未知"} · {(edge.source_paper?.topics ?? []).join("、")}
        </dd>
      </dl>

      <h3>关联记录（{references.length}）</h3>
      <p className="hint">
        同一对论文的多次引用只计一条边，但每次出现的原始位置都保留如下。
      </p>
      <ol className="reference-list">
        {references.map((ref) => (
          <li key={ref.id}>
            <div className="ref-head">
              <span className="badge">第 {ref.occurrence_index} 次出现</span>
              <span className="muted">
                {ref.file_name} · 第 {ref.line_no} 行
              </span>
              <span className="badge match">{ref.match_type === "doi" ? "DOI 精确匹配" : "人工关联"}</span>
            </div>
            <div className="ref-title">{ref.title ?? "（无标题）"}</div>
            <dl className="ref-meta">
              <dt>原始 DOI</dt><dd>{ref.doi_raw ?? "—"}</dd>
              <dt>规范化 DOI</dt><dd>{ref.doi_norm ?? "—"}</dd>
              <dt>年份</dt><dd>{ref.year ?? "—"}</dd>
              <dt>作者</dt><dd>{ref.authors.join("；") || "—"}</dd>
            </dl>
            {ref.raw?.context && <p className="quote">“{ref.raw.context}”</p>}
            {ref.raw?.cited_pages && <p className="muted small">引用位置：{ref.raw.cited_pages}</p>}
            {ref.match_type === "manual" && (
              <button className="danger-ghost small" onClick={() => onUnlink(ref.id)}>
                撤销人工关联
              </button>
            )}
            <details>
              <summary>原始 JSON</summary>
              <pre>{JSON.stringify(ref.raw, null, 2)}</pre>
            </details>
          </li>
        ))}
      </ol>

      {edge.source_paper_id === edge.target_paper_id && (
        <p className="hint">这是一条自引用边，仅在「纳入自引用」时参与计算。</p>
      )}
    </aside>
  );
}
