# Get3W Harness Bench

Get3W Harness Bench 是独立于 Get3W Desktop 的 Harness 评测与集成验收仓库，为 Get3W 的多 Harness 选型、接入和版本升级提供可复现的测试依据。

## 仓库目标

本仓库需要回答三个问题：

1. **同一个模型交给不同 Harness，完成任务的表现有什么差异？** 在模型版本、任务、预算和环境等共同条件一致的情况下，分别独立运行 [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness)、[Pi](https://github.com/earendil-works/pi) 和 [OpenCode](https://github.com/anomalyco/opencode)，建立各自的原生能力基线，记录任务成功率、结果质量、耗时、模型用量和失败原因，为 Get3W 选择和配置 Harness 提供依据。
2. **同一个 Harness 接入 Get3W 后，是否出现能力损失？** 对每个 Harness，使用同一版本、同一模型和同一批任务，配对比较“原生执行”与“通过 Get3W Server/Adapter 执行”的结果，检查工具调用、上下文、权限、附件、会话状态或结果传递是否在集成过程中发生变化，并保留可追溯的证据。
3. **Get3W 的桌面交互和后续升级是否仍符合预期？** 在真实、隔离的 Get3W Desktop 中核查 Harness 选择、流式输出、中止、权限、会话恢复及桌面工具等行为；更新 Harness、Get3W 或集成配置时，重跑固定任务和契约，发现回归并为发布验收提供依据。

因此，评测包含两种不同的比较：**不同 Harness 之间的原生能力比较**，以及**同一 Harness 接入 Get3W 前后的配对比较**。前者帮助选型，后者帮助定位集成损失；真实桌面契约另行验证产品交互是否正确。

每次评测应交付固定的任务清单、模型与运行版本、配置和预算、逐任务评分、原始执行轨迹及汇总报告。结论必须注明适用范围，并区分能力回归、基础设施失败和证据不足，供开发者逐项复核。模型接口、任务锁、Harness 版本、工具/权限配置、预算和环境均纳入比较身份。

本仓库负责评测工具、任务集接入、驱动与验收规则；Get3W 的多 Harness 产品功能在 Desktop 仓库实现。能力评估需要具有代表性的真实任务，集成契约任务用于核查具体行为。通过有限任务集表示在对应版本和测试条件下达到验收要求，不能证明所有场景下绝对无损。

## 当前实现状态

当前交付是可测试的评测控制器、原创集成任务集和驱动接口。**尚未完成三种 Harness 的真实能力验收**：Docker daemon、经过验证的运行镜像/模型配置、Get3W 隔离启动器、多 Harness 接口、桌面断言驱动，以及第三方任务授权/评分器仍需补齐。具体状态见 [实施核对表](plans/README.md)。没有生成或宣称真实能力分数。

## 安装与验证

需要 Python 3.11+、uv；真实执行另需 Docker。

```sh
uv sync --extra dev --locked
uv run pytest -q
uv run ruff check .
uv run get3w-bench --help
```

依赖由 `uv.lock` 固定。所有命令从仓库根目录运行。配置示例是模板，`REPLACE_` 必须替换为测量值，不是可用的发行物。

## 两类任务

`suites/get3w-contract-v1` 包含 60 个 MIT 原创任务，六类各十个，覆盖文件读取/转换、聚合、统计、HTML 转义和 Markdown 输出，并核查输入文件未被修改。每个任务的 oracle 在代理容器外评分。它们是集成契约样本，难度与分布不能代表通用能力；十个参数变体也不能作为十个独立真实世界问题来作质量非劣效结论。

`suites/locks` 已提供 smoke12、regression60 固定清单。原始任务生成器为 `scripts/generate_suite.py`。测试对每项验证空输出、正确输出、篡改输入。

外部能力任务集的接入和授权要求见 [UPSTREAM.md](UPSTREAM.md)。没有授权就不会加载，不包含其 274/26 个任务或仿造评分器。

## 运行流程

1. 将合法固定版本的每个 Harness 准备成基础镜像，记录二进制摘要与版本；使用 `images/Dockerfile.runtime` 添加本项目 worker。镜像中 `/opt/bench-runtime.json` 的格式见 `configs/bench-runtime.example.json`。三种 CLI 的命令构造与终态解析在 `native_worker.py`；实际发行物兼容性需要验证，不能仅凭退出码为零判成功。
2. 配置每个版本真实支持的 provider/model 格式。runtime config 文件只能写到 `/state`；`$ENDPOINT` 和 `$TOKEN` 在每次运行中替换。DeepSeek 的 Cordis overlay 另需 `patch` 路径。原始模型 ID/revision 必须匹配镜像声明。
3. 使用 `images/Dockerfile.grader` 构建原创任务评分镜像；基础镜像与最终镜像都使用真实 digest。外部任务另行实现经过验证的可信评分器，输出 [评分 receipt](docs/protocol.md)。
4. 建立只能访问模型网关的隔离网络；原生容器仅允许 `none` 或 Docker `Internal` 网络。网关默认只监听 loopback；容器运行时必须配置可达的 `gateway.bind_host/advertise_host` 和防火墙。仅 Docker Internal 标记不足以证明完整网络隔离，真实验收还须验证无法绕过网关访问公网。集成运行必须提供相同约束。
5. 配置并启动真实 Get3W bridge，见 [协议](docs/protocol.md)。当前 headless driver 支持 OpenCode API，隔离启动器由 Get3W 构建环境提供；Pi/DeepSeek 在 Get3W 尚未集成时返回 blocked。绝不回退为原生 CLI 后冒充集成结果。
6. 复制 `configs/experiment.example.yaml`，填模型、预算、镜像、环境和六个目标（三种 Harness × native/get3w）。先小预算 smoke，再 regression，再授权的完整能力任务集。示例只有一个 Pi 配对，不足以发布。

```sh
export GET3W_MODEL_API_KEY='provider key'
export GET3W_BENCH_TOKEN='local bridge token'
uv run get3w-bench doctor --config experiment.yaml
uv run get3w-bench run --config experiment.yaml --output artifacts/run-001
uv run get3w-bench contract --config experiment.yaml --target opencode-get3w --output artifacts/contracts-opencode
uv run get3w-bench compare artifacts/run-001/results.json --contracts artifacts/all-contracts.json --output artifacts/report-001
```

`doctor` 在缺失依赖时返回 2。每个 run 目录必须全新；每次运行建立独立 workspace/state/trace 和模型网关。`max_trials` 到达后剩余 observation 保留 blocked。模型重试计入请求预算；禁止静默重跑覆盖旧结果。多次重复在同一任务内聚合。配对执行按重复次数交替顺序。

## 结果与判定

`results.json` 汇总原始运行，逐次目录保存身份诊断、原始 Harness 日志、Get3W 快照/最终 transcript、provider 请求响应、usage 和独立 grade。网关不保存认证头，供应商凭据仅保留在控制器环境；disposable token 可进入短期控制文件。请求正文/响应可能包含敏感内容，目录须按敏感实验数据保管，报告不要直接公开。

原生结果也会输出描述性平均分。跨 Harness 的分数需要核查共同模型、锁、预算和环境，不能将不同配置的均值直接排成能力榜。

集成质量使用任务级配对 cluster bootstrap，10,000 次，重复先在任务内平均：95% CI 下界 ≥ -0.02 为 pass，上界 < -0.02 为 regression，其余 inconclusive。少于 30 个任务为 insufficient_evidence。任何身份不匹配、缺失配对、缺失 usage/trace 或基础设施错误为 not_comparable；代理失败不能通过删样本提高成绩。`product` 模式仅描述，不证明等价。供应商模型版本须可固定，否则 revision 只是声明，不能证明后端权重未变。

桌面契约覆盖选择绑定、流/最终一致性、中止清队列、权限拒绝、问题取消、重启恢复、并发隔离、附件、MCP、浏览器停止、电脑接管。所有场景必须有真实桌面证据，单个 passed 不足以通过。发布要求三种 Harness 各自的通用能力配对通过，且各自完整桌面契约通过。当前缺失项不会被跳过后判通过。

报告为离线 HTML、JSON、JUnit。退出码 0 表示相应命令通过；2 表示阻塞/未通过。单次 `run` 成功只代表执行完成，不代表发布验收。

## 版本同步

Bench 不 fork 三个 Harness。升级时新增不可变 runtime 配置/镜像摘要，与 Get3W 的同一发行物配对；先运行 smoke/契约，再完整能力集。旧版本、任务锁、模型和报告保持不变。将“上游自身版本差异”和“同版 Get3W 集成差异”分开运行；禁止 native 升级而 Get3W 未升级时报告集成损失。自动更新不能直接越过版本验收门禁。
