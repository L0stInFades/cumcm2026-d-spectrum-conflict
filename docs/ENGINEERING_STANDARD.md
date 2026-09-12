# Forge 工程规范 v1.0

本规范定义本仓库（CUMCM 2026 D 题：时频冲突检测与消解）从数据接入到论文发布的全部工程约束。它按互联网行业生产系统的标准编写：唯一计算面、幂等阶段、契约、门禁、清单、可观测、可审计、可复现。规范中的"必须 / 禁止"为硬约束，"应当"为默认做法，偏离需在 ADR 中记录理由。

## 0. 目标

1. 论文中的每一个数字、表格、图形都能追溯到同一次云端运行（run）的某个阶段（stage）产物及其 SHA-256。
2. 任何人拿到仓库与 Modal 账号，可在不修改代码的情况下重建全部结果与 PDF。
3. 每个交付物在发布前都经过自动门禁；门禁不通过则不能发布。

## 1. 十条原则

1. **唯一计算面**：所有数据解析、数值计算、优化求解、统计、测试、绘图、LaTeX 排版、PDF 检查与打包必须在 Modal 执行。本地只允许：编辑文本、Git 操作、提交云端任务、下载产物、核对 SHA-256、查看文件。本地禁止 `import pandas`/`numpy`/`openpyxl` 之类的处理；本地禁止运行 `pytest`、`xelatex`。
2. **一切皆阶段**：工作单元是 `stage @ run_id`。阶段函数签名 `fn(ctx) -> metrics`，只写 `ctx.stage_dir`，只读依赖阶段目录与原始输入。
3. **不可变输入**：题目 PDF 与附件原样保存在仓库根目录，任何代码不得改写；`ingest` 记录其 SHA-256。
4. **单一事实来源**：论文数值只能来自 `generated/numbers.tex`（由各阶段 `ctx.number()` 汇总）或 `generated/tables/*.tex`（由 `tables` 阶段生成）；禁止在 `.tex` 中手工键入结果数字。
5. **契约先行**：输入数据契约（`pipelines/<p>/contracts.py: INPUT_CONTRACTS`）、结果模板契约（`RESULT_CONTRACTS`）与阶段 metrics 均为显式对象；契约失败即阶段失败。
6. **门禁**：`lint`（ruff check、ruff format、mypy）、`test`（pytest + 覆盖率）、`qa`（论文与结果文件检查）必须全部通过，`release` 拒绝任何未通过门禁的构建。
7. **可复现**：镜像依赖版本固定；随机源全部经 `ctx.seed_everything(salt)`；每个阶段 manifest 记录代码树摘要、配置摘要、依赖阶段输出摘要、参数、环境与包版本；支撑材料 zip 采用固定时间戳与固定顺序，内容相同则散列相同。
8. **可观测**：每个阶段写结构化日志 `events.jsonl` 与 `manifest.json`；`tools/cli.py status|logs` 在云端读取，不下载全部产物。
9. **可审计**：所有交付文件带 SHA-256；支撑材料内含 `MANIFEST.json`；发布目录含 `release_manifest.json`；本地下载后必须校验散列。
10. **小步提交**：Conventional Commits；涉及结果的提交在正文注明 `run: <run_id>`；里程碑打 tag。

## 2. 仓库布局

```
<X>题.pdf, 附件/              原始输入（不可变）
forge/                        运行时：阶段执行、清单、契约、xlsx、tex、pdfqa、打包、绘图、Modal 应用
pipelines/common/             通用阶段：ingest, lint, test, paper, qa, package, release；validation 共享实现
pipelines/<p>/                本题阶段与契约（validate 与全部科学阶段）
manuscript/                   论文源码（main.tex + sections/ + references.bib + ai_usage.tex）；generated/ 只在云端生成
tests/unit|integration/       单元 / 性质（hypothesis）/ 集成测试
configs/default.toml          运行配置；configs/project.json 项目元数据
tools/cli.py, Makefile        本地控制面（只提交/下载/校验）
docs/                         本规范、建模标准、架构、运行手册、ADR、MDR、题目简报
artifacts/                    云端产物下载区（不入库）
releases/<tag>/               交付物与发布清单（入库）
AI_USAGE.md                   AI 工具使用记录（入库，编译进《AI工具使用详情.pdf》）
```

## 3. 分支与提交

- 主干 `main` 始终可构建；功能分支 `feat/<topic>`、修复分支 `fix/<topic>`，合并前需 lint/test 阶段通过。
- 提交信息：`<type>(<scope>): <subject>`，type ∈ feat, fix, model, exp, paper, infra, docs, test, chore, release。示例：`model(q2): implicit radial FV scheme with Newton iteration`。
- 里程碑 tag：`v0.1.0`（首个绿色流水线）、`v0.2.0`（全部科学阶段）、`v1.0.0`（论文发布）…；发布 tag 对应 `releases/<tag>/`。

## 4. 运行与阶段模型

- `run_id = YYYYMMDD-HHMMSS-<git7>`，由 CLI 铸造；同一 run 内各阶段共享 `/vol/runs/<run_id>/`。
- 阶段注册：`@stage(name, deps=(...), description=...)`；依赖必须在同一 run 已完成，或用 `--from-run` 复制旧 run 的依赖输出。
- 幂等：已完成的阶段默认跳过；`--force` 清空该阶段目录后重跑。阶段失败时 manifest 记录 `status=failed` 与 traceback。
- 资源档：`small`(2 CPU/4 GB/2 h)、`medium`(8 CPU/16 GB/6 h)、`large`(32 CPU/64 GB/12 h)。预计超过 10 分钟的阶段必须用 `--spawn` 分离运行或在后台执行，并用 `status`/`wait` 轮询。
- 阶段命名：接入与门禁使用固定名（ingest, validate, lint, test, paper, qa, package, release）；科学阶段以问题或功能命名（如 q1, q2, detect, resolve, classify, forecast），`results` 生成结果工作簿，`figures`、`tables` 生成论文图表。

### manifest.json 字段

`schema, run_id, stage, status, started_at, finished_at, duration_s, code_ref{git_sha, branch, dirty, code_digest, files}, params, config_digest, deps{stage: outputs_digest}, inputs{path: sha256}, outputs{path: sha256, bytes}, outputs_digest, metrics, runtime{python, platform, cpu_count, modal_task_id, packages}, error`。

## 5. 契约

- 输入契约：每张数据表一个 `FrameContract`（列名、类型、范围、单调性、步长、唯一性、正则、自定义检查）。`validate` 阶段失败即终止流水线。
- 结果契约：每个 `result*.xlsx` 一个 `WorkbookContract`（表名与模板一致、A1 与模板一致、行数、数值区、空白策略、小数位 ≤ 4）。`qa` 阶段执行。
- 写结果文件必须使用 `forge.xlsx.write_result(template, out, sheets)`，禁止手工构造工作簿。

## 6. 门禁

| 门禁 | 检查 | 失败后果 |
|---|---|---|
| lint | ruff check、ruff format --check、mypy(forge) | 阶段失败 |
| test | pytest 全部通过；JUnit 与覆盖率报告落盘 | 阶段失败 |
| qa | 摘要 1 页；正文（含参考文献）≤ 30 页；无未定义引用；无 TeX 错误；字体全嵌入；A4；Overfull ≤ 20 pt；无缺字；\val 无冲突；含《AI工具使用详情.pdf》；身份信息黑名单为空；论文 ≤ 20 MB；全部结果契约通过 | 阶段失败，release 拒绝 |
| package | 支撑材料成员与论文附录清单完全一致；≤ 20 MB；CRC 校验 | 阶段失败 |
| release | 需要 qa 通过；生成 SHA-256 清单 | 拒绝发布 |

身份信息观察名单（"大学、学院、赛区、队号、指导教师、@"）命中不阻断，但写入 `qa_report.json` 供人工复核，复核结论记录于 CHANGELOG。

## 7. 科学阶段编写规范

1. 一个阶段解决一个问题或一个功能；输入来自 `ctx.dep(...)`，输出写 `ctx.out(...)`；返回 JSON 可序列化 metrics。
2. 论文数字用 `ctx.number("Key", value, fmt)` 登记，Key 只含字母、语义化（如 `QthreeDryingHours`）。
3. 随机性只能通过 `ctx.seed_everything("<salt>")`。
4. 求解器结果必须由独立校验器复核（PDE：守恒/解析解/网格收敛；优化：独立可行性检查与界；统计：回测），校验报告写入阶段目录并在论文"模型检验"中引用。
5. 长时间计算写进度事件（`ctx.log.info("progress", ...)`），并将中间结果落盘以便断点续算。
6. 图：`forge.plotting.new_figure/save`，矢量 PDF + PNG 预览，色板 Okabe–Ito，中文字体自动探测；绘图前阅读 dataviz 规范。
7. 表：`tables` 阶段生成 `tables/*.tex`（booktabs）并同时输出同名 CSV；表内数字与 `results` 一致。
8. 计算量：阶段应能在 `medium` 档 6 小时内完成；更重的实验拆分为可续算的子阶段。

## 8. 论文流水线

- `manuscript/main.tex` 固定骨架：摘要页（第 1 页）→ 问题重述 → 问题分析 → 假设与符号 → 各问题模型与求解 → 模型检验 → 评价与推广 → AI 使用声明 → 参考文献（正文结束标签 `page:body-end`）→ 附录（支撑材料清单、复现记录、完整程序）。
- `paper` 阶段在云端合成 `generated/{numbers,meta,code_listing,support_files,repro_table}.tex`、拷贝 `tables/`、`figures/`，三遍 XeLaTeX + BibTeX；同时编译《AI工具使用详情.pdf》。
- 参考文献使用 BibTeX（gbt7714 数值样式，缺失时回退 unsrt）；所有引用必须真实、可核查。
- 页面预算：正文 24–30 页；附录不限。

## 9. 发布

1. `python3 tools/cli.py run lint,test,paper,qa,package,release` 全绿。
2. `python3 tools/cli.py release --version vX.Y.Z` 下载并校验；`git add releases/vX.Y.Z && git commit -m "release: vX.Y.Z (run <id>)" && git tag vX.Y.Z`。
3. GitHub 公开发布采用 Unlicense。本仓库为非参赛的公开研究记录，自 2026-09-12 起公开；题目与附件的著作权归组委会所有，Unlicense 只覆盖本仓库自有内容。

## 10. 安全与合规

- 论文、结果文件、支撑材料中不得出现参赛者姓名、学校、赛区、队号、邮箱；Git 元数据不打包（`.git` 排除）。
- 仓库不得包含任何令牌或凭证（`.modal.toml`、`.env` 在 `.gitignore`）。
- 按《全国大学生数学建模竞赛人工智能工具使用规定（2026年试行）》如实披露 AI 使用；`AI_USAGE.md` 与《AI工具使用详情.pdf》内容必须与实际一致。

## 11. 决策记录

- ADR（`docs/adr/`）：工程与基础设施决策。
- MDR（`docs/mdr/`）：建模决策——每条记录问题、备选方案、选择理由、对结果的影响与验证方式。凡是题目歧义的解释、假设的取舍、目标函数的定义，必须有 MDR。

## 12. 完成定义（Definition of Done）

- [ ] `ingest, validate` 通过，数据契约无错误
- [ ] 每个问题有独立科学阶段，metrics 与 numbers 登记完整
- [ ] 每个求解结果有独立校验器复核记录
- [ ] `results` 生成全部结果工作簿并通过结果契约
- [ ] `figures`、`tables` 产物全部被论文引用
- [ ] `lint, test`（覆盖率报告）通过
- [ ] `paper, qa, package, release` 通过；`releases/<tag>/` 入库且散列核对一致
- [ ] MDR 覆盖全部关键建模决策；CHANGELOG 更新；AI_USAGE.md 与实际一致
- [ ] README 客观描述方法、结果、局限与复现方式
