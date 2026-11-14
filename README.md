# CodeBridge

[![verify](https://github.com/solamn-1042/codebridge-mcp-demo/actions/workflows/verify.yml/badge.svg)](https://github.com/solamn-1042/codebridge-mcp-demo/actions/workflows/verify.yml)

独立公开展示版：已有个人项目的工程化整理，包含真实协议评测与 CI。首次安装与量化结果见 [验收记录](docs/VALIDATION.md)。下文 `C:/projects` 是路径示例，请替换为你的实际路径。

DeepSeek Harness 是提供模型会话、Agent Loop 和工具运行环境的宿主；本项目扩展仓库工具及其生命周期管理。

面向本地代码仓库接手与改动复核的 Agent 工具扩展。通过 MCP 将代码定位、按行读取、具体 Git 差异和固定检查接入 DeepSeek Harness，返回可追溯的文件路径、行号和执行结果。

## 使用场景

开发者让 Agent 接手陌生仓库时，通常需要先了解项目结构，搜索实现位置，阅读相关代码，再检查改动。通用文件工具和 Shell 工具可以完成这些动作，但需要自行控制读取范围、选择正确的 Git diff 模式并解释命令失败。

CodeBridge 将这个过程收敛为有边界的仓库工具：概览 → 搜索 → 按行读取 → 文件级 diff → 固定检查。模型选择工具和相对文件路径，仓库根目录与可执行命令由本地配置确定。

## 工具

| 工具 | 功能 |
|---|---|
| repo_overview | README 摘要、项目清单、顶层目录及分支 |
| search_code | UTF-8 代码内容的字面量检索，返回路径、行号和片段 |
| read_file | 按行区间读取文件，输出行号及后续读取位置 |
| change_summary | Git 文件状态、改动数量及 diff 统计 |
| git_diff | 指定文件的 staged、unstaged 或 HEAD 到工作区的具体 patch |
| run_project_check | 只接受 test，固定执行当前解释器的 pytest -q |
| tool_metrics | SQLite 中的调用次数、平均/P95 耗时与错误类型 |

DSH 中的名称为 mcp__codebridge__工具名。自定义 Cordis 插件另提供 codebridge_status、codebridge_set_enabled 和 codebridge_restart 三个控制工具。

## 架构与代码归属

- server.py：本项目的 MCP 业务工具及统一异常/观测包装。
- repository_policy.py：相对路径检查、真实路径边界、链接拒绝、已知敏感路径排除及文件读取预算。
- execution.py：固定参数子进程、文件暂存输出、超时终止及有限结果返回。
- telemetry.py：只保存工具名、调用 ID、耗时、错误类型和输出长度的 SQLite 记录。
- plugins/codebridge-manager.ts：本项目的 Cordis 启停、状态和手动重连编排。
- lib/codebridge-manager.js：由 npm run build 生成、供 WebUI 安装后加载的 JavaScript 入口。
- package.json 的 dsh.bundle.patch：声明可安装的 DSH 组合包，指向 dsh.mcp.patch.yml。
- @deepseek-ai/dsh-mcp-client：官方 MCP 连接、工具发现与注册组件。
- @deepseek-ai/cordis：官方插件/Fiber 生命周期机制。
- mcp：Python MCP 协议 SDK。

模型调用、Agent Loop 和会话管理由 DSH 提供。CodeBridge 扩展的是仓库工具与服务管理，不另行实现 Agent 引擎。

## 当前目录运行

多个插件共用一套 DSH 宿主。本项目默认复用同级 deepseek-harness，构建和集成测试无需在 CodeBridge 中安装 DSH 或运行 npm install。Cordis、tools 和 MCP Client 声明为由宿主提供的 peer，插件安装时不自动下载这些包。现有 node_modules 缓存链接无需改动。

PowerShell：

```powershell
Set-Location 'C:\projects\CodeBridge'
& '.\.venv\Scripts\python.exe' -m pytest -q
npm run test:cordis
& '.\.venv\Scripts\python.exe' eval\benchmark.py --rounds 20
```

独立启动 stdio 服务：

```powershell
& '.\.venv\Scripts\python.exe' server.py
```

该命令等待 MCP Host 的标准输入输出通信，不提供网页或 HTTP 端口。MCP SDK 集成测试会实际连接该服务。

在全新普通目录准备插件：使用 Python 3.12 创建 .venv，运行 pip install -r requirements.txt；使用 Node 22.19+（22.x）或 Node 24+ 执行 npm run build。构建使用 Node 自带的类型擦除功能。集成测试通过宿主自己的包解析机制复用已安装依赖，默认宿主为 ../deepseek-harness；宿主位于其他目录时设置 CODEBRIDGE_DSH_ROOT。Python 环境及本插件额外使用的第三方库仍需按插件需要准备。

## DSH 接入

### 在已有 WebUI 中安装

本包 0.1.1 适配 DSH 0.2.1-alpha.4 和 0.2.0-rc.2。在 CodeBridge 目录执行 npm run build，然后在已有 deepseek-harness WebUI 的「插件 → 添加插件 / 安装第三方插件」中填入目录的绝对路径：

```text
C:/projects/CodeBridge
```

输入的是含 package.json 的目录。DSH 从其中的 dsh.bundle.patch 读取插件补丁；codebridge.mcp.json 是其他 MCP Host 使用的配置，不能作为 DSH 插件导入。

也可在共享宿主目录通过 CLI 安装到它的 Web profile：

```powershell
Set-Location 'C:\projects\deepseek-harness'
pnpm dsh plugin --profile web add 'link:C:/projects/CodeBridge'
```

安装成功后在插件列表启用 codebridge-cordis-lifecycle；若界面提示需要重启，停止原窗口并重新启动。安装目标由运行中的 DSH profile 决定，CLI 的 DSH_HOME 需要与该实例一致。本地路径安装保留本目录及其 .venv；移动项目后需按新路径重新安装。

默认配置使用插件所在目录的 .venv 解释器、server.py 和 .codebridge/audit.sqlite3，并将 CodeBridge 本身作为被读取的仓库。Windows 使用 .venv/Scripts/python.exe，其他平台使用 .venv/bin/python。读取其他仓库时，在当前 profile 的 cordis.patch.yml 添加条目覆盖：

```yaml
- id: mcp-codebridge
  config:
    enabled: true
    repositoryRoot: 'C:/projects/your-repository'
    pythonCommand: 'C:/projects/CodeBridge/.venv/Scripts/python.exe'
    auditDb: 'C:/projects/CodeBridge/.codebridge/audit.sqlite3'
```

repositoryRoot 和 auditDb 必须是绝对路径；pythonCommand 可为解释器绝对路径或 PATH 中的命令。这三个字段仅用于构造默认 MCP 连接；显式提供完整 mcp 配置时，连接使用 mcp 中的 command、args、cwd、env 等字段。仓库根目录固定于服务启动时，修改后需重载插件。

Python 环境缺失或启动失败时，三个管理工具仍可用，codebridge_status 返回 disabled 和 error；补齐环境后调用 codebridge_restart 恢复。成功加载后应有三个 codebridge_ 管理工具和七个 mcp__codebridge__ 业务工具。

### 启动共享 WebUI

已有 WebUI 运行时，安装插件后继续使用该实例即可。需要启动时，可继续在 deepseek-harness 目录执行 pnpm start:web；开发宿主本身时使用 pnpm dev:web。

也可以在项目目录的 PowerShell 中执行：

```powershell
Set-Location 'C:\projects\CodeBridge'
npm start
```

npm start 和 start.cmd 都启动共享 deepseek-harness 中已构建的 DSH，使用其正常 profile，不再单独设置 CodeBridge/.dsh。CODEBRIDGE_DSH_ROOT 可指定另一个源码仓库或已安装的 @deepseek-ai/dsh 包目录。DSH_HOME 如有设置则原样传入，需要与安装插件时使用的 WebUI 一致。插件需先安装并启用到该 profile。
仅启动服务器而不打开浏览器时，执行 npm start -- --no-open。
保持启动窗口打开；停止服务按 Ctrl+C。

浏览器应打开启动输出里的完整认证 URL。已有 DSH 实例需要重新加载更新后的插件与配置，才能看到新增工具。

可向 Agent 发出以下请求：

> 用 CodeBridge 查看仓库概览，搜索 change_summary 的实现，按行读取相关代码，再查看 server.py 的 Git patch。根据代码与 diff 说明改动，明确区分已验证结果和推测。

> 查询 CodeBridge 状态，禁用服务，确认业务工具撤销，然后重新启用。

> CodeBridge 服务异常后调用 codebridge_restart，随后调用 repo_overview 验证恢复。

启停和重连在同一 Cordis 运行时内完成。当前配置关闭官方 MCP Client 的自动重连，以验证本项目显式重连入口；检查命令不会被自动重跑。codebridge_status 表示插件生命周期状态，不是服务实时健康探测。

## 读取与执行边界

- 仓库根目录由 CODEBRIDGE_REPO_ROOT 配置；工具只能指定相对文件路径。
- 拒绝绝对路径、父目录跳转、Windows ADS/设备名、尾点/尾空格路径别名，以及符号链接和 Junction。
- 排除依赖、运行数据、已知凭证文件和 Git 忽略的未跟踪内容。
- 搜索最多扫描 1000 个候选文件，文件内容扫描预算 5 秒；Git 元数据调用另有 10 秒超时。
- 单文件文本读取最多 256 KiB；按行读取最多 200 行、12000 字符，单行最多 400 字符。
- Git diff 只读取指定文件，最多返回 12000 字节，并禁用外部 diff/textconv。
- pytest 检查最多 120 秒，使用固定参数及 shell=False，超时尝试终止进程树；每个输出流最多返回 4000 字节。
- 输入 Schema 由 MCP SDK 生成并校验；工具内另做范围、路径和白名单检查。
- 工具级错误返回错误码；SQLite 不保存源代码、查询内容或命令输出。审计不可写时，业务工具仍可返回结果。

这些是应用层限制，适用于可信本地仓库。pytest 会执行仓库代码并可能产生缓存或其他副作用，当前不提供操作系统级沙箱。路径检查不保证防御恶意并发替换文件，已知敏感文件排除也不等于检测所有源码中的秘密。

## 验证与指标

- tests/test_repository_tools.py：实际 Git 仓库、读取/搜索预算、路径拒绝、Junction、diff 模式、固定检查及超时清理。
- tests/test_mcp_protocol.py：真实 stdio 工具发现、完整仓库流程，以及异常后同一 MCP 会话的连续调用。
- tests/test_cordis_manager.mjs：真实 Cordis/DSH MCP Client 集成，覆盖启停、卸载、启动失败和服务崩溃后的重连。
- tests/test_dsh_bundle.mjs：宿主依赖复用、兼容性拒绝、真实 CLI 离线安装、WebUI 本地包检查、Loader 加载十个工具，以及复制到 node_modules 后的 JavaScript 入口和路径配置。
- eval/benchmark.py：不调用模型的真实 stdio 回归评测，记录响应耗时、策略拒绝和后续调用结果。
- eval/tool_benchmark.json：实际执行结果，含环境、样本范围、逐次记录及源文件 SHA256。
- eval/tasks.md：独立的模型任务评测设计，尚不提供模型任务效果提升结论。

评测口径及项目设计见 docs/设计与场景说明.md；可直接使用的项目文字见 docs/简历项目.md。订单示例与本项目的注册项、实现和目录对照见 [DSH插件对照与接入](docs/DSH插件对照与接入.md)。
