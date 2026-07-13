# SASAbs v2 全量项目审计与发布闭环报告

审计日期：2026-07-13（Asia/Shanghai）
仓库：`E:\desktop\SASAbs_saxs-absolute-calibration`
当前分支：`codex/sasabs-release-hardening`
基线：`main@6ba966c715753f59a44009f1ee2ab07d15fc93f5`
审计模式：full + release hardening

## 1. 执行摘要

结论：**建议快进合并/push。**

原始审计共登记 24 项：P0=0、P1=10、P2=12、P3=2。当前状态为
**verified=21、blocked=0、open=3**。全部 P1 已闭环；仍开放的 AUD-015、AUD-017、AUD-020
分别受限于可见 GUI/人工 dark exposure 证据、GUI 主线程真实交互体验、真实大批次/束线性能基准，
不构成当前代码安全 gate 的已知阻塞。

本轮把版本升级到 2.0.0，并完成以下发布关键路径：

1. 公共 API 恢复历史位置参数兼容；新参数 keyword-only。
2. v2 CLI 使用显式安全参数；危险历史假设只通过显式 `bl19b2-abs2d-v1-legacy` 入口启用。
3. BL19B2 重跑命令覆盖 mask、标准、几何修正与执行策略；monitor mode 单边界规范化。
4. 标准端不确定度使用实际估计器的有限差分灵敏度；reference/system coverage 分离。
5. 缺少 raw BG/dark covariance 时，combined uncertainty 正确保持 `partial`，不伪报 complete。
6. CalibrationRecord v2 绑定源文件、模型、reference、integration 和 robust estimator；正式输出前重新读取并校验当前源文件。
7. SRM 3600 别名统一、厚度锁定 0.1055 cm，并加入保守平行性 QC；μ 成分输入消除 1/100 尺度歧义。
8. Tab2/Tab3 正式输出统一使用当前 record/context gate，严格处理 Q/2θ/χ 与 q 单位。
9. Cal2D 五件套采用事务 staging/no-overwrite/rollback；rollback 不删除并发替换文件；整包 rerun 身份一致。
10. text/canSAS/NXcanSAS 自产 1D provenance 可写入、重读并通过 formal gate。
11. K history、稳定读后哈希、resume provenance、worker/stem、launcher cwd/log 等 P2 安全项闭环。
12. README、architecture、runbook、CHANGELOG 与版本元数据同步至 v2 安全合同。

最终冻结树代码、artifact 与独立 QA 门禁全部通过：

- 最终 pytest：`500 passed in 19.00s`；JUnit `.audit-work/pytest-release-final-v6.xml`
- 最终 ruff/compileall/diff-check：`全部通过`
- 最终 wheel/sdist build：通过；wheel 隔离 target import、CLI、launcher、entry points smoke 全部通过
- 最终 wheel：`saxsabs-2.0.0-py3-none-any.whl`；SHA-256 `154AF0ECC504619DED8C7C23BC2C43C208E047FAEC9C751394BE49EF025C4A9F`
- 最终 sdist：`saxsabs-2.0.0.tar.gz`；SHA-256 `7080CC47DB13B9DCBEED448AA4F3D1F234AC506C66AFB76D3D98867ED4CE9DCC`
- 最终独立 QA：A/B/C/D/resume 全部 PASS；定向 8 + 96 tests；无新增 P0/P1/P2

## 2. 架构与发布范围

### 主要入口与数据流

- 安装包：`src/saxsabs/`。
- 科研核心：`src/saxsabs/core/`。
- 解析与导出：`src/saxsabs/io/`。
- CLI：`src/saxsabs/cli.py` 与 `src/saxsabs/__main__.py`。
- 桌面工作台：`SASAbs.py`、`saxsabs_workbench.py`、`saxsabs_workbench.pyw`。
- BL19B2 批处理：`src/saxsabs/workflows/bl19b2_abs2d.py`。
- Tab1：标准/BG/dark/几何 → K、record/context。
- Tab2：样品/BG/dark → 归一化与校准 → 1D/sector/χ/Cal2D。
- Tab3：外部或自产 1D → provenance/axis gate → buffer/绝对标度 → 多格式导出。
- BL19B2：配置/输入快照 → reference/mask/K → per-frame 2D → QC/provenance/rerun。

### Git 与资产边界

- 初始 `main` 与 `origin/main` 为 0/0；当前修复位于 `codex/sasabs-release-hardening`。
- 用户未跟踪资产 `docs/superpowers/` 未修改，不属于发布提交。
- 本报告与 `.audit-work/*.md` 是审计产物；生成的 XML、wheel、cache 不应作为源码提交。
- 当前尚未执行暂存、commit、merge、push 或分支删除。

## 3. 风险闭环地图

| 区域 | 原风险 | 当前控制 | 状态 |
|---|---|---|---|
| API/CLI 兼容 | 位置参数错位；同版本隐式安全语义变化 | 恢复位置兼容；2.0.0 + 显式 legacy | verified |
| rerun/provenance | mask、策略、科学参数不能完整重放 | CLI/Config/rerun/signature 全字段贯通 | verified |
| uncertainty | 标准端缺项仍 complete；证书 k 外推 system | 有限差分与 shared-variable 灵敏度；coverage 分离；未知 covariance 为 partial | verified |
| calibration record | K 来源不完整；缓存验证可被源文件事后变化绕过 | schema v2 + source hash/model/参数；formal gate 每次重读复验 | verified |
| SRM/μ | 错厚度、不平行 ratio、成分尺度含糊 | 0.1055 cm、alias/QC、比例严格归一化 | verified |
| Tab2/Tab3 信任 | 默认 K、axis 混淆、auto/dry-run 分叉、1D 回读丢 provenance | 当前 record/context gate；严格 axis；共享验证；round-trip provenance | verified |
| Cal2D 输出 | 残包、跨运行混合、rollback 误删竞争文件 | 五件套 gate、事务 staging/no-overwrite、samefile rollback、package rerun ID | verified |
| history/input state | CSV 损坏覆盖、read→hash TOCTOU、resume 改写创建信息 | fail-closed+原子写；双哈希/stat；last_resume_validation | verified |
| launcher/path | cwd 阴影、不可写日志、极端 worker/stem | package 优先、日志 fallback、1..32、稳定短名 | verified |
| 可见 GUI | 布局、DPI、人工 dark exposure 路径未完成真实点击 | 仅 headless 逻辑 gate 有证据 | open |
| 真实性能 | 大批次/束线存储吞吐未知 | 不宣称性能提升 | open |

## 4. 问题状态

| 状态 | ID |
|---|---|
| verified（21） | AUD-001～AUD-014、AUD-016、AUD-018、AUD-019、AUD-021～AUD-024 |
| open（3） | AUD-015、AUD-017、AUD-020 |
| blocked（0） | 无 |

完整字段、触发条件、影响、修复和证据映射见 `.audit-work/findings.md`。

### QA 最后一轮补充闭环

- AUD-011：Cal2D rollback 原先可能在后续成员冲突时删除竞争者已替换的目标。现在只有当目标仍与本事务 staged 文件为同一文件时才清理，否则保留。
- AUD-007/AUD-010：正式 gate 不再只信任内存中的验证布尔值；每次重新读取 record、复验源文件与当前 context/K。自产 text/canSAS/NXcanSAS 写入并回读 operator provenance。
- AUD-019/AUD-021：resume 校验不覆盖首次创建 provenance，另写 `last_resume_validation`。
- AUD-008：工作流入口统一 SRM aliases，避免 core 正确而 workflow 分叉。

## 5. 科研语义审计结论

### 已验证合同

| 合同 | 当前结论 |
|---|---|
| K 方向与厚度单位 | 保持 `I_ref / I_meas_per_cm`；mm→cm 路径有回归 |
| SRM 3600 厚度 | 证书路径固定为 0.1055 cm；错误 override 提前拒绝 |
| SRM 平行性 | 非平行 ratio 不再静默压缩为单一 K |
| μ composition | 总和约 1 或 100 的完整输入归一化到 1；其他拒绝 |
| 标准端 uncertainty | T、MON、BG-MON、thickness、alpha 通过实际估计器有限差分传播 |
| 共享变量 | shared alpha 与 shared BG monitor 按联合灵敏度处理 |
| coverage | reference 与 system 分开；证书 coverage 不外推到未知组合预算 |
| combined status | raw BG/dark covariance 无输入时为 `partial`，未知项不设为 0 |
| custom reference | raw 与 canonical q/I/u/U、模型与哈希进入 record |
| axis/unit | Q、q_nm⁻¹、2θ、χ 分流；2θ 需要波长；不一致坐标拒绝 |

### 严格边界

- 未提供 raw BG/dark covariance，因此不能声称获得完整 system expanded uncertainty。
- 未用真实 BL19B2 或其他束线原始数据验证物理结果；当前证据来自测试夹具、匿名最小样例、人工数值反例和代码审查。
- schema v1 记录仅为兼容读取，不升级为 complete 或可信正式输出来源。
- 没有真实标准、样品、detector、PONI 与束线 metadata 的联合数据时，不把软件门禁等同于束线端计量认证。

## 6. 输出、provenance 与恢复安全

### CalibrationRecord v2

- source files 使用相对路径并按顺序记录 SHA-256。
- 标准、BG、dark、custom reference、模型 id/version/canonical hash、alpha、background rule、integration unit/method/version/npt、robust estimator 参数均绑定到记录。
- record 读取时验证 schema 与 source；正式 Tab2/Tab3 导出前再次从磁盘读取并验证，避免源文件在 GUI 会话中被篡改/删除后继续使用旧缓存状态。
- K history CSV 遇损坏 fail-closed；更新使用临时文件、fsync 和原子替换。

### Cal2D package

- resume 要求 image、mask NPY、mask EDF、PONI、metadata 全部存在、shape 一致且 context/参数/引用匹配。
- 写入先进入 staging，再执行 no-overwrite 提交。
- 任一成员冲突时回滚本事务已提交成员；只有仍与本事务 staged inode/file identity 一致的目标才删除，保护并发替换文件。
- always-run 使用 package-level rerun ID，避免一个科学包混入多个运行的成员。
- creation provenance 保持不变，后续验证写入独立 `last_resume_validation` 字段。

### 1D 导出回读

- text、canSAS XML 与 NXcanSAS HDF5 均可携带 calibration context fingerprint/operator provenance。
- parser 把核心格式 provenance 与文本注释 provenance 合并。
- 自产文件重新导入后仍必须经过当前 record/context gate，不因“由本软件写出”而放宽信任边界。

## 7. GUI 与可操作性

### 已有证据

- Tab2 auto-reference 不再被 fixed reference 预加载阻断。
- dry-run 与正式输出复用同一安全 gate。
- Tab3 正式输出要求当前、完整、源文件可验证的 calibration record。
- raw 外部 1D 需要可审计 operator provenance；axis 和单位不允许猜测。
- workers 限制 1..32，超长 stem 使用稳定短名。
- launcher 避免 cwd shadow，日志可回退用户/临时目录。

### 未完成证据

- 自动化启动没有出现可接管的可见 GUI 窗口。
- 因此未完成真实鼠标/键盘点击、窗口缩放、DPI、主题、滚动、控件遮挡与截图验收。
- 未通过可见 GUI 验证人工 dark exposure 主路径。
- 上述边界保留为 AUD-015/AUD-017 open，不能把 headless 测试写成视觉验收。

## 8. 性能与真实数据边界

已通过共享 parser、buffer 单次预载、稳定输入 gate 等方式减少可证明的重复工作，但没有在真实大批次、
真实 detector 图像、NAS/束线存储、432 帧等条件下重新建立吞吐、峰值内存和失败恢复基准。
AUD-020 保持 open；报告不声称性能提升，也不以本地匿名临时数据替代束线性能。

## 9. 验证状态

### 已完成的中间证据

- 最后一轮科学 QA：316 项聚焦测试通过，科研域 PASS。
- BL19B2 最新聚焦回归：119 passed。
- Cal2D exporter 事务/竞态聚焦回归：15 passed。
- 发生在最终 QA 修复之前的中间全量回归：473 passed。
- 中间 wheel 可构建、安装并包含 legacy GUI、launcher 和两个 console entry points。

这些是中间修复证据，不能替代最终冻结结果。最终树随后以 500 passed、静态检查通过、版本 2.0.0、wheel/sdist 构建与隔离 smoke 通过完成放行；最终 artifact 哈希见下表。

### 最终门禁

| 检查项 | 要求 | 当前结果 |
|---|---|---|
| 全量 pytest | 0 fail；保存 JUnit XML | `500 passed in 19.00s`；`.audit-work/pytest-release-final-v6.xml` |
| ruff | `ruff check src tests SASAbs.py saxsabs_workbench.py` | `通过` |
| compileall | package、GUI 与 launcher 全部可编译 | `通过` |
| diff check | `git diff --check` 无错误 | `通过` |
| version smoke | CLI、package、legacy 入口一致为 2.0.0 | `2.0.0` |
| wheel/sdist build | 冻结树重新构建 | `通过`；`saxsabs-2.0.0-py3-none-any.whl`、`saxsabs-2.0.0.tar.gz` |
| wheel install smoke | 隔离 target import、CLI、launcher、entry points | `全部通过` |
| wheel SHA-256 | 最终 artifact 身份 | `154AF0ECC504619DED8C7C23BC2C43C208E047FAEC9C751394BE49EF025C4A9F` |
| sdist SHA-256 | 最终 artifact 身份 | `7080CC47DB13B9DCBEED448AA4F3D1F234AC506C66AFB76D3D98867ED4CE9DCC` |
| 独立 QA | A/B/C/D/resume；无新增 P0/P1/P2 | 全部 PASS；定向 8 + 96 tests |

详细命令、历史证据与最终证据槽位见 `.audit-work/evidence.md`。

## 10. 发布与 Git 建议

当前唯一结论：**建议快进合并/push。**

门禁通过后的安全顺序：

1. 确认 `docs/superpowers/` 仍为用户资产并以可逆方式排除。
2. 只精确暂存预期源码、测试、文档和审计 Markdown；不使用不经审查的全量暂存。
3. 检查 staged diff、`git diff --cached --check`、版本与生成物排除情况。
4. 提交 `codex/sasabs-release-hardening`。
5. `git fetch --prune` 并确认 `origin/main` 未漂移。
6. 切换 `main`，`git pull --ff-only origin main`，再 `git merge --ff-only codex/sasabs-release-hardening`。
7. 必要 smoke 通过后 `git push origin main`；观察远端 CI 到终态。
8. 只有 push/CI 成功后，使用 `git branch -d codex/sasabs-release-hardening` 删除已合并本地分支。
9. 不 force push，不使用 `-D`，不删除用户 stash/资产。

任何最终门禁失败、远端漂移、CI 失败或 staged 范围异常都应停止合并/push。

## 11. 最终自检

- [x] 24 项问题均有状态；P0/P1/P2/P3=0/10/12/2。
- [x] verified/open/blocked=21/3/0。
- [x] 全部 P1 闭环；QA 新发现已归入原问题账本。
- [x] AUD-015、AUD-017、AUD-020 保持 open，未虚构可见 GUI 或真实束线/性能证据。
- [x] combined uncertainty 的未知 covariance 明确保持 partial。
- [x] 用户 `docs/superpowers/` 资产不在发布范围。
- [x] 未把中间 473 passed 或旧 wheel 哈希冒充最终结果。
- [x] 最终 pytest/ruff/compile/diff-check 已在冻结树通过：`500 passed in 19.00s`，静态门禁全部通过。
- [x] 最终 wheel/sdist 构建、隔离 smoke 与 SHA-256 已记录并通过。
- [x] 最终独立 QA A/B/C/D/resume 已通过；定向 8 + 96 tests，无新增 P0/P1/P2。
- [ ] commit/快进合并/push/CI/分支清理已完成：尚未执行。
