                                                         
import { defineTool } from '@deepseek-ai/dsh-tools'
import * as mcpClient from '@deepseek-ai/dsh-mcp-client'
import { dirname, isAbsolute, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

export const name = 'codebridge-lifecycle-manager'
export const inject = ['tools']

                    
                    
                    
                 
                 
              
                              
                            
                              
                                  
 

                      
                   
                        
                         
                  
                   
 

// Both plugins/ (source) and lib/ (installed ESM) are one level below the root.
const projectRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')

function validateConfig(value          = {})                                         {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new TypeError('CodeBridge manager config must be an object')
  const config = value                          
  for (const field of ['pythonCommand', 'repositoryRoot', 'auditDb']         ) {
    if (config[field] !== undefined && (typeof config[field] !== 'string' || !config[field].trim())) {
      throw new TypeError(`${field} must be a non-empty string`)
    }
  }
  const repositoryRoot = config.repositoryRoot ?? projectRoot
  const auditDb = config.auditDb ?? resolve(projectRoot, '.codebridge/audit.sqlite3')
  if (!isAbsolute(repositoryRoot)) throw new TypeError('repositoryRoot must be an absolute path')
  if (!isAbsolute(auditDb)) throw new TypeError('auditDb must be an absolute path')
  const mcp = config.mcp ?? {
    transport: 'stdio',
    serverName: 'codebridge',
    command: config.pythonCommand ?? resolve(projectRoot, process.platform === 'win32' ? '.venv/Scripts/python.exe' : '.venv/bin/python'),
    args: [resolve(projectRoot, 'server.py')],
    cwd: projectRoot,
    env: { CODEBRIDGE_REPO_ROOT: repositoryRoot, CODEBRIDGE_AUDIT_DB: auditDb },
    toolCallTimeoutMs: 135000,
    failOnStartupError: true,
    reconnect: { enabled: false },
  }                      
  if (config.enabled !== undefined && typeof config.enabled !== 'boolean') throw new TypeError('enabled must be boolean')
  if (!mcp || typeof mcp !== 'object' || Array.isArray(mcp) || mcp.transport !== 'stdio') throw new TypeError('mcp.transport must be stdio')
  if (typeof mcp.serverName !== 'string' || !/^[A-Za-z0-9_-]{1,32}$/.test(mcp.serverName)) throw new TypeError('mcp.serverName must match [A-Za-z0-9_-]{1,32}')
  if (typeof mcp.command !== 'string' || !mcp.command.trim()) throw new TypeError('mcp.command is required')
  if (mcp.cwd !== undefined && typeof mcp.cwd !== 'string') throw new TypeError('mcp.cwd must be a string')
  if (mcp.toolCallTimeoutMs !== undefined && (!Number.isInteger(mcp.toolCallTimeoutMs) || mcp.toolCallTimeoutMs < 1000)) {
    throw new TypeError('mcp.toolCallTimeoutMs must be an integer of at least 1000')
  }
  if (mcp.failOnStartupError !== undefined && typeof mcp.failOnStartupError !== 'boolean') throw new TypeError('mcp.failOnStartupError must be boolean')
  if (mcp.reconnect !== undefined && (!mcp.reconnect || typeof mcp.reconnect.enabled !== 'boolean')) throw new TypeError('mcp.reconnect.enabled must be boolean')
  if (mcp.args !== undefined && (!Array.isArray(mcp.args) || !mcp.args.every((item) => typeof item === 'string'))) {
    throw new TypeError('mcp.args must be an array of strings')
  }
  if (mcp.env !== undefined && (!mcp.env || typeof mcp.env !== 'object' || Array.isArray(mcp.env) || Object.values(mcp.env).some((item) => typeof item !== 'string'))) {
    throw new TypeError('mcp.env must contain string values')
  }
  return {
    enabled: config.enabled !== false,
    mcp: {
      ...mcp,
      args: mcp.args ?? [],
      cwd: mcp.cwd ?? '',
      env: mcp.env ?? {},
      failOnStartupError: mcp.failOnStartupError ?? true,
    },
  }
}

function outputSchema() {
  return {
    schema: {
      type: 'object',
      properties: {
        enabled: { type: 'boolean', required: true },
        serverName: { type: 'string', required: true },
        state: { type: 'string', required: true },
        error: { type: 'string' },
        restartCount: { type: 'number', required: true },
      },
      additionalProperties: false,
    }         ,
    render: (_args         , value         ) => [{ type: 'text'         , text: JSON.stringify(value) }],
  }
}

export async function apply(ctx         , rawConfig         )                {
  const config = validateConfig(rawConfig)
  let child                   
  let phase                                                   = 'disabled'
  let transition                   = Promise.resolve()
  let lastError                    
  let restartCount = 0

  const state = () => ({
    enabled: phase === 'enabled',
    serverName: config.mcp.serverName,
    state: phase,
    restartCount,
    ...(lastError ? { error: lastError } : {}),
  })

  const changeState = (enabled         , restart = false)                                    => {
    const next = transition.then(async () => {
      if (restart && child) {
        phase = 'stopping'
        await child.dispose()
        child = undefined
      }
      if (enabled) {
        if (child?.uid !== null && child !== undefined) {
          phase = 'enabled'
          return state()
        }
        phase = 'starting'
        const fiber = ctx.plugin(mcpClient, config.mcp)
        child = fiber
        try {
          await fiber.await()
          phase = 'enabled'
          lastError = undefined
          if (restart) restartCount += 1
          return state()
        } catch (error) {
          if (child === fiber) child = undefined
          phase = 'disabled'
          lastError = error instanceof Error ? error.message : String(error)
          await fiber.dispose().catch(() => undefined)
          throw error
        }
      }

      const fiber = child
      child = undefined
      if (fiber) {
        phase = 'stopping'
        await fiber.dispose()
      }
      phase = 'disabled'
      return state()
    })
    transition = next.catch(() => undefined)
    return next
  }

  ctx.tools.register(defineTool({
    name: 'codebridge_status',
    description: 'Show CodeBridge plugin lifecycle state and startup errors; enabled is not a live service health check.',
    parameters: {},
    output: outputSchema(),
    async execute() {
      return state()
    },
  }))

  ctx.tools.register(defineTool({
    name: 'codebridge_restart',
    description: 'Dispose and recreate the CodeBridge MCP connection after service failure. Does not retry executed checks.',
    parameters: {},
    output: outputSchema(),
    async execute() {
      try {
        return await changeState(true, true)
      } catch (error) {
        return { ...state(), error: error instanceof Error ? error.message : String(error) }
      }
    },
  }))

  ctx.tools.register(defineTool({
    name: 'codebridge_set_enabled',
    description: 'Enable or disable the CodeBridge MCP service. Disabling unregisters its MCP tools; enabling reconnects and discovers them again.',
    parameters: {
      enabled: { type: 'boolean', required: true, description: 'true to start CodeBridge; false to stop it.' },
    },
    output: outputSchema(),
    async execute(args) {
      try {
        return await changeState(args.enabled)
      } catch (error) {
        return {
          ...state(),
          error: error instanceof Error ? error.message : String(error),
        }
      }
    },
  }))

  ctx.effect(() => async () => {
    await changeState(false)
  }, 'codebridge.manager.child-mcp-client')

  // Keep the control tools available even if the Python service fails to start.
  if (config.enabled) {
    try { await changeState(true) } catch { /* The error is exposed by codebridge_status. */ }
  }
}
