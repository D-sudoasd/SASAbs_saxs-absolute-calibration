# 证据账本

说明：EV-001～EV-019 是初始审计和首轮修复的历史证据；它们不能替代当前冻结树的最终门禁。
新增 v2 闭环证据列于 EV-020 之后。EV-030～EV-033 是当前冻结树的最终门禁，均已通过。

| EV-ID | 目的 | 命令/方法 | 环境/工作目录 | 状态 | 关键输出 | 日志/产物 | 支持范围 |
|---|---|---|---|---|---|---|---|
| EV-001 | Git 基线 | branch/HEAD/status/merge-base/rev-list | PowerShell；仓库根 | pass | `main@6ba966c`；初始 origin 0/0；`docs/superpowers/` 为用户未跟踪资产 | `.audit-work/state.md` | 范围/保护 |
| EV-002 | 比较范围 | `git diff --name-status/--stat 0a3d680..HEAD` | 仓库根 | pass | 旧审计比较范围已登记 | 初版报告 | 风险地图 |
| EV-003 | 修改前 pytest | `py -3.11 -m pytest -q --tb=short --junitxml=.audit-work\pytest-baseline.xml` | Python 3.11；受限网络 | partial | 309 passed；隔离 wheel 依赖下载失败 | `.audit-work/pytest-baseline.xml` | 基线 |
| EV-004 | 基线构建替代验证 | 本地 build 依赖 + `--no-build-isolation` | 仓库根 | pass | 基线 wheel 可构建 | `.audit-work/wheel-baseline/` | 打包基线 |
| EV-005 | 静态/语法基线 | ruff；compileall | Python 3.11 | pass | 全通过 | 工具输出 | 基线 |
| EV-006 | 入口/核心 smoke | CLI/workbench version；83 项聚焦 pytest | Python 3.11 | pass | 基线 v1.1.1；83 passed | 初版报告 | 基线 |
| EV-007 | API/CLI 初始审计 | 调用链、直接旧调用、90 项聚焦测试 | 仓库根 | pass | 定位位置参数、CLI、rerun、文档缺陷 | 初版报告 | AUD-003/004/005/023/024 |
| EV-008 | 科研数值初始审计 | 130 项核心测试、人工小样例、规范核对 | Python 3.11 | pass | 主公式正确；定位 uncertainty/SRM/μ/record 缺口 | 初版报告 | AUD-006/007/008/009/018 |
| EV-009 | I/O 初始审计 | 106 项聚焦测试、fault injection、writer 调用映射 | Python 3.11 | pass | 定位 stale PONI、残缺 Cal2D、事务/移植性风险 | 初版报告 | AUD-001/002/011/012/019 |
| EV-010 | GUI/参数流初始审计 | 35 项 headless、withdrawn Tk geometry、可见 UI 尝试 | Windows/Tk | partial | 逻辑路径有证据；可见窗口不可接管，无截图 | 初版报告 | AUD-010/014-017/019/022 |
| EV-011 | safe PONI red | changed-source 反例 | Python 3.11 | expected-fail | 2 个反例修复前未拒绝 | 测试输出 | AUD-001 |
| EV-012 | safe PONI green | 同反例 + 正常 PONI writer | Python 3.11 | pass | 3 passed | 测试输出 | AUD-001 |
| EV-013 | Cal2D 首轮闭环 | package validator、目录 PONI、残包 | Python 3.11 | pass | focused tests passed | 测试输出 | AUD-002 |
| EV-014 | rerun/monitor red-green | 策略字段、monitor 规范化 | Python 3.11 | pass | 修复前失败，修复后通过 | 测试输出 | AUD-005/013 |
| EV-015 | 性能/状态初始测量 | 调用计数、匿名 TIFF/DAT、tracemalloc、TOCTOU 复现 | 本地临时数据 | pass | 识别资源、重复读取、输入变化风险；不代表束线性能 | 初版报告 | AUD-017/020/021 |
| EV-016 | 首轮 pre-QA 回归 | pytest/ruff/compile/wheel/CLI | Python 3.11 | historical-pass | 314 passed、1 deselected；后续代码已继续变化 | `.audit-work/pytest-final.xml` | CHG-001..003 历史证据 |
| EV-017 | 首轮独立 QA | 两名只读 reviewer + 聚焦测试 | Python 3.11 | discovery | 发现 mask/CLI 字段/空目录/账本缺口 | 初版报告 | 触发进一步修复 |
| EV-018 | 首轮 post-QA 回归 | pytest/ruff/compile/wheel | Python 3.11 | historical-pass | 首轮中间回归通过；旧 wheel 哈希仅属中间树 | `.audit-work/pytest-final-after-qa.xml` | 首轮修复历史证据 |
| EV-019 | 首轮 QA 复核 | 两名只读 reviewer | Python 3.11 | superseded | 当时未发现新增 P0-P2；后续深度 QA 又发现闭环缺口 | 初版报告 | 历史，不作为最终放行 |
| EV-020 | API、Cal2D、SRM 闭环 | calibration/Cal2D/BL19B2 聚焦测试，含旧位置调用与厚度反例 | Python 3.11 | pass | API 兼容；SRM aliases/0.1055 cm/QC；BL19B2 最新聚焦 119 passed | 测试输出 | AUD-002/003/008/011 |
| EV-021 | v2 CLI/legacy/重放 | CLI parse/help/migration；Config→rerun 往返 | Python 3.11 | pass | 安全 v2 与显式 v1 legacy 分离；字段可重放 | 测试输出 | AUD-004/005/013 |
| EV-022 | 不确定度语义 | finite-difference、shared variables、coverage/status 反例 | Python 3.11 | pass | 标准端灵敏度闭环；combined unknown covariance 保持 partial | 测试输出 | AUD-005/006 |
| EV-023 | record/context/history | v2 round-trip、relative source、hash tamper/delete、v1 incomplete、CSV fault | Python 3.11 | pass | source/model/参数身份绑定；损坏记录 fail-closed | 测试输出 | AUD-007/018/019 |
| EV-024 | μ 输入 | fractions/percent/ambiguous totals 参数化测试 | Python 3.11 | pass | 合法输入归一化至 1；含糊输入拒绝 | 测试输出 | AUD-009 |
| EV-025 | GUI/output/launcher 安全 | headless formal gates、axis、auto refs、transaction、stable snapshot、launcher smoke | Windows/Python 3.11 | pass-with-boundary | 代码/逻辑 gate 通过；无可见窗口证据 | 测试输出 | AUD-010/011/012/014-017/019-022 |
| EV-026 | version/docs/manifest | 版本一致性测试、CLI version、README/architecture/runbook/changelog、MANIFEST 核对 | 仓库根 | pass | package/CITATION/codemeta/根 `.zenodo.json` 统一 2.0.0；sdist 必需 metadata/conftest 纳入 manifest；历史 submission 快照保留 | `tests/test_version_metadata.py` 与文档/manifest diff | AUD-023/024 |
| EV-027 | 中间全量门禁 | `py -3.11 -m pytest -q --tb=short --junitxml=.audit-work\pytest-release-final-v2.xml`；ruff/compile/diff-check | Python 3.11 | historical-pass | 473 passed；发生于最后一轮 QA 修复之前，**不得作为最终数量** | `.audit-work/pytest-release-final-v2.xml` | 中间回归 |
| EV-028 | 中间构建与安装 smoke | `python -m build --no-isolation`；wheel install target；entry point/package content 检查 | Python 3.11 | historical-pass | 中间 wheel 可构建/安装；README 与最终 QA 修复后源码继续变化，旧哈希作废 | `.audit-work/dist-release-final/` | 中间打包证据 |
| EV-029 | 最后一轮独立 QA 发现项 | 科研、I/O/兼容、Git/release 三域只读审查与聚焦回归 | Python 3.11 | historical-discovery | 发现 rollback 竞态、record reload、自有 1D provenance 与冻结后重建要求；随后均完成闭环 | reviewer 输出 | AUD-007/010/011/019/021 |
| EV-030 | 最终冻结树 pytest | `py -3.11 -m pytest -q --tb=short --junitxml=.audit-work\pytest-release-final-v6.xml` | Python 3.11 | pass | `500 passed in 19.00s` | `.audit-work/pytest-release-final-v6.xml` | 最终代码放行 |
| EV-031 | 最终静态与版本门禁 | ruff；compileall；`git diff --check`；version smoke | 仓库根 | pass | ruff/compileall/diff-check 全部通过；版本 `2.0.0` | 工具输出 | 最终代码放行 |
| EV-032 | 最终冻结 artifact | build --no-isolation、SHA-256、wheel 隔离 target、sdist 解包验证 | Python 3.11 | pass | wheel `154AF0ECC504619DED8C7C23BC2C43C208E047FAEC9C751394BE49EF025C4A9F`；sdist `7080CC47DB13B9DCBEED448AA4F3D1F234AC506C66AFB76D3D98867ED4CE9DCC`；wheel import/CLI/launcher/entry points 通过；sdist 根含 metadata/conftest，解包内 version tests `2 passed` | `.audit-work/dist-release-final-v4/` | 最终 artifact 放行 |
| EV-033 | 最终独立 QA | A/B/C/D/resume 与 release metadata/packaging 复核最终 diff、门禁、artifact 与恢复路径 | 仓库根 | pass | 全部 PASS；无新增 P0/P1/P2；metadata 与 sdist manifest 闭环 | reviewer 输出 | 最终独立放行 |

## 放行判据

EV-030～EV-033 全部通过，当前冻结树满足本地发布门禁，建议快进合并/push。后续 staged 范围异常、远端漂移或 CI 失败仍应停止流程并重新审查。

## 证据边界

- 可见 GUI：无可接管窗口，不得表述为视觉验收完成。
- 真实束线数据：未提供、未运行，不得表述为束线端验证完成。
- 不确定度：raw BG/dark covariance 未知时 combined 结果正确保持 `partial`。
- 性能：本地匿名数据与调用计数只能证明风险/调用变化，不能替代真实大批次和束线存储基准。