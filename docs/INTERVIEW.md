# CodeBridge：项目讲解与面试问答

本底稿与售后Agent配套，强调工具治理和协议集成。参考[JavaGuide项目面试指南](https://javaguide.cn/ai/interview-questions/agent-project-interview-guide.html)的准备思路，事实来源为当前CodeBridge代码、测试与VALIDATION.md。

## 30秒：面向HR

CodeBridge是给AI编程助手使用的代码仓库工具扩展。它把了解项目、定位代码、读取具体行、检查Git改动和运行固定测试串起来，并控制可以访问的路径和执行的命令。我关注的是让工具结果可以核对，以及出错后会话还能继续，不把任意Shell执行权直接交给模型。项目有Python协议测试、插件生命周期测试和Windows/Linux CI记录。

## 三分钟：面向技术面

场景是接手陌生仓库和复核改动。普通文件或Shell工具也能完成任务，但调用方需要自己限制读取范围、处理不同diff模式和命令失败。我将这些动作整理成7个业务工具，通过真实stdio MCP连接到DeepSeek Harness；另用Cordis提供状态、启停和重连3个管理入口。

输入是相对路径、搜索词、行号或固定检查名。服务端固定仓库根目录，拒绝父目录跳转、绝对路径、Windows ADS/设备路径和链接越界；固定检查只允许test映射pytest -q，shell=False。结果包含文件路径、行号、截断标志和错误码，便于Agent引用，而不是只给一段不透明文本。

验证分成Python回归、真实MCP传输、宿主集成和工具耗时评测。27项Python用例包含参数化路径攻击；10项DSH集成覆盖启停、卸载、启动失败、崩溃恢复和安装加载。20轮协议评测正常调用121/121，错误后的合法读取40/40；这些是工具协议稳定性，不是模型完成开发任务的成功率。

## 十分钟演示安排

1. 解释DSH提供模型和Agent Loop，CodeBridge提供业务工具和管理插件。
2. 用MCP客户端列出7个工具，调用repo_overview→search_code→read_file。
3. 展示staged/unstaged/HEAD差异，说明不能把不同模式混为一谈。
4. 读取../outside或.env，看到明确拒绝；随后正常读取文件，验证会话未断。
5. 执行test，再尝试test; whoami，说明固定参数和任意Shell的区别。
6. 在真实宿主演示禁用/启用或重连；没有宿主时展示测试记录，不能伪装手工跑过界面。
7. 打开VALIDATION.md和原始benchmark，讲计时包含IPC但不包含模型推理。

## 按场景—技术—优化—测试组织回答

| 场景 | 方案与代价 | 能拿出的证据 |
|---|---|---|
| 接手仓库需要可定位结果 | 搜索返回路径、行号、片段；读取和输出有预算 | repository_tools搜索与读取测试 |
| 模型可能读敏感文件或越界 | 根目录约束、路径检查、已知敏感文件排除；不是所有秘密检测 | 9种参数化路径拒绝、Junction测试 |
| 固定检查可能挂起或输出爆炸 | 固定pytest参数、120秒超时、输出限制、子进程清理 | timeout、bounded_output、child_process测试 |
| 一次参数错误不能毁掉会话 | 结构化错误返回，同一stdio会话继续合法调用 | test_schema_errors_and_denial_do_not_end_mcp_session |
| 插件状态与业务工具生命周期不同步 | Cordis管理启停与重连；status不是实时健康探测 | test_cordis_manager.mjs、test_dsh_bundle.mjs |
| 工具耗时需要可追溯 | SQLite仅记元数据；审计失败不阻塞读取 | telemetry故障与字段测试、tool_benchmark.json |

## 高频追问及回答

### 它是不是Agent？

CodeBridge自身不是完整Agent引擎，而是MCP工具服务和插件。DeepSeek Harness负责模型会话和Agent Loop，模型决定何时调用这些工具。把宿主已有能力算成自己实现会经不起追问。

### 为什么使用MCP，直接Function Calling不行吗？

只在一个进程里用，直接函数注册更简单。这里希望工具通过标准Host/Client接入宿主，stdio隔离进程并进行工具发现，因此使用MCP。Function Calling负责模型表达调用意图，MCP负责传输与协议，业务权限仍由CodeBridge检查。

### 为什么有Python和TypeScript？Cordis负责什么？

Python实现文件/Git/固定检查及SQLite审计；TypeScript/Cordis处理DSH插件生命周期。官方MCP Client负责连接和工具注册。选择带来了跨语言构建和版本兼容成本，所以用真实宿主集成测试验证安装、加载与卸载。

### 27项测试是什么？

test_server.py有4项；test_repository_tools.py有12个测试函数，其中路径拒绝参数化为9个用例，所以共20项；test_mcp_protocol.py有3项。合计27个执行用例，不等于27个业务功能，也不是代码覆盖率100%。

### 7个业务工具和3个入口分别是什么？

业务工具：repo_overview、search_code、read_file、change_summary、git_diff、run_project_check、tool_metrics。管理入口：codebridge_status、codebridge_set_enabled、codebridge_restart。工具数量是接口组织方式，不是越多越好。

### 为什么不用任意Shell？

该场景只需要固定测试，因此test映射到当前Python解释器的pytest -q，拒绝额外命令，shell=False。这样减少命令拼接面，但pytest本身会执行仓库代码，所以仍只能处理可信仓库；不属于操作系统沙箱。

### 路径限制能彻底阻止攻击吗？

不能。已覆盖常见绝对路径、父目录、ADS、设备名和链接等边界，已知凭证文件被排除；但没有声称完全防御恶意并发替换文件，也不能发现所有源码中嵌入的秘密。不可信仓库需要隔离容器/沙箱和进一步审查。

### 为什么报错后可以继续？

工具级错误返回结构化错误，不因一个参数错误终止整个MCP会话。真实stdio测试中先传缺失参数、错误类型或越界路径，再在同一连接读取合法文件，验证会话还可用。

### 超时和重试如何处理？

固定检查120秒上限，超时尝试终止进程树，返回有限输出。服务重连是显式管理操作，不自动重跑检查命令，因为测试可能产生副作用。没有实现任务级幂等写接口，也没有外部支付动作。

### 有没有自己的优化效果？

已做的是工具边界、生命周期和错误恢复的工程整理与验证。记录有20轮正常121/121、越界拒绝20/20、Schema错误20/20、错误后合法读取40/40。没有固定基线证明“开发效率提高多少”或“模型任务成功率提升多少”，不把这些协议通过数当成业务收益。

### 工具耗时多少？

原始评测中代码搜索平均70.73ms、P95 78.70ms；Git diff平均68.66ms、P95 73.48ms。样本来自临时Git/Python仓库、20轮真实stdio调用，包含IPC，不含模型推理，不代表大型仓库高并发性能。

### 会记录源码和密钥吗？

SQLite记录工具名、调用ID、耗时、错误码和输出长度，不保存查询内容、源码或完整命令输出。审计不可写时工具返回仍可继续，并标明记录失败。秘密仍可能存在于被读取文件，因此文件策略不能代替数据治理。

### status是不是健康检查？

不是。它主要表示插件生命周期状态，不保证子进程当前实时可用。服务崩溃后的恢复通过显式restart及随后业务调用核验。区分生命周期状态和实际业务探测，是面试时值得说明的边界。

### 如果扩大到多人远程使用？

当前stdio本地服务没有多租户身份和网络访问入口。要远程化先设计认证授权、每用户仓库范围、执行沙箱、资源配额和审计，再评估传输方式；不能把本地stdio配置直接放公网。

## 与指南中其他主题的对应边界

模型选择、长期Memory、RAG检索和人工审批不由CodeBridge实现，不能硬套售后Agent能力。它的State主要是插件和连接状态；权威文件与Git状态来自仓库。请求错误、工具响应和审计用于排障，但没有完整分布式Trace平台。没有生产事故，只有真实协议/宿主测试与故障注入。

## 面试前亲自准备

按README装好环境，跑一次Python测试和stdio benchmark；有匹配DSH宿主时再跑10项集成。亲自看一遍路径拒绝、错误后继续读取、重连，以及pytest不是沙箱的原因。项目为AI辅助整理，讲自己真正理解和复现过的设计，不声称独立原创官方Harness、Cordis或MCP SDK。

证据入口：README.md、docs/VALIDATION.md、eval/tool_benchmark.json、tests/。本次新增的是面试说明，未将售后项目的性能或业务能力写入CodeBridge。