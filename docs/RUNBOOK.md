# 运行手册

## 0. 前提

- 本地：Python ≥ 3.11（仅标准库）、Modal CLI（`modal token set` 已完成）、git。本地不安装科学计算依赖。
- 云端：首次运行会构建镜像（TeX Live + 科学栈，约 10 分钟），之后命中缓存。

## 1. 常用命令

```bash
python3 tools/cli.py provision                      # 验证云端工具链（TeX、字体、求解器）
python3 tools/cli.py run ingest,validate --new-run  # 新 run：接入 + 契约校验
python3 tools/cli.py run q1 --size medium           # 运行科学阶段（同一 run）
python3 tools/cli.py run q3 --size large --spawn    # 长任务：分离运行，返回 FUNCTION_CALL_ID
python3 tools/cli.py wait <FUNCTION_CALL_ID>        # 阻塞等待分离任务结果
python3 tools/cli.py status                         # 云端读取本 run 全部 manifest
python3 tools/cli.py logs q1                        # 云端读取阶段事件日志
python3 tools/cli.py exec --code 'import pandas as pd; print(pd.read_parquet(RUN_DIR/"ingest/data/附件1__Sheet1.parquet").head())'
python3 tools/cli.py exec --file scratch/explore.py # 云端执行探索脚本（RUN_DIR/VOL/REPO 已注入）
python3 tools/cli.py fmt                            # 云端 ruff --fix + format，改动文件自动拷回本地
python3 tools/cli.py run lint,test                  # 门禁
python3 tools/cli.py run paper,qa,package,release   # 论文 → 质检 → 打包 → 发布
python3 tools/cli.py download --stage paper         # 下载到 artifacts/ 并核对散列
python3 tools/cli.py release --version v1.0.0       # 交付物到 releases/v1.0.0/ 并核对散列
```

`make` 提供同名快捷目标（`make run STAGE=q1 SIZE=medium`、`make status`、`make smoke` 等）。

## 2. 长任务

- 预计超过 10 分钟：使用 `--spawn`（`modal run --detach` + `spawn`），然后 `status`/`wait`；或在后台执行 `run`（在 Claude Code 中用 run_in_background）。
- 阶段内部定期写进度事件与中间文件，失败后可用 `--force` 重跑；依赖阶段不必重跑。

## 3. 探索数据

所有探索通过 `exec` 在云端进行。脚本内可用 `RUN_DIR`（当前 run 目录）、`RUNS`、`VOL`、`REPO`。输出会原样打印到本地终端。

## 4. 阅读产物

- `status`：每个阶段的状态、用时、输出摘要、错误摘要。
- `logs <stage>`：结构化事件（含 metrics）。
- `download --stage <stage>`：把阶段目录下载到 `artifacts/runs/<run_id>/<stage>/` 并逐文件核对 SHA-256；PNG 预览可直接查看。

## 5. 论文构建失败排查

1. `paper` 失败：错误信息含 `xelatex failed on pass N` 与日志尾部；常见原因是未定义的 `\val` 宏（对应阶段未登记该数字）、缺失图文件（`paper.sources` 未包含生成该图的阶段）、TeX 语法错误。
2. `qa` 失败：`qa_report.json` 的 `checks` 列出未通过项；`download --stage qa` 后查看。
3. `package` 失败：`support material members differ` 表示论文附录清单与实际打包成员不一致——通常是 `paper` 之后又新增了阶段目录；重跑 `paper` 再 `qa,package`。

## 6. 禁止事项

- 禁止在本地运行任何数据处理或排版命令；禁止手工修改 `artifacts/`、`releases/` 中的产物。
- 禁止在 `.tex` 中手写结果数字。
- 禁止提交凭证、`artifacts/`、`__pycache__`。
