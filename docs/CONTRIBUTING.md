# 协作约定

1. 分支 `feat/…`、`fix/…`、`paper/…`；合并到 `main` 前 `lint,test` 阶段必须通过。
2. Conventional Commits；涉及结果的提交在正文写 `run: <run_id>`。
3. 每个建模决策（歧义解释、假设取舍、目标定义）先写 `docs/mdr/NNNN-*.md`，再改代码。
4. 每个 PR/提交只做一件事；重构与建模改动分开提交。
5. 代码风格由 ruff 与 mypy 约束；公共函数必须有类型注解与一句话文档字符串。
