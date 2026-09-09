"""Register/remove the local read-only MCP server through SiYuan's settings API."""
import argparse
import copy
import json
from pathlib import Path
import sys
import urllib.request

import pipeline

SERVER_ID = '20260908043000-vectors'
SERVER_NAME = 'SiYuan Knowledge'


def api(endpoint, payload, token):
    req = urllib.request.Request('http://127.0.0.1:6806'+endpoint, json.dumps(payload).encode(),
                                 {'Content-Type': 'application/json', 'Authorization': 'Token '+token})
    with urllib.request.urlopen(req, timeout=90) as response:
        result = json.load(response)
    if result.get('code') != 0:
        raise RuntimeError(result.get('msg', 'SiYuan API failed'))
    return result.get('data')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--remove', action='store_true')
    args = parser.parse_args()
    disk = json.loads((Path(pipeline.config()['workspace'])/'conf'/'conf.json').read_text('utf-8'))
    token = disk.get('api', {}).get('token', '')
    live = api('/api/system/getConf', {}, token)
    live_conf = live.get('conf', live)
    original = live_conf['ai']
    ai = copy.deepcopy(original)
    servers = ai.setdefault('mcp', {}).setdefault('servers', [])
    servers[:] = [s for s in servers if s.get('id') != SERVER_ID]
    if not args.remove:
        servers.append({'id': SERVER_ID, 'name': SERVER_NAME, 'enabled': True, 'type': 'stdio',
                        'command': sys.executable, 'args': ['-u', '-B', str(pipeline.BASE/'mcp_server.py')],
                        'inheritEnv': ['SystemRoot', 'TEMP', 'TMP', 'USERPROFILE', 'LOCALAPPDATA'],
                        'env': {'PYTHONIOENCODING': 'utf-8',
                                'VECTOREMBED_SOURCE_VERSION': pipeline.digest((pipeline.BASE/'pipeline.py').read_bytes() + (pipeline.BASE/'mcp_server.py').read_bytes())[:16]},
                        'timeout': 180, 'trustToolAnnotations': True})
    selection_change = False
    # This installation has its embedding-only model selected for agent and editing.
    # Add a chat-capable model to the existing local provider without removing models.
    if not args.remove:
        provider = next((p for p in ai['providers'] if p.get('baseURL', '').rstrip('/') in
                         {'http://localhost:11434/v1', 'http://127.0.0.1:11434/v1'}), None)
        if provider is None:
            raise RuntimeError('No existing local Ollama provider; configure one in SiYuan first')
        models = provider['models']
        chat = next((m for m in models if m['name'] == 'qwen3-siyuan:8b'), None)
        if chat is None:
            chat = {'id': '20260908043000-qwensiy', 'name': 'qwen3-siyuan:8b', 'displayName': 'Qwen3 8B (SiYuan 32K)', 'enabled': True, 'contextLength': 32768}
            models.append(chat)
        by_id = {m['id']: m['name'] for p in ai['providers'] for m in p['models']}
        for purpose in ('agent', 'editing'):
            if 'embed' in by_id.get(ai[purpose]['modelId'], '').lower() or ai[purpose]['modelId'] == '20260908043000-qwen8bc':
                ai[purpose]['modelId'] = chat['id']
                selection_change = True
    print(json.dumps({'action': 'remove' if args.remove else 'register', 'server': SERVER_NAME,
                      'transport': 'stdio', 'chat_selection_corrected': selection_change,
                      'tools': ['search_knowledge', 'knowledge_status', 'explicit_relationships'],
                      'apply': args.apply}, indent=2))
    if args.apply:
        reports = pipeline.BASE/'reports'
        reports.mkdir(exist_ok=True)
        # Only save fields we change. Never persist provider API keys or the API token.
        snapshot = {'previous_server': next((s for s in original.get('mcp', {}).get('servers', []) if s.get('id') == SERVER_ID), None),
                    'agent_model_id': original['agent']['modelId'], 'editing_model_id': original['editing']['modelId'],
                    'note': 'Remove this MCP server with --remove. Restore model IDs through settings if desired. Existing providers and credentials were preserved.'}
        backup = reports/'connection-before.json'
        if not backup.exists():
            backup.write_text(json.dumps(snapshot, indent=2), 'utf-8')
        api('/api/setting/setAI', ai, token)
        print(json.dumps({'saved': True}))


if __name__ == '__main__':
    main()
