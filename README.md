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

（研究完成后由发布流程补充：关键结果、检验结论、局限。）

## 许可

本仓库以 Unlicense 释出至公有领域（见 `UNLICENSE`）。题目与附件的著作权归全国大学生数学建模竞赛组委会所有，仅为复现目的随仓库保存。
