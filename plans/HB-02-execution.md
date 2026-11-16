# HB-02 执行、隔离与模型证据

- [x] 原生 Docker argv supervisor、deadline、进程组/容器清理。
- [x] 禁止 Docker socket；只读 root/control，独立 workspace/state/trace。
- [x] 原生仅允许 none 或 internal 网络。
- [x] 三种 CLI 命令构造与 JSON 终态解析。
- [x] 版本核对、镜像 receipt/model 绑定与运行配置文件替换。
- [x] 每次独立模型网关、模型/参数绑定、请求/输出预算。
- [x] provider 原始请求响应、SSE usage、trace 与覆盖率保存。
- [x] 缺失 usage、环境/runtime 身份不匹配拒绝等价比较。
- [ ] Docker daemon 可用（本机 socket 不存在）。
- [ ] 【不依赖 Get3W 集成】OpenCode 固定发行物镜像、模型配置与 CLI 真实兼容性验证（优先）。
- [ ] 【不依赖 Get3W 集成】DeepSeek 固定发行物镜像、模型配置与 CLI 真实兼容性验证。
- [ ] 【不依赖 Get3W 集成】Pi 固定发行物镜像、模型配置与 CLI 真实兼容性验证。
- [ ] 【不依赖 Get3W 集成】三个原生目标环境的真实测量与身份签发。
- [ ] 【仅 OpenCode】Get3W OpenCode 目标环境的真实测量与身份签发。
- [ ] 【等待 Get3W 集成 DeepSeek】Get3W DeepSeek 目标环境的真实测量与身份签发。
- [ ] 【等待 Get3W 集成 Pi】Get3W Pi 目标环境的真实测量与身份签发。
- [ ] 【不依赖 Get3W 集成】原生容器到网关可达、公网不可绕过的网络验收。
- [ ] 【仅 OpenCode】Get3W OpenCode 环境的同等网络验收。
- [ ] 【等待 Get3W 集成 DeepSeek】Get3W DeepSeek 环境的同等网络验收。
- [ ] 【等待 Get3W 集成 Pi】Get3W Pi 环境的同等网络验收。
- [ ] 真实模型 revision/endpoint、预算与凭据配置。

运行模板不是已构建镜像；runtime metadata 是可信构建方的声明，不能当作独立供应链证明。
