# 引文图谱工作台

论文与参考文献的引文图谱应用：导入论文 CSV 与参考文献 JSONL，按年份、主题、作者筛选，
查看引用关系、入度/出度、年度 × 主题引用与 PageRank，并保存筛选条件与排名结果的快照。

技术栈：Python + FastAPI + NetworkX + SQLite（后端），React + Vite + d3-force（前端）。

## 目录结构

```
backend/
  app/
    main.py        FastAPI 路由、静态前端服务
    db.py          SQLite 表结构与连接
    importer.py    CSV / JSONL 导入（幂等、DOI 精确匹配、标题候选）
    matching.py    DOI/标题匹配与候选打分
    normalize.py   DOI、标题、列表字段、年份的规范化
    graph.py       边重建、异常检测、筛选、PageRank、年度 × 主题矩阵
  tests/
    test_citations.py
  requirements.txt
frontend/          React 19 + Vite 8 前端（构建产物由 FastAPI 直接提供）
samples/           演示数据：papers.csv 与 references.jsonl
scripts/           Playwright 截图脚本（可选）
```

## 运行

### 1. 后端

```bash
python -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
.venv/bin/python -m uvicorn backend.app.main:app --port 8000
```

默认数据库为 `backend/data/citations.db`（首次启动自动建表）。可用
`CITATION_DB=/path/to/file.db` 指向其他数据库，测试使用临时库。

### 2. 前端

```bash
cd frontend
npm install
npm run dev      # http://localhost:5173，/api 代理到 127.0.0.1:8000
```

或先构建、再由后端统一提供（单端口部署）：

```bash
cd frontend && npm run build
# 之后 http://127.0.0.1:8000/ 直接打开构建后的页面
```

后端在 `frontend/dist` 存在时会挂载 `/assets` 并提供 `GET /`。开发时也可以使用
`npm run preview`，但预览端口不带 `/api` 代理，需访问后端提供的页面。

### 3. 载入样例

页面左侧「载入样例」按钮会重置数据库并导入 `samples/` 下的两个文件。也可以：

```bash
curl -X POST http://127.0.0.1:8000/api/import/sample
```

样例包含：重名标题（P001/P005）、同一 DOI 的多种写法（URL、`DOI:` 前缀、大写、空白）、
重复引用（P001→P002 出现 2 次算 1 条边）、引用环、自引用（P009→P009）、
引用未来年份论文（8 条）以及 2 个无法解析的 DOI（留在待确认列表）。
默认排除异常边：10 个节点、25 条边、9 条异常边被排除、8 条待确认。

## 数据格式

### 论文 CSV

表头至少包含 `id` 与 `title`；其余列按需：

```csv
id,title,year,authors,venue,doi,topics
P001,Graph Neural Networks for Citation Analysis,2018,Alice Chen; Bob Liu,J. Graph Mining,https://doi.org/10.1000/GNN.2018,graphs;machine learning
```

- `id` / `paper_id`：论文唯一标识（重复导入时按 id 更新，不会重复插入）。
- `authors` / `topics`：支持分号、逗号、竖线分隔，或 JSON 数组字符串。
- `doi`：任意写法，导入时规范化。

### 参考文献 JSONL

每行一个 JSON 对象，需能定位「引用者论文」：

```json
{"source_paper_id": "P001", "title": "Topics Modeling of Scholarly Records", "authors": ["Frank Moore", "Grace Kim"], "year": 2017, "doi": "DOI:10.1000/topic-model-2017", "context": "Related work on topic models.", "cited_pages": "pp. 12-14"}
```

- 引用者字段：`source_paper_id` / `source_paper` / `citing_paper_id` / `source_id` / `paper_id`，
  或 `source_doi`、`source_title`。找不到引用者论文的行会被跳过并给出警告。
- 被引用字段：`title`、`doi`、`year`、`authors`；`context` / `cited_pages` 等原样保留。
- 导入幂等：以 `sha256(文件 + 行号 + 原始 JSON)` 去重；同一文件重复导入不会产生重复记录。
- 同一论文引用同一文献可有多条记录：它们合并为一条边，`occurrence_count` 记录出现次数，
  每条记录仍保留自己的文件、行号、`occurrence_index` 与原始 JSON。

## DOI 与标题匹配

DOI 精确匹配（不做模糊匹配）：

1. 去掉 `https://doi.org/`、`http://dx.doi.org/`、`doi:`、`doi ` 等前缀（可叠加）；
2. 去掉所有空白（含零宽字符）；
3. 统一小写。

规范化后与论文的 `doi_norm` 精确比较。唯一命中 → 自动关联（`match_type=doi`）；
同一 DOI 对应多篇论文 → 不自动关联，进入待确认并标注原因；无 DOI 或未命中 →
按标题生成候选（`difflib` 相似度 + 词元 Jaccard + 年份/作者加权，阈值 0.55），
**只作为候选展示，必须由用户确认**。重名标题会同时给出多个候选及打分理由。

撤销人工关联后，该记录回到待确认列表、重新生成候选，原始 JSON、文件与行号均保留；
关系（边、度数、PageRank）随即重算。DOI 自动匹配不能撤销（由数据决定，返回 409）。

## 图谱与排名

- 方向固定：**引用者 → 被引用者**；入度 = 被引用次数，出度 = 引用他人次数。
- 一个 (引用者, 被引用者) 对只产生一条边。
- 异常边：`self_citation`（自引用）与 `future_year`（被引用论文年份晚于引用者）。
  默认**排除**；可按类型「纳入」或「显式排除」，两者互斥（同类型同时纳入和排除返回 400）。
- 年份筛选：保留年份在范围内的论文，且只保留两端都在范围内的边；无年份的论文在设定
  年份范围时排除。主题/作者筛选为大小写不敏感的 OR 匹配。
- 筛选后重新构图并重算 PageRank；被排除的异常边会在「排名与详情」中列出明细。

### PageRank

手写幂迭代，显式记录收敛状态：

- 阻尼系数 `δ` 严格满足 `0 < δ < 1`（默认 0.85），越界返回 400。
- 悬挂节点（无出边）的概率质量**均分给全部节点**。
- 收敛阈值 `tol`（默认 `1e-8`，允许 `1e-14`–`0.1`），最大迭代 `max_iter`（默认 200，允许 10–2000）。
- 返回 `converged`、`iterations`、`error`、`threshold`、`alpha`、`max_iter`；未收敛时界面显示
  「未收敛（达到最大迭代）」。
- 空图返回 `empty: true` 与 `converged: true`；孤立节点保留在图中并参与排名。

### 年度 × 主题

每条边的引用计入**被引用论文**的年份与主题；多主题论文会出现在多个主题列，
因此单元格合计可能大于边数，表格同时给出边数与合计。

## 快照

保存快照时把当前筛选条件与完整结果（排名、矩阵、排除边、收敛信息）一起写入 SQLite；
载入快照直接恢复当时的筛选与排名，不重新计算。可删除快照。

## 界面视图

- **图谱**：力导向静态布局；节点大小/颜色随入度变化，箭头表示引用方向；可聚焦某篇论文、
  显示全部标题、悬停查看入度/出度/PageRank，点击边（或异常边）打开原始参考文献抽屉。
- **排名与详情**：按 PageRank / 入度 / 出度 / 年份排序，支持标题、作者、主题过滤；
  显示收敛状态、迭代次数、误差与阈值，并列出被排除的异常边。
- **年度 × 主题**：热力图，每个单元格为「该年份、该主题的论文被引用次数」，带合计行。
- **作者视角**：按作者汇总其论文收到的引用（入度合计），点击作者查看论文明细。
- **待确认**：候选打分与理由、确认关联、手动搜索目标论文、查看原始 JSON。

## API 摘要

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/health` | 论文 / 引用记录 / 待确认 / 边计数 |
| POST | `/api/import/papers` | 上传论文 CSV（multipart，字段名 `file`） |
| POST | `/api/import/references` | 上传引用 JSONL，导入后重建边 |
| POST | `/api/import/sample` | 重置并导入 `samples/` 样例 |
| POST | `/api/reset` | 清空数据（含快照） |
| POST | `/api/edges/rebuild` | 从已关联记录重建全部边 |
| GET | `/api/papers?q=` | 论文列表 / 搜索 |
| GET | `/api/taxonomy` | 年份、作者、主题、期刊清单 |
| GET | `/api/references/pending` | 待确认记录与候选 |
| GET | `/api/references/search?ref_id=&q=` | 人工检索候选论文 |
| POST | `/api/references/{id}/link` | 人工关联，body `{"target_paper_id": "P003"}` |
| POST | `/api/references/{id}/unlink` | 撤销人工关联（仅 `manual`） |
| POST | `/api/graph` | 传入筛选条件，返回元信息、排名、矩阵 |
| POST | `/api/graph/edges` | 仅返回本次纳入/排除的边 |
| GET | `/api/edges/{source}/{target}` | 边的原始参考文献与关联记录 |
| POST/GET | `/api/snapshots` | 保存 / 列出快照 |
| GET/DELETE | `/api/snapshots/{id}` | 读取 / 删除快照 |

筛选请求体字段：`year_min`、`year_max`、`topics`、`authors`、
`include_anomalies`、`exclude_anomalies`、`alpha`、`tol`、`max_iter`。

## 测试

```bash
.venv/bin/python -m pytest backend/tests -q
```

覆盖 DOI 规范化与变体合并、重名标题候选、导入幂等、DOI 歧义不自动关联、
重复引用的一次性边与出现位置、人工关联/撤销后重算、异常边默认排除与纳入、
年份筛选双端规则、PageRank 收敛与悬挂节点均分（对照 NetworkX `google_matrix`
平稳分布）、空图与孤立节点、HTTP 往返与快照恢复。

## 设计说明

- **SQLite 为唯一事实来源**：边不入用户写入，而是由已关联的引用记录推导；撤销关联后
  边自然消失，原始引用记录不受影响。
- **幂等导入**：重复上传同一文件不会造重复数据；论文按 id upsert。
- **不自动做模糊匹配**：标题相似度只用于排序候选，最终关联由用户确认，避免错误连线。
- **滚动重编号**：每次重建边时，`occurrence_index` 按（文件, 行号）重新编号，
  保证「第 N 次出现」在关联变化后仍然稳定。
- **排名与筛选分离**：筛选决定图的范围，PageRank 只在该范围上计算；快照同时保存二者。
- **前端无外部依赖**：d3-force 仅用于一次性静态布局（预迭代后渲染），图表配色为
  单色相蓝色顺序色阶，深色模式使用单独选定的色阶；中文字体自托管（Noto Sans SC）。
