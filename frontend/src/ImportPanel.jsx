import React, { useState } from "react";
import { api } from "./api.js";

export default function ImportPanel({ onImport, onSample, onReset, onRebuild, health }) {
  const [papersFile, setPapersFile] = useState(null);
  const [refsFile, setRefsFile] = useState(null);

  return (
    <section className="panel-card">
      <div className="panel-head">
        <h2>数据导入</h2>
      </div>
      <p className="hint">
        论文 CSV（id, title, year, authors, doi, topics）；参考文献 JSONL 每行一条，
        用 source_paper_id 指向引用者。DOI 去前缀与空白、统一小写后精确匹配。
      </p>

      <label className="file-input">
        <span>论文 CSV</span>
        <input
          type="file"
          accept=".csv,text/csv"
          onChange={(e) => setPapersFile(e.target.files?.[0] ?? null)}
        />
      </label>
      <button
        className="primary"
        disabled={!papersFile}
        onClick={async () => {
          if (papersFile) {
            await onImport("papers", papersFile);
            setPapersFile(null);
          }
        }}
      >
        导入论文
      </button>

      <label className="file-input">
        <span>参考文献 JSONL</span>
        <input
          type="file"
          accept=".jsonl,.json,application/x-ndjson"
          onChange={(e) => setRefsFile(e.target.files?.[0] ?? null)}
        />
      </label>
      <button
        className="primary"
        disabled={!refsFile || !(health?.papers > 0)}
        onClick={async () => {
          if (refsFile) {
            await onImport("references", refsFile);
            setRefsFile(null);
          }
        }}
      >
        导入参考文献
      </button>
      {!(health?.papers > 0) && <p className="hint">请先导入论文 CSV。</p>}

      <div className="button-row">
        <button className="secondary" onClick={onSample}>
          载入样例
        </button>
        <button className="secondary" onClick={onRebuild}>
          重算关系
        </button>
        <button className="danger-ghost" onClick={onReset}>
          清空
        </button>
      </div>
      {health && (
        <dl className="mini-dl">
          <dt>论文</dt><dd>{health.papers}</dd>
          <dt>引用记录</dt><dd>{health.references}</dd>
          <dt>边</dt><dd>{health.edges}</dd>
          <dt>待确认</dt><dd>{health.pending}</dd>
        </dl>
      )}
    </section>
  );
}
