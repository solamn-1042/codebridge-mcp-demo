import assert from 'node:assert/strict'
import { test } from 'node:test'
import { Context, ToolRuntime } from './dsh-runtime.mjs'
import * as manager from '../plugins/codebridge-manager.ts'
import { fileURLToPath } from 'node:url'
import { dirname, resolve, join } from 'node:path'
import { mkdtempSync, writeFileSync, readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'

const projectRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const python = resolve(projectRoot, '.venv', 'Scripts', 'python.exe')
const service = resolve(projectRoot, 'server.py')
const toolNames = ['repo_overview', 'change_summary', 'run_project_check', 'search_code', 'read_file', 'git_diff', 'tool_metrics']
const codebridgeTools = toolNames.map(name => 'mcp__codebridge__' + name)
const controls = ['codebridge_status', 'codebridge_set_enabled', 'codebridge_restart']
const signal = () => ({ signal: new AbortController().signal })
const decode = result => JSON.parse(result.content[0].text)

function setup(t) {
  const root = mkdtempSync(join(tmpdir(), 'codebridge-cordis-'))
  writeFileSync(join(root, 'README.md'), '# Sample\n')
  const context = new Context().extend({ systemPrompt: { tools: () => () => undefined } })
  new ToolRuntime(context, {})
  t.after(() => { rmSync(root, { recursive: true, force: true }) })
  const config = {
    enabled: true,
    mcp: { transport: 'stdio', serverName: 'codebridge', command: python, args: [service],
           cwd: projectRoot, env: { CODEBRIDGE_REPO_ROOT: root, CODEBRIDGE_AUDIT_DB: join(root, 'audit.sqlite3') },
           toolCallTimeoutMs: 135000, failOnStartupError: true, reconnect: { enabled: false } },
  }
  return { root, context, config }
}

test('register, disable, re-enable, restart and unload all tools', async t => {
  const { context, config } = setup(t)
  const fiber = context.plugin(manager, config)
  t.after(() => fiber.dispose())
  await fiber.await()
  const tools = fiber.ctx.tools
  const names = () => new Set(tools.schemas().map(item => item.name))
  for (const name of [...codebridgeTools, ...controls]) assert.ok(names().has(name))
  assert.equal((await tools.get('codebridge_status').execute({})).state, 'enabled')
  assert.equal((await tools.get('codebridge_set_enabled').execute({ enabled: false })).state, 'disabled')
  for (const name of codebridgeTools) assert.equal(names().has(name), false)
  for (const name of controls) assert.ok(names().has(name))
  assert.equal((await tools.get('codebridge_set_enabled').execute({ enabled: true })).state, 'enabled')
  for (const name of codebridgeTools) assert.ok(names().has(name))
  const restarted = await tools.get('codebridge_restart').execute({})
  assert.equal(restarted.restartCount, 1)
  assert.equal(decode(await tools.get('mcp__codebridge__repo_overview').execute({}, signal())).readme_excerpt, '# Sample\n')
  await fiber.dispose()
  for (const name of [...codebridgeTools, ...controls]) assert.equal(names().has(name), false)
})

test('startup failure preserves controls and a later restart restores service', async t => {
  const { root, context, config } = setup(t)
  const launcher = join(root, 'launcher.py')
  const marker = join(root, 'ready.flag')
  writeFileSync(launcher,
    'import pathlib,sys,runpy\n' +
    'if not pathlib.Path(' + JSON.stringify(marker) + ').exists(): sys.exit(2)\n' +
    'sys.path.insert(0,' + JSON.stringify(projectRoot) + ')\n' +
    'runpy.run_path(' + JSON.stringify(service) + ',run_name="__main__")\n')
  config.mcp.args = [launcher]
  const fiber = context.plugin(manager, config)
  t.after(() => fiber.dispose())
  await fiber.await()
  const tools = fiber.ctx.tools
  assert.equal((await tools.get('codebridge_status').execute({})).state, 'disabled')
  assert.ok((await tools.get('codebridge_status').execute({})).error)
  writeFileSync(marker, 'ready')
  assert.equal((await tools.get('codebridge_restart').execute({})).state, 'enabled')
  assert.equal(decode(await tools.get('mcp__codebridge__repo_overview').execute({}, signal())).readme_excerpt, '# Sample\n')
})

test('service crash and restart preserve the same Cordis runtime', async t => {
  const { root, context, config } = setup(t)
  const launcher = join(root, 'launcher.py')
  const pidFile = join(root, 'service.pid')
  writeFileSync(launcher,
    'import os,pathlib,sys,runpy\n' +
    'pathlib.Path(' + JSON.stringify(pidFile) + ').write_text(str(os.getpid()))\n' +
    'sys.path.insert(0,' + JSON.stringify(projectRoot) + ')\n' +
    'runpy.run_path(' + JSON.stringify(service) + ',run_name="__main__")\n')
  config.mcp.args = [launcher]
  config.mcp.toolCallTimeoutMs = 3000
  const fiber = context.plugin(manager, config)
  t.after(() => fiber.dispose())
  await fiber.await()
  const tools = fiber.ctx.tools
  const before = decode(await tools.get('mcp__codebridge__repo_overview').execute({}, signal()))
  assert.equal(before.readme_excerpt, '# Sample\n')
  process.kill(Number(readFileSync(pidFile, 'utf8')))
  await new Promise(resolve => setTimeout(resolve, 300))
  await assert.rejects(() => tools.get('mcp__codebridge__repo_overview').execute({}, signal()))
  const restarted = await tools.get('codebridge_restart').execute({})
  assert.equal(restarted.state, 'enabled')
  assert.equal(decode(await tools.get('mcp__codebridge__repo_overview').execute({}, signal())).readme_excerpt, '# Sample\n')
})

test('invalid lifecycle configuration fails before starting a child', async t => {
  const { context, config } = setup(t)
  config.enabled = 'yes'
  const fiber = context.plugin(manager, config)
  t.after(() => fiber.dispose())
  await assert.rejects(() => fiber.await(), /enabled must be boolean/)
})

