# 结果总览（供论文撰写者使用）

> 全部数值来自同一次云端运行 **run `20260912-102234-ea48b61`**，该 run 的 17 个阶段（ingest, validate, detect, resolve, resolve_interval, compare, pack, bench, sensitivity, results, figures, tables, lint, test, paper, qa, fmt）全部 `status=completed`。run id 中的短号是创建该 run 时的提交；各阶段的实际代码版本记录在自身 `manifest.json` 的 `code_ref.git_sha` 中（科学阶段与下游阶段在 MDR-0009 / MDR-0010 落地后整体重跑）。论文中只能通过 `\val<Key>` 宏或 `generated/tables/*.tex` 引用；下文括号内为 numbers 键名。图文件位于 `figures` 阶段的 `figures/`（PDF + PNG 预览），表文件位于 `tables` 阶段的 `tables/`（同名 CSV 并存）。结果工作簿位于 `results` 阶段目录根。

## 0. 方法总览

| 问题 | 方法（一句话） | 独立校验（与求解器分离） |
|---|---|---|
| 1 | 半开区间冲突判定；成对枚举 O(n²·(m_i+m_j)) 与按频段分桶的扫描线 O(N log N + K) 两种实现互相对照；冲突图统计 | 时频单元格集合求交（`validators.validate_detection`） |
| 2 | 每计划恰选一动作（保持/频移/时移/撤销）的 0-1 模型：时频单元格 AtMostOne 约束 + 成对蕴含团约束 + 强制撤销割；七级词典序（撤销 A/B/C → 调整 A/B/C → 归一化幅度）用 CP-SAT 逐级求解，逐级加入由现任解导出的上界割并在整个词典序过程中保持现任解（MDR-0009，热启动来源见 MDR-0008）；HiGHS 独立建模逐级给出 LP 下界与限时 MILP；分离权重单目标（前置、独立热启动）与四种目标方案对照 | 逐计划合法性 + 单元格集合零冲突 + 重算表 1 与目标向量（`validate_resolution`） |
| 3 | 主解释（MDR-0005/0010-A）：以问题 2 方案为固定占用，在 100 × [0, T_end] 的自由单元中最大装填新增 C 类计划（变量 x_{f,s}，单元格 AtMostOne，max Σx）：贪心提示 + CP-SAT；上界：CP-SAT 界、HiGHS LP 界、HiGHS MILP 界、自由单元容量界、逐频段容量界。备选解释（MDR-0010-B，既有计划可任意平移）：首次适配重排给下界、面积守恒给上界 | 参数/边界/既有-既有、既有-新增、新增-新增零冲突（`validate_packing`）；重排另检查 w/d/g/n 不变与区域包含 |
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
- **备选解释 B（MDR-0010，重要）**：题目原文说"**如果不限制频段和时间的平移幅度**"，而新增装备本无"原位置"可平移，故该句更可能是允许**既有计划**不受 10Δf / 5Δt 限制地再次平移以腾出空间。本文以解释 A（既有计划固定）为主解释填写 `result3.xlsx`（模板只记录新增装备，无处记录既有计划的新位置），同时给出 B 的严格区间：
  - **上界（对 A、B 同时成立）**：平移不改变任一计划占用的单元数，故被占用单元总数 S 为常数，新增数量 ≤ ⌊(100·T_end − S)/72⌋ = `QthreeFreeCellBound`（亦即 `QthreeAltRepackBound`）。
  - **下界（构造）**：按占用单元数降序的"首次适配"重排既有计划（`repack_existing`，移动 `QthreeAltRepackMoved` 个计划、保持 w/d/g/n 不变），再在剩余自由单元上用同一 CP-SAT 装填模型求最大新增数 `QthreeAltRepackNewPlans`（状态 `QthreeAltRepackStatus`，贪心下界 `QthreeAltRepackGreedy`）；该布局经同一独立校验器复核（`QthreeAltRepackValidator`）。解释 A 的最优值本身也是 B 的下界。
  - 表 `tab_q3_summary` 末行给出"下界 / 上界"；图 `fig_q3_repack`（建议图注：既有计划按首次适配重排后（灰）与在其上装填的新增 C 类计划（绿）；对照 `fig_q3_layout` 可见重排把既有计划压到低频段与早时刻，从而腾出大片连续自由区域）。
- **备选解释（T_end 取法）**：T_end 取原始计划最晚结束时刻（643）——当问题 2 方案的最晚结束时刻等于 643 时两者相同，此时不产生 `QthreeAltHorizon` 等键。

## 4. 问题 4：允许 C 类调整间隔

- **主结果（表 1 格式）**：`tab_q4_table1`；键 `QfourKeepA/B/C`、`QfourAdjustA/B/C`、`QfourCancelA/B/C`、`QfourKeepTotal`、`QfourAdjustTotal`、`QfourCancelTotal`、`QfourVector`；间隔调整数 `QfourGapChanged`、平均/最大 |Δg|（`QfourMeanAbsGapChange`、`QfourMaxAbsGapChange`）；其余键与问题 2 同名（前缀 `Qfour`）。
- **与问题 2 对照**（`compare` 阶段）：`tab_q4_compare`、`fig_q4_comparison`（(a) 各类调整数量对照；(b) 问题 4 的动作构成）；键 `QfourLexNotWorse`（词典序不劣于问题 2）、`QfourCancelDelta`、`QfourAdjustDelta`、`QfourAmplitudeDelta`、`QfourHorizonDelta`（间隔改变导致的最晚结束时刻变化）。
- **备选目标方案**：`tab_q4_schemes`；被撤销计划解释 `tab_q4_cancelled`。**图**：`fig_q4_resolution`。**结果文件**：`result4.xlsx`（`ResultFourRows` 行）。
- **验证**：`QfourValidator` = 通过；`tab_validation` 第 4 行。
- **（本节数值由最终 run 填写，见文末"最终数值"。）**

## 5. 灵敏度与稳健性

- **最大平移幅度**（`sensitivity` 阶段，`tab_sensitivity`、`fig_sensitivity`）：情形 (5,2)、(5,5)、(10,2)、(10,5)、(15,5)、(20,10)；基准 (10,5) 直接引用问题 2 的解（同一模型），其余情形以之热启动；键 `SensCases`、`SensBaseCancelTotal`、`SensBaseAdjustTotal`、`SensMinCancelTotal`、`SensMaxCancelTotal`、`SensMinAdjustTotal`、`SensMaxAdjustTotal`、`SensAllOptimal`、`SensAllValid`、`SensMonotone`（动作集合更大者词典序不劣、更小者不优）。
  - **论文可用的结论**：撤销数量对频移上限极为敏感——上限由 10 提高到 15 个频段时撤销数降为 0（即"不撤销任何计划"在 (15,5) 下已可行），上限收紧到 5 时撤销数急剧上升。这说明撤销并非资源总量不足所致，而是平移幅度上限造成的局部拥塞。
  - **监督说明（诚实性）**：动作集合更大的情形 (15,5)、(20,10) 的词典序不劣性在 MDR-0009 之后由构造保证（基准解在更大模型中可行，因而成为现任解并给出上界割），它不再是一个独立的检验；动作集合更小的情形 (5,2)、(5,5)、(10,2) 中基准解一般不可行、不产生割，其"不优于基准"仍是真正的检验。论文应按此措辞陈述。
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

1. 调整数量与幅度各级在时限内未必证明最优：论文必须按"值 / 证明下界 / 状态"报告，不得声称全局最优（撤销各级除外，见最终数值）。现任解上界割（MDR-0009）保证报告值不劣于任何已知可行解，但不提供最优性证明。
2. LP 松弛下界对装填型约束很弱（撤销 C 一级 LP 下界为 0），CP-SAT 的内部界是主要证据。
3. 优先级的词典序解释（MDR-0003）是主观建模选择；备选方案 T/S/W 的对照说明结论对解释的敏感程度。
4. 离散化粒度（Δf、Δt）与"只改一个参数"的动作集合是题目给定；连续化或多参数调整未建模。
5. 问题 3 假定新增计划参数与既有 C 类完全相同，且既有计划不动（MDR-0005 / MDR-0010 解释 A）。报告的 109 是**"在本文这一个问题 2 方案之上"的最大值**，而非跨所有无冲突方案的最大值——不同的问题 2 最优解会给出不同的答案，论文必须如此措辞。本轮有一个值得写进论文的经验观察：上一轮撤销 17 个计划的方案只能再放 100 个，本轮撤销 12 个（占用单元更多）反而能再放 **109** 个，说明**可装填数量主要由既有计划的布局对齐程度决定，而不是由自由单元的总数决定**（自由单元容量界 673 远未被触及，紧的界来自 CP-SAT 的组合论证）。
6. 问题 3 的题意存在实质性歧义（MDR-0010）："不限制平移幅度"若指既有计划也可重排，答案落在 [557, 673] 而非 109，相差约 5 倍。本文给出主解释与备选区间，但无法断定命题人的本意。
7. 合成实例的规模基准只报告固定时限下的状态，不代表大规模实例可证明最优。
8. 灵敏度的"动作集合更大者不更差"对 (15,5)、(20,10) 由构造保证（见第 5 节的监督说明），不是独立检验。

## 7a. 论文应陈述的理论要点（均已在代码/测试中体现）

1. **冲突的单元格刻画**（命题）：计划 i 的第 k 次使用占用单元集合 U_i = {(b,t): f_i ≤ b < f_i+w_i, s_i+k(d_i+g_i) ≤ t < s_i+d_i+k(d_i+g_i)}；两计划冲突 ⇔ U_i ∩ U_j ≠ ∅（半开区间相交判据 lo1 < hi2 ∧ lo2 < hi1）。性质测试 `test_property_interval_arithmetic_matches_cell_sets` 与校验器即此命题。
2. **检测复杂度**：成对枚举为 O(n²·(m_i+m_j))（双指针合并两条已排序的使用序列）；按频段分桶的扫描线为 O(N log N + K)，N = Σ_i w_i·n_i 为 (使用次, 频段) 项数，K 为输出对数。附件实例 N = 20·10·3 + 40·15·4 + 90·3·12 = 6240。
3. **消解模型的精确性**（命题）：对每个单元 (b,t)，覆盖它的 (计划, 动作) 变量至多一个为真，当且仅当消解后无冲突；单元格 AtMostOne 约束数 ≤ 单元数，字面量总数 Σ_i |O_i|·w_i·d_i·n_i（`QtwoMemberships`）。成对蕴含团约束与强制撤销割均由单元格行推出，不改变可行域（MDR-0004）。
4. **NP-难性**：只允许"保持/撤销"时，问题 2 的第一层（最少撤销）等价于冲突图 G 的最大（权）独立集（保留集合必须是独立集），一般图上 NP-难；允许平移是其推广（每个顶点有一个候选位置列表，属列表装填/图着色型问题）。
5. **分离权重与词典序等价**（命题）：设第 k 级取值范围为 [0, U_k]，权重 W_k = Π_{j>k}(U_j+1)，则单目标 Σ_k W_k·L_k 的最优解是词典序最优解（证明：相邻两级之间 W_k > Σ_{j>k} W_j U_j）。`separated_weights` 与 `test_separated_weights_dominate_lower_levels` 实现并检验；`QtwoWeightedAgree` 报告两种求法向量一致。
6. **问题 3 的上界链**：CP-SAT 界 ≥ 最优值 ≤ HiGHS LP 松弛上界 ≤ 逐频段容量界 ≤ 自由单元容量界 ⌊自由单元数/72⌋ ≤ 空区域界 ⌊100·T_end/72⌋；`tab_q3_summary` 给出全部数值与 gap。
7. **现任解上界割的有效性**（命题，MDR-0009）：设词典序求解进行到第 k 级，前 k−1 级的最优值 v_1,…,v_{k−1} 已作为等式固定；若 x\* 可行且满足 L_j(x\*) = v_j (j < k)，则第 k 级的受限最优值 v_k ≤ L_k(x\*)。因此把 L_k ≤ L_k(x\*) 加入模型不删除任何第 k 级最优解，各级最优值不变；同时报告值恒 ≤ L_k(x\*)，即"永不劣于任何已知可行解"。证明：x\* 本身是受限问题的可行点，故受限最小值不超过它的取值。对应测试 `test_incumbent_cut_preserves_optimum_and_never_worsens_the_hint`。
8. **面积守恒与问题 3 的解释无关上界**（命题，MDR-0010）：平移只改变 (f, s)，不改变 (w, d, g, n)，故每个计划占用的单元数 w·d·n 不变，既有计划占用的单元总数 S 与布局无关。区域共 100·T_end 个单元，每个新增 C 类计划占 3·2·12 = 72 个单元，故无论既有计划是否允许再平移，新增数量 ≤ ⌊(100·T_end − S)/72⌋。
9. **C 类计划的相位平铺**（引理，用于说明装填上界的紧性）：C 类周期 d+g = 10、时长 d = 2，故同一 3 频段带内首次时间取 s、s+2、s+4、s+6、s+8 的五个计划互不冲突且在其共同跨度内恰好铺满该带的全部单元；这给出"局部利用率可达 100%"的构造，测试 `test_repack_fills_a_strip_exactly_and_refuses_an_impossible_region` 即此引理。

## 8. 最终数值

> 本节的全部数值取自 run `20260912-102234-ea48b61`。该 run 的 `resolve`、`resolve_interval`、`pack`、`bench`、`sensitivity`、`compare` 及其下游阶段在修复 MDR-0009 之后重跑，每个阶段的 `manifest.json` 记录了各自的 `code_ref.git_sha`（run id 中的 7 位短号是该 run 创建时的提交，不是各阶段的提交）。论文只能通过 `\val<Key>` 或 `generated/tables/*.tex` 引用这些数字。

### 8.0 问题 1（`tab_q1_summary`）

150 个计划中检出 **297 对**冲突（`QoneConflictPairs`），类别对 AA/AB/AC/BB/BC/CC = 0/21/66/10/181/19；卷入冲突的计划 148 个（A 20 / B 40 / C 88），冲突的使用次对数 431；冲突图 1 个连通分量、最大分量 148、最大度 8（`QoneTopDegreeId` = B009）、平均度 3.96、密度 0.0266；时频单元 64300 个、被占用 14698（22.9%）、重叠 1842、最晚结束时刻 643。成对枚举 11 ms、分桶扫描线 6 ms，两者给出完全相同的 297 对；独立单元格集合校验器真值 297、缺失 0、多余 0（`QoneValidator` = 通过）。`result1.xlsx` 297 行。

### 8.1 问题 2（表 1 格式，`tab_q2_table1`）

| 类别 | 保留数量 | 调整数量 | 撤销数量 |
|---|---|---|---|
| A 类 | 4 | 16 | 0 |
| B 类 | 3 | 37 | 0 |
| C 类 | 7 | 71 | 12 |
| **合计** | **14** | **124** | **12** |

目标向量 `QtwoVector` = (0, 0, 12, 16, 37, 71, 750)，归一化总幅度 `QtwoAmplitude` = 75.0；频移 85 个（均值 6.24、最大 10、合计 530），时移 39 个（均值 2.82、最大 5、合计 110），间隔调整 0 个；调整后最晚结束时刻 `QtwoHorizonAfter` = 643（与原始相同）。

**逐级最优性证据（`tab_q2_solver`）**

| 层级 | 值 | CP-SAT 证明下界 | 状态 | 用时/s |
|---|---|---|---|---|
| 撤销 A | 0 | 0 | **OPTIMAL** | 0.6 |
| 撤销 B | 0 | 0 | **OPTIMAL** | 1.5 |
| 撤销 C | **12** | **12** | **OPTIMAL** | 364.3 |
| 调整 A | 16 | 7 | FEASIBLE | 300.4 |
| 调整 B | 37 | 20 | FEASIBLE | 300.5 |
| 调整 C | 71 | 37 | FEASIBLE | 300.6 |
| 幅度（×10） | 750 | 424 | FEASIBLE | 240.5 |

**论文可以并且只可以声称**：撤销数量 (0, 0, 12) 已被 CP-SAT 证明为该词典序前三级的全局最优——即"在不撤销任何 A、B 类计划的前提下，必须撤销的 C 类计划数最少为 12"，这是题目首要目标上的**最优性证明**；此外"零撤销不可行"也已被证明（固定撤销 A = 撤销 B = 撤销 C = 0 时模型 INFEASIBLE，4.2 s）。调整各级与幅度级只报告"值 / 证明下界 / 状态"，不得声称最优。

**交叉验证**：分离权重单目标（独立标量化，MDR-0009 前置执行）返回同一向量 (0, 0, 12, 16, 37, 71, 750)，`QtwoWeightedAgree` = 通过；HiGHS 在其证明最优的各级与 CP-SAT 一致，`QtwoHighsAgree` = 通过。**诚实说明**：两种标量化都以同一现任解为起点，且都未能改进调整各级，故该一致性主要说明"两种搜索都没有找到更好的解"，而不是独立地证明了最优性；最优性的唯一证据是 CP-SAT 的证明下界一列。

**模型规模**：变量 4589，时频单元 54768，AtMostOne 约束 53046 → 去重 35406，变量-单元隶属 491904，成对蕴含团约束 58587，可能冲突的计划对 1843。

### 8.2 问题 3

**主解释 A（既有计划固定；填入 `result3.xlsx`）**：新增 C 类计划 `QthreeNewPlans` = **109**，且**三个独立上界全部等于 109**——CP-SAT 界 109（状态 OPTIMAL）、HiGHS LP 松弛界 109.00、HiGHS MILP 界 109（状态 Optimal）——故 `QthreeGap` = 0、`QthreeOptimal` = 通过：**这是一个被三种方法共同证明的全局最优值**。

| 项目 | 数值 |
|---|---|
| T_end（问题 2 方案最晚结束时刻） | 643 |
| 既有计划数 / 占用单元 / 自由单元 | 138 / 15816 / 48484 |
| 候选放置位置 (f, s) / AtMostOne 约束 | 1344 / 4378 |
| 贪心下界 | 103 |
| CP-SAT 值（状态）/ 界 / 用时 | 109（OPTIMAL）/ 109 / 0.18 s |
| HiGHS LP 松弛上界 | 109.00 |
| HiGHS MILP 值 / 界（状态） | 109 / 109（Optimal） |
| 自由单元容量界 ⌊48484/72⌋ / 逐频段容量界 / 空区域界 | 673 / 658 / 893 |
| **最终结果 / 最紧上界 / gap** | **109 / 109 / 0** |
| 时频利用率（前 / 后） | 24.6% / 36.8% |

**备选解释 B（既有计划可任意平移，MDR-0010）**：首次适配重排把全部 138 个既有计划重新放置（`QthreeAltRepackMoved` = 138，w/d/g/n 全部不变、区域包含与零冲突均经独立校验），候选位置增至 34761、约束 43488；在该布局上 CP-SAT 给出 **557**（状态 OPTIMAL、界 557，7.7 s），即该布局下的精确最大值。因此解释 B 的最优值满足

> **557 ≤ (解释 B 的最大新增 C 类计划数) ≤ 673**，

下界由上述可行布局构造给出，上界由面积守恒命题给出（⌊(100·643 − 15816)/72⌋ = 673；HiGHS 对该模型的 LP 松弛在 120 s 时限内给到 594.6，也落在区间内）。若采用解释 B，时频利用率将由 24.6% 升至 (15816 + 557×72)/64300 = **87.0%**。

**论文必须明确指出**：两种解释的答案相差约 5 倍（109 vs ≥557），差别完全来自"是否允许既有计划再次平移"。本文以 A 为主解释（与 `result3.xlsx` 模板一致、可被评阅者独立复核），并把 B 的区间作为正式的备选分析给出。

### 8.3 灵敏度：最大平移幅度（`tab_sensitivity`、`fig_sensitivity`）

| (最大频移, 最大时移) | 撤销 A/B/C（合计） | 调整合计 | 归一化幅度 | 各级最优 |
|---|---|---|---|---|
| (5, 2) | 0/0/59（59） | 81 | 31.0 | **是（全部 7 级）** |
| (5, 5) | 0/0/42（42） | 95 | 45.6 | 否 |
| (10, 2) | 0/0/24（24） | 114 | 64.4 | 否 |
| **(10, 5)（题目给定，= 问题 2 主结果）** | **0/0/12（12）** | **124** | **75.0** | 否（撤销三级已证明最优） |
| (15, 5) | 0/0/**0**（0） | 125 | 98.4 | 否 |
| (20, 10) | 0/0/**0**（0） | 117 | 120.2 | 否 |

`SensCases` = 6，`SensAllValid` = 通过（六个情形的解全部通过独立校验），`SensMonotone` = 通过。

**论文可用的核心结论**：撤销数量对**频段平移上限**极其敏感——上限由题目的 10Δf 放宽到 15Δf 时，撤销数从 12 直接降到 **0**（即不必撤销任何计划）；反之收紧到 5Δf 时升至 42–59。把两个上限分别放宽，可以定量比较二者的作用：**频段上限 +5**（5→10，时移固定）使撤销数由 59→24（tmax=2）、42→12（tmax=5），即减少 30–35 个；**时间上限 +3**（2→5，频移固定）使撤销数由 59→42（fmax=5）、24→12（fmax=10），即减少 12–17 个。频域放宽的效果约为时域的两倍，说明冲突主要是**频域拥塞**而非时域拥塞——这与问题 1 的统计一致（B–C 类冲突 181 对占 61%，而 B 类频宽 15 为三类之最）。若能把最大频移放宽到 15Δf，代价仅是多调整 1 个计划、总幅度由 75.0 升到 98.4，却可完全避免撤销——这是一条有实际价值的管理建议。

### 8.4 问题 4（表 1 格式，`tab_q4_table1`）

| 类别 | 保留数量 | 调整数量 | 撤销数量 |
|---|---|---|---|
| A 类 | 7 | 13 | 0 |
| B 类 | 4 | 36 | 0 |
| C 类 | 3 | 78 | 9 |
| **合计** | **14** | **127** | **9** |

目标向量 `QfourVector` = (0, 0, 9, 13, 36, 78, 776)，归一化总幅度 77.6；频移 58 个（合计 400）、时移 38 个（合计 112）、**间隔调整 31 个**（`QfourGapChanged` = 31，均值 |Δg| = 4.90、最大 10、合计 152）；调整后最晚结束时刻 `QfourHorizonAfter` = **718**（问题 2 为 643，`QfourHorizonDelta` = +75——放宽间隔会把最后一次使用推后，这一点必须在论文中与问题 3 的资源区域定义一并说明，见 MDR-0006）。

**逐级证据（`tab_q4_solver`）**：撤销 A / 撤销 B 为 0（均 OPTIMAL）；撤销 C = 9（FEASIBLE，证明下界 3，600.6 s，现任解上界割为 10——**词典序搜索把已知最好的 10 改进到 9**）；调整 A = 13（下界 5）、调整 B = 36（下界 17）、调整 C = 78（下界 40）、幅度 = 776（下界 354）。

**与问题 2 对照（`compare` 阶段，`tab_q4_compare`、`fig_q4_comparison`）**：`QfourLexNotWorse` = 通过（(0,0,9,…) 词典序优于 (0,0,12,…)）；`QfourCancelDelta` = −3、`QfourAdjustDelta` = +3、`QfourAmplitudeDelta` = +2.6、`QfourHorizonDelta` = +75。**结论**：允许 C 类调整间隔，可把必须撤销的计划从 12 个减到 9 个（减少 25%），代价是多调整 3 个计划、总幅度增加 2.6、时间跨度延长 75Δt。

**诚实说明**：`QfourWeightedAgree` = 未通过——分离权重单目标在 180 s 内只回到 (0, 0, 10, 12, 35, 75, 752)，未能复现词典序解。这不是矛盾（词典序解 (0,0,9,…) 严格更优），而是说明单次加权求解在该规模上比逐级求解弱；论文应如此陈述，不得把它当作"两法一致"的证据。`QfourHighsAgree` = 通过（HiGHS 在其证明最优的各级与 CP-SAT 一致）。

### 8.5 目标方案对照（MDR-0003 的备选分析，`tab_q2_schemes` / `tab_q4_schemes`）

| 方案 | 问题 2 撤销 A/B/C（合计） | 问题 2 调整合计 | 问题 4 撤销 A/B/C（合计） | 问题 4 调整合计 |
|---|---|---|---|---|
| P：类别内嵌七级词典序（主方案） | 0/0/12（12） | 124 | 0/0/9（9） | 127 |
| T：总撤销数优先 | 2/6/0（8） | 113 | 2/2/5（9） | 119 |
| S：不含优先级 | 1/7/0（8） | 113 | 3/6/0（9） | 108 |
| W：纯加权和 | 0/5/7（12） | 112 | 0/0/12（12） | 115 |

**这是论文中最重要的一张对照表**：方案 T/S 把撤销总数从 12 降到 8，但**代价是撤销 2 个 A 类和 6 个 B 类计划**；题目明确要求"A 类优先级最高、B 类其次、C 类最低，高优先级用频装备的用频计划应尽量保持"，故本文采用 P。论文应直接引用这一对照说明 P 的选择不是任意的：P 是唯一在任何情况下都不撤销 A、B 类计划的方案。（备选方案每级时限仅 30 s，其向量只作定性对照，不作最优性声明。）

### 8.6 验证与确认（V&V）汇总（`tab_validation`、`tab_bench_tiny`、`tab_bench_scaling`）

| 证据 | 结果 |
|---|---|
| 四个独立校验器（与求解器代码分离，用单元格集合求交重算） | 问题 1/2/3/4 **全部通过**（`QoneValidator`、`QtwoValidator`、`QthreeValidator`、`QfourValidator`；问题 3 备选布局 `QthreeAltRepackValidator` 亦通过） |
| 两种检测算法一致 | 通过（成对枚举与分桶扫描线给出同一 297 对） |
| 微型实例穷举对照 | **24/24 全部一致**（`BenchTinyAllAgree` = 通过），最大枚举组合数 262144 |
| 确定性（同种子重复求解同解） | **24/24**（`BenchTinyAllDeterministic` = 通过） |
| 最优性证明 | 问题 2 撤销三级 (0,0,12) 与问题 3 的 109 已证明最优；其余各级给出证明下界 |
| 三重上界一致（问题 3） | CP-SAT 界 = HiGHS LP 界 = HiGHS MILP 界 = 109 = 解值 |
| HiGHS 独立建模交叉验证 | `QtwoHighsAgree` = 通过，`QfourHighsAgree` = 通过 |
| 分离权重单目标 | 问题 2 一致（`QtwoWeightedAgree` = 通过）；问题 4 **不一致**且更差，已在 8.4 节诚实说明 |
| 可扩展性（合成实例） | n = 150/300/600：成对检测 0.010/0.039/0.150 s，扫描线 0.004/0.102/0.016 s，模型 4582/9276/18485 变量、32154/64600/132121 约束，CP-SAT 固定 120 s 时限下均为 FEASIBLE（`BenchScaleAllOptimal` = 未通过，论文须如实说明大规模实例在该时限内未证明最优） |
| 结果文件契约 | `result1–4.xlsx` 四项 **全部通过**（`qa` 阶段 `result:*` 检查），行数 297 / 136 / 109 / 136 |
| 论文门禁 | `qa` 16 项检查全部通过（摘要 1 页、正文页数达标、无未定义引用、无 TeX 错误、字体全嵌入、全 A4、无溢出、无缺字、无数字冲突、AI 使用详情 PDF 存在、体积达标、四个结果文件契约）；身份信息**黑名单命中 0**。观察名单（软提示）命中 5 处，全部位于附录代码清单第 19 页——那里原样列出了 `configs/default.toml`，其中包含观察名单自身的正则 `["大学", "学院", "赛区", "队号", "指导教师", …]`。这是检查器匹配到自己的模式列表，**不是身份信息**；论文与支撑材料中不存在任何作者、学校、赛区、队号或邮箱。 |

## 9. 图表目录与建议图注（供论文直接取用）

`figures` 阶段共 10 张图（矢量 PDF + PNG 预览），`tables` 阶段共 24 张表（booktabs `.tex` + 同名 `.csv`）。每张图表在正文中至少被引用一次，未被引用者不得进入论文。

### 9.1 图（10 张）

| 文件 | 论文用途 | 建议图注 |
|---|---|---|
| `fig_q1_gantt` | 第 4 节（问题 1 结果）正文主图 | 附件 1 中 150 个用频计划在时频平面上的甘特图。横轴为时间（单位 Δt），纵轴为频段编号（单位 Δf）；每个矩形是一个用频计划的一次使用，颜色区分 A（蓝）、B（橙）、C（绿）三类装备；黑色描边标出参与时频冲突的 431 个使用次。全区域 100 × 643 = 64300 个时频单元中 14698 个被占用（22.9%），其中 1842 个被两个及以上计划同时占用。 |
| `fig_q1_structure` | 第 4 节，紧随甘特图 | 冲突的结构。(a) 按装备类别对统计的冲突对数矩阵（共 297 对，B–C 类之间最多，达 181 对）；(b) 冲突图的度分布，最大度为 8，平均度 3.96，148 个计划至少与一个其他计划冲突，仅 2 个计划完全无冲突。 |
| `fig_q2_resolution` | 第 5 节（问题 2）主图 | 问题 2 的冲突消解方案。(a) 消解前：按所采取的动作着色（灰 = 保持、蓝 = 频段平移、橙 = 时间平移、斜线填充 = 撤销），黑边为发生冲突的使用次；(b) 消解后：138 个存留计划（150 − 12 个被撤销）在时频平面上已无任何冲突，箭头指示每个被平移计划的移动方向。 |
| `fig_q2_schemes` | 第 5 节末或第 8 节（灵敏度） | 四种目标方案的对照。(a) 各方案下被调整的计划数（按类别堆叠）；(b) 归一化总调整幅度。方案 P（本文主方案，类别内嵌词典序）是唯一完全不撤销 A、B 类计划的方案。 |
| `fig_q3_layout` | 第 6 节（问题 3）主图 | 在问题 2 的无冲突方案（灰）之上最多可再安排 109 个 C 类用频计划（绿）。资源区域为 100 个频段 × [0, 643)；新增计划与既有计划、以及新增计划彼此之间均无时频冲突。时频利用率由 24.6% 提升至 36.8%。 |
| `fig_q3_repack` | 第 6 节，与上图并列 | 备选解释下的布局：若允许既有计划不受平移幅度限制地重新放置（首次适配降序重排，138 个计划全部移动、各自的频宽/时长/间隔/次数不变），同一资源区域可再安排 557 个 C 类计划，时频利用率达 87.0%。两种解释的答案相差约 5 倍。 |
| `fig_q4_resolution` | 第 7 节（问题 4）主图 | 问题 4 的冲突消解方案，图例与图 `fig_q2_resolution` 相同，另增"间隔调整"一类（31 个 C 类计划改变了使用间隔）。 |
| `fig_q4_comparison` | 第 7 节 | 问题 4 与问题 2 的对照。(a) 各类被调整的计划数；(b) 问题 4 所采取动作的构成。允许 C 类调整间隔后，必须撤销的计划由 12 个降为 9 个。 |
| `fig_sensitivity` | 第 8 节（灵敏度分析）主图 | 消解方案对最大平移幅度的灵敏度。(a) 被调整（按类别堆叠）与被撤销（黑）的计划数；(b) 归一化总调整幅度。频段平移上限由 10Δf 放宽到 15Δf 时撤销数降为 0，收紧到 5Δf 时升至 42–59，说明冲突主要源于频域拥塞。 |
| `fig_bench_scaling` | 第 9 节（模型检验）或附录 | 算法规模基准。合成实例 n = 150/300/600 下两种检测算法与模型构建的用时，以及 CP-SAT 在固定 120 s 时限下的求解时间（纵轴对数刻度）。 |

### 9.2 表（24 张，正文 / 附录分配建议）

- **正文**：`tab_q1_summary`（问题 1 统计摘要）、`tab_q1_category`（类别对矩阵）、`tab_q2_table1` 与 `tab_q4_table1`（题目要求的表 1 格式）、`tab_q4_compare`（问题 2/4 对照）、`tab_q3_summary`（问题 3 的解与上界链）、`tab_q2_solver` 与 `tab_q4_solver`（逐级值/下界/状态——**最优性证据，必须进正文**）、`tab_sensitivity`、`tab_q2_schemes` 与 `tab_q4_schemes`（目标方案对照）、`tab_validation`（四个独立校验器的结论）、`tab_bench_tiny`（穷举对照摘要行）。
- **附录**：`tab_q1_conflicts`（全部 297 对，longtable）、`tab_q1_top_degree`、`tab_q1_multiplicity`、`tab_q2_adjustments` 与 `tab_q4_adjustments`（逐计划动作，longtable）、`tab_q2_cancelled` 与 `tab_q4_cancelled`（被撤销计划的邻域解释）、`tab_q3_plans`（109 个新增计划清单）、`tab_q2_model` 与 `tab_q4_model`（模型规模与热启动来源）、`tab_bench_scaling`。
