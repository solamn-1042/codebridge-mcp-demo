import { spawn } from 'node:child_process'
import { existsSync } from 'node:fs'
import { cliEntry, hostRoot } from './dsh-host.mjs'

if (!existsSync(cliEntry)) {
  process.stderr.write(`CodeBridge: build the shared DSH installation at ${hostRoot} first.\n`)
  process.exit(1)
}

const child = spawn(process.execPath, [cliEntry, 'web', ...process.argv.slice(2)], {
  cwd: hostRoot,
  env: process.env,
  stdio: 'inherit',
})

// The child shares the terminal and receives Ctrl+C; wait for its shutdown.
process.on('SIGINT', () => {})
child.on('error', error => {
  process.stderr.write(`CodeBridge: cannot start DSH: ${error.message}\n`)
  process.exit(1)
})
child.on('exit', code => process.exit(code ?? 1))
