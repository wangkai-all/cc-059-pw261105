import React, { useEffect, useState } from "react";

const ANOMALY_LABELS = {
  self_citation: "自引用（引用自身）",
  future_year: "引用未来年份论文",
};

/**
 * Filter + ranking controls. Every control writes locally; "应用" commits the
 * whole filter object to the server, and the same object is what a snapshot
 * stores alongside the ranking result.
 */
export default function FilterPanel({ filters, taxonomy, onApply, onSaveSnapshot, loading }) {
  const [draft, setDraft] = useState(filters);
  const [snapshotName, setSnapshotName] = useState("");

  useEffect(() => setDraft(filters), [filters]);

  const years = taxonomy.years ?? [];
  const allTopics = taxonomy.topics ?? [];
  const allAuthors = taxonomy.authors ?? [];

  const update = (patch) => setDraft((d) => ({ ...d, ...patch }));

  const toggleList = (key, value) =>
    setDraft((d) => {
      const list = d[key] ?? [];
      const next = list.includes(value) ? list.filter((v) => v !== value) : [...list, value];
      return { ...d, [key]: next };
    });

  const toggleAnomaly = (key, value) =>
    setDraft((d) => {
      const list = d[key] ?? [];
      return { ...d, [key]: list.includes(value) ? list.filter((v) => v !== value) : [...list, value] };
    });

  const anomalyMode = (value) => {
    if (draft.include_anomalies.includes(value)) return "include";
    if (draft.exclude_anomalies.includes(value)) return "exclude";
    return "default";
  };

  const setAnomalyMode = (value, mode) =>
    setDraft((d) => ({
      ...d,
      include_anomalies:
        mode === "include"
          ? Array.from(new Set([...d.include_anomalies, value]))
          : d.include_anomalies.filter((v) => v !== value),
      exclude_anomalies:
        mode === "exclude"
          ? Array.from(new Set([...d.exclude_anomalies, value]))
          : d.exclude_anomalies.filter((v) => v !== value),
    }));

  const clearAll = () =>
    setDraft({
      year_min: null,
      year_max: null,
      topics: [],
      authors: [],
      include_anomalies: [],
      exclude_anomalies: [],
      alpha: 0.85,
      tol: 1e-8,
      max_iter: 200,
    });

  return (
    <section className="panel-card">
      <div className="panel-head">
        <h2>筛选与排名</h2>
      </div>

      <div className="field-grid">
        <label>
          <span>起始年份</span>
          <input
            type="number"
            min={years[0] ?? 0}
            max={years[years.length - 1] ?? 3000}
            value={draft.year_min ?? ""}
            placeholder={years.length ? String(years[0]) : ""}
            onChange={(e) => update({ year_min: e.target.value === "" ? null : Number(e.target.value) })}
          />
        </label>
        <label>
          <span>结束年份</span>
          <input
            type="number"
            min={years[0] ?? 0}
            max={years[years.length - 1] ?? 3000}
            value={draft.year_max ?? ""}
            placeholder={years.length ? String(years[years.length - 1]) : ""}
            onChange={(e) => update({ year_max: e.target.value === "" ? null : Number(e.target.value) })}
          />
        </label>
      </div>
      <p className="hint">年份过滤保留范围内的论文，且边的两端都必须在范围内。</p>

      <div className="chip-group">
        <span className="chip-label">主题</span>
        <div className="chips">
          {allTopics.length === 0 && <span className="hint">暂无主题</span>}
          {allTopics.map((topic) => (
            <button
              key={topic}
              className={draft.topics.includes(topic) ? "chip active" : "chip"}
              onClick={() => toggleList("topics", topic)}
            >
              {topic}
            </button>
          ))}
        </div>
      </div>

      <div className="chip-group">
        <span className="chip-label">作者</span>
        <div className="chips">
          {allAuthors.length === 0 && <span className="hint">暂无作者</span>}
          {allAuthors.map((author) => (
            <button
              key={author}
              className={draft.authors.includes(author) ? "chip active" : "chip"}
              onClick={() => toggleList("authors", author)}
            >
              {author}
            </button>
          ))}
        </div>
      </div>

      <div className="anomaly-group">
        <span className="chip-label">异常边</span>
        {Object.entries(ANOMALY_LABELS).map(([key, label]) => (
          <div key={key} className="anomaly-row">
            <span>{label}</span>
            <div className="segmented" role="radiogroup" aria-label={label}>
              <button
                aria-pressed={anomalyMode(key) === "default"}
                onClick={() => setAnomalyMode(key, "default")}
              >
                默认排除
              </button>
              <button
                aria-pressed={anomalyMode(key) === "include"}
                onClick={() => setAnomalyMode(key, "include")}
              >
                纳入
              </button>
              <button
                aria-pressed={anomalyMode(key) === "exclude"}
                onClick={() => setAnomalyMode(key, "exclude")}
              >
                显式排除
              </button>
            </div>
          </div>
        ))}
      </div>

      <details className="advanced">
        <summary>PageRank 参数</summary>
        <div className="field-grid">
          <label>
            <span>阻尼系数 δ（0–1，不含端点）</span>
            <input
              type="number"
              step="0.01"
              min="0.01"
              max="0.99"
              value={draft.alpha}
              onChange={(e) => update({ alpha: Number(e.target.value) })}
            />
          </label>
          <label>
            <span>收敛阈值</span>
            <input
              type="number"
              step="0.000001"
              min="1e-14"
              value={draft.tol}
              onChange={(e) => update({ tol: Number(e.target.value) })}
            />
          </label>
          <label>
            <span>最大迭代</span>
            <input
              type="number"
              min="10"
              max="2000"
              value={draft.max_iter}
              onChange={(e) => update({ max_iter: Number(e.target.value) })}
            />
          </label>
        </div>
      </details>

      <div className="button-row">
        <button className="primary" disabled={loading} onClick={() => onApply(draft)}>
          应用筛选并重算
        </button>
        <button className="secondary" onClick={clearAll}>
          重置
        </button>
      </div>

      <div className="snapshot-form">
        <label>
          <span>保存为快照</span>
          <input
            type="text"
            value={snapshotName}
            placeholder="例如：2015–2018 · graphs"
            onChange={(e) => setSnapshotName(e.target.value)}
          />
        </label>
        <button
          className="secondary"
          disabled={!snapshotName.trim()}
          onClick={async () => {
            await onSaveSnapshot(snapshotName.trim());
            setSnapshotName("");
          }}
        >
          保存筛选与排名
        </button>
      </div>
    </section>
  );
}
