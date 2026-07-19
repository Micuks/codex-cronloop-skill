# Codex CLI Loop

[English](README.md) · [完整示例](examples/benchmark-monitoring.md) · [更新日志](CHANGELOG.md) · [MIT 许可证](LICENSE)

Loop 在同一个 Codex 任务里交替执行“agent 检查一轮”和“前台 TTY `bash sleep`”。“每 30 分钟检查一次实验”不再安装 cron，也不再每轮重新启动 `codex exec resume`。

![Loop 架构](docs/images/architecture.svg)

## 为什么这样实现

旧版 Loop 依靠 crontab 定时恢复精确 Codex thread。它能够跨进程持久化，但每轮都要重新启动 CLI/模型，还需要调度状态、锁、日志和清理。新版刻意选择更轻的 agent-in-the-loop 方式：

- 保持同一个 Codex 任务和完整上下文；
- 在 PTY 中真实运行前台 `sleep 1800` 或 `sleep 3600`；
- 不创建 crontab、daemon、thread 查询、状态目录或冷启动恢复；
- 计时结束后由同一个 agent 执行一轮基于证据的检查；
- 用户可以在同一任务里随时补充要求或取消；
- 用户明确要求时，可把每轮完成后的报告发送到飞书等外部渠道。

Shell sleep 可以远长于 60 秒。Codex 执行工具会在保持同一前台进程运行的同时返回 session ID，之后以工具支持的时间片轮询。单次工具调用的等待上限，不是 TTY 进程的寿命上限。

## 环境要求

- 支持 PTY 命令和 session 轮询（`exec_command`、`write_stdin`）的 Codex CLI
- 监控期间保持当前 Codex 任务与客户端运行
- Bash 和 `sleep`
- 可选飞书通知：已登录的 [`lark-cli`](https://open.feishu.cn/document/no_class/mcp-archive/feishu-cli-installation-guide.md) 或其他已配置飞书连接器

核心循环不再依赖 Python、cron daemon 或第三方软件包。

## 安装

```bash
git clone https://github.com/Micuks/codex-loop-skill.git
mkdir -p ~/.codex/skills
ln -s "$PWD/codex-loop-skill/loop" ~/.codex/skills/loop
```

如果当前 Codex 进程没有发现 skill，请重启 Codex CLI。也可以直接把 `loop/` 复制到 `~/.codex/skills/loop/`。

## 快速使用

在需要持续监控的任务里输入：

```text
$loop 30m 监控 ./runs/exp-42。检查进程、最新日志、结果有效性和磁盘空间；
只有确认 runner 已退出且不存在重复实例后，才允许安全重启。
全部三轮通过校验并生成 results.xlsx 后停止。
```

Loop 默认立即检查一轮；如果尚未完成，就启动等价于下面调用的前台 TTY 计时器：

```text
exec_command:
  cmd: bash -lc 'sleep 1800'
  tty: true
  yield_time_ms: 30000
```

执行工具返回 session ID 后，Codex 使用空 `write_stdin` 持续等待同一个进程。计时结束后，仍在同一任务里执行下一轮检查。

![前台 TTY 循环示例](docs/images/demo-terminal.svg)

### 可选飞书通知

在请求中明确要求把每轮完成后的报告发送到飞书：

```text
$loop 30m 监控 ./runs/exp-42，每轮检查完成后通知我的飞书；
三轮结果全部有效后停止。
```

通知默认关闭。Loop 会验证已配置的身份和目标，只发送真实监控轮次的报告，不发送 sleep 轮询心跳，并在发送前脱敏疑似密钥和带凭据 URL。通知采用 fail-open：发送失败会在当前任务中报告，但不会把健康的监控轮次判成失败，也不会停止前台 TTY 循环。

间隔使用整数分钟、小时或天，例如 `30m`、`45m`、`1h`、`2h`、`1d`。默认最短 30 分钟；用户明确要求测试时可以使用更短间隔。

## 效果示例

仓库中的[实验监控示例](examples/benchmark-monitoring.md)描述了一个“8 个配置 × 15 个 query × 3 轮”的场景：

1. agent 立即检查 runner、最新日志、结果矩阵、磁盘和负载。
2. 尚未完成时，在 PTY 中以前台进程启动 `sleep 1800`。
3. 执行工具即使中途 yield，也始终轮询同一个 shell session，不重新开始计时。
4. 到期后，agent 带着完整任务上下文再次检查实验。
5. 只有验证完成、用户取消或 TTY session 无法恢复时，循环才结束。

## 安全性与取舍

| 关注点 | 行为 |
|---|---|
| 意外创建后台调度 | 不创建 cron、daemon、tmux、nohup 或 Scheduled Task |
| 重复计时 | 始终轮询一个 session ID，正常 yield 后不重新开始 interval |
| 单次工具等待有上限 | 使用工具允许的最长轮询时间片，前台进程继续运行 |
| 恢复动作越权 | 先诊断，只执行用户明确授权的恢复 |
| 通知正文泄漏凭据 | 发送前脱敏疑似密钥和带凭据 URL |
| 飞书故障打断监控 | 通知失败与监控结果隔离，并在当前任务报告 |
| 用户改变要求 | 在同一任务处理新输入；取消时中断 live TTY |
| 客户端退出或主机重启 | 循环停止；轻量模式有意不提供持久调度 |
| TTY session 丢失 | 明确报告，不伪造近似计时器 |

Loop 面向交互式实验监督。如果必须跨客户端退出或主机重启继续运行，应使用外部持久化调度器，而不是这个轻量模式。

## 仓库结构

```text
loop/                 可安装的 Codex skill
  SKILL.md
  agents/openai.yaml
docs/images/              中英文 README 共用附图
examples/                 展开的监控示例
tests/                    静态契约测试
```

## 开发与测试

```bash
python3 -m unittest discover -s tests -v
```

测试不会启动真实的长时间 sleep、修改本机调度器状态或发送真实通知。

## 许可证

[MIT](LICENSE)
