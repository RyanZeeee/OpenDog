# OpenDog

opendog 是一个运行在终端里的 AI 对话助手项目，目前优先支持 macOS，暂不支持Windows。

![opendog](pic/opendog.png)

项目分成两部分：

```text
src/         Python 引擎代码
workspace/   Agent 配置、技能、记忆和模型设置
```

---

## 快速开始

### 当前支持平台

当前项目按 macOS 优先开发和测试。项目Python 代码不绑定 macOS，但终端交互、shell 工具、路径判断、权限边界和部分 skill 依赖都更接近 macOS/Linux 环境。

推荐使用方式：

| 系统 | 建议 |
|------|------|
| macOS | 推荐，当前主要支持环境 |
| Linux | 理论可运行，但还没有完整测试 |

为什么 Windows 不建议运行：

- shell 工具默认使用 `bash`、`ls`、`rm`、`which`、`chmod` 这类 Unix 命令
- 路径判断主要按 `/Users/...`、`/tmp`、`HOME` 这类 Unix 路径模型设计
- Windows 的盘符路径、反斜杠、PowerShell 语法和当前权限解析器的设计不同
- TUI 的中文输入、换行、终端尺寸在 Windows 终端里还没专项适配



### 在新 Mac 上安装

把项目文件夹拷到新电脑后，一条命令完成安装。它会安装所有依赖、创建 `opendog` 命令，并自动绑定 workspace 路径：

```bash
bash scripts/install_opendog.sh
source ~/.zshrc
```

需要 Python 3.9+，Mac 自带。

### 配置模型

`workspace/config.user.yaml` 里需要至少填好 `provider`、`model`、`api_key`，例如使用 DeepSeek：

```yaml
llm:
  provider: deepseek
  model: deepseek-v4-pro
  api_key: your-api-key-here
  api_base: https://api.deepseek.com
  temperature: 0.7
  max_tokens: 16000
```

历史压缩参数也在同一个配置文件里：

```yaml
history:
  max_tokens: 200000        # 超过这个值触发压缩
  keep_recent_messages: 20  # 压缩时保留最近多少条
  summary_max_tokens: 8000  # 压缩后的摘要最大 token 数
```

这个项目通过 LiteLLM 调用模型。只要是 LiteLLM 支持的 provider，改 `provider`、`model`、`api_key`、`api_base` 四个字段即可。如果用官方接口，`api_base` 可以留空；如果用中转站或 OpenAI 兼容接口，把 `api_base` 改成对应地址。

配置只从 `workspace/config.user.yaml` 读取。项目不会自动加载 `.env`，模型 key、飞书 App Secret 等都直接写在这个 YAML 配置文件里。

### 配置字段速查

`workspace/config.user.yaml` 当前字段：

| 字段 | 作用 |
|------|------|
| `llm.api_base` | 自定义 API 地址 |
| `llm.api_key` | 模型 API key |
| `llm.extra` | 透传给 LiteLLM 的额外参数 |
| `llm.max_tokens` | 单次模型回复最大输出 token |
| `llm.model` | 模型名，例如 `deepseek-v4-flash` |
| `llm.provider` | LiteLLM provider，例如 `deepseek`、`openai`、`anthropic` |
| `llm.temperature` | 默认0.7 |
| `history.keep_recent_messages` | 压缩时保留最近多少条消息 |
| `history.max_tokens` | 超过多少 token 触发压缩 |
| `history.summary_max_tokens` | 历史摘要最大 token |
| `mcpServers.<id>.agent_managed` | 是否允许 Agent 通过 MCP 工具启动/关闭这个服务 |
| `mcpServers.<id>.description` | MCP 服务说明 |
| `mcpServers.<id>.enabled` | 是否启用这个 MCP 服务 |
| `mcpServers.<id>.type` | MCP 连接类型，例如 `sse` |
| `mcpServers.<id>.url` | SSE MCP 服务地址 |
| `feishu.allow_from` | 允许使用 Bot 的 open_id 白名单，空列表表示不限制 |
| `feishu.app_id` | 飞书应用 App ID |
| `feishu.app_secret` | 飞书应用 App Secret |
| `feishu.enabled` | 是否启用飞书入口 |
| `feishu.group_policy` | 群聊策略，当前保留字段 |
| `feishu.streaming` | 是否启用飞书流式卡片 |
| `paths.agents_dir` | Agent 目录，默认 `agents` |
| `paths.skills_dir` | Skills 目录，默认 `skills` |
| `tools.builtin.enabled` | 是否启用内置工具 |
| `tools.plugins.enabled` | 是否启用插件工具 |
| `tools.plugins.paths` | 插件目录列表 |
| `default_agent` | 默认启动的 Agent 目录名 |

### 启动聊天

安装后在项目文件夹下打开终端，运行：

```bash
opendog
```

如果当前终端暂时找不到 `opendog` 命令，先刷新 shell 配置：

```bash
source ~/.zshrc
```

如果还是找不到，重新运行安装脚本：

```bash
bash scripts/install_opendog.sh
```

使用其他 workspace：

```bash
opendog --workspace path/to/workspace
```

常用入口：

```bash
opendog         # 启动终端聊天 TUI
opendog feishu  # 启动飞书长连接入口
opendog cron    # 启动定时任务 runner
```

`opendog feishu` 和 `opendog cron` 是两个独立进程。如果既要接收飞书消息，又要定时推送，需要开两个终端分别运行。

TUI 中输入：

```text
退出
```

即可结束聊天。Agent 正在生成时继续输入内容，会被加入当前任务的“引导”，不会立刻打断当前轮。

---

## Workspace 说明

`workspace/` 是用户可编辑的数据区，代码逻辑不会写死在这里。

```text
workspace/
├── config.user.yaml
├── config.example.yaml
├── agents/
│   ├── Beagle/
│   │   ├── AGENT.md
│   │   ├── SOUL.md
│   │   └── skills.txt
│   └── Designer/
│       ├── AGENT.md
│       ├── SOUL.md
│       └── skills.txt
├── plugins/
│   └── README.md
├── skills/
│   └── your-skill/
│       ├── SKILL.md
│       ├── scripts/
│       ├── package.json
│       └── node_modules/
├── crons/
│   └── your-cron/
│       └── CRON.md
├── memories/
│   ├── topics/
│   ├── projects/
│   └── daily-notes/
└── .runtime/
    ├── feishu_state.json
    └── cron_state.json
```

改模型，就改 `config.user.yaml`。
增加 Agent，就在 `agents/` 下新增一个 Agent 目录。
增加技能，就在 `skills/` 下新增一个技能目录和 `SKILL.md`。如果技能需要脚本或依赖，也放在同一个技能目录里。
增加插件，就在 `plugins/` 下新增一个插件目录，并在里面提供 `plugin.py`。插件里的工具通过 `register_tools(registry)` 注册。
增加定时任务，就在 `crons/` 下新增一个任务目录和 `CRON.md`。


`.runtime/` 是程序自动写入的运行状态目录，不是用户手写配置区。

---

## Agent设计

### 解耦

拆分的核心目的很简单：不要让一个文件什么都管。

```text
读取输入
判断 slash command
等待 MCP
调用 Agent
处理流式输出
显示状态
处理权限弹窗
处理引导
```

这样短期能跑，但后面会越来越难扩展。比如以后想加 Web UI、HTTP API、多 Agent、后台任务、日志系统，就会发现聊天流程和终端界面绑死了。

现在拆成几层：

```text
TUI                  只管显示和用户交互
ConversationRuntime  只管一条输入该走什么流程
AgentSession         只管 LLM + tools 的智能体循环
ToolRegistry         只管工具注册、查找和执行
SkillRegistry        只管 skill 元数据发现
EventBus             只管事件转发，不处理业务
SharedContext        只管共享运行信息
```

每一层只执行自己必须执行的东西：

```text
TUI 不需要知道 Agent 怎么调用工具
Agent 不需要知道结果显示在终端还是网页
工具不需要知道是谁触发了它
EventBus 不需要知道事件背后的业务含义
Command 不需要知道 TUI 怎么渲染结果
```

这带来几个好处：

```text
1. 后面换界面更容易
   终端 TUI、Web UI、HTTP API 都可以把输入交给 ConversationRuntime。

2. 后面加后台任务更容易
   Worker 可以通过 EventBus 发事件，不需要直接操作 TUI。

3. 后面加新工具更容易
   Agent 只通过 ToolRegistry 调工具，不需要在核心循环里写工具名判断。

4. 后面排查问题更容易
   显示问题看 TUI，流程问题看 Runtime，工具问题看 Tools，模型循环问题看 AgentSession。

5. 代码不容易越写越乱
   新功能先判断属于哪一层，而不是全部塞进一个文件。
```



### 核心分层

```text
用户终端
  ↓
CLI / TUI 层
  ↓
ConversationRuntime 对话运行层
  ↓
AgentSession 智能体循环层
  ↓
Tools / Skills / MCP / LLM 底层能力
```

### 各层详解

#### 1. Start Up

入口在 `src/opendog/cli/main.py`。

它负责读取 `workspace/config.user.yaml`，创建 `SharedContext`，加载 Agent，创建或恢复 Session，然后启动 TUI。

`SharedContext` 在 `src/opendog/core/shared_context.py`，统一保存运行时共享信息：

```text
workspace_root   opendog 的配置目录
working_dir      用户启动 opendog 的目录
config           用户配置
session_store    会话存储
```

这样TUI、Runtime、Command 都能拿同一个上下文，不再临时拼对象。

#### 2. TUI

核心在 `src/opendog/cli/tui.py`。

TUI 只负责用户能看见和操作的部分：

```text
启动页
输入框
AI 回复显示
状态栏
权限弹窗
引导显示
滚动和颜色
```

TUI 不直接决定"这一句话应该怎么跑完整对话流程"，而是把输入交给 `ConversationRuntime`。

启动页会显示当前版本、Agent、模型、工作目录、workspace、skill 数量、tool 数量和 MCP 配置数量。启动页只展示状态不参与推理。

#### 3. ConversationRuntime

核心在 `src/opendog/core/conversation_runtime.py`。

负责"一条用户输入怎么被处理"：

```text
判断是不是 / 斜杠命令
执行本地 slash command
未知 slash command 交给 Agent
第一轮消息等待 MCP 工具加载
调用 AgentSession.stream_chat()
把 Agent 事件转换成 RuntimeEvent
把引导内容交给 Session
```

这层的作用是把界面和 Agent 解耦。以后的Web UI、HTTP API，不需要复制 TUI 里的聊天流程。

#### 4. AgentSession

核心在 `src/opendog/core/agent.py`。

它负责真正的 ReAct 循环：

```text
用户消息
  ↓
构建 system prompt
  ↓
发送给 LLM
  ↓
模型可能返回 tool_calls
  ↓
执行工具
  ↓
工具结果写回 messages
  ↓
继续发给 LLM
  ↓
直到模型输出最终答案
```

这里还负责 skills 注入、active skill、引导写入历史、权限检查、工具调用结果处理、上下文压缩和长文件写入保护。

#### 5. Tools / Skills / MCP

工具注册中心在 `src/opendog/tools/registry.py`。

内置工具在：

```text
src/opendog/tools/builtin/
├── filesystem.py
├── shell.py
└── skills.py
```

MCP 在：

```text
src/opendog/tools/mcp/
├── client.py
├── manager.py
├── loader.py
└── tool.py
```

Skills 扫描在 `src/opendog/core/skill_registry.py`，负责扫描 `workspace/skills`，把 skill 的名字和描述注入 system prompt。真正需要某个 skill 时，Agent 再通过 `read` 读取对应的 `SKILL.md`。

#### 6. EventBus

 `src/opendog/core/event_bus.py`

现在它提供三个动作：

```text
subscribe()   订阅某类事件
publish()     发布某个事件
unsubscribe() 取消订阅
```

模块把事件 publish 给 EventBus，关心这类事件的模块通过 subscribe 接收。只负责转发事件不判断业务。

EventBus 支持按事件类型和 session 过滤：

```text
event_type = "status"  只接收只接收状态事件，比如工具调用、思考中、完成这些。
event_type = "*"       接收所有事件，包括 AI 输出、状态、错误、本地消息等。
session_id = None      不限制会话，所有会话的事件都接收。
session_id = "abc"     只接收 abc 会话发出的事件。
```



新增接口原则：

```text
TUI：直连 ConversationRuntime，直接消费 yield 出来的 RuntimeEvent。
新增接口：输入调用 ConversationRuntime，输出订阅 EventBus。
EventBus：只服务新增接口、日志、Worker、监控等旁路接收者。
```

用户输入也会生成 `user_message` 事件并 publish 到 EventBus，但不会发给当前 TUI，避免界面重复显示用户输入。以后多个端口打开同一个 session 时，其他端口可以订阅这个事件来同步显示。



## 工具系统 & MCP

工具统一走注册表：

```text
把工具说明发给模型 → 模型决定要不要调用工具 → 注册表查表执行工具
```

当前支持三类入口：

```text
内置工具 builtin   src/opendog/tools/builtin/
插件工具 plugins  workspace/plugins/
MCP 工具 mcp      通过 mcpServers 配置外部 MCP server，可由 Agent 按需启动和关闭
```

内置工具包括：读文件、写文件、编辑文件、执行 bash 命令、查看技能。
如果想让 Agent 说明当前有哪些工具，它会使用 `list_tools` 按来源分组展示：

```text
builtin  opendog 自带工具
plugin   workspace/plugins/ 下的插件工具
mcp      外部 MCP server 暴露的工具
```

### 内置工具

| 工具 | 作用 |
|------|------|
| `read` | 读取文本文件，支持 `offset` 从指定字符位置开始读 |
| `write` | 创建或覆盖文本文件 |
| `append` | 追加文本到文件末尾，适合长内容分段写入 |
| `edit` | 对单个文件做一次文本替换 |
| `multiedit` | 对单个文件按顺序做多处文本替换 |
| `bash` | 在工作目录中执行 bash 命令，返回 stdout、stderr 和 exit code |
| `list_skills` | 查看当前会话可用的 skill 列表 |
| `list_tools` | 按 builtin / plugin / mcp 来源分组查看工具 |

这些工具都会走同一套权限边界。Agent 不需要知道工具来自哪里，只需要按模型拿到的 tool schema 调用。

### 插件工具

插件工具放在 `workspace/plugins/` 下。支持两种结构：

```text
workspace/plugins/plugin.py
```

或：

```text
workspace/plugins/<plugin-name>/plugin.py
```

`plugin.py` 里需要提供：

```python
def register_tools(registry):
    ...
```

插件内部可以用 `@tool` 定义工具，然后在 `register_tools()` 中注册到工具表：

```python
from opendog.tools.base import tool


@tool(
    name="hello",
    description="返回一句问候。",
    parameters={"type": "object", "properties": {}},
)
async def hello(session):
    return "hello"


def register_tools(registry):
    registry.register(hello)
```

启动时如果 `tools.plugins.enabled: true`，opendog 会扫描 `tools.plugins.paths` 里的插件目录。加载成功的插件工具会显示为 `plugin` 来源。

开关在 `workspace/config.user.yaml`：

```yaml
tools:
  builtin:
    enabled: true
  plugins:
    enabled: true
    paths:
      - plugins
```

### MCP 传输协议

MCP 支持两种传输协议：

| 类型 | 连接方式 | 需要字段 | 适用场景 |
|------|---------|---------|---------|
| `stdio` | 本地启动子进程，通过标准输入输出通信 | `command` + `args` + `env` | 本地可执行的 MCP server（需 Node.js 等运行时） |
| `sse` | HTTP SSE 连接远程服务器，通过流式事件通信 | `url` | 云端托管的 MCP 服务（无需本地依赖） |

`enabled: false` 表示 opendog 启动时不自动打开这个 MCP server。
`agent_managed: true` 表示 Agent 可以通过 `mcp_start_server` 和 `mcp_stop_server` 受控地开关它。

### MCP 启动策略

配置了 `enabled: true` 的 MCP 服务器会在后台并发加载，不会阻塞 TUI 启动。聊天界面会立刻出现，底部状态条显示 spinner + `MCP loading (1/2)` 直到全部就绪。如果第一条消息发出时 MCP 还未加载完成，Agent 会等最多 5 秒再发送，确保首轮对话即可使用 MCP 工具。

---



## 斜杠命令

以 `/` 开头的输入会被拦截并本地执行，不经过 LLM，不消耗 token。

| 命令 | 功能 |
|------|------|
| `/help` | 列出所有可用命令及描述 |
| `/session` | 显示当前会话 ID、agent 名、消息数、创建时间 |
| `/agent` | 列出/切换当前 Agent；`/agent <agent_id>` 切换 Agent |
| `/skills` | 列出所有可用 skill 名称 |
| `/mcp` | 列出 MCP 配置及开关状态；`/mcp <name> on/off` 切换开关（写回 config.user.yaml） |
| `/compact` | 强制压缩当前上下文（消息 < 3 条时提示无需压缩） |

**拦截流程：**

```
用户输入 → 以 / 开头？
              ├── 是 → 查注册表执行命令，结果显示为 event 消息，跳过 LLM
              └── 不是 → 正常走 chat() 流程，发给 LLM
```

不存在的命令（如 `/abc`）会当普通消息发给 LLM 处理。新增命令只需在 `src/opendog/cli/commands.py` 中写一个 Command 子类并注册即可，不用改核心循环。

---



## 打断和引导

当 Agent 正在生成、调用工具或等待工具结果时，用户仍然可以继续输入提示词。这个输入不会打断当前轮，也不会被 TUI 当成下一轮普通消息直接发送，而是作为"引导"加入当前任务。

界面上会显示：

```text
>: 改成黑白极简
  · 已加入引导
```

状态栏会显示：

```text
思考中... · 已加入 1 条引导
```

多条引导会按输入顺序收集。TUI 收到引导后会调用 `AgentSession.add_guidance(text)`，把内容暂存在当前会话的 `pending_guidance` 中。

Agent 下一次安全调用 LLM 前，会把这些引导作为正式 `user` 消息写入会话历史：

```text
[当前任务引导]
用户在当前任务执行期间追加了以下引导，请应用到当前任务中：
改成黑白极简
```


如果模型原本准备结束，但这时还有未消费的引导，Agent 会继续当前循环，让模型再处理一次引导内容。TUI 收到处理状态后，会显示：

```text
· 正在处理引导内容
```

---



## Skills 

每个技能目录是一个自包含单元：

```text
workspace/skills/{skill_name}/
├── SKILL.md
├── scripts/
├── package.json
└── node_modules/
```

opendog 会自动识别 `workspace/skills/*/SKILL.md`，并把每个技能目录的运行资源暴露给 shell：

```text
workspace/skills/*/node_modules      → NODE_PATH
workspace/skills/*/node_modules/.bin → PATH
workspace/skills/*/scripts           → PYTHONPATH
workspace/skills/*                   → PYTHONPATH
```

opendog 在创建会话时扫描一次 `workspace/skills/*/SKILL.md`，只读取 YAML 元数据：

```yaml
---
name: python-helper
description: 帮助处理 Python 编程、调试和报错分析
---
```

然后把技能名称、简介和文件路径追加到 system prompt 的 `Available Skills` 段落。

当任务明显匹配某个 skill 时，opendog 会要求 Agent 先用 `read` 工具读取对应的 `SKILL.md`，再按里面的说明执行。
这条规则目前主要通过 system prompt 约束模型执行顺序。这些运行资源不会直接注入 system prompt。system prompt 只披露 skill 的名称、简介和 `SKILL.md` 路径；需要时 Agent 再读取对应的 `SKILL.md`。

Agent 使用 skill 时，仍然遵守同一套权限边界：工作目录内的命令可以运行；工作目录外会弹出权限申请。

这种设计的优点：

```text
依赖跟当前工作目录绑定，结果更可复现
不污染 opendog 引擎目录
不污染 workspace/skills
不污染项目根目录的 package.json / package-lock.json / node_modules
不依赖系统全局 npm 或 /usr/local、/opt/homebrew
同一个工作目录下可复用缓存依赖
```

缺点也很明确：

```text
换一个项目目录后，需要重新安装一次依赖
依赖仍然会占用当前项目的 .opendog_tmp 空间
首次执行相关 skill 会慢一些
磁盘占用会增加
```

匹配依据来自 skill 的 `name` 和 `description`，所以新增 skill 时要把适用场景写进 description：

```yaml
---
name: ui-ux-pro-max
description: UI/UX design intelligence for web and mobile. Use for HTML/CSS, websites, dashboards, landing pages, and visual design tasks.
---
```

新增、删除、修改 skill 后，需要新开会话或重新启动 `opendog` 才会生效。

---



## 多 Agent

opendog 支持在同一个 workspace 里放多个 Agent。每个 Agent 一个目录：

```text
workspace/agents/
├── Beagle/
│   ├── AGENT.md
│   ├── SOUL.md
│   └── skills.txt      # 可选
└── Designer/
    ├── AGENT.md
    ├── SOUL.md
    └── skills.txt      # 可选
```

文件分工：

```text
AGENT.md    Agent 的身份、能力、硬规则
SOUL.md     Agent 的语气、性格、沟通风格
skills.txt  这个 Agent 可见的专属 skill 列表
```

`AGENT.md` 和 `SOUL.md` 会在加载时拼成同一条 system prompt：

```text
AGENT.md 正文

SOUL.md 正文
```

### 文件格式

#### AGENT.md

`AGENT.md` 使用 YAML frontmatter + Markdown 正文格式：

```md
---
name: Agent的名字
description: 关于Agent的简要描述
---

正文，Agent 的身份、能力和行为规则

Capabilities:

-
-
- 

Behavioral Guidelines:

-
-
-
```

字段说明：

```text
name         Agent 显示名称
description  Agent 简介，会显示在 /agent 列表里
正文          Agent 的身份、能力和行为规则
```

#### SOUL.md

`SOUL.md` 不需要 YAML 头，直接写性格和表达风格：

```md
例：
你说话像一个冷静、专业但不端着的设计搭档。
你会直接指出设计问题，也会给出可落地的修改方向。
你的表达简洁、有判断力，少说套话。
```

它会被拼到 `AGENT.md` 正文后面，用来补充 Agent 的语气和气质。

#### skills.txt

`skills.txt` 是可选文件，一行一个 skill 名：

```text
ui-ux-pro-max
pptx
```

支持用 `#` 写注释：

```text
# Designer 可用的技能
ui-ux-pro-max
pptx
```

如果没有 `skills.txt`，这个 Agent 可以看到全部 skill。  
如果有 `skills.txt`，这个 Agent 只会看到文件里列出的 skill。

### 切换 Agent

查看所有 Agent：

```text
/agent
```

切换到指定 Agent：

```text
/agent Designer
```

切换 Agent 后：

```text
当前 session_id 不变
当前会话历史不清空
不会创建新的历史记录
后续回复使用新 Agent 的 AGENT.md + SOUL.md
/session 会显示新的 Agent 名称
```

### Agent 专属 Skill

所有 skill 仍然统一放在：

```text
workspace/skills/
```

如果某个 Agent 没有 `skills.txt`，它可以看到全部 skill。

如果某个 Agent 有 `skills.txt`，它只会看到文件中列出的 skill：

```text
# workspace/agents/Designer/skills.txt
ui-ux-pro-max
pptx
```

切换 Agent 后，`/skills` 会跟随当前 Agent 变化，只显示当前 Agent 可用的 skill。

---



## 会话记忆与历史

opendog 有两套记忆系统：

`/agent` 切换不会创建新会话，历史仍写入当前 session 文件。

### 1. 会话记录（`.history/`）

每次对话都会自动保存到磁盘，退出 TUI 后不会丢失。

历史目录位于 `src/opendog/.history/`。所有入口都会写到这里：TUI、飞书和 cron 只是使用不同的 `session_id`。

**存储结构：**

```text
src/opendog/.history/
├── index.jsonl              # 每行一个会话概要（标题、时间、消息数）
└── sessions/
    ├── {uuid}.jsonl         # 每行一条消息
    └── {uuid}.jsonl
```

**index.jsonl 每行格式：**

```json
{"id": "abc123", "agent_name": "Beagle", "title": "帮我写排序脚本", "message_count": 12, "created_at": "2026-06-16T10:30:00+08:00", "updated_at": "2026-06-16T11:00:00+08:00"}
```

**写穿机制：** 每条用户和助手消息追加写入 session 文件，同时更新 index。工具调用结果不写入磁盘，助手消息中的 `tool_calls` 引用也会在写入前剥离，避免恢复会话时出现残留的工具调用引用导致 API 报错。上下文压缩后，整个 session 文件会被重写为压缩后的内容。

**容错设计：**
- 首次启动无 `.history` 目录 → 自动跳过选择器，正常新建会话
- index 行损坏 → 跳过该行，其他会话不受影响
- session 文件行损坏 → 跳过该行，部分恢复
- index 有记录但 session 文件被删 → 启动时自动清理孤儿条目
- 压缩后立即退出 → 文件已在压缩时重写，无需额外操作

### 2. 启动时会话选择器

启动 `opendog` 时，如果 `.history/` 中有历史会话，会先弹出一个会话选择界面：

```
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Recent Sessions                                          ┃
┃ ↑↓ 选择  Enter 恢复  n 新建  d 删除  q 退出                 ┃
┃                                                          ┃
  →  06-16 14:30  帮我写个排序脚本  12 条消息                 ┃
     06-16 10:00  今天天气真好  5 条消息                      ┃
     06-15 09:20  (空对话)  0 条消息                         ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
```

操作方式：

| 按键 | 作用 |
|------|------|
| `↑` `↓` | 上下移动选择 |
| `Enter` | 恢复当前选中的会话 |
| `n` | 跳过选择器，创建新会话 |
| `d` | 删除当前选中会话（弹出 y/n 确认） |
| `q` `Esc` | 退出选择器（等同新建） |



### 3. 删除会话记录

#### 删除 TUI 聊天记录

最简单的方法是在启动 `opendog` 时使用会话选择器删除：

```text
opendog
  ↓
选择历史会话
  ↓
按 d
  ↓
按 y 确认
```

这会同时删除对应的 `sessions/{session_id}.jsonl`，并从 `index.jsonl` 里移除记录。

#### 删除飞书聊天记录

飞书聊天记录文件名以 `feishu-` 开头：

```text
src/opendog/.history/sessions/feishu-oc_xxx.jsonl
```

删除某个飞书会话时，需要删除对应 session 文件，并清理 `index.jsonl` 里的同名记录。当前还没有专门命令，推荐先用启动会话选择器删除；如果手动删了 session 文件，下次启动时 `SessionStore` 会自动清理孤儿 index 条目。

如果只是想重置"默认飞书入口"，删除的是这个运行状态文件：

```bash
rm workspace/.runtime/feishu_state.json
```

它不会删除聊天历史，只会让 opendog 下次收到飞书消息时重新记住默认入口。

#### 删除定时任务记录

定时任务聊天记录文件名以 `cron-` 开头：

```text
src/opendog/.history/sessions/cron-morning-news.jsonl
```

删除它只会删除这个定时任务的对话历史，不会删除定时任务本身。

定时任务定义文件在：

```text
workspace/crons/<cron-id>/CRON.md
```

所以要区分两件事：

```text
删除 cron 会话记录 → 删除 src/opendog/.history/sessions/cron-xxx.jsonl
删除 cron 任务本身 → 删除 workspace/crons/xxx/
```

#### 清空全部会话记录

如果确定要清空所有 TUI、飞书、cron 的聊天历史，可以删除整个 `.history`：

```bash
rm -rf src/opendog/.history
```

下次启动会重新创建。这个操作不会删除 `workspace/crons/` 里的定时任务，也不会删除 `workspace/.runtime/feishu_state.json`。

### 4. 工作记忆（`memories/`）

工作记忆是给 Agent 使用的持久记忆区，按类别分目录存放：

```text
workspace/memories/
├── topics/          # 按主题存放知识笔记
├── projects/        # 按项目存放上下文
└── daily-notes/     # 按日期存放工作日志
```

Agent 可以在对话中读取和写入这些目录，把重要信息、用户偏好、项目进度等记录下来，跨会话复用。

---



## 安全边界

opendog 的权限边界按目录 root 判断，不按工具判断。

```text
读/执行允许目录：
- working_dir
- workspace/skills
- 系统临时目录（/tmp、/private/tmp、/var/tmp）

写入允许目录：
- working_dir
- 系统临时目录（/tmp、/private/tmp、/var/tmp）

其它目录：
- 默认拦截，并弹出权限申请
```

`working_dir` 是用户启动 `opendog` 的目录，也是 Agent 的默认工作范围。

```text
working_dir  用户启动 opendog 的目录，也是默认工作范围
workspace    opendog 配置、agent、skills、MCP 设置
```

`workspace/skills/**` 是给 Agent 使用的技能说明和运行资源区，不是用户产物目录。
系统临时目录用于临时文件、缓存和系统工具中转，允许读写，但最终产物仍应输出到 `working_dir`。

### 越界申请

```text
路径不在读/执行允许目录内：弹出权限申请
路径不在写入允许目录内：弹出权限申请
bash 命令里能识别到允许目录外的路径：弹出权限申请
osascript：默认视为可能通过系统应用操作外部资源，弹出权限申请
```

权限申请会跳出黄色弹窗。说明工具、操作、命令、目标、工作目录和越界原因。用户允许后，本次工具调用继续执行；用户拒绝后，工具结果会把拒绝原因返回给模型。输入等待会实时显示倒计时，超过 30 秒没有确认时自动拒绝。

弹窗输入：

```text
y  本轮允许
s  本会话允许
n  拒绝
```

---



## 飞书长连接接口

opendog 支持用飞书长连接模式接收消息，不需要公网 IP，也不需要 Webhook。

飞书是当前唯一的外部消息入口和外部输出端口：

```text
用户主动聊天：飞书 → opendog → 飞书回复
定时任务推送：opendog cron → 飞书
```

### 飞书后台配置

在飞书开放平台创建企业自建应用后：

```text
1. 启用机器人能力
2. 在"凭证与基础信息"里复制 App ID
3. 在事件订阅里添加 im.message.receive_v1
4. 事件模式选择"长连接模式"
5. 在权限管理里添加：
   - im:message
   - im:message.p2p_msg:readonly
6. 发布应用版本，让权限和事件生效
```

第一版只做普通文本回复，没有流式卡片，所以 `streaming` 先保持 `false`。

### 本地配置

`workspace/config.user.yaml`：

```yaml
feishu:
  enabled: true
  app_id: cli_xxx
  app_secret: your-app-secret
  allow_from: []
  group_policy: mention
  streaming: false
```

字段说明：

```text
enabled          是否启用飞书接口
app_id           飞书应用 App ID
app_secret       直接写 App Secret
allow_from       允许使用 Bot 的 open_id 白名单，空列表表示不限制
group_policy     群聊策略，当前保留字段
streaming         是否启用流式卡片，第一版保持 false
```

`allow_from` 为空时，任何能给 Bot 发消息的人都可以使用。填入 open_id 后，只响应这些用户。

### 启动飞书接口

安装/更新依赖后运行：

```bash
opendog feishu
```

`opendog feishu` 只负责接收飞书消息并回复飞书。它不会自动执行定时任务。

如果既要接收飞书聊天，又要让定时任务到点推送，需要开两个终端：

```text
终端 A：opendog feishu
终端 B：opendog cron
```

如果提示缺少飞书 SDK，重新安装项目依赖：

```bash
bash scripts/install_opendog.sh
```

或者手动安装：

```bash
pip3 install lark-oapi
```

### 默认飞书入口

用户不需要手动查询 `chat_id`。

第一次有人在飞书里给 Bot 发消息时，opendog 会从飞书事件里自动拿到 `message.chat_id`，并保存到：

```text
workspace/.runtime/feishu_state.json
```

这个文件是程序自动写的运行状态，不是用户配置。它的作用是记住"默认把主动消息发到哪个飞书聊天"。之后 cron 主动推送时，就可以直接使用这个默认入口。

如果换了飞书群或想重新绑定默认入口，可以删除这个文件，然后在新的飞书聊天里给 Bot 发一条消息：

```bash
rm workspace/.runtime/feishu_state.json
```

### 当前限制

暂不支持：

```text
流式卡片
图片和文件
复杂群话题上下文
消息撤回
```

---



## 定时任务 Cron

Cron 让 opendog 可以到点自己执行任务。它不需要用户发消息触发，但必须保持 `opendog cron` 进程运行。

定时任务适合这些场景：

```text
每天早上 9 点推送新闻
每天下午 6 点总结工作
每周一提醒整理计划
到某个时间自动让 Agent 做一件事
```

当前定时任务的唯一外部输出端口是飞书。

### 工作方式

`opendog cron` 是一个常驻进程。它每 60 秒检查一次当前本机时间，然后扫描：

```text
workspace/crons/*/CRON.md
```

如果某个 `CRON.md` 的 `schedule` 命中了当前时间，就把 `CRON.md` 正文作为 prompt 交给 Agent 执行。

注意：

```text
没有启动 opendog cron → 定时任务不会执行
关闭终端窗口 → cron 进程停止，定时任务不会继续执行
只启动 opendog feishu → 只能接收飞书消息，不会跑定时任务
```

### 创建任务

在 `workspace/crons/` 下新建一个目录，每个任务一个 `CRON.md`：

```text
workspace/crons/
└── morning-news/
    └── CRON.md
```

示例：

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

字段说明：

```text
name                  任务名称
description           任务说明
agent                 使用哪个 Agent；第一版默认仍使用当前 default_agent
schedule              cron 表达式，按本机本地时间匹配
enabled               是否启用，默认 true
one_off               是否执行一次后自动禁用，默认 false
min_interval_minutes  最小执行间隔，默认 5
deliver_to            结果输出端口，当前只保留飞书
正文                  到点发给 Agent 的 prompt
```

常见 `schedule`：

```text
0 9 * * *        每天 9:00
30 18 * * 1-5    周一到周五 18:30
*/10 * * * *     每 10 分钟
```

### 启动和关闭

启动：

```bash
opendog cron
```

关闭：

```text
Ctrl+C
```

或者直接关闭终端窗口。如果没有启动 `opendog cron`，定时任务不会执行。

### 会话记录

每个 cron 使用独立会话：

```text
session_id = cron-{cron_id}
```

例如：

```text
workspace/crons/morning-news/CRON.md
```

会写入：

```text
src/opendog/.history/sessions/cron-morning-news.jsonl
```

执行状态记录在：

```text
workspace/.runtime/cron_state.json
```



### 输出到飞书

当前 cron 只保留一个外部输出端口：飞书。任务完成后把结果发到飞书：

```yaml
deliver_to:
  type: feishu
```

飞书 `chat_id` 不需要用户手动填写。第一次在飞书里给 Bot 发消息时，opendog 会自动把聊天入口保存到：

```text
workspace/.runtime/feishu_state.json
```

之后 cron 主动推送时，会自动使用这个默认飞书入口。这不依赖 `opendog feishu` 是否启动；只要 `opendog cron` 正在运行，并且飞书 `app_id/app_secret` 配好，就可以主动发送飞书消息。如果某个 `CRON.md` 没有写 `deliver_to`，任务仍会执行并写入历史，但不会走外部输出端口。创建新的定时任务时，优先写飞书输出；不要要求用户手动查询 `chat_id`。



## 上下文压缩

**什么时候触发压缩？**

| 场景 | 说明 |
|------|------|
| 每轮对话开始前 | 用户发送新消息时自动检查一次 |
| 手动执行 `/compact` | 用户主动要求立即压缩 |
| API 报超限错误 | 如果模型接口返回"内容过长"的错误，提示用户先 `/compact` 压缩再重试 |

**压缩是怎么运作的？**

用户发来新消息时，OpenDog 会先估算当前对话大概占用了多少 token。如果还没超过 `history.max_tokens`，就跳过压缩，正常继续对话。

如果已经超过上限，或者用户手动输入 `/compact`，就会进入第一级压缩：保留最近 `history.keep_recent_messages` 条消息不动，把更早的消息压缩成一条摘要。压缩后的新历史会变成“摘要 + 最近几条消息”。如果这样已经低于上限，压缩就完成。

如果第一级压缩后还是太长，就进入第二级压缩：不再保留最近消息，而是把全部历史压缩成一条更短的摘要。这样会丢掉更多细节，但可以最大程度保住这段会话的主线。

如果第二级压缩后仍然超过上限，说明这段会话已经太大，继续压缩也不可靠。这时会提示用户开启新对话。

**摘要里保留什么、丢弃什么？**

| 保留 | 丢弃 |
|------|------|
| 用户说了什么 | 助手回复的正文 |
| 调用了什么工具、操作了哪些文件 | 工具返回的大段内容（文件正文、搜索结果等） |
| 有没有报错或权限被拒 | 重复的中间步骤 |
| 之前已有的摘要内容 | |

这些信息拼成一条结构化的摘要，加上 `[opendog 历史摘要]` 标记。摘要总长度控制在 8000 token 以内，超出就截断。

**压缩后会怎样？**

压缩完成后，精简过的对话内容会立即写回磁盘。下次恢复这个会话时，读到的就是压缩后的版本，不会重复压缩。工具返回的具体内容（比如文件正文）不存入本地，只留在当前轮次的内存里。

**相关配置**

在 `workspace/config.user.yaml` 的 `history` 段：

```yaml
history:
  max_tokens: 200000        # 超过这个值就触发压缩
  keep_recent_messages: 20  # 第一级压缩时保留最近多少条
  summary_max_tokens: 8000  # 摘要最多占多少 token
```
