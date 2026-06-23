---
name: cron-ops
description: "当用户想创建、查看、修改、启用、停用、删除 opendog 定时任务时使用这个技能。触发词包括：定时任务、cron、CRON.md、每天/每周/每小时到点执行、提醒我、到某个时间自动做事、自动推送到飞书、取消定时任务、查看有哪些定时任务。这个技能只说明如何用现有文件工具管理 workspace/crons。"
---

# Cron 定时任务管理

这个技能用于通过编辑文件来管理 opendog 的定时任务。

不要创建或请求专门的 cron 工具。定时任务管理本质上就是文件管理：

| 用户想做什么 | 实际要做什么 |
| --- | --- |
| 创建定时任务 | 写入 `workspace/crons/<cron-id>/CRON.md` |
| 查看定时任务列表 | 列出并读取 `workspace/crons/*/CRON.md` |
| 查看某个任务详情 | 读取对应任务的 `CRON.md` |
| 修改定时任务 | 编辑对应任务的 `CRON.md` |
| 暂停定时任务 | 把 `enabled` 改成 `false` |
| 删除定时任务 | 只有用户明确要求删除时，才删除对应任务目录 |

## 文件位置

定时任务文件放在 opendog 的 workspace 里：

```text
workspace/crons/<cron-id>/CRON.md
```

目录名使用安全的小写短横线格式：

```text
morning-news
daily-summary
meeting-reminder
```

不要把定时任务文件放到用户当前项目目录里。

## CRON.md 格式

```md
---
name: Morning News
description: 每天早上总结新闻
agent: Beagle
schedule: "0 9 * * *"
enabled: true
one_off: false
min_interval_minutes: 5
deliver_to:
  type: feishu
---

搜索今天的科技新闻，总结三条最重要的内容。
```

## 字段说明

| 字段 | 含义 |
| --- | --- |
| `name` | 给人看的任务名 |
| `description` | 简短说明 |
| `agent` | 使用哪个 Agent，通常写 `Beagle` |
| `schedule` | cron 表达式，按本机时间判断 |
| `enabled` | `true` 表示启用，`false` 表示暂停 |
| `one_off` | `true` 表示成功执行一次后自动停用 |
| `min_interval_minutes` | 最小执行间隔，默认用 `5` |
| `deliver_to` | 结果输出端口；当前只使用飞书 |
| 正文 | 任务触发时发送给 Agent 的提示词 |

## 时间写法示例

```text
0 9 * * *        每天 9:00
30 18 * * 1-5    周一到周五 18:30
*/10 * * * *     每 10 分钟
```

cron 使用运行 `opendog cron` 那台机器的本地系统时间。

不要创建低于最小间隔的任务：

```text
* * * * *
*/1 * * * *
*/2 * * * *
*/3 * * * *
*/4 * * * *
```

## 结果输出

当前只保留一个输出端口：飞书。

```yaml
deliver_to:
  type: feishu
```

创建新定时任务时，默认把结果输出到飞书。`chat_id` 的处理规则：

1. 通常不要手写 `chat_id`；opendog 会从第一次飞书消息里自动记住默认飞书入口。
2. 如果用户明确要求发到某个特定飞书群或聊天，再询问用户如何指定。
3. 不要编造 `chat_id`。
4. 不要再创建“无外部输出”这类输出端口；当前对外输出只写飞书。

## 创建定时任务

当用户要求创建定时任务时：

1. 把用户的时间需求转换成 cron 表达式。
2. 选择一个安全的任务目录名。
3. 写入 `workspace/crons/<cron-id>/CRON.md`。
4. 告诉用户任务文件路径和执行时间。
5. 提醒用户必须保持 `opendog cron` 运行，任务才会执行。

示例：

```md
---
name: Daily Summary
description: 每天下午总结当天工作
agent: Beagle
schedule: "0 18 * * *"
enabled: true
one_off: false
min_interval_minutes: 5
deliver_to:
  type: feishu
---

总结今天的工作记录，列出完成事项、风险和明天建议。
```

## 查看定时任务

当用户询问有哪些定时任务时：

1. 列出 `workspace/crons` 下的目录。
2. 读取每个任务的 `CRON.md`。
3. 汇总 `name`、`schedule`、`enabled`、`one_off` 和 `deliver_to`。

## 暂停或删除

除非用户明确说“删除”，否则优先暂停任务。

暂停：

```yaml
enabled: false
```

删除：

```bash
rm -rf "workspace/crons/<cron-id>"
```

只删除用户明确指定的那个 cron 任务目录。

## 重要边界

- 使用已有的 `read`、`write`、`edit`、`multiedit` 和 `bash` 工具。
- 不要编造 `create_cron`、`delete_cron` 或其他 cron 专用工具。
- 不要为了 cron 设置去修改 `workspace/config.user.yaml`。
- 不要创建 heartbeat 任务。
- 不要创建比 `min_interval_minutes` 更频繁的任务。
- 必须保持 `opendog cron` 运行；否则定时任务不会执行。
