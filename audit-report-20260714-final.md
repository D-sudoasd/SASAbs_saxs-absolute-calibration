# SASAbs 全量项目审计报告

审计日期：2026-07-14（Asia/Shanghai）
审计模式：`full`
审计目标：当前 dirty snapshot 的全量改动收口、缺陷修复与洁净交付
基线：HEAD `1c82092ab4bc4734c17366babd6ce52fab1b43f8`；基线时 `main...origin/main` 对齐
执行分支：`codex/sasabs-release-hardening-20260714`；最终目标分支：`main`

## 1. 最终结论

当前 closeout 已完成定向修复、私有审计资产迁移和发布边界整理；最终门禁以本报告第 13 节为准。

- **没有确认 P0 级数值公式错误**；公式、单位体系和既有公共 API 未改变。
- **F-001 已关闭**：`audit_outputs/` 与私有 campaign 测试已按样品批次迁移到外部归档，并由 SHA-256 清单核验；仓库新增 local-only ignore 规则。
- **F-002 已关闭**：Fabio detector-image 读取和 reference matching 均在资源释放前复制数据，并以 `try/finally` 确定性关闭句柄。
- **F-003 已关闭**：非法显式 `intensity_state` 现在保留无效元数据证据并返回 `AMBIGUOUS`。
- **F-004 已关闭**：writer 入口拒绝非有限 `q/I`，同时保留不确定度缺失值的既有处理语义。
- F-005 保留为 Workbench/strict runner 的未验证 GUI/campaign 架构残余，不在本轮进行无边界重构。

因此，本轮限定范围的代码修复、发布卫生和可复现验证已闭合；报告不宣称 F-005 已完成。

## 2. 审计边界与保护原则

本轮遵循以下边界：

- 目标是当前 dirty snapshot，不把历史 `audit-report.md` 或历史 `.audit-work/` 的结论当作当前验证。
- 所有既有 tracked/untracked 改动均视为用户资产；本轮仅移除已完成外部归档的私有副本和临时占位物，未 reset 或回退代码。
- 未升级依赖；代码、测试、文档和最终报告改动均纳入当前功能分支。
- 临时审计工作区和 `audit-report-20260714.md` 占位报告不纳入提交；已有 `audit-report.md` 保持不变。
- 私有审计资产与 campaign 测试已按样品批次迁移到外部目录，并逐项完成 SHA-256 核验；仓库不保留其副本。

当前复核证据以仓库中的测试、静态检查、构建产物扫描和本报告第 13 节为准；修复前临时审计证据已在外部归档核验后清理。

外部样品目录中的 `SASAbs_audit_archive_20260714` 保留批次归档和独立哈希清单。

## 3. 项目结构与关键数据流

当前仓库的主要层次清晰：

```text
src/saxsabs/core/       可复用科学计算、单位/状态/不确定性逻辑
src/saxsabs/io/         canSAS/NXcanSAS 解析与导出
src/saxsabs/workflows/  BL19B2 2D 绝对标定与严格 1D 积分
src/saxsabs/cli.py      CLI 入口
SASAbs.py               legacy/desktop Workbench
tests/                  pytest 自动化测试
examples/               最小 2D 与手工验收材料
docs/                   架构、runbook、审计边界
paper/submission/       论文与投稿资产
```

严格 BL19B2 1D 路径的科学链条是：2D package manifest → EDF/metadata/PONI/mask 校验 → 读取已是 `cm^-1` 的 EDF → 仅执行一次 mask 与 solid-angle correction → CSR 积分到 5500 个 `q_A^-1` 点 → profile/sidecar/checksum/completion。代码明确阻止 dark、background、monitor、transmission、thickness、K 和 polarization 的重复执行。

桌面 Workbench 具有独立的 Tab 2/Tab 3 编排、preflight、强制 `CalibrationContext`、intensity-state/ledger 和 disabled legacy resume，但它不是严格 campaign runner 的直接调用者。因此严格 CLI 的通过不等价于 GUI 全路径已经通过。

## 4. G1/G6 基线结果

| 检查 | 结果 | 证据类型 |
|---|---:|---|
| pytest 基线（修复前） | 726 passed in 41.70 s | 直接运行 |
| pytest 最终回归（修复后） | 687 passed in 24.98 s | 直接运行 |
| Ruff | All checks passed | 直接运行 |
| compileall | exit 0 | 直接运行 |
| `git diff --check` | exit 0；仅换行符提示 | 直接运行 |
| CLI version | `saxsabs 2.0.0` | 直接运行 |
| Workbench version | `saxsabs_workbench.py 2.0.0` | 直接运行 |

慢测试集中在 wheel/Workbench 启动、最小 2D 示例、真实 float32 导出重开和若干 resume/mutation 检查；没有从该结果推断出真实 2000 帧 GUI 性能。

## 5. 风险总表

| 编号 | 优先级 | 状态 | 结论 |
|---|---|---|---|
| F-001 | P1 | fixed | 私有审计资产已迁移； `audit_outputs/` 与 `.audit-work/` 为 local-only ignore |
| F-002 | P1 | fixed | Fabio 读取和 reference matching 已确定性 close，并有回归测试 |
| F-003 | P2 | fixed | 非法显式 intensity state fail-closed 为 `AMBIGUOUS` 并保留证据 |
| F-004 | P1 | fixed | writer 入口拒绝 q/I 非有限值；error 缺失语义保留 |
| F-005 | P2 | open/residual | Workbench/strict runner 的 campaign owner、原子发布、真实 UI 证据未闭合 |

## 6. 已确认发现（修复前快照及当前状态映射）

以下各 F 条目的详细描述保留修复前审计证据；当前状态以第 5 节风险总表和第 13 节 closeout 为准。

### F-001 — P1：仓库发布卫生与私有数据边界

修复前统计结果：`audit_outputs/` 共 213 个文件、83,327,789 bytes，即 79.47 MiB；其中 204 个是未跟踪且未被 ignore 的文件，34 个文件含束线私有路径前缀。`git ls-files audit_outputs` 为 0；当时的 `.gitignore` 没有 `audit_outputs/` 规则。

多个 campaign 测试直接 `from audit_outputs import ...`，campaign runner 还含 H 盘默认输入/输出路径。结果是：

1. 当前工作区的 green test 结果不能由 fresh clone 重现。
2. 若未来误 add，这些私有路径与大文件可能进入仓库/发布物。
3. 即使不 add，当前快照也不满足“可交付 release candidate”的 provenance 边界。

本轮没有删除、移动、匿名化或重写这些用户资产；需要用户明确选择 local-only fixture、匿名 synthetic fixture、受控模块迁移或仅发布前 gate。这个发现保持 blocked。

### F-002 — P1：Fabio 句柄关闭不完整

`src/saxsabs/workflows/bl19b2_abs2d.py:1746` 的 `read_detector_image()` 使用 `fabio.open(...).data` 后直接返回；没有在 `finally` 中保存并关闭 image object。`src/saxsabs/core/reference_matching.py:81` 起的 `build_reference_library()` 对每个候选图打开后读取 metadata，也没有对 image object 做确定性 close。

严格 1D `_load_mask()`、`_load_validate_edf()` 和严格 2D resume verifier 有正确的 `try/finally/close`，所以这是部分路径缺陷，不应夸大为“所有 Fabio 路径都泄漏”。但在批量读样品/参考图时，它仍可能造成 Windows 文件锁或资源累积。

最小修复方向：先把 `image_file.data` 复制为独立 C-contiguous 数组，再在 `finally` close；reference matching 采用相同模式；添加成功与 data decode 异常两条回归测试。本轮没有声称已修复。

### F-003 — P2：非法显式强度状态被静默忽略

`src/saxsabs/core/intensity_state.py:131` 的 `_state_from_metadata()` 对未知 token 返回 `None`；`assess_intensity_state()` 之后仍可使用单位/列名推断状态。

直接 probe：

```text
intensity_state = "not-a-state"
intensity_unit  = "1/cm"
i_col           = "i"
=> ABSOLUTE_CM_INV, evidence=("unit:1/cm",)
```

当前强度缩放调用者仍会拒绝 absolute 输入，因此本 probe 没有直接证明已经产生错误绝对强度；但 provenance 元数据本身已经损坏而没有被报告，违反严格状态机应有的 fail-closed 预期。建议存在非空显式值但无法识别时直接得到 `AMBIGUOUS`，并保留 `invalid_metadata:intensity_state` 证据。

### F-004 — P1：public writer 接受非有限 q/I

`src/saxsabs/io/writers.py:70` 的 `_prepare_profile_arrays()` 仅检查 shape，不检查 q/I 是否 finite，也不检查 q 是否单调。直接 probe 将：

```text
q = [0.1, NaN]
I = [1.0, Inf]
err = [0.1, NaN]
```

写成：

```xml
<Q unit="1/A">nan</Q>
<I unit="1/cm">inf</I>
```

同样的非有限 q/I 也进入 NXcanSAS HDF5。`err=NaN` 被跳过是当前代码的显式行为，但 q/I 不应在公开科学输出边界静默穿透。建议对 q/I 做 finite 校验，对 error 制定明确的 finite/non-negative policy，并增加 XML/HDF5 两种格式的 fail-closed 测试。

### F-005 — P2：Workbench 与严格 runner 的剩余边界

CLI 明确调用 `run_bl19b2_abs2d`；Workbench 的 `run_batch`、`run_external_1d_batch` 是独立方法。当前代码和文档已做了很多安全强化：legacy exists-only resume 被禁用、preflight/CalibrationContext/ledger gate 已存在、strict 1D 有 per-artifact checksum 与 completion。

但本轮没有证据证明 Workbench 已经拥有：

- multi-folder campaign owner 与逐目录 accepted-frame/T_rep/MAD/P5-P95/d_fixed 发布表；
- whole-campaign staging + atomic publish；
- 与 strict runner 一致的 content-signature resume；
- 真实 2000 帧交互性能、取消、DPI/键盘/中文英文/深浅主题矩阵。

因此不能把 strict CLI 通过外推成 GUI 全路径通过。

## 7. 科学数据与物理语义审计

### 7.1 事实、解释、推断分层

| 层级 | 本轮结论 |
|---|---|
| 实验/输入事实 | 本轮没有读取私有束线数据；所有实际数据结果仅来自仓库 fixture、synthetic test 和代码 probe |
| 数据处理事实 | strict 1D 仅接受已是 `cm^-1` 的 EDF，并强制 5500 `q_A^-1`、CSR、一次 solid angle、无 polarization |
| 数据解释 | correction ledger、intensity state、K/thickness/buffer gate 用于阻止重复校正；`do_not_repeat` 被当作 guard 而非物理证明 |
| 机制/外推 | 名义材料密度是理想混合模型，不是实测 bulk density；孔隙率会偏置线性 μ 和 derived thickness |
| 作者/项目主张 | “Workbench 已等价于严格 runner”“真实 GUI 已通过”本轮没有充分证据支持 |

### 7.2 NIST 30 keV 与三种材料

官方 NIST Table 1 的密度与 Table 3 的 30 keV 质量衰减系数，与代码快照一致：

- Al：2.699 g/cm³，1.128 cm²/g
- Ti：4.540 g/cm³，4.972 cm²/g
- V：6.110 g/cm³，5.564 cm²/g
- Zr：6.506 g/cm³，24.85 cm²/g
- Nb：8.570 g/cm³，26.66 cm²/g
- Sn：7.310 g/cm³，41.21 cm²/g

参考：[NIST Table 1](https://physics.nist.gov/PhysRefData/XrayMassCoef/tab1.html)、[NIST Table 3](https://physics.nist.gov/PhysRefData/XrayMassCoef/tab3.html)。NIST 对混合物采用按质量分数加和，并提醒元素密度可能是 nominal；这与项目将密度标注为 ideal/model-derived、将不确定性标为 partial 的实现边界一致。

独立本地计算复现：

```text
Ti-24Nb-4Zr-8Sn: mu = 74.55035538810252 cm^-1
sum(w_i * (mu/rho)_i) * rho_ideal = 74.55035538810252 cm^-1
T_median = 0.5 -> d_fixed = 0.009297704577684208 cm
```

### 7.3 不确定性与边界

本轮代码阅读和已有测试支持以下结论：

- raw-count 统计项包含 sample/background/dark 的共享 dark 系数传播；
- 缺失的 reference、monitor、transmission、alpha、covariance 等组件保持 `None`/`partial`，没有被偷偷当成 0；
- expanded uncertainty 只有在完整未知项、有限数组和 coverage factor 都具备时才标记 available；
- masked detector pixels 用零占位但在 summary 中排除，并要求后续分析使用分布的 mask；
- SRM 厚度、NIST 快照、composition、PONI/mask/signature 等均写入 provenance 或 processing signature。

仍需注意：共享 blank/dark covariance 没有被量化时，完整系统不确定性不能被宣传为“完整”；理想混合密度也不能替代样品 bulk density 认证。

## 8. UI/UX 审计

静态代码证据显示：

- root/Toplevel 已使用 screen-aware geometry；
- Tab 2/Tab 3 legacy exists-only resume 控件被禁用，并在 run gate 中拒绝；
- preflight fingerprint 会绑定配置、文件身份和 calibration context；
- K、μ、material provenance 与 correction ledger 具备只读/重算/失效机制。

本轮没有打开实际 GUI 窗口，也没有截图或自动化视觉/键盘验收。因此以下结论保持未验证：

- 1024×700、100/125/150/200% DPI；
- 中英文、深浅主题、焦点顺序、键盘操作、非颜色状态提示；
- 2000 帧预检/筛选/取消时的响应性；
- Workbench 输出目录 owner、整批失败恢复和 completion 展示。

## 9. 性能审计

已验证：修复前完整 pytest 726 项在 35.29 s 内通过；迁移私有 campaign 测试并完成修复后，完整 pytest 687 项在 24.98 s 内通过。没有发现静态上明显的 O(N²) 新增路径或测试级资源爆炸。

未验证：真实束线 2000 帧、内存峰值、磁盘吞吐、Fabio/pyFAI 多线程、GUI 主线程阻塞、取消响应。不能用单机 pytest 时间替代这些验收。

## 10. 修复与变更记录

本轮纳入了用户要求的全部有效代码、测试、文档和可复现验证改动，并完成以下限定范围修复：

- F-002：detector-image 读取和 reference matching 使用 `try/finally` 关闭 Fabio handle，并复制数组后再释放资源；增加成功、异常和资源关闭回归测试。
- F-003：非法显式 `intensity_state` 返回 `AMBIGUOUS`，并保留 `invalid_metadata:intensity_state` 证据。
- F-004：writer 拒绝包含 NaN/Inf 的 q/I 数组；不确定度缺失值仍按既有规则处理。
- F-001：新增 `audit_outputs/` 与 `.audit-work/` 的 local-only ignore 规则；私有审计资产和 campaign 测试按批次外部归档并核验后移除仓库副本。
- 同时保留本轮已有的科学工作流、文档和测试改动；未改变公式、单位体系、依赖版本或已有公共 API。

已有 `audit-report.md` 未覆盖；临时审计工作区和本轮占位报告未提交。

## 11. 发布门禁状态

1. [x] `audit_outputs/` 已完成 local-only ignore 与按批次外部归档，fresh clone 不依赖私有副本。
2. [x] F-002 已修复，并有成功、异常和资源关闭回归测试。
3. [x] F-003 已修复，并固定非法显式状态的 provenance 证据。
4. [x] F-004 已修复，并固定 q/I 非有限值的 fail-closed 行为。
5. [ ] F-005 的真实 Workbench/strict-runner campaign、atomic publish、resume、DPI/键盘/取消和 2000 帧验收仍待后续范围明确后完成。
6. [x] pytest、Ruff、compileall、CLI/Workbench 版本、隔离构建及私有路径扫描均已完成；最终 Git 门禁在交付步骤复核。

## 12. 审计自检

- [x] 先基线，再风险图、复现、回归、最终报告。
- [x] 区分直接运行、静态代码证据、独立数值 probe、外部权威来源和未验证项。
- [x] 没有把测试绿色外推为真实数据或 GUI 已验证。
- [x] 外部归档前记录文件数量、大小和 SHA-256，复制后逐项核验，确认后才移除仓库副本。
- [x] 未覆盖已有 `audit-report.md`；临时审计 state 和占位报告未提交。
- [x] F-005 仍明确标记为 residual，未把 GUI/strict-runner 未验证项外推为已完成。
- [x] 当前报告状态与 F-001–F-004 的修复结果一致。

## 13. Closeout verification

本节记录本轮修复、归档和发布门禁的最终结果：

| 检查 | 结果 |
|---|---|
| 定向回归 | 202 passed in 4.87 s |
| 完整 pytest | 687 passed in 24.98 s |
| Ruff | All checks passed |
| compileall | exit 0 |
| CLI / Workbench | `saxsabs 2.0.0` / `saxsabs_workbench.py 2.0.0` |
| 隔离构建 | sdist 与 wheel 均成功；包内无私有路径、审计目录或 campaign 测试名 |
| 2025A1750 外部归档 | 61 files，253,726 bytes；manifest SHA-256 逐项核验通过 |
| 2026A1756 外部归档 | 151 files，82,745,256 bytes；manifest SHA-256 逐项核验通过 |
| 仓库私有边界 | 私有 audit_outputs 副本和 campaign 测试已移除；未发现私有 H 盘路径残留 |
| Git 交付 | 提交、快进合并、push、分支清理和最终工作区状态以交付步骤的实时门禁为准 |

本轮不改变公式、单位体系、依赖版本或既有公共 API；F-005 仍是未形成直接可复现失败的架构残余，后续应单独立项而非在本轮无边界扩展。
