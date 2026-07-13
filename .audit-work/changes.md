# 修改账本

本账本描述 v2 发布硬化的代码闭环；最终冻结门禁为 `500 passed in 19.00s`，ruff/compileall/diff-check 通过，版本 `2.0.0`，wheel/sdist 与隔离安装 smoke 通过，独立 QA 无新增 P0/P1/P2。所有修改均应在精确暂存前再次由 `git diff` 核对。

## CHG-001｜AUD-001

- 范围：BL19B2 safe PONI 身份与续跑。
- 修改前：存在旧 safe PONI 时可能静默复用；pydidas 路径可能直接覆盖。
- 修改后：先渲染并比较内容/哈希；几何不一致时 fail-closed，不改变既有 safe PONI。
- 兼容性：相同几何续跑不变。
- 验证：普通 PONI、pydidas Cali.yaml 的 red→green 与回归。
- 回退风险：移除一致性门会重新允许 provenance 错配。

## CHG-002｜AUD-002/AUD-011/AUD-012

- 范围：Workbench Cal2D 五件套、事务提交、resume 与 rerun。
- 修改前：仅主 EDF 存在即可 skip；写入中断会留残包；并发冲突 rollback 可能误删后来者文件。
- 修改后：image/mask NPY/mask EDF/PONI/metadata 及 shape/context/参数联合验证；staging 后 no-overwrite 提交；rollback 仅在目标仍与本事务 staged 文件 `samefile` 时清理；整包使用同一 rerun ID。
- 兼容性：完整且身份一致的包仍可 resume；残缺、损坏、错配或竞争目标明确失败。
- QA 补充：Cal2D rollback 竞态闭环归入 AUD-011。
- 验证：fault injection、并发替换、残包、目录 PONI、package-level rerun 聚焦测试。
- 回退风险：会重新出现混合科学包或外部文件误删风险。

## CHG-003｜AUD-003

- 范围：calibration 与 buffer subtraction 公共 Python API。
- 修改前：新增参数插入历史位置参数顺序，旧合法调用确定性错位。
- 修改后：恢复旧位置参数顺序；新增参数设为 keyword-only。
- 兼容性：旧位置调用恢复；新调用语义保持显式。
- 验证：旧调用反例、关键字新调用和全量回归。

## CHG-004｜AUD-004/AUD-005/AUD-013

- 范围：BL19B2 CLI、Config、重跑脚本、签名与版本迁移。
- 修改前：危险旧默认值隐式存在；mask、执行策略和非默认科学字段不能完整重放；monitor mode 规范化分叉。
- 修改后：版本升为 2.0.0；安全 v2 入口要求显式参数；`bl19b2-abs2d-v1-legacy` 仅在显式确认后恢复旧假设；mask、standard、solid-angle、polarization、run policy 全字段贯通；monitor mode 单边界规范化。
- 兼容性：不伪装为 v1.1.1；历史行为仍有显式、可审计入口。
- 验证：CLI help/parse/migration、Config→rerun→Config 往返、签名一致性。

## CHG-005｜AUD-006

- 范围：科研不确定度预算与 coverage 语义。
- 修改前：样品端分量齐全时可能在缺标准端贡献的情况下返回 complete，并把证书 coverage factor 外推到组合 system budget。
- 修改后：通过中心有限差分重跑实际估计器传播标准 T/MON/BG-MON/thickness/alpha；shared alpha 与 shared BG monitor 采用联合灵敏度；reference 与 system coverage 分离。
- 语义边界：raw BG/dark covariance 未提供时，combined uncertainty 必须为 `partial`，system expanded uncertainty 不可用；未知量不当作 0。
- 验证：缺项、共享变量、有限差分和 coverage 反例；独立科研 QA。
- 回退风险：会重新产生虚假的 complete/expanded uncertainty。

## CHG-006｜AUD-007/AUD-018/AUD-019

- 范围：CalibrationRecord schema v2、source identity、K history。
- 修改前：record 未完整绑定标准/BG/dark/custom reference、模型与统计参数；缓存的校验布尔值可在源文件事后变化后继续被信任；历史 CSV 损坏或中断存在覆盖风险。
- 修改后：source 使用相对路径和有序 SHA-256；自定义 reference 同时保存 raw/canonical q-I-u-U；SRM/Water 保存 model id/version/canonical hash；记录 alpha、BG rule、integration、robust estimator；读取和正式使用时复验源文件；K history 损坏即停并采用临时文件+fsync+原子替换。
- 兼容性：v1 可读但明确 incomplete，不自动升级为可信 v2。
- QA 补充：record reload/source tamper 闭环归入 AUD-007。
- 验证：round-trip、移动、篡改、删除、损坏 CSV、no-clobber 和 v1 兼容测试。

## CHG-007｜AUD-008

- 范围：SRM 3600 标准身份、厚度与平行性 QC。
- 修改前：别名分叉且可接受非证书厚度；不平行 ratio 仍可产出 K。
- 修改后：统一 `SRM3600`、`srm-3600`、`nist_srm3600`、`NIST SRM 3600` 等别名；隐式/显式厚度均约束为 0.1055 cm；不满足保守平行性门即拒绝。
- 兼容性：正确证书参数不变；错误 0.1 cm 等输入提前失败。
- 验证：别名参数化、厚度正反例、ratio QC 与 GUI/CLI 接线测试。

## CHG-008｜AUD-009

- 范围：μ composition 输入与 GUI 接线。
- 修改前：`Fe:95` 或其他非规范总和仅 warning 后继续。
- 修改后：只接受总和约 1 的分数或约 100 的完整百分比，并精确归一化到 1；含糊/残缺尺度 fail-closed。
- 兼容性：化学式和单元素合法路径保留。
- 验证：分数、百分数、边界、异常值及 GUI 聚焦测试。

## CHG-009｜AUD-010/AUD-014/AUD-015/AUD-016

- 范围：Tab2/Tab3 正式输出信任、auto-reference、dry-run、1D provenance。
- 修改前：正式 gate 可依赖缓存 record 状态；auto-reference 先加载 fixed references；dry-run 与正式验证漂移；自产 1D 导出后回读丢 calibration context。
- 修改后：正式 gate 每次重读 record、复验源文件与当前 context/K；auto-reference 按真实分支加载；dry-run 复用正式安全 gate；text/canSAS/NXcanSAS 写入 operator provenance，parser 回读并与注释 provenance 合并。
- 单位边界：Q、2θ、χ 严格区分；`q_nm^-1` 转换为 Å⁻¹；2θ 必须有波长；跨轴不一致拒绝。
- QA 补充：1D provenance round-trip 闭环归入 AUD-010。
- 验证：writer→reader→formal gate、source tamper、axis/单位、auto refs 与 dry-run 聚焦测试。
- 未闭环：可见 GUI/布局和人工 dark exposure 证据仍属于 AUD-015 open。

## CHG-010｜AUD-017/AUD-020/AUD-021

- 范围：资源上限、稳定输入快照、重复读取与 resume provenance。
- 修改前：workers 无上限、长 stem 可能越界；read→hash 存在 TOCTOU；resume 验证会覆盖首次创建信息。
- 修改后：workers 限制 1..32；stem 最长 120 字符并附稳定哈希；关键输入采用读前/读后双哈希+stat 一致性门；buffer/reference 共享 parser 并单次预载；resume 另记 `last_resume_validation`。
- QA 补充：creation provenance 不可变闭环归入 AUD-019/AUD-021。
- 验证：极值 worker、长路径、输入变化、parser 调用计数和 resume metadata 测试。
- 未闭环：真实桌面主线程体验和真实大批次/束线性能仍为 AUD-017/AUD-020 open。

## CHG-011｜AUD-022

- 范围：Workbench launcher 与 Windows 启动脚本。
- 修改前：cwd 可阴影正确模块；日志写 cwd 会在只读目录失败。
- 修改后：优先解析已安装 package/source；日志写用户目录，失败时回退临时目录；启动脚本不再注入 cwd。
- 验证：cwd shadow、不可写日志、入口解析和 subprocess smoke。
- 未覆盖：自动化未获得可接管的可见窗口。

## CHG-012｜AUD-023/AUD-024

- 范围：版本元数据、sdist manifest、生成目录 ignore 和用户/维护者文档。
- 修改后：`pyproject.toml`、package、legacy launcher、CITATION、codemeta、根 `.zenodo.json` 统一 2.0.0；README、architecture、runbook、CHANGELOG 更新安全边界、六子命令、legacy 迁移和 provenance 合同；新增 `MANIFEST.in` 将 CHANGELOG/CITATION/codemeta/.zenodo/tests/conftest 纳入 sdist；新增 `.audit-work/sdist-*/` ignore。
- 历史边界：submission/software paper 的既有 1.1.1 内容保留为历史快照并明确说明，不伪造回溯版本。
- 验证：根 metadata 版本一致性、CLI version、文档核对；sdist 解包根包含 release metadata 与 `tests/conftest.py`，解包内 version tests `2 passed`。
- 最终构建：`.audit-work/dist-release-final-v4/` 中 wheel 与 sdist 构建通过；wheel 隔离 smoke、sdist 解包与 version tests 通过。

## 最终门禁状态

- 全量 pytest：`500 passed in 19.00s`；`.audit-work/pytest-release-final-v6.xml`
- ruff/compileall/diff-check：`全部通过`
- wheel/sdist build：通过；wheel 隔离 target import/CLI/launcher/entry points 通过；sdist 解包 metadata/conftest 完整，解包内 version tests `2 passed`
- wheel SHA-256：`154AF0ECC504619DED8C7C23BC2C43C208E047FAEC9C751394BE49EF025C4A9F`
- sdist SHA-256：`7080CC47DB13B9DCBEED448AA4F3D1F234AC506C66AFB76D3D98867ED4CE9DCC`
- 独立最终 QA：A/B/C/D/resume 与 release metadata/packaging 全部 PASS；无新增 P0/P1/P2