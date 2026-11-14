import assert from 'node:assert/strict'
import { test } from 'node:test'
import { mkdtempSync, mkdirSync, readFileSync, rmSync, symlinkSync, writeFileSync, cpSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { spawnSync } from 'node:child_process'
import { Context, ToolRuntime, PluginManager, boot, initProfile, loadProfileDirectory,
  loadOverlayPatches, composeEntries, installAnchor as anchor, hostScope,
  evaluatePluginCompatibility, getDshRuntimeVersion, McpClient } from './dsh-runtime.mjs'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const manifest = JSON.parse(readFileSync(join(root, 'package.json'), 'utf8'))

test('linked plugin uses host services despite an existing private node_modules', async () => {
  assert.equal((await import('@deepseek-ai/dsh-tools')).default, ToolRuntime)
  assert.equal((await import('@deepseek-ai/dsh-mcp-client')).apply, McpClient.apply)
  assert.equal((await import('@deepseek-ai/cordis')).Context, Context)
  assert.equal(manifest.dependencies?.['@deepseek-ai/dsh'], undefined)
  assert.equal(manifest.devDependencies?.['@deepseek-ai/dsh'], undefined)
})

test('bundle compatibility accepts tested hosts and rejects untested runtimes', () => {
  for (const version of ['0.2.0-rc.2', '0.2.1-alpha.4']) {
    assert.equal(evaluatePluginCompatibility(manifest, {}, version), undefined)
  }
  assert.ok(evaluatePluginCompatibility(manifest, {}, '0.3.0'))
  assert.equal(evaluatePluginCompatibility(manifest, {}, getDshRuntimeVersion()), undefined)
})

function temporary(t) {
  const dir = mkdtempSync(join(tmpdir(), 'codebridge-bundle-'))
  t.after(() => rmSync(dir, { recursive: true, force: true }))
  return dir
}

test('shared DSH installs a local link offline without version exemptions', { timeout: 40000 }, t => {
  const home = temporary(t)
  const dir = join(home, 'profiles/smoke')
  initProfile(dir, [])
  const result = spawnSync(process.execPath, [join(dirname(anchor), 'lib/bin.js'), 'plugin', '--profile', 'smoke',
    'add', `link:${root}`, '--offline'], {
    cwd: dirname(anchor), env: { ...process.env, DSH_HOME: home }, encoding: 'utf8', timeout: 30000,
  })
  assert.equal(result.status, 0, `${result.stdout}\n${result.stderr}\n${result.error ?? ''}`)
  const profile = loadProfileDirectory('test', dir, anchor)
  assert.deepEqual(profile.skippedBundles, [])
  assert.equal(profile.layers[0].packageName, manifest.name)
})

test('WebUI plugin manager accepts the local CodeBridge bundle', { timeout: 20000 }, async t => {
  const dir = temporary(t)
  initProfile(dir, [])
  writeFileSync(join(dir, 'cordis.yml'), '[]\n')
  const ctx = await boot('test', join(dir, 'cordis.yml'), [], ctx => {
    ctx.provide('profileContext', {
      name: 'test', dir, startedBundles: [], installAnchor: anchor,
      cwd: root, home: dir, patchPath: join(dir, 'cordis.patch.yml'), overlays: [],
    })
  })
  t.after(() => ctx.fiber.dispose())
  const manager = ctx.plugin(PluginManager, {})
  await manager.await()
  // A local manifest inspection does not need the developer's pnpm registry lookup.
  ctx.pluginManager.registries = async () => ({ registry: null, fallbackRegistries: [], resolved: null })
  const inspection = await ctx.pluginManager.inspect(root)
  assert.equal(inspection.status, 'accepted', JSON.stringify(inspection))
  assert.equal(inspection.bundle, true)
  assert.equal(inspection.name, manifest.name)
  assert.equal(inspection.version, manifest.version)
})

test('installed profile resolves the bundle patch and boots all ten tools through Loader', { timeout: 20000 }, async t => {
  const dir = temporary(t)
  initProfile(dir, [manifest.name])
  mkdirSync(join(dir, 'node_modules'), { recursive: true })
  symlinkSync(root, join(dir, 'node_modules', manifest.name), process.platform === 'win32' ? 'junction' : 'dir')
  const profile = loadProfileDirectory('test', dir, anchor)
  assert.deepEqual(profile.skippedBundles, [])
  const patches = profile.layers.flatMap(layer => layer.patches)
  const entries = composeEntries([patches])
  assert.equal(entries[0].name, pathToFileURL(join(dir, 'node_modules', manifest.name, 'lib/codebridge-manager.js')).href)
  writeFileSync(join(dir, 'cordis.yml'), '[]\n')
  const ctx = await boot('test', join(dir, 'cordis.yml'), patches, ctx => {
    ctx.provide('systemPrompt', { tools: () => () => undefined })
    new ToolRuntime(ctx, {})
  })
  t.after(() => ctx.fiber.dispose())
  const names = ctx.tools.schemas().map(tool => tool.name)
  assert.equal(names.filter(name => name.startsWith('mcp__codebridge__')).length, 7)
  assert.equal(names.filter(name => name.startsWith('codebridge_')).length, 3)
  assert.equal((await ctx.tools.get('codebridge_status').execute({})).state, 'enabled')
  const result = await ctx.tools.get('mcp__codebridge__repo_overview').execute({}, { signal: new AbortController().signal })
  assert.equal(JSON.parse(result.content[0].text).repository_name, 'CodeBridge')
  await ctx.fiber.dispose()
  assert.equal(ctx.tools?.schemas().length ?? 0, 0)
})

test('plain JavaScript entry loads from a copied node_modules package and accepts explicit paths', { timeout: 20000 }, async t => {
  const dir = temporary(t)
  const installed = join(dir, 'node_modules', manifest.name)
  mkdirSync(installed, { recursive: true })
  for (const file of ['package.json', 'lib', 'dsh.mcp.patch.yml', 'server.py', 'repository_policy.py', 'execution.py', 'telemetry.py']) {
    cpSync(join(root, file), join(installed, file), { recursive: true })
  }
  symlinkSync(hostScope, join(dir, 'node_modules', '@deepseek-ai'), process.platform === 'win32' ? 'junction' : 'dir')
  const entry = composeEntries([loadOverlayPatches('test', join(installed, manifest.dsh.bundle.patch))])[0]
  const plugin = await import(entry.name)
  const ctx = new Context().extend({ systemPrompt: { tools: () => () => undefined } })
  new ToolRuntime(ctx, {})
  const fiber = ctx.plugin(plugin, {
    enabled: false, pythonCommand: resolve(root, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python'),
    repositoryRoot: root, auditDb: join(dir, 'audit.sqlite3'),
  })
  t.after(() => fiber.dispose())
  try {
    await fiber.await()
    assert.equal((await ctx.tools.get('codebridge_status').execute({})).state, 'disabled')
    const status = await ctx.tools.get('codebridge_set_enabled').execute({ enabled: true })
    assert.equal(status.state, 'enabled', JSON.stringify(status))
    const result = await ctx.tools.get('mcp__codebridge__repo_overview').execute({}, { signal: new AbortController().signal })
    assert.equal(JSON.parse(result.content[0].text).repository_name, 'CodeBridge')
  } finally {
    await fiber.dispose()
  }
})
