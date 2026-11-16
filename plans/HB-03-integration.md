# HB-03 Get3W 与桌面接入

- [x] 版本化认证 bridge host、诊断、session/turn/events/snapshot/abort/delete。
- [x] OpenCode 驱动使用真实 HeadlessThreadClient create/send/wait/export/abort API。
- [x] 不支持的 Harness 返回阻塞，不用原生回退。
- [x] Playwright Electron 隔离 profile runner、逐场景断言接口与截图证据。
- [x] 11 项桌面场景目录和完整性门禁。
- [ ] 【仅 OpenCode】基于真实 startEmbeddedServer 的产品专属隔离启动器。
- [ ] 【仅 OpenCode】11 项产品专属桌面行为断言和选择器实现。
- [ ] 【仅 OpenCode】bridge/session deadline、去重、abort 和 SIGTERM 真实进程无残留验收。
- [ ] 【仅 OpenCode】完整 Electron 运行证据。
- [ ] 【等待 Get3W 集成 DeepSeek】产品侧提供真实 DeepSeek Server/Adapter、Harness 选择和会话绑定接口（外部依赖，属于 Desktop 多 Harness 计划）。
- [ ] 【等待 Get3W 集成 DeepSeek】适配 Bench 集成驱动和隔离启动器，验证真实路由、身份、模型网关、事件及清理。
- [ ] 【等待 Get3W 集成 DeepSeek】实现并运行 DeepSeek 的 11 项桌面断言，保存完整证据。
- [ ] 【等待 Get3W 集成 Pi】产品侧提供真实 Pi Server/Adapter、Harness 选择和会话绑定接口（外部依赖，属于 Desktop 多 Harness 计划）。
- [ ] 【等待 Get3W 集成 Pi】适配 Bench 集成驱动和隔离启动器，验证真实路由、身份、模型网关、事件及清理。
- [ ] 【等待 Get3W 集成 Pi】实现并运行 Pi 的 11 项桌面断言，保存完整证据。

DeepSeek/Pi 的上述任务当前不可执行。对应 Harness 集成就绪后只解锁其自身任务，
不要求另一个 Harness 同时完成。三个 Harness 的原生 CLI 评测不受此限制。

当前 Node 文件仅做语法检查；Python 协议测试使用受控 transport，不能代替真实 Get3W。
Desktop 仓库没有修改；不自动操作个人安装版或个人历史。
