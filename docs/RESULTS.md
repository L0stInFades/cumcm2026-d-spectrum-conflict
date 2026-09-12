# 结果总览（供论文撰写者使用）

> 全部数值来自同一次云端运行 **run `20260912-102234-ea48b61`**（代码 `ea48b61`；lint/test 门禁在 `971a46a` 复跑，仅格式差异）。论文中只能通过 `\val<Key>` 宏或 `generated/tables/*.tex` 引用；下文括号内为 numbers 键名。图文件位于 `figures` 阶段的 `figures/`（PDF + PNG 预览），表文件位于 `tables` 阶段的 `tables/`（同名 CSV 并存）。结果工作簿位于 `results` 阶段目录根。

## 0. 方法总览

| 问题 | 方法（一句话） | 独立校验（与求解器分离） |
|---|---|---|
| 1 | 半开区间冲突判定；成对枚举 O(n²·(m_i+m_j)) 与按频段分桶的扫描线 O(N log N + K) 两种实现互相对照；冲突图统计 | 时频单元格集合求交（`validators.validate_detection`） |
| 2 | 每计划恰选一动作（保持/频移/时移/撤销）的 0-1 模型：时频单元格 AtMostOne 约束 + 成对蕴含团约束 + 强制撤销割；七级词典序（撤销 A/B/C → 调整 A/B/C → 归一化幅度）用 CP-SAT 逐级求解，逐级加入由现任解导出的上界割并在整个词典序过程中保持现任解（MDR-0009，热启动来源见 MDR-0008）；HiGHS 独立建模逐级给出 LP 下界与限时 MILP；分离权重单目标（前置、独立热启动）与四种目标方案对照 | 逐计划合法性 + 单元格集合零冲突 + 重算表 1 与目标向量（`validate_resolution`） |
| 3 | 以问题 2 方案为固定占用，在 100 × [0, T_end] 的自由单元中最大装填新增 C 类计划（变量 x_{f,s}，单元格 AtMostOne，max Σx）：贪心提示 + CP-SAT；上界：CP-SAT 界、HiGHS LP 界、HiGHS MILP 界、自由单元容量界、逐频段容量界 | 参数/边界/零冲突（`validate_packing`） |
| 4 | 问题 2 模型 + C 类"间隔调整"动作 g'∈[g−10,g+10]∩[1,∞)；同一词典序目标；`compare` 阶段与问题 2 对照 | 同问题 2，另检查 g' 范围与仅 C 类使用 |

求解预算（MDR-0008、MDR-0009）：CP-SAT 各级时限 [20, 20, 600, 300, 300, 300, 240] s、24 线程、固定种子；到时未证明最优的级以最好可行值固定并记录证明下界，论文按"值 / 下界 / 状态"如实报告；HiGHS 每级 LP 40 s、MILP 20 s；备选目标方案每级 30 s；分离权重单目标 180 s。

**现任解保持（MDR-0009）。** 热启动提示来自 `configs/hints/*.json`（前一轮经独立校验的现任解，含 run id 与目标向量）。求解器在每级求解前加入割 L_k ≤ L_k(x\*)，其中 x\* 是当前现任解（可行且满足此前各级已固定的等式）——该割不割去任何最优解，故各级最优值不变，但保证**报告向量在词典序上永不劣于热启动提示，也永不劣于分离权重解**。前一轮实现在每级结束时用该级自身的解覆盖提示，使撤销 C 由已知可行的 12 退化为 17；修复后该退化消失（诊断见 MDR-0009）。分离权重标量化改为在词典序求解**之前**、以文件现任解热启动，因而是真正独立的第二次搜索，其结果同时作为词典序求解的起点。

## 1. 问题 1：冲突检测

- **关键数值**：150 个计划（`QonePlans`）中检测出 **297 对**冲突（`QoneConflictPairs`）；按类别对 AA/AB/AC/BB/BC/CC = 0/21/66/10/181/19（`QoneConflictPairsAA` … `QoneConflictPairsCC`）；卷入冲突的计划 148 个（`QonePlansInConflict`；A/B/C = 20/40/88，`QonePlansInConflictA/B/C`）；冲突的使用次对数 431（`QoneUsePairs`）；冲突图 1 个连通分量、最大分量 148（`QoneComponents`、`QoneLargestComponent`）、最大度 8、平均度 3.96、密度 0.0266（`QoneMaxDegree`、`QoneMeanDegree`、`QoneDensity`）；时频单元 64300 个、被占用 14698（22.9%）、重叠 1842、最晚结束时刻 643（`QoneCellsTotal`、`QoneCellsOccupied`、`QoneOccupancyPercent`、`QoneCellsOverlap`、`QoneHorizon`）；成对枚举与扫描线用时（`QonePairwiseMs`、`QoneSweepMs`）；度最大的装备（`QoneTopDegreeId`）。
- **表**：`tab_q1_summary`（统计摘要）、`tab_q1_category`（类别对矩阵）、`tab_q1_top_degree`（度最大的 10 个装备）、`tab_q1_multiplicity`（冲突使用次对数的分布）、`tab_q1_conflicts`（全部 297 对，longtable，放附录）。
- **图**：`fig_q1_gantt`（建议图注：附件 1 全部用频计划的时频平面甘特图，颜色区分 A/B/C 类，黑边标出发生冲突的使用次）；`fig_q1_structure`（(a) 类别对冲突矩阵；(b) 冲突图度分布）。
- **验证**：两种检测算法给出完全相同的 297 对（阶段内断言）；独立单元格集合校验器真值 297 对、缺失 0、多余 0（`QoneValidator` = 通过；`tab_validation` 第 1 行）。
- **结果文件**：`result1.xlsx`，297 行（`ResultOneRows`），按装备编号字典序，模板表头原文保留。
- **局限**：检测本身精确无近似；"冲突对"按计划对计数，同一对计划多次使用重叠只计一次（`tab_q1_multiplicity` 给出强度补充）。

## 2. 问题 2：冲突消解（词典序）

- **主结果（表 1 格式）**：`tab_q2_table1`；数字键 `QtwoKeepA/B/C`、`QtwoAdjustA/B/C`、`QtwoCancelA/B/C`、`QtwoKeepTotal`、`QtwoAdjustTotal`、`QtwoCancelTotal`。目标向量 `QtwoVector`（撤销 A, 撤销 B, 撤销 C, 调整 A, 调整 B, 调整 C, 幅度×10）。
- **调整幅度统计**：频移计划数 / 平均 / 最大 / 合计（`QtwoFreqShifted`、`QtwoMeanAbsFreqShift`、`QtwoMaxAbsFreqShift`、`QtwoSumAbsFreqShift`），时移同理（`QtwoTimeShifted` …），归一化总幅度 `QtwoAmplitude`（= Σ|δ|/10 + Σ|τ|/5），调整后最晚结束时刻 `QtwoHorizonAfter`。逐计划动作见 `tab_q2_adjustments`（longtable，附录）与 `result2.xlsx`（`ResultTwoRows` 行，仅列出被调整/撤销的计划）。
- **最优性证据**：`tab_q2_solver`（每级 CP-SAT 值/下界/状态/用时、HiGHS LP 下界、MILP 值/下界/状态）；`tab_q2_model`（模型规模：变量 `QtwoVars`、单元 `QtwoCells`、约束 `QtwoRows`/`QtwoRowsRaw`、隶属 `QtwoMemberships`、团约束 `QtwoGroups`、可能冲突的计划对 `QtwoInteractingPairs`）。逐级键：`QtwoValueCancela` … `QtwoValueAmplitude`、`QtwoBoundCancela` …、`QtwoStatusCancela` …、`QtwoLpBoundCancela` …。汇总键：`QtwoAllOptimal`、`QtwoHighsAgree`、`QtwoHighsAllOptimal`、`QtwoWeightedAgree`、`QtwoCpsatSeconds`、`QtwoHighsSeconds`、`QtwoWeightedSeconds`；热启动 `QtwoHintUsed`、`QtwoHintFeasible`、`QtwoHintVector`。
- **被撤销计划的解释**：`tab_q2_cancelled`（每个被撤销计划的频段/首次时间、冲突邻居数、其中 A/B 类邻居数、可用平移动作数），用于论文说明撤销为何不可避免。
- **备选目标方案（MDR-0003）**：`tab_q2_schemes` 与 `fig_q2_schemes`：P（主方案）、T（总量优先）、S（无优先级）、W（纯加权）的撤销/调整/幅度对照；键 `QtwoSchemeXAdjustTotal`、`QtwoSchemeXCancelTotal`、`QtwoSchemeXAmplitude`、`QtwoSchemeXAdjustA`（X ∈ {P,T,S,W}）。
- **图**：`fig_q2_resolution`（建议图注：(a) 消解前的时频平面，被调整/撤销的计划按动作着色，黑边为冲突使用次；(b) 消解后无冲突的计划，箭头为平移方向）。
- **验证**：`QtwoValidator` = 通过（150 个决策、存留计划零冲突、表 1 与目标向量重算一致）；`tab_validation` 第 2 行。
- **（本节数值由最终 run 填写，见文末"最终数值"。）**

## 3. 问题 3：新增 C 类计划的最大数量

- **解释**（MDR-0005）：问题 2 方案固定；新增 C 类计划参数与附件 C 类相同（宽 3、时长 2、间隔 8、次数 12，跨度 112，`QthreeSpan`）；资源区域 100 × [0, T_end]，T_end = 问题 2 方案的最晚结束时刻（`QthreeHorizon`）；新增计划之间及与既有计划均无冲突。
- **关键数值**：新增数量 `QthreeNewPlans`；最紧上界 `QthreeUpperBound`、gap `QthreeGap`、是否最优 `QthreeOptimal`；候选位置数 `QthreeCandidates`、AtMostOne 约束数 `QthreeRows`、贪心下界 `QthreeGreedy`；CP-SAT 状态/值/界/用时（`QthreeCpsatStatus`、`QthreeCpsatValue`、`QthreeCpsatBound`、`QthreeCpsatSeconds`）；HiGHS LP 上界 `QthreeLpBound`（`QthreeLpValue`）、MILP `QthreeHighsStatus`/`QthreeHighsValue`/`QthreeHighsBound`；容量界 `QthreeFreeCellBound`（⌊自由单元/72⌋）、`QthreePerBandBound`、`QthreeEmptyRegionBound`（无既有计划时 ⌊100·T_end/72⌋）；利用率前后 `QthreeUtilBefore`、`QthreeUtilAfter`；自由单元 `QthreeFreeCells`。
- **表**：`tab_q3_summary`（上界与解的对照）、`tab_q3_plans`（新增计划清单，附录）。**图**：`fig_q3_layout`（建议图注：问题 2 方案的既有计划（灰）与新增 C 类计划（绿）在时频平面上的布局）。
- **验证**：`QthreeValidator` = 通过（参数、边界、与既有计划及彼此零冲突）。
- **备选解释**：T_end 取原始计划最晚结束时刻（643）——当问题 2 方案的最晚结束时刻等于 643 时两者相同（本轮情形，`QthreeHorizon` = 643，故未产生 `QthreeAlt*` 键）；"允许既有计划再任意平移"的联合优化以容量界 `QthreeFreeCellBound`、`QthreeEmptyRegionBound` 作为上界讨论。

## 4. 问题 4：允许 C 类调整间隔

- **主结果（表 1 格式）**：`tab_q4_table1`；键 `QfourKeepA/B/C`、`QfourAdjustA/B/C`、`QfourCancelA/B/C`、`QfourKeepTotal`、`QfourAdjustTotal`、`QfourCancelTotal`、`QfourVector`；间隔调整数 `QfourGapChanged`、平均/最大 |Δg|（`QfourMeanAbsGapChange`、`QfourMaxAbsGapChange`）；其余键与问题 2 同名（前缀 `Qfour`）。
- **与问题 2 对照**（`compare` 阶段）：`tab_q4_compare`、`fig_q4_comparison`（(a) 各类调整数量对照；(b) 问题 4 的动作构成）；键 `QfourLexNotWorse`（词典序不劣于问题 2）、`QfourCancelDelta`、`QfourAdjustDelta`、`QfourAmplitudeDelta`、`QfourHorizonDelta`（间隔改变导致的最晚结束时刻变化）。
- **备选目标方案**：`tab_q4_schemes`；被撤销计划解释 `tab_q4_cancelled`。**图**：`fig_q4_resolution`。**结果文件**：`result4.xlsx`（`ResultFourRows` 行）。
- **验证**：`QfourValidator` = 通过；`tab_validation` 第 4 行。
- **（本节数值由最终 run 填写，见文末"最终数值"。）**

## 5. 灵敏度与稳健性

- **最大平移幅度**（`sensitivity` 阶段，`tab_sensitivity`、`fig_sensitivity`）：情形 (5,2)、(5,5)、(10,2)、(10,5)、(15,5)、(20,10)；基准 (10,5) 直接引用问题 2 的解（同一模型），其余情形以之热启动；键 `SensCases`、`SensBaseCancelTotal`、`SensBaseAdjustTotal`、`SensMinCancelTotal`、`SensMaxCancelTotal`、`SensMinAdjustTotal`、`SensMaxAdjustTotal`、`SensAllOptimal`、`SensAllValid`、`SensMonotone`（动作集合更大者词典序不劣、更小者不优）。
- **目标方案对照**：`tab_q2_schemes`、`tab_q4_schemes`（P/T/S/W）。
- **问题 3 的 T_end 取法**：见第 3 节。

## 6. 验证与确认（V&V）证据一览

| 证据 | 产物 | 键 |
|---|---|---|
| 独立校验器（四个问题） | `tab_validation`，各阶段 `validation_report.json` | `QoneValidator`、`QtwoValidator`、`QthreeValidator`、`QfourValidator` |
| 两种检测算法一致 | `detect/stats.json`（detectors_agree） | — |
| 小实例穷举对照（24 个随机微型实例，全部动作组合枚举） | `tab_bench_tiny` | `BenchTinyInstances`、`BenchTinyAgree`、`BenchTinyAllAgree`、`BenchTinyMaxCombinations` |
| 确定性（同种子重复求解相同解） | `bench/tiny.json` | `BenchTinyDeterministic`、`BenchTinyAllDeterministic` |
| 最优性界 | `tab_q2_solver`、`tab_q4_solver`、`tab_q3_summary` | `Q*Bound*`、`Q*LpBound*`、`QthreeUpperBound` |
| 交叉验证（HiGHS 独立建模） | 同上 | `QtwoHighsAgree`、`QfourHighsAgree` |
| 分离权重单目标 = 词典序 | `tab_q2_model` | `QtwoWeightedAgree`、`QfourWeightedAgree` |
| 可扩展性（合成实例 n = 150/300/600） | `tab_bench_scaling`、`fig_bench_scaling` | `BenchScaleMinN`、`BenchScaleMaxN`、`BenchScaleMaxPairwiseSeconds`、`BenchScaleMaxSweepSeconds`、`BenchScaleMaxCpsatSeconds`、`BenchScaleMaxStatus`、`BenchScaleAllOptimal`、`BenchScaleDetectorsAgree` |

## 7. 局限

1. 调整数量与幅度各级在时限内未必证明最优：论文必须按"值 / 证明下界 / 状态"报告，不得声称全局最优（撤销各级除外，见最终数值）。
2. LP 松弛下界对装填型约束很弱（撤销 C 一级 LP 下界为 0），CP-SAT 的内部界是主要证据。
3. 优先级的词典序解释（MDR-0003）是主观建模选择；备选方案 T/S/W 的对照说明结论对解释的敏感程度。
4. 离散化粒度（Δf、Δt）与"只改一个参数"的动作集合是题目给定；连续化或多参数调整未建模。
5. 问题 3 假定新增计划参数与既有 C 类完全相同，且既有计划不动（MDR-0005）。
6. 合成实例的规模基准只报告固定时限下的状态，不代表大规模实例可证明最优。

## 7a. 论文应陈述的理论要点（均已在代码/测试中体现）

1. **冲突的单元格刻画**（命题）：计划 i 的第 k 次使用占用单元集合 U_i = {(b,t): f_i ≤ b < f_i+w_i, s_i+k(d_i+g_i) ≤ t < s_i+d_i+k(d_i+g_i)}；两计划冲突 ⇔ U_i ∩ U_j ≠ ∅（半开区间相交判据 lo1 < hi2 ∧ lo2 < hi1）。性质测试 `test_property_interval_arithmetic_matches_cell_sets` 与校验器即此命题。
2. **检测复杂度**：成对枚举为 O(n²·(m_i+m_j))（双指针合并两条已排序的使用序列）；按频段分桶的扫描线为 O(N log N + K)，N = Σ_i w_i·n_i 为 (使用次, 频段) 项数，K 为输出对数。附件实例 N = 20·10·3 + 40·15·4 + 90·3·12 = 6240。
3. **消解模型的精确性**（命题）：对每个单元 (b,t)，覆盖它的 (计划, 动作) 变量至多一个为真，当且仅当消解后无冲突；单元格 AtMostOne 约束数 ≤ 单元数，字面量总数 Σ_i |O_i|·w_i·d_i·n_i（`QtwoMemberships`）。成对蕴含团约束与强制撤销割均由单元格行推出，不改变可行域（MDR-0004）。
4. **NP-难性**：只允许"保持/撤销"时，问题 2 的第一层（最少撤销）等价于冲突图 G 的最大（权）独立集（保留集合必须是独立集），一般图上 NP-难；允许平移是其推广（每个顶点有一个候选位置列表，属列表装填/图着色型问题）。
5. **分离权重与词典序等价**（命题）：设第 k 级取值范围为 [0, U_k]，权重 W_k = Π_{j>k}(U_j+1)，则单目标 Σ_k W_k·L_k 的最优解是词典序最优解（证明：相邻两级之间 W_k > Σ_{j>k} W_j U_j）。`separated_weights` 与 `test_separated_weights_dominate_lower_levels` 实现并检验；`QtwoWeightedAgree` 报告两种求法向量一致。
6. **问题 3 的上界链**：CP-SAT 界 ≥ 最优值 ≤ HiGHS LP 松弛上界 ≤ 逐频段容量界 ≤ 自由单元容量界 ⌊自由单元数/72⌋ ≤ 空区域界 ⌊100·T_end/72⌋；`tab_q3_summary` 给出全部数值与 gap。

## 8. 最终数值（由 run `20260912-102234-ea48b61` 填写）

（待本轮全部阶段完成后填写：问题 2/4 的表 1、目标向量、各级状态与下界、问题 3 数量、灵敏度与基准结果。）
