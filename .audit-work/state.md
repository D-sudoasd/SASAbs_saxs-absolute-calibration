# SASAbs v2 发布闭环状态

- 任务日期：2026-07-13（Asia/Shanghai）
- 仓库：`E:\desktop\SASAbs_saxs-absolute-calibration`
- 当前分支：`codex/sasabs-release-hardening`
- 基线：`main@6ba966c715753f59a44009f1ee2ab07d15fc93f5`
- 当前 Gate：G7 最终发布门禁（完成）
- 发布结论：**建议快进合并/push。**
- P0/P1/P2/P3：0/10/12/2
- verified/blocked/open：21/0/3
- 最终 pytest：`500 passed in 19.00s`；JUnit `.audit-work/pytest-release-final-v6.xml`
- 最终静态门禁：`ruff / compileall / git diff --check` 全部通过
- 最终版本 smoke：`2.0.0`
- 最终 wheel：`saxsabs-2.0.0-py3-none-any.whl`；SHA-256 `154AF0ECC504619DED8C7C23BC2C43C208E047FAEC9C751394BE49EF025C4A9F`
- 最终 sdist：`saxsabs-2.0.0.tar.gz`；SHA-256 `7080CC47DB13B9DCBEED448AA4F3D1F234AC506C66AFB76D3D98867ED4CE9DCC`
- artifact smoke：wheel 隔离 target import、CLI、launcher、entry points 全部通过；sdist 解包根包含 release metadata 与 `tests/conftest.py`，解包内 version tests `2 passed`
- 最终独立 QA：A/B/C/D/resume 全部 PASS；定向 8 + 96 tests；无新增 P0/P1/P2
- 用户已有资产：未跟踪 `docs/superpowers/`，未修改、未纳入发布范围
- Git 操作：尚未暂存、提交、合并、push 或删除分支

## 已闭环范围

- AUD-001..AUD-014：verified。
- AUD-016、AUD-018、AUD-019、AUD-021、AUD-022：verified。
- AUD-023、AUD-024：verified。
- Release metadata/packaging：根 `.zenodo.json` 已统一为 2.0.0 并纳入 version test；新增 `MANIFEST.in` 将 CHANGELOG/CITATION/codemeta/.zenodo/tests/conftest 纳入 sdist；新增 `.audit-work/sdist-*/` ignore。
- P1 全部闭环：公共 API 位置参数兼容、v2 CLI/显式 legacy、完整重放参数、不确定度状态语义、calibration record v2、SRM 3600、μ 输入、Tab3 信任与单位边界。
- P2 安全闭环：Cal2D 多文件事务与竞态保护、package-level rerun、auto-reference、Tab3 provenance、模型输入校验、K history 原子写、稳定读后哈希、launcher 隔离。
- QA 补充闭环：
  - Cal2D rollback 仅清理由本事务仍持有的目标，避免删除并发替换文件（AUD-011）。
  - 正式导出前重新读取并校验 calibration record 及其源文件；1D 自产物 provenance 可写回并重读（AUD-007/AUD-010）。
  - resume 验证不再覆盖首次创建 provenance，改记 `last_resume_validation`（AUD-019/AUD-021）。

## 仍开放但不阻塞发布的范围

- AUD-015：缺少可见 GUI 窗口、布局截图与人工 dark exposure 主路径证据；headless/逻辑 gate 已覆盖。
- AUD-017：worker 上限和稳定短文件名已修复；GUI 主线程交互体验仍需真实桌面验证。
- AUD-020：未用真实大批次/真实束线数据做性能与存储基准。

## 严格证据边界

- 可见 GUI 启动未出现可由自动化工具接管的窗口，因此不得宣称完成视觉、DPI、主题或真实点击验收。
- 未使用真实 BL19B2/束线原始数据；现有证据来自自动测试、匿名最小样例和代码级审查。
- raw BG/dark covariance 缺少可验证输入时，combined uncertainty 正确保持 `partial`；不把未知项当作 0，也不生成伪完整 system expanded uncertainty。
- 最终冻结树 pytest、ruff、compileall、diff-check、版本 smoke、wheel/sdist 构建、隔离安装 smoke 与独立 QA 全部通过。

## 下一步

1. 保护 `docs/superpowers/` 后精确暂存、提交。
2. 确认远端未漂移，快进合并到 `main`、push 并观察 CI。
3. push/CI 成功后使用 `git branch -d` 安全删除已合并本地分支。
