#!/usr/bin/env node

import fs from 'node:fs';
import process from 'node:process';
import readline from 'node:readline';
import { spawn } from 'node:child_process';

const REFRESH_TOOL = 'aios_refresh_code_mirrors';
const LOCAL_SEARCH_TOOL = 'aios_search_local_code';

const SUPPORT_TOOLS = new Set([
  'confluence_get_page',
  'confluence_get_page_children',
  'confluence_get_page_labels',
  'confluence_get_spaces',
  'confluence_search',
  'jira_get_all_projects',
  'jira_get_create_meta',
  'jira_get_issue',
  'jira_get_issue_types',
  'jira_get_transitions',
  'jira_search',
]);
const mode = process.env.AIOS_ZDEV_MODE || 'support';
if (!['local', 'support', 'sync'].includes(mode)) throw new Error('invalid AIOS_ZDEV_MODE');
const allowedTools = mode === 'support' ? SUPPORT_TOOLS : new Set();

const configPath = process.env.ZDEV_MCP_CONFIG;
const serverName = process.env.ZDEV_MCP_SERVER || 'zdev_upstream';
if (!configPath) throw new Error('ZDEV_MCP_CONFIG is required');

const payload = JSON.parse(fs.readFileSync(configPath, 'utf8'));
const config = payload.mcpServers?.[serverName];
if (!config || typeof config.command !== 'string' || !Array.isArray(config.args)) {
  throw new Error('invalid upstream MCP configuration');
}

const upstream = spawn(config.command, config.args, {
  env: { ...process.env, ...(config.env || {}) },
  stdio: ['pipe', 'pipe', 'inherit'],
});
const listRequestIds = new Set();
const refreshConfig = {
  script: process.env.AIOS_REFRESH_SCRIPT,
  mirrorRoot: process.env.AIOS_MIRROR_ROOT,
  repositoryMap: process.env.AIOS_REPOSITORY_MAP,
};
const searchConfig = {
  script: process.env.AIOS_LOCAL_SEARCH_SCRIPT,
  mirrorRoot: process.env.AIOS_MIRROR_ROOT,
  repositoryMap: process.env.AIOS_REPOSITORY_MAP,
  versionSets: process.env.AIOS_VERSION_SETS_FILE,
  defaultVersion: process.env.AIOS_DEFAULT_VERSION || '5.5.30',
};
const refreshEnabled = Object.values(refreshConfig).every((value) => typeof value === 'string' && value.length > 0);
const refreshAvailable = refreshEnabled && mode !== 'local';
const searchAvailable = [searchConfig.script, searchConfig.mirrorRoot, searchConfig.repositoryMap, searchConfig.versionSets]
  .every((value) => typeof value === 'string' && value.length > 0);

function send(message) {
  process.stdout.write(`${JSON.stringify(message)}\n`);
}

function deny(request, reason = 'method_not_allowed') {
  if (request.id === undefined) return;
  send({
    jsonrpc: '2.0',
    id: request.id,
    result: { content: [{ type: 'text', text: reason }], isError: true },
  });
}

readline.createInterface({ input: process.stdin }).on('line', (line) => {
  let request;
  try {
    request = JSON.parse(line);
  } catch {
    process.exitCode = 1;
    upstream.kill('SIGTERM');
    return;
  }
  const method = request.method;
  if (method === 'tools/call' && request.params?.name === LOCAL_SEARCH_TOOL && searchAvailable) {
    const args = request.params?.arguments;
    const version = args?.version || searchConfig.defaultVersion;
    const terms = args?.terms;
    const repositories = args?.repositories;
    if (
      typeof version !== 'string'
      || !/^\d+\.\d+\.\d+$/.test(version)
      || !Array.isArray(terms)
      || terms.length < 1
      || terms.length > 8
      || terms.some((term) => typeof term !== 'string' || term.length < 1 || term.length > 128)
      || (repositories !== undefined && (!Array.isArray(repositories) || repositories.some((name) => typeof name !== 'string')))
    ) {
      deny(request, 'local_code_search_input_invalid');
      return;
    }
    const command = [
      searchConfig.script,
      '--mirror-root', searchConfig.mirrorRoot,
      '--repository-map', searchConfig.repositoryMap,
      '--version-sets', searchConfig.versionSets,
      '--version', version,
      '--terms-json', JSON.stringify(terms),
      '--max-results', '80',
    ];
    if (repositories !== undefined) command.push('--repositories-json', JSON.stringify(repositories));
    const child = spawn('python3', command, { stdio: ['ignore', 'pipe', 'ignore'] });
    let output = '';
    child.stdout.on('data', (chunk) => {
      if (output.length < 80_000) output += chunk.toString();
    });
    child.on('exit', (code) => {
      if (request.id === undefined) return;
      send({
        jsonrpc: '2.0',
        id: request.id,
        result: {
          content: [{ type: 'text', text: code === 0 ? output.trim() : 'local_code_search_failed' }],
          isError: code !== 0,
        },
      });
    });
    return;
  }
  if (method === 'tools/call' && request.params?.name === REFRESH_TOOL && refreshAvailable) {
    const child = spawn('python3', [
      refreshConfig.script,
      '--mirror-root', refreshConfig.mirrorRoot,
      '--repository-map', refreshConfig.repositoryMap,
    ], { stdio: ['ignore', 'pipe', 'ignore'] });
    let output = '';
    child.stdout.on('data', (chunk) => {
      if (output.length < 16_384) output += chunk.toString();
    });
    child.on('exit', (code) => {
      if (request.id === undefined) return;
      send({
        jsonrpc: '2.0',
        id: request.id,
        result: {
          content: [{ type: 'text', text: code === 0 ? output.trim() : 'mirror_refresh_failed' }],
          isError: code !== 0,
        },
      });
    });
    return;
  }
  if (method === 'tools/call' && !allowedTools.has(request.params?.name)) {
    deny(request, 'tool_not_allowed');
    return;
  }
  if (method === 'tools/list' && request.id !== undefined) listRequestIds.add(String(request.id));
  if (
    !['initialize', 'ping', 'tools/list', 'tools/call'].includes(method)
    && typeof method === 'string'
    && !method.startsWith('notifications/')
  ) {
    deny(request);
    return;
  }
  upstream.stdin.write(`${JSON.stringify(request)}\n`);
});

readline.createInterface({ input: upstream.stdout }).on('line', (line) => {
  let response;
  try {
    response = JSON.parse(line);
  } catch {
    process.exitCode = 1;
    upstream.kill('SIGTERM');
    return;
  }
  if (response.id !== undefined && listRequestIds.delete(String(response.id))) {
    const tools = Array.isArray(response.result?.tools) ? response.result.tools : [];
    response.result = {
      ...response.result,
      tools: tools
        .filter((tool) => allowedTools.has(tool?.name))
        .map((tool) => ({
          ...tool,
          annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true },
        }))
        .concat(refreshAvailable ? [{
          name: REFRESH_TOOL,
          description: 'Fetch and prune the five registered AIOS bare mirrors. Never checkout, commit, or push.',
          inputSchema: { type: 'object', properties: {}, additionalProperties: false },
          annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: true },
        }] : [])
        .concat(searchAvailable ? [{
          name: LOCAL_SEARCH_TOOL,
          description: 'Search the immutable local five-repository AIOS snapshot for a release. Use for every source-code, implementation-location, call-chain, error-text, dGPU, GuestTools, or version-check question. Never ask the user for a local path. Extract 1-8 short code identifiers or error fragments as terms. Defaults to the latest approved version.',
          inputSchema: {
            type: 'object',
            properties: {
              version: { type: 'string', pattern: '^\\d+\\.\\d+\\.\\d+$' },
              terms: { type: 'array', minItems: 1, maxItems: 8, items: { type: 'string', minLength: 1, maxLength: 128 } },
              repositories: {
                type: 'array',
                uniqueItems: true,
                items: { enum: ['aios', 'zstack', 'premium', 'zstack-utility', 'zstack-ui-next'] },
              },
            },
            required: ['terms'],
            additionalProperties: false,
          },
          annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true },
        }] : []),
    };
  }
  send(response);
});

for (const signal of ['SIGINT', 'SIGTERM']) {
  process.on(signal, () => {
    upstream.kill(signal);
    process.exit(0);
  });
}

upstream.on('exit', (code, signal) => {
  if (signal && !process.exitCode) process.exitCode = 1;
  else process.exitCode = code ?? process.exitCode ?? 1;
});
