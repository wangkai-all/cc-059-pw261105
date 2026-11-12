import React, { useState } from "react";

/**
 * Year × topic citation counts. A heatmap: sequential blue ramp, one cell per
 * (year, topic) pair, values printed in every cell because the grid is small
 * and exact counts are the point. Hover shows the same number plus context.
 */
const RAMP = ["#cde2fb", "#b7d3f6", "#9ec5f4", "#86b6ef", "#6da7ec", "#5598e7", "#3987e5", "#2a78d6", "#256abf", "#184f95"];

function cellColor(value, max) {
  if (value === 0 || max === 0) return "var(--surface-2)";
  const idx = Math.max(1, Math.round((value / max) * (RAMP.length - 1)));
  return RAMP[idx];
}

function textColor(value, max) {
  if (value === 0 || max === 0) return "var(--text-muted)";
  const idx = Math.round((value / max) * (RAMP.length - 1));
  return idx >= 5 ? "#f7fbff" : "var(--text-primary)";
}

export default function TopicMatrix({ graph }) {
  const [hover, setHover] = useState(null);
  const matrix = graph?.matrix;

  if (!matrix) return null;

  const { years, topics, cells, edges, total } = matrix;
  const max = Math.max(0, ...cells.map((c) => c.citations));
  const lookup = new Map(cells.map((c) => [`${c.year}|${c.topic}`, c.citations]));

  if (years.length === 0 || topics.length === 0) {
    return (
      <section className="panel-card wide">
        <h2>年度 × 主题引用</h2>
        <p className="empty">当前筛选下没有可统计的年份或主题。</p>
      </section>
    );
  }

  return (
    <section className="panel-card wide">
      <div className="panel-head row">
        <div>
          <h2>年度 × 主题引用</h2>
          <p className="hint">
            统计每条边的被引用论文所属年份与主题；一篇论文有多个主题时会出现在多个列。
            当前 {edges} 条边，单元格合计 {total}。
          </p>
        </div>
        <div className="graph-legend">
          <span className="legend-label">引用数</span>
          <span className="ramp" aria-hidden="true" />
          <span className="muted">0</span>
          <span className="muted">→ {max}</span>
        </div>
      </div>

      <div className="heatmap-wrap" onPointerLeave={() => setHover(null)}>
        <table className="heatmap">
          <thead>
            <tr>
              <th className="sticky-col">年份</th>
              {topics.map((t) => (
                <th key={t} className="rotated"><span>{t}</span></th>
              ))}
            </tr>
          </thead>
          <tbody>
            {years.map((year) => (
              <tr key={year}>
                <th className="sticky-col year">{year}</th>
                {topics.map((topic) => {
                  const value = lookup.get(`${year}|${topic}`) ?? 0;
                  return (
                    <td
                      key={topic}
                      className="cell"
                      style={{ background: cellColor(value, max), color: textColor(value, max) }}
                      onPointerMove={(e) => {
                        const rect = e.currentTarget.getBoundingClientRect();
                        setHover({
                          year,
                          topic,
                          value,
                          x: rect.left + rect.width / 2,
                          y: rect.top,
                        });
                      }}
                    >
                      {value > 0 ? value : ""}
                    </td>
                  );
                })}
              </tr>
            ))}
            <tr className="totals">
              <th className="sticky-col">合计</th>
              {topics.map((topic) => (
                <td key={topic}>
                  {cells.filter((c) => c.topic === topic).reduce((s, c) => s + c.citations, 0)}
                </td>
              ))}
            </tr>
          </tbody>
        </table>
      </div>

      {hover && (
        <div className="tooltip fixed" style={{ left: hover.x - 90, top: hover.y - 70 }}>
          <div className="tooltip-title">{hover.topic}</div>
          <div className="tooltip-sub">{hover.year} 年发表的论文被引用</div>
          <dl><dt>引用次数</dt><dd>{hover.value}</dd></dl>
        </div>
      )}
    </section>
  );
}
