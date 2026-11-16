# 上游来源与授权门禁

Get3W 原创代码和 `suites/get3w-contract-v1` 使用本仓库 MIT LICENSE。
没有复制第三方 Harness-Bench 的任务、评分器、代码或数据。

待导入来源：https://github.com/Qihoo360/Harness-Bench
调研锁定提交：`b8d89634c6f445fcc68ceb6744a59bef6cdf4863`。
核查 LICENSE、LICENSE.md、LICENSE.txt、COPYING、NOTICE、LICENSE-MIT、LICENSE-MIT.md
未发现可用许可证；GitHub license API 当时被限流。此记录不是法律结论，也不是使用授权。
**状态：unverified，禁止导入/分发，真实上游能力测试阻塞。**

取得明确授权后，在仓库外保存完整证据与以下授权 JSON：

```json
{
  "status": "approved",
  "source": "https://github.com/Qihoo360/Harness-Bench",
  "commit": "b8d89634c6f445fcc68ceb6744a59bef6cdf4863",
  "license": "实际核查的许可或书面授权",
  "evidence": "可审计的许可证/授权文件位置",
  "reviewed_by": "实际审核人"
}
```

`lock --source /absolute/clean/checkout --authorization /absolute/authorization.json`
校验提交和干净工作树。授权文件属于显式人工审核记录，工具不能判断授权文字是否有效。
保留所有第三方 notices，不能把上游内容改标为本项目 MIT。

通用任务和多模态任务分开锁定、评分和报告。源码目录只读，任务包禁止符号链接；
锁覆盖 prompt、workspace、测试和任务元数据的全部文件。任何修改要求生成新锁。
上游评分器必须按真实 ABI 单独适配和验证，不能用本项目原创 oracle 代替。
原计划每类 2/10 个任务，在通用 Web 类仅一个任务时不可执行；当前规则先按类选择，
再按 sha256(task_id) 从剩余任务中补足 12/60，生成锁记录最终清单。

Harness 自身使用独立、固定版本的合法发行物：
- https://github.com/deepseek-ai/deepseek-harness
- https://github.com/earendil-works/pi
- https://github.com/anomalyco/opencode

每个发行物需记录 tag、commit、版本输出、下载/构建摘要、原始许可证及模型配置 ABI。
本仓库没有供应这些发行物，也没有声称某个未经测试的最新版本兼容。
