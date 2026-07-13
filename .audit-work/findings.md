# 问题账本

结论：原始 24 项问题的优先级分布为 P0/P1/P2/P3 = **0/10/12/2**；当前状态为
**verified=21、blocked=0、open=3**。follow-up 本地门禁通过；**最终完成以第二轮远端 CI 成功为条件**。

| ID | 优先级 | 分类 | 状态 | 路径/符号 | 触发条件与影响 | 修复闭环 | 证据 | 剩余边界 |
|---|---|---|---|---|---|---|---|---|
| AUD-001 | P1 | 几何/provenance | verified | BL19B2 safe PONI | 同路径几何改变可复用旧 PONI，导致错误续跑 | 比较渲染内容/哈希，不一致即 fail-closed | EV-011/012/018/020 | 无已知阻塞 |
| AUD-002 | P1 | Cal2D 完整性 | verified | Cal2D resume/writer | 五件套残缺或上下文错配可误报完成 | 五件套、shape、PONI、context、参数联合 gate；无效 PONI 写前拒绝 | EV-013/020/027 | 无已知阻塞 |
| AUD-003 | P1 | API 兼容 | verified | calibration/buffer 公共 API | 新参数插入旧位置顺序会破坏既有调用 | 恢复旧位置顺序；新增参数 keyword-only | EV-020 | 新参数须按关键字传入 |
| AUD-004 | P1 | CLI 兼容 | verified | BL19B2 CLI | 历史命令依赖隐式 monitor/μ，无法安全解释 | 发布版本升至 2.0.0；危险旧语义仅由显式 legacy 入口启用 | EV-021/026 | legacy 假设不会隐式恢复 |
| AUD-005 | P1 | 重放可复现性 | verified | rerun/CLI/config | mask、策略、standard、几何修正遗漏会改变 K/输出 | CLI、Config、rerun、signature/YAML 全字段贯通 | EV-021/022 | 无已知阻塞 |
| AUD-006 | P1 | 不确定度语义 | verified | uncertainty budget | 标准端或 covariance 缺失时曾可误报 complete | 标准 T/MON/BG-MON/d/alpha 灵敏度；reference/system coverage 分离；未知 covariance 保持 partial | EV-022/029 | combined uncertainty 在当前可证输入下正确为 partial |
| AUD-007 | P1 | calibration provenance | verified | calibration record/context v2 | K 来源、模型、源数据或源文件事后变化未被完整绑定 | v2 绑定标准/BG/dark/custom reference、模型/参数/哈希；正式 gate 每次重读 record 并复验源文件 | EV-023/029 | v1 仅兼容读取并标 incomplete |
| AUD-008 | P1 | SRM 科研约束 | verified | SRM 3600/K QC | 错厚度或不平行 ratio 会造成绝对标度偏差 | SRM 别名统一；锁定 0.1055 cm；证书约束与保守平行性门 | EV-020/025/029 | 更严格阈值可配置，不允许放宽证书边界 |
| AUD-009 | P1 | μ 输入 | verified | μ calculator/GUI | `Fe:95` 等比例尺度含糊可放大 μ | 仅接受总和约 1 或约 100，并精确归一化到 1；其他 fail-closed | EV-024 | 化学式/单元素兼容路径保留 |
| AUD-010 | P1 | GUI 信任/单位 | verified | Tab3/formal export | 默认 K、raw 缺 provenance、2θ 冒充 Q 或自产 1D 回读丢上下文 | 正式导出要求当前 record/context；Q/2θ/χ 严格处理；自产文本/canSAS/NXcanSAS provenance 可写回重读 | EV-025/029 | 可见 GUI 尚未完成视觉验收 |
| AUD-011 | P2 | 多文件输出安全 | verified | Cal2D transaction | 中途失败、目标冲突或并发替换会留下混合包/误删外部文件 | staging + create-if-absent no-overwrite 发布；后续冲突不删除已发布成员，残片由完整性门拒绝；overwrite 模式使用 backup rollback | EV-009/025/029 | 多文件包不具备全局单一原子提交；no-overwrite 冲突可保守保留残片，但不会覆盖或删除竞争者文件 |
| AUD-012 | P2 | RunPolicy | verified | Cal2D always-run | 目标存在时缺 package-level rerun 身份 | 整包分配统一 rerun ID，成员不会跨运行混合 | EV-025 | 无已知阻塞 |
| AUD-013 | P2 | monitor provenance | verified | monitor mode builders/run | 合法大小写/空白输入曾导致计算、签名和脚本漂移 | 单一边界规范化并贯通主入口、签名与重放 | EV-014/018 | 无已知阻塞 |
| AUD-014 | P2 | Tab2 控制流 | verified | auto-reference | auto 模式仍先强制加载 fixed BG/Dark | reference 分支前移，共享验证按实际模式执行 | EV-025 | 无已知阻塞 |
| AUD-015 | P2 | GUI/预检/布局 | open | Tab1/Tab2 | 可见布局、人工 dark exposure、真实点击路径缺证据 | dry-run 与正式路径已复用安全 gate；逻辑测试已覆盖 | EV-010/025 | **仍缺可见 GUI/布局截图与人工 dark exposure 主路径证据** |
| AUD-016 | P2 | Tab3 provenance/状态 | verified | parser/buffer/export | parser 分叉、状态不更新或 metadata 覆盖会削弱审计 | 共享 parser、buffer 单次预载、RunPolicy 与 operator provenance 合并 | EV-025/029 | 无已知阻塞 |
| AUD-017 | P2 | 资源/路径/GUI 线程 | open | workers/stem/Tk | 极端 worker、超长 stem 或主线程等待影响可靠性 | workers 限制 1..32；stem 采用 120 字符上限+稳定哈希 | EV-025 | **GUI 主线程体验仍需真实桌面验证** |
| AUD-018 | P2 | 模型校验 | verified | calibration/record | 重复 q、Inf、矛盾 U、零 MAD 等边界可产生伪稳健结果 | 核心不变量与有限值校验 fail-closed；统计参数写入 record | EV-023 | 无已知阻塞 |
| AUD-019 | P2 | 持久化/provenance | verified | record/K history/resume | 绝对路径、损坏 CSV、中断或 resume 覆盖创建信息 | 相对 source 路径；K history 损坏即停、临时文件+fsync+原子替换；resume 另记 last_resume_validation | EV-023/025/029 | 首次创建 provenance 保持不可变 |
| AUD-020 | P2 | 性能 | open | GUI/uncertainty/resume | 大批次/大 2D 可能放大 I/O、内存和等待 | 已减少重复 parser/缓冲读取并采用稳定 gate；未宣称真实吞吐提升 | EV-015/025 | **未做真实大批次或束线存储基准** |
| AUD-021 | P2 | 输入快照/TOCTOU | verified | read→hash | 采集或同步中文件变化会使哈希不代表已分析数据 | 读前/读后双哈希与 stat 一致性门；resume 验证不改写创建 provenance | EV-015/025/029 | 持续变化输入会明确失败 |
| AUD-022 | P2 | launcher 隔离 | verified | workbench launcher | cwd 阴影模块或不可写 cwd 可启动错版/无法记录日志 | package source 优先；用户/临时日志目录 fallback；启动脚本去 cwd 注入 | EV-025 | 可见启动窗口未被自动化接管 |
| AUD-023 | P3 | metadata/version | verified | release metadata/CLI/docs | `.zenodo.json` 等版本元数据或迁移说明可能陈旧 | pyproject/package/CITATION/codemeta/`.zenodo.json` 统一 2.0.0 并纳入 version test；六子命令与 legacy 边界同步 | EV-026/030/032 | submission 快照明确保留历史版本 |
| AUD-024 | P3 | 文档/打包/CI 质量 | verified | README/MANIFEST/dev tests | sdist 缺 metadata/conftest、Python 3.10 无 `tomllib` 或 no-isolation dev 环境缺 build tools 会使发布矩阵失败 | README 去重；`MANIFEST.in` 纳入 release files；忽略 sdist 工作目录；version test 使用 3.10 兼容 regex；dev extra 显式含 `setuptools>=69` 与 `wheel`；wheel test 失败显示 stdout/stderr | EV-026/032/034/035 | 第二轮远端 CI 待 follow-up push 后复验 |

## 状态核对

- verified：AUD-001～AUD-014、AUD-016、AUD-018、AUD-019、AUD-021～AUD-024，共 21 项。
- open：AUD-015、AUD-017、AUD-020，共 3 项。
- blocked：无。
- follow-up 本地冻结门禁：focused `18 passed`；全量 `500 passed in 19.48s`；ruff/compileall/diff-check 通过；版本 `2.0.0`；final-v5 wheel/sdist 与 smokes 通过并记录 SHA-256。首轮 `ci` run `29228584901` 为 failure；截至本地冻结点，follow-up 尚未 commit/merge/push，第二轮 CI 尚未触发。