import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { stripTypeScriptTypes } from 'node:module'

// Node does not strip TypeScript in node_modules; ship a plain ESM entry.
const source = await readFile(new URL('../plugins/codebridge-manager.ts', import.meta.url), 'utf8')
const output = stripTypeScriptTypes(source, { mode: 'strip' })
await mkdir(new URL('../lib/', import.meta.url), { recursive: true })
await writeFile(new URL('../lib/codebridge-manager.js', import.meta.url), output)
