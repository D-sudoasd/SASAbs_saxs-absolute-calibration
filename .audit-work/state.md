# SASAbs v2 发布闭环状态

- 任务日期：2026-07-13（Asia/Shanghai）
- 仓库：`E:\desktop\SASAbs_saxs-absolute-calibration`
- 当前分支：`codex/ci-release-followup`
- 审计起点：`main@6ba966c715753f59a44009f1ee2ab07d15fc93f5`
- 已发布基础：`main == origin/main == cfad783`
- 当前 Gate：CI follow-up 本地冻结门禁通过；最终完成以第二轮远端 CI 成功为条件
- 发布结论：**follow-up 本地放行；建议提交、快进合并并 push，最终完成以第二轮远端 CI 成功为条件。**
- P0/P1/P2/P3：0/10/12/2
- verified/blocked/open：21/0/3
- 最终 pytest：`500 passed in 19.48s`；JUnit `.audit-work/pytest-release-final-v7.xml`
- 最终静态门禁：`ruff / compileall / git diff --check` 全部通过
- 最终版本 smoke：`2.0.0`
- 最终 wheel：`saxsabs-2.0.0-py3-none-any.whl`；SHA-256 `7081EA14E70CE317DCAA125C7131EFA3C4E5BBB51F25A4CC582215A8857DD281`
- 最终 sdist：`saxsabs-2.0.0.tar.gz`；SHA-256 `E569AA62C980963F06A96047A310D2E580AB6AEDD516F59870E8907ADBFE0595`
- artifact smoke：wheel 隔离 target import、CLI、launcher、entry points 全部通过；sdist 解包根包含 release metadata 与 `tests/conftest.py`，解包内 version tests `2 passed`
- 最终独立 QA：A/B/C/D/resume 全部 PASS；CI follow-up focused 18 passed；无新增 P0/P1/P2
- 用户已有资产：`docs/superpowers/` 已保存在 `stash@{0}`，未纳入发布提交
- Git/CI 截止状态：release commit `cfad783` 已 fast-forward 合并并 push，且 `main == origin/main == cfad783`；follow-up 尚未 commit/merge/push，第二轮 CI 尚未触发

## 已闭环范围

- AUD-001..AUD-014：verified。
- AUD-016、AUD-018、AUD-019、AUD-021、AUD-022：verified。
- AUD-023、AUD-024：verified。
- Release metadata/packaging：根 `.zenodo.json` 已统一为 2.0.0 并纳入 version test；新增 `MANIFEST.in` 将 CHANGELOG/CITATION/codemeta/.zenodo/tests/conftest 纳入 sdist；新增 `.audit-work/sdist-*/` ignore。
- CI follow-up：首轮 GitHub Actions `ci` run `29228584901` 最终 failure；除 ubuntu 3.11 外的 Ubuntu/macOS/Windows 矩阵均失败。根因是 Python 3.10 collection 无 `tomllib`，以及 `pip wheel --no-build-isolation` 路径的 dev 环境未显式安装 `setuptools>=69` 与 `wheel`；旧测试捕获 stderr 使日志不透明。follow-up 已改用 Python 3.10 兼容 regex、补齐 dev build 依赖，并在 wheel test 失败时显示 stdout/stderr。
- P1 全部闭环：公共 API 位置参数兼容、v2 CLI/显式 legacy、完整重放参数、不确定度状态语义、calibration record v2、SRM 3600、μ 输入、Tab3 信任与单位边界。
- P2 安全闭环：Cal2D 多文件事务与竞态保护、package-level rerun、auto-reference、Tab3 provenance、模型输入校验、K history 原子写、稳定读后哈希、launcher 隔离。
- QA 补充闭环：
  - Cal2D no-overwrite 后续冲突时不删除任何已发布路径；残片由完整性门拒绝，避免 TOCTOU 误删并发替换文件（AUD-011）。
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
- follow-up 本地冻结树 focused 18、全量 500、ruff、compileall、diff-check、版本 smoke、wheel/sdist 构建与 smokes 全部通过。
- 审计截止语气：截至 follow-up 本地冻结点，follow-up 尚未 commit/merge/push，第二轮远端 CI 尚未触发；不得写成远端已绿。

## 下一步

1. 精确暂存并提交 `codex/ci-release-followup` 的 CI 兼容修复。
2. 确认 `origin/main@cfad783` 未漂移，快进合并到 `main` 并 push。
3. 观察第二轮远端 CI 到成功；成功后使用 `git branch -d` 安全删除已合并 follow-up 分支。
