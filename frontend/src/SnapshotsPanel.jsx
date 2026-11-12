import React from "react";

export default function SnapshotsPanel({ snapshots, onLoad, onDelete }) {
  return (
    <section className="panel-card">
      <div className="panel-head">
        <h2>快照</h2>
        <p className="hint">保存筛选条件与当时的排名结果；载入时两者一起恢复。</p>
      </div>
      {snapshots.length === 0 && <p className="empty small">暂无快照。</p>}
      <ul className="snapshot-list">
        {snapshots.map((s) => (
          <li key={s.id}>
            <div>
              <strong>{s.name}</strong>
              <div className="muted small">
                {formatFilters(s.filters)} · {s.created_at}
              </div>
            </div>
            <div className="snapshot-actions">
              <button className="secondary small" onClick={() => onLoad(s)}>
                载入
              </button>
              <button className="ghost small" onClick={() => onDelete(s.id)}>
                删除
              </button>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

function formatFilters(f) {
  const parts = [];
  if (f.year_min != null || f.year_max != null) {
    parts.push(`年份 ${f.year_min ?? "…"}–${f.year_max ?? "…"}`);
  }
  if (f.topics?.length) parts.push(`主题：${f.topics.join("、")}`);
  if (f.authors?.length) parts.push(`作者：${f.authors.join("、")}`);
  if (f.include_anomalies?.length) parts.push(`纳入异常：${f.include_anomalies.join("、")}`);
  if (f.exclude_anomalies?.length) parts.push(`排除异常：${f.exclude_anomalies.join("、")}`);
  parts.push(`δ=${f.alpha}`);
  return parts.join(" · ");
}
