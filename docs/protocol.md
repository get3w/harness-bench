# Bench ABI v1

## Get3W bridge

`bridges/node/bridge.mjs` 提供 loopback HTTP 主机，要求 Bearer `GET3W_BENCH_TOKEN`。
`GET3W_BENCH_DRIVER` 指向可信 ESM 驱动。每个 session 有独立 runtime，DELETE/SIGTERM 清理。
Bridge 没有原生回退。

- GET `/v1/info` → `{protocol_version:1,runtimes:[{harness,available,runtime_version,runtime_digest}]}`。
- POST `/v1/sessions` 接收 request（task/instruction/model/budget/environment/expected_identity/workspace/run_directory），返回 `{session_id,identity,environment_digest}`。
- POST `/v1/sessions/:id/turns` 接收 `{request_id,text}`，一次 admission，驱动负责去重。
- GET `/v1/sessions/:id/events?after=cursor` → `{events:[],cursor}`，cursor 为单调递增事件位置。
- GET `/v1/sessions/:id` → `{status,trace_complete}`。终态：completed、model_error、protocol_error、aborted、timeout、infrastructure_error、blocked。
- POST `/v1/sessions/:id/abort` 接收 `{clear_queue:true}`；DELETE session 必须停止并清理。
- POST `/v1/contracts` → `{scenario,harness,status,execution_mode:"real_desktop",evidence}`，缺失驱动返回 blocked。

identity 包含 harness、runtime_version、runtime_digest、tools_fingerprint、permissions_fingerprint、profile_fingerprint。environment_digest 为 environment 对象按排序 key、无空格 JSON 的 SHA256，与 Python fingerprint 一致。启动器必须测量真实运行物和环境，不能把 expected_identity 原样回显充当证据。

## 当前 OpenCode headless driver

```sh
GET3W_BENCH_DRIVER=./bridges/node/headless-driver.mjs \
GET3W_HEADLESS_MODULE=/absolute/desktop/packages/headless-threads/dist/index.js \
GET3W_BENCH_LAUNCHER=/absolute/verified-launcher.mjs \
node bridges/node/bridge.mjs
```

launcher 导出 `runtimes()` 和 `start(input)`。`start` 必须通过真实 Get3W `startEmbeddedServer`/已构建 Server 管理 runtime，而不是直接调用 OpenCode CLI；返回：

```js
{
  isolated: true,
  workspace: input.workspace,
  modelEndpoint: input.model.endpoint,
  identity: measuredIdentity,
  environmentDigest: measuredEnvironmentDigest,
  clientOptions: { baseUrl, workspaceId, token, hostToken, engine },
  model: { providerId, modelId },
  stop: async () => { /* stop server and all engine children */ }
}
```

每次 start 配置独立 HOME/XDG/GET3W_DATA_DIR、空配置/历史、workspace、网关 token、工具/权限。当前仓库未供应此产品专属启动器，因此此路径尚未获得真实运行验收。不能连个人正在运行的 Get3W 来替代。支持 Pi/DeepSeek 需要多 Harness 真实 Server/Adapter API，当前 client 不支持它们。

## Electron driver

`desktop-contracts.mjs` 导出 `run({executablePath,entry,output,harness,driverPath})`。
需要运行环境提供 Playwright。创建隔离 profile、启动开发 Electron、逐项调用 driver 的 11 个同名导出函数，每项须返回非空 `assertions:[{passed:true,...}]`，保存截图并最终关闭应用。缺少断言函数为 blocked，断言异常为 failed。该 runner 不包含产品 selector/行为断言，因此尚不能单独执行完整桌面验收；产品具备多 Harness 之后补齐，不可用模拟 renderer 替代。

## Native runtime

容器工作目录 `/workspace`；控制请求 `/run/bench/request.json` 只读；状态 `/state` 和证据 `/trace` 独立可写。镜像自带 runtime identity/config。worker 从固定 executable 获取版本，构造三种 Harness 的 argv，无 shell 拼接；原始 stdout 逐行保存。控制器强制 deadline、杀进程组，并销毁容器。不得挂载 Docker socket 或宿主凭据。

## Trusted grader

只读 `/task`、`/workspace`，可写 `/grade`，网络关闭。成功退出后必须生成 `/grade/grade.json`：

```json
{"schema_version":1,"score":1,"passed":true,"pass_threshold":0.8,"cases":[{"id":"core-result","weight":1,"core":true,"passed":true}]}
```

权重总和为 1；gate 的权重为 0，gate 失败总分归零；任何 core 失败不能 pass。
控制器重算 score/pass 并拒绝不一致的 receipt。评分器与 Harness 分开镜像。
