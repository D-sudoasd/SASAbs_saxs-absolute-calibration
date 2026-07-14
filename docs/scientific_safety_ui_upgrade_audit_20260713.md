# SAXSAbs 科学安全与 UI 升级审计

初版：2026-07-13

本轮代码事实复核：2026-07-14

## 结论先行

本轮已经关闭了一批会直接诱发误操作的 Workbench 缺口：正式 Tab 2 只允许固定厚度；逐帧
Beer-Lambert 与 Tab 2/Tab 3 existence-only resume 在 UI 禁用，强制赋值也会在 Dry Check 和 Run
双重失败关闭；K 与 μ 只读；BG/Dark library 改动立即使 preflight 失效；Tab 3 raw 禁用；K-only/Kd、
`raw_counts`/relative/absolute 状态、`do_not_repeat` 和 absolute buffer 已形成精确阶段契约；NIST 30 keV μ provenance 绑定可用的 PONI
能量并处理 stale payload。主窗口与 μ 窗口也已经屏幕自适应/可滚动。严格 1D 和严格 2D resume
读取路径还补上了 FabIO close。

这些改动显著降低了“重复 K/厚度校正”“沿用旧 preflight”“手改 K”“误把 Elam 当 NIST”以及小屏
不可操作的风险。但项目目前仍不能宣称 Workbench 等价于严格 BL19B2 campaign runner。以下关键
P0/P1 边界仍未关闭：

1. 正式多目录/每试样固定厚度 campaign 仍只能由 strict CLI/batch owner 管理；
2. Workbench 与严格 BL19B2 runner 仍是两套编排/科学 kernel；
3. K-only 只要求 inherited ledger 含 thickness，尚未要求其数值与来源；
4. Workbench 尚无 campaign-level 原子发布和 content-signature resume；
5. `audit_outputs/` 约 79 MiB，且 batch-specific tests/产物保留私有 `H:\...` 路径耦合，仓库发布卫生尚未关闭。

因此，2026A1756 正式重处理仍应以严格 runner 的 include manifest、thickness derivation、processing
signature 和 correction ledger 为权威。Workbench 当前适合标定、检查和受约束的交互式处理，不应
被文档包装成严格 runner 的完整图形前端。

## 状态定义与审计边界

- **已实现**：当前工作树有实际执行入口和针对性代码/测试，不代表本轮已经重跑全量 H 盘验收。
- **部分实现**：局部路径已经安全，但尚未覆盖同类入口或整批事务边界。
- **待实现 P0**：可能改变绝对尺度、复用错误结果或破坏正式输出隔离。
- **待实现 P1**：主要影响稳定性、可取消性、资源管理和规模化使用。
- **冻结基线**：历史 v4 结果只读保留；升级不得原地补写或覆盖。

本次复核只评价仓库代码和文档。未重新计算 H 盘 v4 全树哈希，因此不在这里声称历史结果已完成
升级前后哈希复验。

## 本轮已实现

| 项目 | 当前代码事实 | 安全效果 | 尚存边界 |
|---|---|---|---|
| 固定厚度正式门 | Tab 2 仅 formal fixed；per-frame Beer-Lambert radio disabled；强制 auto 后 Dry Check BLOCKED，Run 再拒绝 | 逐帧 T 只影响 norm，不会再从 Workbench 正式输出吸收到逐帧厚度 | 多目录/每试样固定厚度表和 owner 仍在 strict campaign path |
| legacy resume 正式门 | Tab 2/Tab 3 exists-only resume checkbutton disabled；强制开启后 Dry Check BLOCKED，Run 再拒绝 | 同名旧文件不会因仅存在而被正式跳过 | Workbench 尚无替代的 content-signature resume |
| K/μ 只读 | Tab 2、Tab 3 K 为 `readonly`；Tab 2 μ 也为 `readonly`，只能由当前 μ payload 写入 | 阻止临时手改 K/μ 与 provenance 脱钩 | 活动 CalibrationRecord 仍由现有 Workbench 上下文验证 |
| preflight 指纹硬门 | Run 初始禁用；Dry Check 生成规范化配置指纹；tracked value 与 BG/Dark library add/recursive-add/clear 立即失效；两个 Run 入口再校验 | 没有批准、BLOCKED 或配置已变时不能运行 | 文件 identity 目前是 resolved path、size、mtime，不是所有输入内容 SHA；CAUTION 尚无持久化确认 |
| Tab 3 raw 禁用 | raw 单选按钮禁用；即使程序性强制 raw，正式 K gate 也会拒绝 | 暗场曝光和 NIST blank 契约未统一前不再伪装成正式 raw-1D 全校正 | 原 raw 代码仍存在，应等待共享 2D 核心后再决定是否恢复 |
| 1D 强度状态与实际账本 | formal K/Kd 只接受明确 `relative`；`raw_counts`、absolute、ambiguous 均拒绝；`corrections_applied` 与 `do_not_repeat` union 后防重复，但 required-existing 的物理证明只认 `corrections_applied`；二者冲突即 ambiguous；K/d 要求 `d>0` 并加 K+thickness；K-only 只加 K 且要求 inherited thickness | raw 计数、已绝对化、状态不明、重复或冲突操作全部失败关闭 | K-only inherited thickness 的数值/来源尚未强制 |
| absolute buffer gate | buffer 必须 `absolute_cm^-1`、`1/cm`、`corrections_applied` 含 K+thickness、未含 buffer、显式完整 CalibrationContext fingerprint 且 numeric K 与 active K 匹配；operator payload/do-not-repeat 不可替代；Dry Check 验证 q coverage；报告含 `BufferKFactor`/`BufferAlphaUncertainty`；可选 `u(alpha)` 有限非负、空值保留 None/NaN；统计与合成标准不确定度分列，逐谱保存 alpha/不确定度模型；core kernel 缺失即失败关闭 | 防止相对/不同标度/重复 buffer、弱 fallback、q 外推和误标不确定度，并显式传播 scale uncertainty | 已关闭本轮 UI gate |
| NIST 30 keV 材料核心 | `core/material_attenuation.py` 固定表快照、wt% 解析、理想体积加和密度、μ/ρ、线性 μ、partial uncertainty、孔隙警告和 provenance SHA | NIST 与 xraydb/Elam 来源不再混名；μ 内部值不再截到两位 | NIST 快照只适用于 30 keV；理想密度不是实测/认证合金密度 |
| GUI μ provenance JSON | edited composition 决定 nominal/custom identity；任一输入改变即清空 μ/payload 并禁用 export；export 重读/重哈希 PONI path/content/energy，变化必须重算；Elam 禁用 porosity 并记录 xraydb version；NIST 记录 PONI identity/energy，可用能量非 30 keV 即拒绝；fixed formal metadata/preflight 不带诊断 μ 且记 `mu_used_in_thickness_model=false` | 材料身份、数据库版本、几何兼容、stale 状态和“μ 未参与 fixed 厚度”可追溯 | PONI energy 缺失时明确 `not geometry-bound`；payload 仍未绑定 per-folder accepted raw T |
| 屏幕自适应 | 主 root 和 μ Toplevel 使用 screen-aware geometry；Tab 2/3 与 μ 内容可滚动 | 1024 x 700 等紧凑视口更可操作 | 仍需多 DPI、双语、双主题和键盘矩阵 |
| FabIO close | 严格 1D 两个 reader 与严格 2D resume verifier 在 `finally` 关闭对象 | 这些路径的 Windows 锁/句柄风险已降低 | shared reference loader、严格 2D 主 loader 和多处 Workbench reader 仍未关闭 |

## 科学链与当前契约

### 1. K 标定链

正式 K 必须来自 source-verified CalibrationRecord，并绑定 standard、blank、dark、reference、PONI、
mask、flat、monitor mode、solid-angle/polarization 和估计器参数。Workbench 的 Tab 2/Tab 3 K 只读
只解决“运行时手改值”的问题，不等于 GUI 与严格 runner 已经共享同一个标定编排实现。

SRM 3600 厚度仍锁定为 `0.1055 cm`。系统不确定度在共享 blank/dark 原始计数协方差未量化时应保持
`partial`，不能用证书 coverage factor 代替整条处理链的 coverage factor。

### 2. 固定厚度、逐帧 T 的绝对 2D 链

对厚度不变的原位试样，目标公式保持为：

```text
sample_norm = (S - D * exp_s / exp_D) / (exp_s * MON_s * T_s)
blank_norm  = (BG - D * exp_bg / exp_D) / (exp_bg * MON_bg)
I_abs_2D    = (sample_norm - alpha * blank_norm) * K / d_fixed
```

上式是 `rate` monitor 语义；`integrated` 语义去掉 exposure 因子，但仍保留每帧自己的 `MON_s * T_s`。
固定厚度只替换厚度分支，不得取消每帧 transmission 归一化。

严格 runner 已支持每目录独立 include manifest 和 thickness derivation，并将其哈希纳入 processing
signature、重跑命令及逐帧 metadata。Workbench 现在把 per-frame Beer-Lambert 控件禁用，并在
Dry Check/Run 两次拒绝强制 auto 值；这已关闭旧算法进入正式 GUI 输出的入口。它仍未把“审核帧集合
→ T_rep/MAD/P5-P95 → d_fixed → per-folder row”做成 multi-folder campaign owner，因此这类正式
任务继续由 strict CLI/batch path 承担。

### 3. NIST 30 keV 成分模型

当前锁定名义 wt% 与回归值为：

| 材料 | 名义 wt% | μ (`cm^-1`) |
|---|---|---:|
| Ti-24Nb-4Zr-8Sn | Ti 64, Nb 24, Zr 4, Sn 8 | 74.550355 |
| Ti-6Al-4V | Ti 90, Al 6, V 4 | 20.989980 |
| Zr-2.5Nb | Zr 97.5, Nb 2.5 | 162.949617 |

密度采用元素密度的理想比体积加和，参数来源必须标记为 `composition_model_derived`。它不是样品实际
密度认证值；实际孔隙率未知时不得虚构误差条，EBM 样品还应保留孔隙风险警告。

`mu_calculator.py` 使用的是 xraydb 的 Elam 数据，适合任意能量诊断比较；它不是 NIST XCOM 接口，
也不能在文档或 UI 中写成“XCOM via xraydb”。

Workbench μ 字段已只读。μ 工具按当前编辑后的 composition 重新识别 nominal material；编辑预设成分
后不会继续冒用 preset identity。source、energy/wavelength、preset、composition、density 或 porosity
任一改变都会清空 μ/provenance、禁用 export 并使 Tab 2 preflight 失效。Elam 模式禁用 porosity，JSON
记录 `xraydb_version`。NIST 模式记录 PONI path/hash/energy；若 PONI 提供能量且与 30 keV 不符，计算
失败关闭；PONI energy 不可得时明确记录 `not geometry-bound`，不冒充已经完成几何绑定。

### 4. 绝对 2D 到 1D

严格 1D workflow 的目标是 5500 个 `q_A^-1` 点、CSR 积分、应用 mask 和一次 solid-angle，不重复
dark、background、MON、T、thickness 或 K。它会核对 correction ledger、PONI/mask、输入 manifest、
逐帧签名和输出 profile 哈希。

Workbench 新增的 1D state/ledger 已能防止重复 K/Kd/buffer，并按本次实际执行生成账本：

- `corrections_applied` 表示已经执行的物理操作；`do_not_repeat` 作为执行 guard，两者取 union 做重复检查；
- 两个 ledger 同时存在但集合不一致时，状态变为 ambiguous，正式缩放失败；
- K/d 要求有限且 `d>0`，本次加入 K 和 thickness；
- K-only 只加入 K，并要求 inherited ledger 已含 thickness，不会再次除厚度；
- Tab 3 将最终稳定序列化账本写入逐帧 `CorrectionsApplied`；Tab 2 按实际 CalibrationContext 推导
  dark/background/solid-angle/polarization/flat 等条目。

K-only 当前仍只证明“输入 ledger 声称 thickness 已执行”，尚未要求 inherited thickness 数值与来源。
普通 Tab 2/Tab 3 也没有严格 1D 的 run/frame content-signature resume；不安全的 existence-only resume
已禁用并在 Dry Check/Run 失败关闭，而不是继续作为替代方案。

### 5. Absolute buffer subtraction

buffer 只接受显式 `absolute_cm^-1` 且单位为 `1/cm` 的输入；物理账本
`corrections_applied` 必须含 K 和 thickness、不得已含 buffer。它还必须携带显式完整
CalibrationContext fingerprint，并记录与当前 active K 一致的 numeric `k_factor`；operator payload
fallback 和 `do_not_repeat` 都不能替代绝对尺度证明。Dry Check 在 Run 前验证 sample q grid 完全落入
buffer q range，禁止端点外推；共享 core kernel 不可用时直接失败，不启用简化 fallback。

Workbench 现已提供可选 `u(alpha)`：必须是有限非负值，并传入唯一的 core `subtract_buffer` 参与误差
传播；留空则保存为 `None`，combined uncertainty 继续为 NaN，不把未知值偷设为 0。文本谱中
`Error_Statistical_cm^-1` 只含样品与缩放后 buffer 的统计项，
`Error_CombinedStandard_cm^-1` 再加入 `I_buffer^2 u(alpha)^2`，兼容列
`Error_cm^-1` 在 buffer 路径上指向合成标准不确定度。每个单独谱文件自身也记录 buffer 安全
文件名与 SHA-256、alpha、`u(alpha)`、传播公式和 uncertainty type；逐帧 report 与 run metadata
继续记录 buffer state、unit、physical ledger、context fingerprint、`BufferKFactor`、
`BufferAlphaUncertainty`、完整 path 和 SHA-256。
文本谱重读时，显式命名但全为 NaN 的 combined 列仍被保留为主误差列，不会静默回退到有限的
statistical-only 列；若外部文件同时给出 statistical 和 combined-standard 且没有兼容 Error 列，
combined-standard 也不再受源列顺序影响。这保证“合成不确定度未知”在往返读取后仍然失败关闭。

## 仍未完成的 P0

| 编号 | 缺口 | 为什么仍是 P0 | 目标验收 |
|---|---|---|---|
| P0-1 | GUI 与 strict BL19B2 runner 未统一 | 同一公式仍可能在大回调和 workflow 中漂移 | GUI 只构造严格配置并调用共享 runner；逐像素 probe 两入口一致 |
| P0-2 | formal multi-folder/per-sample campaign 只在 strict owner | Workbench 单一 fixed 输入不能表达各目录 accepted raw T、T_rep、μ、d 与 drift | GUI 调用 strict campaign owner，并逐目录展示 frame identities、T_rep/MAD/P5-P95、μ/d 与 derivation hash |
| P0-3 | K-only inherited thickness 缺数值/来源 | ledger marker 能防重复，但不能完整追溯已经使用的 d | K-only formal input 必须携带有限正 thickness、单位、推导/测量来源和指纹，并与 operator context 一致 |
| P0-4 | Workbench 无 atomic campaign publish/content-signature resume | 虽然 exists-only resume 已彻底禁用，但 Workbench 仍不能安全续跑或证明整批一次完整发布 | owner manifest + staging + atomic publish；run/frame/input/output signature/hash 全匹配才 resume |

## 仍未完成的 P1

| 编号 | 缺口 | 目标 |
|---|---|---|
| P1-1 | preflight identity/CAUTION 尚不完整 | 关键文件由 size/mtime 提升为内容 SHA；CAUTION 逐项确认并写入 run metadata |
| P1-2 | FabIO 只在部分路径 close | 统一 copy-array/copy-header + `finally close` loader，并覆盖正常/异常测试 |
| P1-3 | 无后台 JobController | 长任务进入可取消 worker；Tk 线程只接收进度/结果事件；关闭窗口可安全收尾 |
| P1-4 | 预检与正式 output root 仍需彻底解耦 | 纯预检不占 owner；只有显式报告根才写 preflight artifact |
| P1-5 | 大型 GUI callback 与状态分散 | 将读取、校验、处理、发布拆为测试化 service；增加只读 readiness card |
| P1-6 | 多 DPI/主题/语言/键盘证据不足 | 100/125/150/200% × 中英 × 深浅主题，验证滚动、焦点、截断和非颜色状态 |
| P1-7 | 大批量交互性能未闭环 | 2000 帧预检/筛选不冻结、可取消、计数和失败清单可导出 |
| P1-8 | `audit_outputs/` 与本批测试耦合 | 可复用脚本迁入受控模块；测试改为匿名合成 fixture；大型/私有产物保持 local-only 并显式 ignore |

## UI 精修目标

### 全局 readiness 卡

顶栏应只读显示：K record/fingerprint、formula version、monitor mode、当前科学链、材料/μ 来源、厚度
来源、correction ledger、preflight level/fingerprint、output owner/policy。用户不应再从多个输入框和日志
自行推断“现在能否正式运行”。

### Tab 2：per-folder 表格

推荐列为：

```text
folder | material | accepted/total | T_rep | MAD | P5-P95 | drift
       | mu_source | mu_cm^-1 | d_fixed_cm | derivation_sha256 | status
```

点击行应展开 accepted/rejected frame identities 和原因。表格只接受 include manifest 中的相对路径；
重复、缺失、绝对路径和目录穿越必须失败关闭。已禁用的 per-frame Beer-Lambert 不应重新进入 formal
UI；若未来恢复诊断功能，必须调用隔离的 diagnostic owner，不能与正式结果共用输出目录。

### Tab 3：阶段转换而非公式选择

默认只允许两类操作：

- 打开并检查 `absolute_cm^-1`，可查看/重导出，但不能再乘 K/Kd；
- K/d：将带 `intensity_state=relative`、兼容 operator context 且尚未 K/thickness 的 1D 转为 absolute，
  `d` 必须有限且正；
- K-only：输入必须声明 thickness 已做，本次只乘 K；正式 provenance 仍需补 thickness 数值与来源；
- buffer：只接受 context 匹配、单位 `1/cm`、已含 K+thickness 且 q coverage 完整的 absolute profile。

raw 入口在 sample/BG/dark 独立 exposure、NIST blank、单位和阶段契约统一到共享 2D 核心前保持禁用。

### 输出与运行

每个正式批次应形成不可变 package：

```text
<output-root>/<run-id>/
  config/owner.json
  config/preflight.json
  config/processing_signature.json
  manifests/input_snapshot.csv
  manifests/output_checksums.csv
  metadata/
  data/
  qc/
  logs/
  completion.json
```

创建阶段写入 sibling staging 目录；只有全部目录、帧、哈希和 completion 校验通过后才原子发布。正式
UI 不应原地 overwrite 历史 run；新结果用新 run ID，并在 metadata 中记录 `supersedes`。

## 实机截图对照验收方法

本轮 UI 截图属于会话级 visualization 产物，不在仓库内，也不是科学输出 provenance；因此本报告不
硬链任何仓库外绝对路径。

验收方法如下：

1. before/after 使用相同屏幕、窗口尺寸、DPI、语言、主题和 active tab；
2. 只捕获 Workbench 窗口，优先使用 Win32 `PrintWindow` 一类隔离窗口方法；
3. 排除带远程控制覆盖层、黑区、窗口边框缺失、文字不可辨认或滚动位置不一致的图片；
4. Tab 1/2/3 与 μ 窗口逐一对照可达性、滚动/截断、K/μ 只读、raw/legacy/resume/Run 禁用状态和状态栏；
5. 截图清单与实机验收日志一起保存在会话产物中，但发布文档只记录方法和结论，不伪装成版本化证据。

静态截图不能证明键盘顺序、长任务取消、文件锁、2000 帧性能或科学公式正确性；这些必须由单测、
数值 probe 和动态手工验收分别证明。

## 发布验收矩阵

| 领域 | 期望 | 当前状态 |
|---|---|---|
| 固定厚度 formal gate | Tab 2 只允许 fixed；逐帧 T 仍影响 norm | **UI disabled + Dry Check/Run hard block 已实现** |
| legacy resume | Tab 2/3 exists-only control 不可选，强制开启也拒绝 | **已实现** |
| K/μ 只读 | Tab 2 K/μ 与 Tab 3 K 不能手改 | **已实现** |
| preflight | 无批准/BLOCKED/配置变动不能 Run；BG/Dark mutation 立即失效 | **已实现；内容 SHA 与 CAUTION 确认待补** |
| Tab 3 raw | UI 禁用且强制进入也被正式 gate 拒绝 | **已实现** |
| 1D 阶段/账本 | K/d `d>0`；K-only 不重复 thickness；do-not-repeat union/conflict；report ledger 一致 | **已实现；K-only thickness 数值/来源待补 P0** |
| absolute buffer | 1/cm + physical K/thickness + full context + matching K + q coverage + `u(alpha)` + 统计/合成不确定度分列 | **已实现；未知 `u(alpha)` 保持 None/NaN，逐谱 provenance 完整** |
| NIST μ | edited identity、stale invalidation、PONI energy check、Elam xraydb version | **已实现；缺 PONI energy 明示 not geometry-bound** |
| per-folder derivation | accepted raw T 清单 + per-folder 表格/owner + hash | **strict campaign 已有；Workbench 待实现 P0** |
| GUI/runner 单实现 | Workbench 直接调用严格 2D/1D workflow | **待实现 P0** |
| output owner/atomic batch | 整批要么完整发布，要么明确 incomplete | **待实现 P0** |
| Workbench safe resume | signature/hash/完整输出集一致才 skip | **待实现 P0；exists-only 已禁用** |
| FabIO close | 所有读取路径正常/异常均无句柄泄漏 | **部分实现 P1** |
| JobController | UI 不冻结、可取消、异常可收尾 | **待实现 P1** |
| 屏幕 geometry | 1024 x 700 初始可达 | **代码已实现；多 DPI 实机矩阵待补** |
| v4 冻结 | 升级前后 H 盘全树 SHA-256 清单一致 | **待现场复验** |
| 三材料 probe | 逐像素公式、HDF5/EDF 一致、K 固定 | **由主批次验收报告确认，不在本文档冒充完成** |

## 发布判定

当前最准确的产品状态是：

- 严格 BL19B2 runner：正式 campaign 处理基线；
- Workbench：固定厚度/legacy/resume 硬门、K/μ/preflight、K-only/Kd/do-not-repeat、absolute buffer、
  NIST/Elam/PONI provenance 等防误操作升级已落地，但尚不是 strict runner 的等价前端；
- multi-folder campaign owner、kernel unification、K-only inherited thickness 数值/来源、
  atomic campaign publish/content-signature resume 是必须明确保留的边界；
- FabIO 全路径、JobController、CAUTION 持久确认和多 DPI/accessibility 仍是工程 P1。

只有 P0 全部关闭、GUI 与 runner 单实现、v4 冻结哈希通过、三材料 probe/全量 resume 通过并完成多 DPI
实机矩阵后，才能把 Workbench 对外描述为“严格科学处理 UI”。
