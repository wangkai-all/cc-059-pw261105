import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  forceCenter,
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
  forceX,
  forceY,
} from "d3-force";

/**
 * "in-degree" (被引用数) is the magnitude the node color encodes. Blue ramp
 * steps come from the reference sequential palette; text stays in ink tokens.
 */
const RAMP = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95"];

function rampColor(value, max) {
  if (max <= 0) return RAMP[0];
  const ratio = Math.max(0, Math.min(1, value / max));
  const index = Math.min(RAMP.length - 1, Math.round(ratio * (RAMP.length - 1)));
  return RAMP[index];
}

const WIDTH = 980;
const HEIGHT = 620;

export default function GraphView({ graph, onSelectEdge, onCloseSelection }) {
  const svgRef = useRef(null);
  const [layout, setLayout] = useState({ nodes: [], edges: [] });
  const [hover, setHover] = useState(null);
  const [focusNode, setFocusNode] = useState(null);
  const [showLabels, setShowLabels] = useState(false);

  const data = useMemo(() => {
    if (!graph) return { nodes: [], edges: [] };
    return { nodes: graph.ranking.nodes, edges: graph.ranking.edges };
  }, [graph]);

  useEffect(() => {
    if (!data.nodes.length) {
      setLayout({ nodes: [], edges: [] });
      return;
    }
    const nodes = data.nodes.map((n) => ({ ...n }));
    // d3-force rebinds `source`/`target` to node objects during the simulation,
    // so keep the original ids alongside them for rendering.
    const links = data.edges.map((e, i) => ({
      ...e,
      id: `${e.source}->${e.target}-${i}`,
      sourceId: e.source,
      targetId: e.target,
    }));

    // Seed deterministically so the layout is stable across filter re-renders.
    const goldenAngle = Math.PI * (3 - Math.sqrt(5));
    nodes.forEach((node, index) => {
      const radius = 40 + 26 * Math.sqrt(index);
      const angle = index * goldenAngle;
      node.x = WIDTH / 2 + radius * Math.cos(angle);
      node.y = HEIGHT / 2 + radius * Math.sin(angle);
    });

    const degreeById = new Map(nodes.map((n) => [n.id, n.in_degree + n.out_degree]));
    const sim = forceSimulation(nodes)
      .force(
        "link",
        forceLink(links)
          .id((d) => d.id)
          .distance((l) => 92 + 8 * (l.occurrence_count || 1))
          .strength(0.5)
      )
      .force("charge", forceManyBody().strength((d) => -340 - 30 * (degreeById.get(d.id) ?? 0)))
      .force("collide", forceCollide().radius((d) => radiusFor(d) + 14).iterations(2))
      .force("center", forceCenter(WIDTH / 2, HEIGHT / 2))
      .force("x", forceX(WIDTH / 2).strength(0.04))
      .force("y", forceY(HEIGHT / 2).strength(0.04))
      .stop();

    const iterations = Math.min(900, Math.max(260, nodes.length * 55));
    for (let i = 0; i < iterations; i += 1) sim.tick();
    for (const node of nodes) {
      node.x = Math.max(40, Math.min(WIDTH - 40, node.x ?? WIDTH / 2));
      node.y = Math.max(40, Math.min(HEIGHT - 40, node.y ?? HEIGHT / 2));
    }
    setLayout({ nodes, edges: links });
    return () => sim.stop();
  }, [data]);

  const maxIn = useMemo(
    () => Math.max(1, ...data.nodes.map((n) => n.in_degree)),
    [data.nodes]
  );

  const neighbors = useMemo(() => {
    if (!focusNode) return null;
    const set = new Set([focusNode]);
    for (const e of data.edges) {
      if (e.source === focusNode) set.add(e.target);
      if (e.target === focusNode) set.add(e.source);
    }
    return set;
  }, [focusNode, data.edges]);

  const nodeById = useMemo(
    () => Object.fromEntries(layout.nodes.map((n) => [n.id, n])),
    [layout.nodes]
  );

  const edgeHover = (event, edge, entering) => {
    if (entering) {
      const [mx, my] = pointer(event);
      setHover({ kind: "edge", edge, x: mx, y: my });
    } else {
      setHover(null);
    }
  };

  const pointer = (event) => {
    const rect = svgRef.current.getBoundingClientRect();
    return [event.clientX - rect.left, event.clientY - rect.top];
  };

  if (!graph) {
    return <section className="panel-card wide"><p className="empty">尚未加载图谱。</p></section>;
  }

  if (data.nodes.length === 0) {
    return (
      <section className="panel-card wide">
        <h2>图谱</h2>
        <p className="empty">
          当前筛选下没有论文。调整年份 / 主题 / 作者筛选，或先导入数据、确认待确认引用。
        </p>
      </section>
    );
  }

  return (
    <section className="panel-card wide graph-card">
      <div className="panel-head row">
        <div>
          <h2>引文图谱</h2>
          <p className="hint">
            箭头由引用者指向被引用者；节点颜色与大小随入度（被引用次数）加深。点击边查看原始记录。
          </p>
        </div>
        <div className="graph-controls">
          <label className="toggle">
            <input
              type="checkbox"
              checked={showLabels}
              onChange={(e) => setShowLabels(e.target.checked)}
            />
            显示全部标题
          </label>
          {focusNode && (
            <button className="ghost small" onClick={() => setFocusNode(null)}>
              取消聚焦
            </button>
          )}
        </div>
      </div>

      <div className="graph-legend">
        <span className="legend-label">入度</span>
        <span className="ramp" aria-hidden="true" />
        <span className="muted">0</span>
        <span className="muted">→ {maxIn}</span>
        <span className="legend-sep" />
        <span className="legend-anomaly">
          <span className="dash" aria-hidden="true" /> 异常边（已纳入时可见）
        </span>
      </div>

      <svg
        ref={svgRef}
        className="graph-svg"
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        role="img"
        aria-label={`引文图谱，${data.nodes.length} 个节点，${data.edges.length} 条边`}
      >
        <defs>
          <marker
            id="arrow"
            viewBox="0 0 10 10"
            refX="9"
            refY="5"
            markerWidth="7"
            markerHeight="7"
            orient="auto-start-reverse"
          >
            <path d="M 0 0 L 10 5 L 0 10 z" fill="var(--text-secondary)" />
          </marker>
          <marker
            id="arrow-anomaly"
            viewBox="0 0 10 10"
            refX="9"
            refY="5"
            markerWidth="7"
            markerHeight="7"
            orient="auto-start-reverse"
          >
            <path d="M 0 0 L 10 5 L 0 10 z" fill="var(--status-warning)" />
          </marker>
        </defs>

        {layout.edges.map((edge) => {
          const source = nodeById[edge.sourceId];
          const target = nodeById[edge.targetId];
          if (!source || !target) return null;
          const isAnomaly = edge.anomalies?.length > 0;
          const dim = focusNode && !(neighbors.has(edge.sourceId) && neighbors.has(edge.targetId));
          const stroke = isAnomaly ? "var(--status-warning)" : "var(--text-secondary)";
          const marker = isAnomaly ? "arrow-anomaly" : "arrow";
          if (edge.sourceId === edge.targetId) {
            const r = radiusFor(source);
            return (
              <g key={edge.id} className={dim ? "edge dim" : "edge"}>
                <path
                  d={`M ${source.x - r} ${source.y} a ${r} ${r} 0 1 1 ${r * 2} 0`}
                  fill="none"
                  stroke={stroke}
                  strokeWidth={Math.min(4, 1.2 + edge.occurrence_count * 0.6)}
                  markerEnd={`url(#${marker})`}
                  onClick={() => onSelectEdge(edge.sourceId, edge.targetId)}
                  onPointerMove={(e) => edgeHover(e, edge, true)}
                  onPointerLeave={(e) => edgeHover(e, edge, false)}
                />
              </g>
            );
          }
          const dx = target.x - source.x;
          const dy = target.y - source.y;
          const dist = Math.sqrt(dx * dx + dy * dy) || 1;
          const sx = source.x + (dx / dist) * radiusFor(source);
          const sy = source.y + (dy / dist) * radiusFor(source);
          const tx = target.x - (dx / dist) * (radiusFor(target) + 6);
          const ty = target.y - (dy / dist) * (radiusFor(target) + 6);
          return (
            <g key={edge.id} className={dim ? "edge dim" : "edge"}>
              <line
                x1={sx}
                y1={sy}
                x2={tx}
                y2={ty}
                stroke={stroke}
                strokeWidth={Math.min(4, 1.2 + edge.occurrence_count * 0.6)}
                markerEnd={`url(#${marker})`}
                onClick={() => onSelectEdge(edge.sourceId, edge.targetId)}
                onPointerMove={(e) => edgeHover(e, edge, true)}
                onPointerLeave={(e) => edgeHover(e, edge, false)}
                className="edge-hit"
              />
              {edge.occurrence_count > 1 && (
                <text x={(sx + tx) / 2} y={(sy + ty) / 2 - 5} className="edge-count">
                  ×{edge.occurrence_count}
                </text>
              )}
            </g>
          );
        })}

        {layout.nodes.map((node) => {
          const r = radiusFor(node);
          const dim = focusNode && !neighbors.has(node.id);
          const fill = rampColor(node.in_degree, maxIn);
          const label = node.title?.length > 48 ? `${node.title.slice(0, 46)}…` : node.title;
          const showLabel = showLabels || (focusNode && neighbors.has(node.id));
          return (
            <g
              key={node.id}
              transform={`translate(${node.x},${node.y})`}
              className={dim ? "node dim" : node.isolated ? "node isolated" : "node"}
              onClick={() => setFocusNode((cur) => (cur === node.id ? null : node.id))}
              onPointerMove={(e) => {
                const [x, y] = pointer(e);
                setHover({ kind: "node", node, x, y });
              }}
              onPointerLeave={() => setHover(null)}
              role="button"
              aria-label={`${node.title}，${node.year ?? "年份未知"}，入度 ${node.in_degree}，PageRank ${node.pagerank.toFixed(5)}`}
            >
              <circle r={r} fill={fill} stroke="var(--surface-1)" strokeWidth={2} />
              {node.isolated && <circle r={r + 4} fill="none" stroke="var(--text-muted)" strokeWidth={1} strokeDasharray="3 3" />}
              {(showLabel || (maxIn > 0 && node.in_degree >= maxIn * 0.9)) && (
                <text
                  y={-r - 7}
                  textAnchor="middle"
                  className={node.in_degree >= maxIn * 0.9 ? "node-label" : "node-label small"}
                >
                  {label}
                </text>
              )}
            </g>
          );
        })}
      </svg>

      {hover && (
        <div
          className="tooltip"
          style={{
            left: flipX(hover.x, svgRef.current),
            top: flipY(hover.y, svgRef.current),
          }}
        >
          {hover.kind === "node" ? (
            <>
              <div className="tooltip-title">{hover.node.title}</div>
              <div className="tooltip-sub">
                {hover.node.id} · {hover.node.year ?? "年份未知"}
              </div>
              <dl>
                <dt>入度（被引用）</dt><dd>{hover.node.in_degree}</dd>
                <dt>出度（引用他人）</dt><dd>{hover.node.out_degree}</dd>
                <dt>PageRank</dt><dd>{hover.node.pagerank.toFixed(5)}</dd>
                <dt>主题</dt><dd>{hover.node.topics.join("、") || "—"}</dd>
              </dl>
            </>
          ) : (
            <>
              <div className="tooltip-title">
                {hover.edge.sourceId} → {hover.edge.targetId}
              </div>
              <div className="tooltip-sub">
                出现 {hover.edge.occurrence_count} 次
                {hover.edge.anomalies?.length ? " · 异常边" : ""}
              </div>
              <div className="tooltip-hint">点击查看原始参考文献</div>
            </>
          )}
        </div>
      )}
    </section>
  );
}

function radiusFor(node) {
  const inDegree = node.in_degree ?? 0;
  return 11 + Math.min(16, Math.sqrt(inDegree) * 5.5);
}

/** Keep the tooltip inside the graph card: flip left/up when it would overflow. */
function flipX(x, svg) {
  const width = svg?.clientWidth ?? WIDTH;
  const left = x + 14;
  return left + 290 > width ? Math.max(8, x - 304) : left;
}

function flipY(y, svg) {
  const height = svg?.clientHeight ?? HEIGHT;
  const top = y + 14;
  return top + 150 > height ? Math.max(8, y - 164) : top;
}
