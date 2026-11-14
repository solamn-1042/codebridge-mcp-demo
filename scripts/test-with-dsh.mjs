import { mkdtempSync, mkdirSync, rmSync, symlinkSync, writeFileSync, readFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { after } from 'node:test'
import { importHost, installAnchor, projectRoot } from './dsh-host.mjs'

const { Context } = await importHost('@deepseek-ai/cordis')
const { PluginPackages, createRuntimeResolution, initProfile, loadProfileDirectory, getDshRuntimeVersion } = await importHost('@deepseek-ai/dsh-app-boot')
const home = mkdtempSync(join(tmpdir(), 'codebridge-host-'))
const dir = join(home, 'profiles/test')
const manifest = JSON.parse(readFileSync(join(projectRoot, 'package.json'), 'utf8'))
initProfile(dir, [manifest.name])
const profileManifest = join(dir, 'package.json')
const profile = JSON.parse(readFileSync(profileManifest, 'utf8'))
profile.dependencies = { [manifest.name]: `link:${projectRoot}` }
writeFileSync(profileManifest, JSON.stringify(profile))
mkdirSync(join(dir, 'node_modules'), { recursive: true })
symlinkSync(projectRoot, join(dir, 'node_modules', manifest.name), process.platform === 'win32' ? 'junction' : 'dir')
const resolution = await createRuntimeResolution({ installAnchor, home, profile: loadProfileDirectory('test', dir, installAnchor) })
const context = new Context()
new PluginPackages(context, { resolution })
after(async () => {
  await context.fiber.dispose()
  rmSync(home, { recursive: true, force: true })
})
process.stdout.write(`Testing against shared DSH ${getDshRuntimeVersion()}\n`)
await import('../tests/test_cordis_manager.mjs')
await import('../tests/test_dsh_bundle.mjs')
