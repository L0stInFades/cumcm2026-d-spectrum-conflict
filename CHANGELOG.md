# 变更记录

格式遵循 Keep a Changelog；版本号遵循语义化版本。

## [Unreleased]

### Added
- 问题 1–4 的科学阶段：`detect`（成对枚举与分桶扫描线两种检测算法，冲突图统计）、`resolve`（时频单元格 AtMostOne 模型 + 七级词典序 CP-SAT，分离权重单目标与 HiGHS MILP/LP 交叉验证，四种目标方案对照）、`pack`（新增 C 类计划最大装填：CP-SAT + 贪心提示 + LP/MILP/容量上界）、`resolve_interval`（C 类间隔调整动作）、`bench`（穷举对照与规模基准）、`sensitivity`（最大平移幅度灵敏度）、`results`、`figures`、`tables`。
- 独立校验器 `pipelines/d/validators.py`（单元格集合求交），MDR-0001…0007，`docs/DATA_NOTES.md`，单元/性质测试。

## [0.1.0] - 2026-09-12

### Added
- Forge 云端运行时（阶段/运行/清单模型、数据与结果契约、事件日志、确定性打包）。
- 通用流水线：ingest、validate、fmt、lint、test、paper、qa、package、release；全部在 Modal 执行。
- CUMCM 格式论文骨架（XeLaTeX + BibTeX gbt7714），自动生成数字宏、支撑材料清单、复现记录与完整程序附录。
- 工程规范、建模与写作标准、运行手册、ADR/MDR、AI 使用记录、Unlicense。

### Verified
- 三题仓库全链路冒烟通过：25 项单元/性质/集成测试，13 项论文与结果 QA 检查，发布散列核对一致。
