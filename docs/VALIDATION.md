# 公开展示版验收记录

首次发布提交 `557d24e6417876259b23e5b0a783d5fcc8755db1` 的 [GitHub Actions](https://github.com/solamn-1042/codebridge-mcp-demo/actions/runs/43572719537) 已完成：Windows/Linux两项任务均成功。

2026-11-14，Windows 11 / Python 3.12.14。真实 stdio MCP、临时 Git/Python 样例仓库，重复20轮，无模型调用。

| 项目 | 实测 |
|---|---:|
| Python 回归测试 | 27 项通过 |
| 正常调用 | 121/121 |
| 目录越界拒绝 | 20/20 |
| Schema 错误识别 | 20/20 |
| 两类错误之后的合法读取 | 40/40 |
| 代码搜索平均 / P95 | 70.73 / 78.70 ms |
| Git diff 平均 / P95 | 68.66 / 73.48 ms |

原始逐次记录、环境、源文件 SHA256：`../eval/tool_benchmark.json`。统计包含 IPC，不包含模型推理；不是用户任务成功率、生产负载或效率提升数据。

## 首次安装

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m pytest -q
python eval/benchmark.py --rounds 20
```

Linux/macOS 使用 `source .venv/bin/activate`。通用 MCP 客户端配置见根目录 `codebridge.mcp.json`，替换样板中的绝对路径；Windows 解释器为 `.venv/Scripts/python.exe`，Linux 为 `.venv/bin/python`。

DeepSeek Harness（DSH）提供上层模型会话和 Agent Loop。本项目 Python 实现7个仓库工具，TypeScript/Cordis 实现3个生命周期管理入口，MCP是两者之间的协议，不把官方宿主的能力计为本项目原创。

插件集成需 Node 22.19+（22.x）或 Node 24+，以及已有 DSH 0.2.0-rc.2 或0.2.1-alpha.4宿主。设置 `CODEBRIDGE_DSH_ROOT` 指向真实宿主目录后执行 `npm run build`、`npm run test:cordis`。不要求在插件里复制整套宿主依赖。

## CI 与运维边界

CI 在 Windows/Linux 执行 Python 测试和5轮协议评测，上传原始结果；DSH 集成需匹配宿主，当前未纳入云端CI。读取当前 Actions 状态才能判断某次提交是否通过。

服务异常时先检查状态、Python解释器和根目录配置，再手动重连；不自动重跑项目检查。升级前备份配置和停止写入后的审计库，记录版本；回滚同时恢复插件源码和编译产物。默认仅 stdio，不向公网暴露远程执行接口。

pytest执行的是被分析仓库代码，可能产生副作用，仅应用于可信仓库。白名单和路径约束不是操作系统沙箱。面对不可信代码应采用独立容器或沙箱。仓库没有生产SLA、用户规模或高并发性能声明。

DSH 0.2.1-alpha.4 的 10 项真实集成测试已在本次独立副本中全部通过，包含 Loader 加载7个业务工具及3个管理工具、服务崩溃恢复和生命周期卸载。
