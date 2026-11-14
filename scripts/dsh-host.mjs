import { existsSync, readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

export const projectRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')

// Point to an existing source checkout or an installed @deepseek-ai/dsh directory.
export const hostRoot = resolve(process.env.CODEBRIDGE_DSH_ROOT ?? join(projectRoot, '../deepseek-harness'))
const cliRoot = existsSync(join(hostRoot, 'apps/cli/package.json')) ? join(hostRoot, 'apps/cli') : hostRoot
export const installAnchor = join(cliRoot, 'package.json')
if (!existsSync(installAnchor) || JSON.parse(readFileSync(installAnchor, 'utf8')).name !== '@deepseek-ai/dsh') {
  throw new Error(`No DSH installation at ${hostRoot}; set CODEBRIDGE_DSH_ROOT to an existing deepseek-harness directory.`)
}
export const cliEntry = join(cliRoot, 'lib/bin.js')
export const hostRequire = createRequire(installAnchor)
export const importHost = name => import(pathToFileURL(hostRequire.resolve(name)).href)
export const hostScope = hostRequire.resolve.paths('@deepseek-ai/dsh-tools')
  .map(path => join(path, '@deepseek-ai'))
  .find(path => existsSync(join(path, 'dsh-tools/package.json')))
