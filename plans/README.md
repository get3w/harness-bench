# Harness Bench 实施核对表

本清单记录本仓库真实状态，与 Desktop 多 Harness 产品实现分开。日期：2026-11-16。
`[x]` 代表代码已实现并通过本地可运行检查；`[ ]` 代表未完成或外部阻塞。

- [HB-00 范围、来源与授权](HB-00-sources.md)
- [HB-01 任务、锁与评分](HB-01-tasks.md)
- [HB-02 执行、隔离与模型证据](HB-02-execution.md)
- [HB-03 Get3W 与桌面接入](HB-03-integration.md)
- [HB-04 比较与发布判定](HB-04-comparison.md)
- [HB-05 自动化与开发验证](HB-05-validation.md)
- [HB-06 真实能力验收](HB-06-acceptance.md)

当前不是“全部完成”：控制器和原创契约任务已落地；第三方授权、真实镜像/模型、产品接口和桌面断言仍未完成。未执行项在报告中保留 blocked，不得把单测通过解释成真实能力通过。

## 执行顺序与依赖标记

当前 Get3W Desktop 只支持 OpenCode，尚未集成 DeepSeek Harness、Pi。
以下标记是执行前置条件，不是完成状态；所有未完成任务继续使用 `[ ]`。

- **【不依赖 Get3W 集成】**：三个 Harness 的原生执行、镜像、任务、评分和原生基线，可独立推进。
- **【仅 OpenCode】**：当前阶段的 Get3W 配对与桌面验证；仍须先完成 OpenCode 隔离启动器等运行条件。
- **【等待 Get3W 集成 DeepSeek】**：只能在 Get3W 的 DeepSeek Server/Adapter 和对应 Bench 驱动实际就绪后执行。
- **【等待 Get3W 集成 Pi】**：只能在 Get3W 的 Pi Server/Adapter 和对应 Bench 驱动实际就绪后执行。
- **【等待三 Harness 集成验收】**：三者全部满足前置条件后才执行的整体验收。

按以下阶段推进，详细任务与完成条件见 [HB-06](HB-06-acceptance.md)：

1. **OpenCode 原生闭环**：固定版本/模型/预算，完成少量任务，再运行 smoke12。
2. **OpenCode Get3W 闭环与阶段验收**：隔离启动器、同版配对、11 项真实桌面契约；阶段结果仅覆盖 OpenCode。
3. **DeepSeek/Pi 原生基线**：不等待 Desktop 集成；可与前两阶段独立推进。
4. **授权能力任务集与原生能力比较**：授权与评分器准备可从现在开始；真实能力比较须等待运行环境和代表性任务就绪。
5. **逐个接入后的验收**：DeepSeek、Pi 各自满足 Get3W 集成前置条件后，再运行对应配对和桌面测试；二者互不等待。
6. **三 Harness 整体验收**：汇总同一验收批次的完整证据，执行整体发布门禁。

**执行限制：**当前 Get3W 阶段运行配置只启用 OpenCode 的 `native/get3w` 目标；
DeepSeek/Pi 独立基线配置只启用各自 `native` 目标。示例配置不是当前阶段的直接运行指令，
尤其不能启用其中的 `pi-get3w`。未集成项目记录“等待产品集成/未执行”，不能用原生 CLI
冒充集成路径、删除等待项后宣称整体通过，或为了运行 Bench 提前实现整套 Desktop 多 Harness 功能。

文档中的等待标记不等于 CLI 自动开关，执行者必须核对实际配置。现有 `compare` 的
`release_verdict` 仍是三 Harness 整体门禁：仅完成 OpenCode 时应保留 `not_passed`，
另行记录 OpenCode 阶段验收，不能据此宣称整体发布通过。
