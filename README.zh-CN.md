# Codex CLI Cronloop

[English](README.md) · [完整示例](examples/benchmark-monitoring.md) · [MIT 许可证](LICENSE)

Cronloop 把“每 30 分钟检查一次实验”这样的简短请求，转换成对**当前 Codex CLI 精确线程**的安全定时恢复。每次唤醒只执行一轮基于证据的检查，保存状态与日志；完成条件经过验证后，只删除属于自己的 cron 条目。

![Cronloop 架构](docs/images/architecture.svg)

## 为什么需要 Cronloop

长时间实验往往会跨越多次交互。普通 cron 能唤醒进程，却不会保留 agent 上下文，也不会说明何时可以安全恢复。Cronloop 补上了这层执行契约：

- 使用精确 thread UUID 恢复，不使用不确定的 `--last`；
- 每次唤醒只执行一轮，不让 agent 原地 sleep，也不创建嵌套调度器；
- 使用文件锁和最近活动窗口避免重复运行；
- 明确检查范围、恢复权限、禁止事项、汇报字段和结束条件；
- 单轮超时短于调度间隔，并可用完成标记文件快速停止；
- 通过独立标记块幂等更新 crontab，不影响其他任务；
- prompt、配置、状态与日志均保存在本机，敏感文件权限为 `0600`。

如果产品本身提供可靠的 Scheduled Tasks，应优先使用原生能力；Cronloop 是 Codex CLI 的本地兜底方案。

## 环境要求

- Linux 或具有 `cron`、`crontab`、`flock` 的类 Unix 主机
- Python 3.9+
- 已登录的 `codex` CLI
- 当前线程可由本机 Codex CLI 恢复，并能读取 `CODEX_THREAD_ID`

运行器不依赖第三方 Python 包。

## 安装

```bash
git clone https://github.com/Micuks/codex-cronloop-skill.git
mkdir -p ~/.codex/skills
ln -s "$PWD/codex-cronloop-skill/cronloop" ~/.codex/skills/cronloop
```

如果当前 Codex 进程未发现新 skill，请重启 Codex CLI。也可以不使用软链接，直接把 `cronloop/` 复制到 `~/.codex/skills/cronloop/`。

## 快速使用

在需要持续接手工作的 Codex 线程中输入：

```text
$cronloop 30m 监控 ./runs/exp-42。检查进程、日志、结果有效性和磁盘空间；
只有确认 runner 已退出且不存在重复实例后，才允许安全重启。
全部三轮通过校验并生成 results.xlsx 后停止。
```

Skill 会把简短指令展开为单轮执行契约，必要时先展示给用户确认，然后安装 cron 条目、检查 daemon/marker 状态，并返回 job ID、日志目录和删除命令。

![安装和状态效果示例](docs/images/demo-terminal.svg)

也可以直接检查或停止任务：

```bash
python3 ~/.codex/skills/cronloop/scripts/cronloop.py list
python3 ~/.codex/skills/cronloop/scripts/cronloop.py status --job-id benchmark-watch
python3 ~/.codex/skills/cronloop/scripts/cronloop.py remove --job-id benchmark-watch
```

支持 `30m`、24 的小时因子（`1h`、`2h`、`3h`、`4h`、`6h`、`8h`、`12h`）以及 `1d`。为避免无意义的频繁唤醒，小于 30 分钟的间隔会被拒绝。

## 效果示例

仓库中的[实验监控示例](examples/benchmark-monitoring.md)描述了一个“8 个配置 × 15 个 query × 3 轮”的场景：

1. 每 30 分钟恢复同一个线程，检查 runner、最新日志、结果矩阵、磁盘和主机负载。
2. 运行健康时只汇报证据，不干预实验。
3. runner 消失时先诊断；只有恢复操作被明确授权且能够避免重复运行，才执行恢复。
4. 所有矩阵单元有效后，生成最终表格并验证产物，然后汇报完成并删除自己的 cron 标记块。

这样可以让 agent 持续参与诊断和调优，同时无需在两次检查之间维持模型进程。

## 安全设计

| 风险 | 防护措施 |
|---|---|
| 恢复了错误会话 | 强制要求精确 UUID 和对应本地 rollout |
| 多轮重叠运行 | 非阻塞文件锁 + 线程最近活动检查 |
| 单轮失控 | 每轮超时必须短于调度间隔 |
| Prompt 泄漏凭据 | 拒绝疑似密钥赋值，落盘文件权限为 `0600` |
| 代理 URL 泄漏凭据 | 不保存带用户名或密码的代理 URL |
| 破坏已有 crontab | 只替换或删除指定的 `BEGIN/END CRONLOOP` 块 |
| 恢复动作越权 | 展开后的 prompt 必须写明范围、允许恢复和禁止动作 |
| 完成后仍继续唤醒 | 验证完成后执行该 job 专属的删除命令 |

Cronloop 不使用跳过审批/沙箱的参数，也不能唤醒普通网页或 API 对话；它只处理本机 Codex CLI 能定位并恢复的线程。

## 仓库结构

```text
cronloop/                 可直接安装的 Codex skill
  SKILL.md
  agents/openai.yaml
  scripts/cronloop.py
docs/images/              中英文 README 共用的版本化附图
examples/                 展开的 prompt 与效果产物示例
tests/                    使用伪 crontab/伪 Codex 的隔离测试
```

## 开发与测试

```bash
python3 -m unittest discover -s tests -v
python3 cronloop/scripts/cronloop.py --help
```

测试只使用临时目录，不会写入真实 crontab，也不会恢复真实线程。

## 许可证

[MIT](LICENSE)
