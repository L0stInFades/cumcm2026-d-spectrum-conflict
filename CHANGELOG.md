# 变更记录

格式遵循 Keep a Changelog；版本号遵循语义化版本。

## [Unreleased]

### Added
- 问题 1–4 的科学阶段：`detect`（成对枚举与分桶扫描线两种检测算法，冲突图统计）、`resolve`（时频单元格 AtMostOne 模型 + 七级词典序 CP-SAT，分离权重单目标与 HiGHS MILP/LP 交叉验证，四种目标方案对照）、`pack`（新增 C 类计划最大装填：CP-SAT + 贪心提示 + LP/MILP/容量上界）、`resolve_interval`（C 类间隔调整动作）、`bench`（穷举对照与规模基准）、`sensitivity`（最大平移幅度灵敏度）、`results`、`figures`、`tables`。
- 独立校验器 `pipelines/d/validators.py`（单元格集合求交），MDR-0001…0007，`docs/DATA_NOTES.md`，单元/性质测试。
- 热启动与求解预算（MDR-0008）：`configs/hints/*.json` 保存前一轮经独立校验的现任解（含 run id、代码版本与目标向量），`resolve`/`resolve_interval` 默认以其作为 CP-SAT 与 HiGHS 的提示；阶段报告记录提示是否可行及其目标向量（`QtwoHintVector` 等）。
- `sensitivity` 依赖 `resolve`：基准情形 (10, 5) 直接引用问题 2 的解，其余情形以其热启动；新增词典序单调性检查（`SensMonotone`）。
- `tests/unit/test_d_hints.py`：提示映射、提示可行性、HiGHS 逐级独立时限。

### Fixed
- `pipelines/d/stages.py` 缺少 `import json`（热启动读取路径）。
- HiGHS 交叉验证复用同一求解器对象时运行时钟跨级累计，首级耗尽时限后其余各级立即超时；现每级每个松弛新建求解器，LP 与 MILP 分别设时限。
- 源代码注释/表头中的希腊字母与数学符号（δ τ ∪ ≤ ≥ ⌊ ⌋）在论文程序附录的等宽字体中缺字，改为 ASCII 写法。

## [0.1.0] - 2026-09-12

### Added
- Forge 云端运行时（阶段/运行/清单模型、数据与结果契约、事件日志、确定性打包）。
- 通用流水线：ingest、validate、fmt、lint、test、paper、qa、package、release；全部在 Modal 执行。
- CUMCM 格式论文骨架（XeLaTeX + BibTeX gbt7714），自动生成数字宏、支撑材料清单、复现记录与完整程序附录。
- 工程规范、建模与写作标准、运行手册、ADR/MDR、AI 使用记录、Unlicense。

### Verified
- 三题仓库全链路冒烟通过：25 项单元/性质/集成测试，13 项论文与结果 QA 检查，发布散列核对一致。
