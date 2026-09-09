"""Create/update the operator guide using native SiYuan APIs, never raw .sy writes."""
import json
from pathlib import Path
import pipeline
from connect_siyuan import api

cfg = json.loads((Path(pipeline.config()['workspace'])/'conf'/'conf.json').read_text('utf-8'))
token = cfg['api']['token']
target = '/Local AI in SiYuan/Using the local knowledge index'
existing = api('/api/query/sql', {'stmt': "SELECT id,box FROM blocks WHERE type='d' AND hpath='/Local AI in SiYuan/Using the local knowledge index'"}, token)
content = (pipeline.BASE/'SIYUAN-GUIDE.md').read_text('utf-8')
if existing:
    doc_id = existing[0]['id']
    # Avoid replacing an existing user-edited guide; this publisher is create-once.
    print(json.dumps({'document_id': doc_id, 'created': False, 'note': 'Existing note preserved'}))
else:
    parents = api('/api/query/sql', {'stmt': "SELECT id,box FROM blocks WHERE type='d' AND hpath='/Local AI in SiYuan'"}, token)
    if len(parents) != 1:
        raise RuntimeError('Expected one Local AI in SiYuan parent document')
    doc_id = api('/api/filetree/createDocWithMd', {'notebook': parents[0]['box'], 'path': target, 'markdown': content}, token)
    (pipeline.BASE/'reports'/'guide.json').write_text(json.dumps({'document_id': doc_id, 'hpath': target}, indent=2), 'utf-8')
    print(json.dumps({'document_id': doc_id, 'created': True}))
