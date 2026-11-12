import React, { useEffect, useMemo, useState } from "react";
import GraphView from "./GraphView.jsx";
import FilterPanel from "./FilterPanel.jsx";
import PendingPanel from "./PendingPanel.jsx";
import RankingTable from "./RankingTable.jsx";
import TopicMatrix from "./TopicMatrix.jsx";
import EdgeDrawer from "./EdgeDrawer.jsx";
import SnapshotsPanel from "./SnapshotsPanel.jsx";
import ImportPanel from "./ImportPanel.jsx";
import AuthorView from "./AuthorView.jsx";
import { api } from "./api.js";

const DEFAULT_FILTERS = {
  year_min: null,
  year_max: null,
  topics: [],
  authors: [],
  include_anomalies: [],
  exclude_anomalies: [],
  alpha: 0.85,
  tol: 1e-8,
  max_iter: 200,
};

export default function App() {
  const [filters, setFilters] = useState(DEFAULT_FILTERS);
  const [graph, setGraph] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [pending, setPending] = useState({ pending: [], count: 0 });
  const [taxonomy, setTaxonomy] = useState({ years: [], authors: [], topics: [] });
  const [health, setHealth] = useState(null);
  const [selection, setSelection] = useState(null); // {edge} for drawer
  const [tab, setTab] = useState("graph");
  const [snapshots, setSnapshots] = useState([]);
  const [toast, setToast] = useState("");

  const notify = (message) => {
    setToast(message);
    window.clearTimeout(notify._t);
    notify._t = window.setTimeout(() => setToast(""), 3200);
  };

  const refreshBase = async () => {
    const [h, t, p, s] = await Promise.all([
      api.health(),
      api.taxonomy(),
      api.pending(),
      api.listSnapshots(),
    ]);
    setHealth(h);
    setTaxonomy(t);
    setPending(p);
    setSnapshots(s.snapshots);
  };

  const runGraph = async (nextFilters = filters) => {
    setLoading(true);
    setError("");
    try {
      const result = await api.graph(nextFilters);
      setGraph(result);
    } catch (err) {
      setError(err.message || String(err));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refreshBase().catch((err) => setError(err.message));
    runGraph(DEFAULT_FILTERS);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const onImport = async (kind, file) => {
    setLoading(true);
    setError("");
    try {
      const res = await api.importFile(kind, file);
      await refreshBase();
      await runGraph();
      notify(
        kind === "papers"
          ? `论文导入完成：新增 ${res.stats.papers_added}，更新 ${res.stats.papers_updated}`
          : `参考文献导入完成：新增 ${res.stats.references_added}，DOI 精确匹配 ${res.stats.doi_matched}，待确认 ${res.stats.pending}；重建 ${res.rebuild.edges} 条边`
      );
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const onSample = async () => {
    setLoading(true);
    setError("");
    try {
      const res = await api.importSample();
      await refreshBase();
      await runGraph();
      notify(`样例已载入：${res.rebuild.edges} 条边，${res.references.pending} 条待确认`);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const onReset = async () => {
    if (!window.confirm("清空所有论文、引用记录、边与快照？此操作不可撤销。")) return;
    setLoading(true);
    try {
      await api.reset();
      await refreshBase();
      await runGraph();
      notify("已清空数据");
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const onApplyFilters = async (next) => {
    setFilters(next);
    await runGraph(next);
  };

  const onLink = async (refId, targetId) => {
    try {
      const res = await api.link(refId, targetId);
      await refreshBase();
      await runGraph();
      notify(`已建立人工关联，当前 ${res.rebuild.edges} 条边`);
    } catch (err) {
      setError(err.message);
    }
  };

  const onUnlink = async (refId) => {
    try {
      const res = await api.unlink(refId);
      await refreshBase();
      await runGraph();
      notify(`已撤销人工关联，当前 ${res.rebuild.edges} 条边`);
    } catch (err) {
      setError(err.message);
    }
  };

  const onSaveSnapshot = async (name) => {
    try {
      await api.saveSnapshot(name, filters);
      setSnapshots((await api.listSnapshots()).snapshots);
      notify(`快照「${name}」已保存，包含筛选条件与排名结果`);
    } catch (err) {
      setError(err.message);
    }
  };

  const onLoadSnapshot = async (snapshot) => {
    const detail = await api.getSnapshot(snapshot.id);
    if (detail.result) {
      setFilters(detail.filters);
      setGraph(detail.result);
      notify(`已载入快照「${snapshot.name}」（保存时的筛选与排名）`);
    }
  };

  const onDeleteSnapshot = async (id) => {
    await api.deleteSnapshot(id);
    setSnapshots((await api.listSnapshots()).snapshots);
  };

  const onRebuild = async () => {
    try {
      const res = await api.rebuild();
      await refreshBase();
      await runGraph();
      notify(`已重新计算：${res.rebuild.edges} 条边，${res.rebuild.pending_references} 条待确认`);
    } catch (err) {
      setError(err.message);
    }
  };

  const stats = useMemo(() => {
    if (!graph) return null;
    const { ranking, meta } = graph;
    return {
      nodes: ranking.nodes.length,
      edges: ranking.edges.length,
      isolated: ranking.nodes.filter((n) => n.isolated).length,
      pending: pending.count,
      anomalyExcluded: meta.anomaly_excluded,
      converged: ranking.converged,
    };
  }, [graph, pending]);

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">
            ⟶
          </span>
          <div>
            <h1>引文图谱工作台</h1>
            <p className="subtitle">论文 ← 参考文献 · 方向固定为「引用者 → 被引用者」</p>
          </div>
        </div>
        <div className="topbar-stats">
          {health && (
            <>
              <Stat label="论文" value={health.papers} />
              <Stat label="边" value={health.edges} />
              <Stat label="待确认" value={health.pending} accent={health.pending > 0} />
            </>
          )}
        </div>
      </header>

      {error && (
        <div className="banner error" role="alert">
          {error}
          <button className="ghost" onClick={() => setError("")}>
            关闭
          </button>
        </div>
      )}
      {loading && <div className="banner info">正在计算…</div>}

      <div className="layout">
        <aside className="sidebar">
          <ImportPanel
            onImport={onImport}
            onSample={onSample}
            onReset={onReset}
            onRebuild={onRebuild}
            health={health}
          />
          <FilterPanel
            filters={filters}
            taxonomy={taxonomy}
            onApply={onApplyFilters}
            onSaveSnapshot={onSaveSnapshot}
            loading={loading}
          />
          <SnapshotsPanel
            snapshots={snapshots}
            onLoad={onLoadSnapshot}
            onDelete={onDeleteSnapshot}
          />
        </aside>

        <main className="main">
          <nav className="tabs" role="tablist">
            {[
              ["graph", "图谱"],
              ["ranking", "排名与详情"],
              ["matrix", "年度 × 主题"],
              ["authors", "作者视角"],
              ["pending", `待确认${pending.count ? ` (${pending.count})` : ""}`],
            ].map(([key, label]) => (
              <button
                key={key}
                role="tab"
                aria-selected={tab === key}
                className={tab === key ? "tab active" : "tab"}
                onClick={() => {
                  setTab(key);
                  setSelection(null);
                }}
              >
                {label}
              </button>
            ))}
          </nav>

          {graph && stats && (
            <div className="statrow" aria-label="当前视图统计">
              <Stat label="节点" value={stats.nodes} />
              <Stat label="边（已纳入）" value={stats.edges} />
              <Stat label="孤立节点" value={stats.isolated} />
              <Stat label="异常边（已排除）" value={stats.anomalyExcluded} />
              <Stat
                label="PageRank"
                value={stats.converged ? "已收敛" : "未收敛"}
                accent={!stats.converged}
              />
            </div>
          )}

          {tab === "graph" && (
            <GraphView
              graph={graph}
              onSelectEdge={async (source, target) => {
                const detail = await api.edge(source, target);
                setSelection(detail);
              }}
              onCloseSelection={() => setSelection(null)}
            />
          )}

          {tab === "ranking" && (
            <div className="two-col">
              <RankingTable graph={graph} />
              <div className="panel-card">
                <h2>选中边的明细</h2>
                <EdgeDrawer
                  selection={selection}
                  onClose={() => setSelection(null)}
                  onUnlink={onUnlink}
                  onOpenEdge={async (source, target) => {
                    setSelection(await api.edge(source, target));
                  }}
                />
              </div>
            </div>
          )}

          {tab === "matrix" && <TopicMatrix graph={graph} />}

          {tab === "authors" && <AuthorView graph={graph} />}

          {tab === "pending" && (
            <PendingPanel
              pending={pending.pending}
              onLink={onLink}
              onUnlink={onUnlink}
              onChanged={async () => {
                await refreshBase();
                await runGraph();
              }}
            />
          )}
        </main>
      </div>

      {tab !== "ranking" && selection && (
        <EdgeDrawer
          side
          selection={selection}
          onClose={() => setSelection(null)}
          onUnlink={onUnlink}
          onOpenEdge={async (source, target) => {
            setSelection(await api.edge(source, target));
          }}
        />
      )}

      {toast && <div className="toast">{toast}</div>}
    </div>
  );
}

function Stat({ label, value, accent = false }) {
  return (
    <div className={accent ? "stat accent" : "stat"}>
      <span className="stat-value">{value}</span>
      <span className="stat-label">{label}</span>
    </div>
  );
}
