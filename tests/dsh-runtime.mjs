import { importHost, installAnchor, hostScope } from '../scripts/dsh-host.mjs'

export const { Context } = await importHost('@deepseek-ai/cordis')
export const { default: ToolRuntime } = await importHost('@deepseek-ai/dsh-tools')
export const { default: PluginManager } = await importHost('@deepseek-ai/dsh-plugin-manager')
export const McpClient = await importHost('@deepseek-ai/dsh-mcp-client')
export const { boot, initProfile, loadProfileDirectory, loadOverlayPatches, composeEntries,
  evaluatePluginCompatibility, getDshRuntimeVersion } = await importHost('@deepseek-ai/dsh-app-boot')
export { installAnchor, hostScope }
