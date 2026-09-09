"""Exercise the native SiYuan Agent against the registered local tools."""
import datetime
import json
from pathlib import Path
import urllib.request
import sys
import pipeline
from connect_siyuan import api

cfg = json.loads((Path(pipeline.config()['workspace'])/'conf'/'conf.json').read_text('utf-8'))
session_id = datetime.datetime.now().strftime('%Y%m%d%H%M%S')+'-vesmoke'
payload = {'sessionID': session_id, 'message': 'Read-only integration check. Call mcp_SiYuan_Knowledge_knowledge_status, then call mcp_SiYuan_Knowledge_search_knowledge with query "What is City Hall and how is City Planning different?", project "City-Hall", top_k 3. Answer in one short paragraph grounded in these tool results and cite their SiYuan block links. Do not edit any notes, run scripts, or use unrelated tools. /no_think', 'language': 'en_US'}
timestamp = int(datetime.datetime.now().timestamp()*1000)
payload['userEntryID'] = session_id+'-user'
api('/api/ai/agent/saveSession', {'id': session_id, 'title': 'Local knowledge retrieval check', 'createdAt': timestamp,
                                'updatedAt': timestamp, 'entries': [{'id': payload['userEntryID'], 'type': 'user', 'content': payload['message']}], 'expectedRevision': 0}, cfg['api']['token'])
req = urllib.request.Request('http://127.0.0.1:6806/api/ai/agent/chat', json.dumps(payload).encode(),
                             {'Content-Type': 'application/json', 'Authorization': 'Token '+cfg['api']['token']})
path = pipeline.BASE/'reports'/'agent-smoke.jsonl'
print(json.dumps({'session_id': session_id, 'report': str(path)}), flush=True)
events = []
with urllib.request.urlopen(req, timeout=300) as response, path.open('w', encoding='utf-8') as output:
    event_type = ''
    for raw in response:
        line = raw.decode('utf-8').strip()
        if line.startswith('event:'):
            event_type = line[6:].strip()
        if line.startswith('data:'):
            value = line[5:].strip()
            try:
                event = json.loads(value)
                event['type'] = event_type
                events.append(event)
                output.write(json.dumps(event, ensure_ascii=False)+'\n')
                output.flush()
                if event_type not in {'content', 'reasoning', 'delta', 'thinking'}:
                    print(json.dumps(event, ensure_ascii=False)[:1400], flush=True)
            except ValueError:
                print(value[:500], flush=True)
done = next((e for e in events if e['type'] == 'done'), None)
errors = [e for e in events if e['type'] == 'error']
summary = {'session_id': session_id, 'completed': bool(done) and not errors,
           'tools_called': [e['name'] for e in events if e['type'] == 'tool_call'],
           'answer': ''.join(e.get('token', '') for e in events if e['type'] == 'content'), 'errors': errors}
if done:
    api('/api/ai/agent/saveSession', {'id': session_id, 'commitTurnID': done['turnID'],
                                    'expectedRevision': 1, 'updatedAt': int(datetime.datetime.now().timestamp()*1000)}, cfg['api']['token'])
(pipeline.BASE/'reports'/'agent-smoke-summary.json').write_text(json.dumps(summary, indent=2, ensure_ascii=False), 'utf-8')
print(json.dumps(summary, ensure_ascii=False), flush=True)
if not summary['completed']:
    sys.exit(1)
