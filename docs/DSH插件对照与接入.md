# DSH 插件对照与接入

本文对照 deepseek-harness/scratch-plugin 中的教学订单插件与 CodeBridge 中的仓库工具插件。deepseek-harness 是 DSH 框架源码仓库，其 packages/ 包含大量官方插件；这里的“订单插件”仅指 scratch-plugin 自定义示例。

## 注册内容

两个插件均声明 inject = ['tools']，消费 DSH 已有的 ctx.tools 服务，并通过 ctx.tools.register 注册模型可调用的工具。二者都没有用 ctx.provide 或 Service 定义新的独立 Context 服务。Python 侧的 MCPServer("CodeBridge") 是由子进程提供的 MCP 服务端。

| 插件 | 注册的工具 | 实际执行者 |
|---|---|---|
| ai-ticket-order-tool | ticket_order_lookup | 同一 Node 进程中的 queryOrder 函数 |
| codebridge-lifecycle-manager | codebridge_status、codebridge_set_enabled、codebridge_restart | Cordis 插件中的状态与子 Fiber 管理逻辑 |
| CodeBridge 的子 MCP Client | mcp__codebridge__repo_overview、mcp__codebridge__search_code、mcp__codebridge__read_file、mcp__codebridge__change_summary、mcp__codebridge__git_diff、mcp__codebridge__run_project_check、mcp__codebridge__tool_metrics | 通过 stdio 调用 Python server.py |

订单查询将订单号去除首尾空格并转为大写，支持硬编码的 A001（机械键盘、已发货）与 A002（蓝牙耳机、退款中）。格式错误返回 INVALID_ORDER_ID，未命中返回 ORDER_NOT_FOUND。设置 DSH_PLUGIN_SMOKE_TEST=1 时，加载后会额外调用一次 A002 并打印结果。

CodeBridge 默认启动时提供十个工具。codebridge_set_enabled(false) 撤销七个 MCP 工具，保留三个管理工具；重新启用时重新连接并发现工具；codebridge_restart 销毁并重建子 MCP Client。卸载父插件时，管理工具、子连接和业务工具均随 Cordis 生命周期清理。注册表本身拥有注册 effect，因此调用 ctx.tools.register 已能随插件卸载撤销工具。

## 执行与生命周期

| 维度 | 订单示例 | CodeBridge |
|---|---|---|
| 组成 | 单个 TypeScript 工具插件 | TypeScript 生命周期插件、官方 MCP Client、Python MCP 服务 |
| 数据 | 内存中的教学订单表 | 实际代码仓库、Git 状态及 SQLite 调用指标 |
| 协议 | 直接调用 Node 函数 | Node 与 Python 之间的 MCP stdio 通信 |
| 工具发现 | apply 中直接注册一个工具 | 直接注册三个管理工具，再由 MCP Client 发现并注册七个业务工具 |
| 参数 | orderId 字符串 | 按工具区分的查询、相对文件路径、行区间、diff 模式和固定检查类型 |
| 返回 | JSON 字符串，经 output.render 转为文本 | 管理工具返回对象；业务工具返回带调用元数据的 JSON 文本，经 MCP Client 转为 DSH 工具结果 |
| 执行副作用 | 可选的加载时教学查询 | 启动 Python、按需运行 Git/pytest、写入审计指标 |
| 恢复 | 无外部连接 | 串行处理启停和重启，启动失败保留管理入口 |
| 状态含义 | 无连接状态 | enabled 表示生命周期已启用，不是 Python 实时健康探测；服务崩溃后需要重连并调用业务工具验证 |

CodeBridge 使用官方 @deepseek-ai/dsh-mcp-client 负责 MCP 协议、连接与工具转换，自身负责服务启停编排和 Python 仓库业务。默认关闭自动重连，以 codebridge_restart 提供显式恢复；重启不重跑已经执行的检查。

## 文件组织

| 用途 | deepseek-harness/scratch-plugin | CodeBridge |
|---|---|---|
| 可安装包声明 | package.json 中的 dsh.bundle.patch | package.json 中的 dsh.bundle.patch |
| 组合补丁 | cordis.yml | dsh.mcp.patch.yml |
| 插件源码 | src/order-tool.ts | plugins/codebridge-manager.ts |
| 安装后入口 | 本机绝对路径指向源码 | lib/codebridge-manager.js，由 npm run build 生成 |
| 业务实现 | 与工具注册放在同一文件 | server.py、repository_policy.py、execution.py、telemetry.py |
| 本地启动 | 由 DSH 宿主加载 | scripts/start-dsh.mjs、start.cmd |
| 协议及集成检查 | 可选加载时查询 | tests/test_cordis_manager.mjs、tests/test_dsh_bundle.mjs、Python 测试 |

补丁文件不要求叫 cordis.yml；DSH 读取 package.json 中 dsh.bundle.patch 指向的文件。src/、plugins/、lib/ 的命名也不是固定要求。决定能否安装的是包声明、补丁能否解析、入口能否加载，以及运行依赖是否齐备。

## WebUI 导入

CodeBridge 的包名为 codebridge-cordis-lifecycle，Cordis 模块名为 codebridge-lifecycle-manager，补丁条目 id 为 mcp-codebridge，MCP 命名空间为 codebridge；这些标识分别用于包安装、插件诊断、条目配置覆盖与工具名称前缀。

在 CodeBridge 目录运行 npm run build，然后在 WebUI 的插件安装框填入 C:/projects/CodeBridge。完整步骤和覆盖其他仓库的配置示例见 [README 的 DSH 接入](../README.md#dsh-接入)。安装目标是当前 WebUI 使用的 profile。

DSH 的本地包预检查会拒绝未声明 dsh.bundle 的目录。CodeBridge 通过 dsh.bundle.patch 暴露补丁，通过补丁相对路径加载 JavaScript 入口，再从入口位置定位 Python 服务和默认虚拟环境。JavaScript 产物随包提供，可避免 Node 对 node_modules 内 TypeScript 类型擦除的限制。npm pack 使用文件白名单打包业务代码与入口；.venv、运行数据和本地缓存需要在目标环境单独准备。

CodeBridge 0.1.1 支持 DSH 0.2.1-alpha.4 与 0.2.0-rc.2。构建、测试和启动默认复用同级 deepseek-harness；CODEBRIDGE_DSH_ROOT 可选择其他已有宿主。插件目录无需安装整套 DSH。运行时组件声明为宿主提供的 peer，由 DSH 为本地链接插件解析到宿主版本，避免把不同版本的工具注册表与 MCP Client 混用。一个宿主 profile 可以同时安装订单示例、CodeBridge 及其他插件；各插件只需准备自己的业务依赖。
