# 时频冲突检测与消解（CUMCM 2026 D 题）

本仓库是 2026 年高教社杯全国大学生数学建模竞赛 D 题的完整研究工程：原始题目与附件、云端流水线、模型与求解程序、测试、论文源码与交付物。所有数据处理、计算、绘图、排版与打包均在 Modal 云端按固定镜像执行；本地只做文本编辑、Git 操作、任务提交、下载与散列校验。

## 内容

- `docs/ENGINEERING_STANDARD.md`：工程规范（阶段/清单/契约/门禁/发布）。
- `docs/MODELING_STANDARD.md`：建模与写作标准、审稿清单。
- `docs/problem_brief.md`：题目分析与建模路线。
- `docs/mdr/`：建模决策记录；`docs/adr/`：工程决策记录。
- `pipelines/d/`：本题的全部模型、求解与结果生成程序。
- `manuscript/`：论文源码；`releases/<tag>/`：论文 PDF、结果工作簿、支撑材料与 SHA-256 清单。

## 复现

```bash
python3 tools/cli.py provision
python3 tools/cli.py run ingest,validate --new-run
# 科学阶段见 docs/RUNBOOK.md 与 pipelines/d/stages.py
python3 tools/cli.py run lint,test,paper,qa,package,release
python3 tools/cli.py release --version <tag>
```

## 结果概要

来自云端运行 `20260912-102234-ea48b61`（17 个阶段全部 `completed`）；完整数值、图表目录与局限见 `docs/RESULTS.md`。

| 问题 | 关键结果 | 最优性 |
|---|---|---|
| 1 冲突检测 | 150 个用频计划中检出 **297 对**时频冲突，涉及 148 个计划 | 精确；两种算法互验 + 独立单元格校验器 |
| 2 冲突消解 | 保留 14 / 调整 124 / **撤销 12**（A、B 类零撤销） | 撤销三级 (0, 0, 12) 经 CP-SAT **证明最优**；调整各级报告值与下界 |
| 3 新增 C 类 | 在问题 2 方案上最多再安排 **109** 个 C 类计划 | CP-SAT 界 = HiGHS LP 界 = HiGHS MILP 界 = 109，**gap = 0** |
| 4 允许改间隔 | 保留 14 / 调整 127 / **撤销 9**（较问题 2 少 25%） | 撤销 A、B 两级证明最优；其余报告值与下界 |

检验：四个与求解器分离的独立校验器全部通过；24/24 微型实例与穷举最优一致且可重复；HiGHS 独立建模交叉验证；`qa` 16 项门禁全部通过。

## 许可

本仓库以 Unlicense 释出至公有领域（见 `UNLICENSE`）。题目与附件的著作权归全国大学生数学建模竞赛组委会所有，仅为复现目的随仓库保存。
