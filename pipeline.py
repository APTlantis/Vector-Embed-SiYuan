"""Local, source-preserving SiYuan inventory, embeddings, and retrieval."""
from __future__ import annotations

import argparse
import collections
import contextlib
import datetime as dt
import hashlib
import functools
import inspect
import io
from html.parser import HTMLParser
import json
import math
import mimetypes
import os
from pathlib import Path
import re
import sqlite3
import sys
import time
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET

BASE = Path(__file__).resolve().parent
VERSION = "siyuan-ast-v2/chunks-v1"
TEXT = set('.md .txt .rst .py .ps1 .psm1 .psd1 .sh .bat .cmd .toml .json .yaml .yml .xml .xaml .svg .html .htm .css .scss .js .mjs .cjs .ts .tsx .jsx .rs .go .c .h .cpp .cs .sql .ini .cfg .conf .csv .tsv .tex .r .d .red'.split())
CODE = set('.py .ps1 .psm1 .psd1 .sh .bat .cmd .js .mjs .ts .tsx .jsx .rs .go .c .h .cpp .cs .sql .r .d .red'.split())
ID = re.compile(r'^\d{14}-[a-z0-9]{7}$')


def config():
    return json.loads((BASE / 'config.json').read_text('utf-8'))


def connect():
    path = BASE / config()['database']
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=60)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA journal_mode=WAL')
    db.executescript('''
      CREATE TABLE IF NOT EXISTS files(
        path TEXT PRIMARY KEY, relative_path TEXT, sha256 TEXT, size INTEGER,
        modified_ns INTEGER, kind TEXT, content_type TEXT, project TEXT,
        document_id TEXT, title_path TEXT, visible_in_siyuan INTEGER,
        embeddable INTEGER, reason TEXT, status TEXT, present INTEGER,
        extraction_version TEXT, last_seen TEXT);
      CREATE TABLE IF NOT EXISTS chunks(
        id TEXT PRIMARY KEY, path TEXT, ordinal INTEGER, text TEXT, text_hash TEXT,
        line_start INTEGER, line_end INTEGER, block_ids TEXT, authority TEXT);
      CREATE INDEX IF NOT EXISTS chunks_path ON chunks(path);
      CREATE TABLE IF NOT EXISTS vectors(
        text_hash TEXT, model_key TEXT, dimensions INTEGER, vector BLOB,
        PRIMARY KEY(text_hash,model_key));
      CREATE TABLE IF NOT EXISTS relations(
        source_path TEXT, source_block_id TEXT, target TEXT, relation TEXT,
        PRIMARY KEY(source_path,source_block_id,target,relation));
      CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, value TEXT);
      CREATE VIRTUAL TABLE IF NOT EXISTS chunk_fts USING fts5(id UNINDEXED,text);
    ''')
    return db


def request(url, payload=None, timeout=180):
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(url, data, {'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode('utf-8', errors='replace')[:1500]
        raise RuntimeError(f'Local API HTTP {exc.code}: {detail}') from exc


def database_session(function):
    @functools.wraps(function)
    def wrapped(*args, **kwargs):
        bound = inspect.signature(function).bind_partial(*args, **kwargs)
        if bound.arguments.get('db') is not None:
            return function(*args, **kwargs)
        with contextlib.closing(connect()) as db:
            return function(*args, **{**kwargs, 'db': db})
    return wrapped


def single_writer(function):
    @functools.wraps(function)
    def wrapped(*args, **kwargs):
        lock_path = (BASE / config()['database']).parent / 'writer.lock'
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open('a+b') as handle:
            if handle.tell() == 0:
                handle.write(b'0')
                handle.flush()
            handle.seek(0)
            try:
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise RuntimeError('Another inventory/embedding writer is active. Wait for it to finish; status and search remain available.') from exc
            try:
                return function(*args, **kwargs)
            finally:
                if os.name == 'nt':
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle, fcntl.LOCK_UN)
    return wrapped


def digest(data):
    return hashlib.sha256(data).hexdigest()


def classify(relative, size):
    parts = relative.parts
    suffix = relative.suffix.lower()
    name = relative.name.lower()
    original_name = re.sub(r'-\d{14}-[a-z0-9]{7}(?=\.)', '', name)
    # Inventory every physical file; only extract knowledge-bearing live data.
    if parts[0] != 'data':
        return 'internal', False, 'workspace configuration, history, cache, or runtime state'
    if any(x in {'.git', 'node_modules', '__pycache__', '.siyuan'} for x in parts[1:]):
        return 'internal', False, 'internal control or generated dependency data'
    if len(parts) > 1 and parts[1] in {'storage', 'plugins', 'widgets', 'emojis'}:
        return 'internal', False, 'application state or installed extension, not imported source'
    if name.startswith('.env') or suffix in {'.key', '.pem', '.pfx', '.p12'} or re.search(r'(credentials|secrets|id_rsa|id_ed25519)', name):
        return 'internal', False, 'credential-like file'
    if original_name in {'package-lock.json', 'pnpm-lock.yaml', 'yarn.lock', 'cargo.lock', 'poetry.lock', 'uv.lock'}:
        return 'generated', False, 'generated dependency lockfile; cataloged, package manifests remain embeddable'
    if size > config()['max_file_bytes']:
        return 'asset', False, 'above configured extraction size limit'
    if suffix == '.sy' and len(parts) > 2 and ID.fullmatch(parts[1]):
        return 'document', True, ''
    if suffix == '.pdf':
        return 'document', True, ''
    if suffix in CODE:
        return ('script' if suffix in {'.py', '.ps1', '.sh', '.bat', '.cmd'} else 'code'), True, ''
    if suffix in TEXT or name in {'dockerfile', 'makefile', 'caddyfile', '.gitignore'}:
        kind = 'manifest' if 'manifest' in name else 'config' if suffix in {'.toml', '.json', '.yaml', '.yml', '.ini', '.cfg', '.conf'} else 'asset' if suffix == '.svg' else 'document'
        return kind, True, ''
    return 'asset', False, 'non-text format; extraction not implemented'


def node_text(node):
    typ = node.get('Type', '')
    if typ == 'NodeTextMark':
        return node.get('TextMarkTextContent', '') or node.get('TextMarkInlineMathContent', '')
    if typ in {'NodeText', 'NodeLinkText', 'NodeCodeBlockCode', 'NodeCodeSpanContent', 'NodeMathBlockContent', 'NodeInlineMathContent', 'NodeHTMLBlock', 'NodeInlineHTML', 'NodeLinkDest', 'NodeBlockRefText', 'NodeBlockRefDynamicText'}:
        return node.get('Data', '')
    if typ in {'NodeSoftBreak', 'NodeHardBreak'}:
        return '\n'
    children = node.get('Children', [])
    separator = '\n' if typ in {'NodeList', 'NodeListItem', 'NodeTable', 'NodeTableHead', 'NodeBlockquote', 'NodeSuperBlock'} else ' | ' if typ == 'NodeTableRow' else ''
    return separator.join(node_text(c) for c in children)


def node_relations(node, source, inherited=''):
    block = node.get('ID', inherited)
    if node.get('Type') == 'NodeLinkDest' and node.get('Data'):
        yield source, block, node['Data'], 'explicit_link'
    for field, kind in [('TextMarkAHref', 'explicit_link'), ('TextMarkBlockRefID', 'block_reference')]:
        if node.get(field):
            yield source, block, node[field], kind
    if node.get('Type') == 'NodeBlockRefID' and node.get('Data'):
        yield source, block, node['Data'], 'block_reference'
    for child in node.get('Children', []):
        yield from node_relations(child, source, block)


def split_text(text, limit, overlap):
    start = 0
    while start < len(text):
        end = min(start + limit, len(text))
        if end < len(text):
            boundary = text.rfind('\n', start + limit // 2, end)
            if boundary > start:
                end = boundary + 1
        value = text[start:end].strip()
        if value:
            yield value, text.count('\n', 0, start) + 1, text.count('\n', 0, end) + 1
        if end == len(text):
            break
        start = max(start + 1, end - overlap)


class SavedArticleParser(HTMLParser):
    """Extract a saved Wikipedia article without scripts, CSS, or navigation."""
    VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}
    SKIP = {'script', 'style', 'svg', 'head', 'nav', 'noscript', 'template'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack, self.article, self.visible = [], [], []

    def handle_starttag(self, tag, attrs):
        if tag not in self.VOID:
            self.stack.append((tag, 'mw-parser-output' in dict(attrs).get('class', '').split()))

    def handle_startendtag(self, tag, attrs):
        pass

    def handle_endtag(self, tag):
        for index in range(len(self.stack)-1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        if not any(tag in self.SKIP for tag, _ in self.stack) and data.strip():
            self.visible.append(data.strip())
            if any(article for _, article in self.stack):
                self.article.append(data.strip())

    def text(self):
        return '\n'.join(self.article or self.visible)


def extract(data, relative, titles, cfg):
    """Return title path, block-aware chunks, and explicit relationships."""
    if relative.suffix.lower() == '.pdf':
        from pypdf import PdfReader
        try:
            reader = PdfReader(io.BytesIO(data))
            pieces = []
            for page_number, page in enumerate(reader.pages, 1):
                text = page.extract_text() or ''
                pieces.extend((f'[PDF page {page_number}]\n{t}', None, None, []) for t, _, _ in split_text(text, cfg['chunk_chars'], cfg['overlap_chars']))
            if not pieces:
                raise ValueError('PDF has no extractable text; OCR is not implemented')
            return '', pieces, []
        except Exception as exc:
            raise ValueError('PDF text extraction failed: ' + str(exc)) from exc
    if relative.suffix.lower() != '.sy':
        if b'\x00' in data[:8192]:
            raise ValueError('binary content in text file')
        text = data.decode('utf-8-sig')
        transformed = relative.suffix.lower() == '.svg'
        if relative.suffix.lower() in {'.html', '.htm'} and ('mw-parser-output' in text or re.search(r'<title>[^<]*Wikipedia', text, re.I)):
            article = SavedArticleParser()
            article.feed(text)
            text = article.text()
            transformed = True
        if relative.suffix.lower() == '.svg':
            svg = ET.fromstring(text)
            # Geometry and embedded raster payloads are not linguistic knowledge.
            fragments = []
            for element in svg.iter():
                tag = element.tag.rsplit('}', 1)[-1]
                if tag in {'title', 'desc', 'text', 'metadata'}:
                    fragments.append(' '.join(element.itertext()))
            text = '\n'.join(fragments)
            text = re.sub(r'data:[^\s"<>]+', '[embedded data omitted]', text)
            text = re.sub(r'[A-Za-z0-9+/=]{300,}', '[binary payload omitted]', text)
            if not text.strip():
                text = 'SVG graphic: ' + re.sub(r'-\d{14}-[a-z0-9]{7}', '', relative.stem)
        return '', [(t, None if transformed else a, None if transformed else b, []) for t, a, b in split_text(text, cfg['chunk_chars'], cfg['overlap_chars'])], []
    node = json.loads(data)
    ids = [p for p in relative.parts[2:-1] if ID.fullmatch(p)] + [node['ID']]
    title = '/' + '/'.join(titles.get(i, i) for i in ids)
    pieces, buffer, blocks = [], [], []
    def flush():
        if buffer:
            pieces.append(('\n\n'.join(buffer), None, None, list(blocks)))
            buffer.clear()
            blocks.clear()
    for child in node.get('Children', []):
        value = node_text(child).strip()
        if not value:
            continue
        block_id = child.get('ID', node['ID'])
        if len(value) > cfg['chunk_chars']:
            flush()
            pieces.extend((t, None, None, [block_id]) for t, _, _ in split_text(value, cfg['chunk_chars'], cfg['overlap_chars']))
        else:
            if sum(map(len, buffer)) + len(value) + len(buffer)*2 > cfg['chunk_chars']:
                flush()
            buffer.append(value)
            blocks.append(block_id)
    flush()
    # Empty folder notes are still meaningful navigation entries.
    if not pieces:
        pieces = [(title, None, None, [node['ID']])]
    return title, pieces, list(node_relations(node, str(Path(cfg['workspace']) / relative)))


def authority_for(title):
    if '/City Planning/' in title or title.endswith('/City Planning'):
        return 'planning-or-history; non-governing'
    if title.startswith('/City-Hall/') or title == '/City-Hall':
        return 'imported City Hall snapshot; verify current canonical source before implementation'
    return 'source material; authority not assigned'


@single_writer
@database_session
def inventory(db=None):
    cfg = config()
    root = Path(cfg['workspace']).resolve(strict=True)
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    paths, walk_errors = [], []
    for parent, dirs, names in os.walk(root, followlinks=False, onerror=lambda e: walk_errors.append(str(e))):
        dirs[:] = [d for d in dirs if not (Path(parent)/d).is_symlink() and not (hasattr(Path(parent)/d, 'is_junction') and (Path(parent)/d).is_junction())]
        paths.extend(Path(parent)/n for n in names)
    if walk_errors:
        raise RuntimeError('Inventory traversal incomplete: ' + '; '.join(walk_errors))
    titles = {}
    for path in paths:
        rel = path.relative_to(root)
        if path.suffix == '.sy' and rel.parts[0] == 'data':
            try:
                node = json.loads(path.read_bytes())
                titles[node['ID']] = node.get('Properties', {}).get('title', node['ID'])
            except (OSError, ValueError, KeyError):
                pass
    counts = collections.Counter()
    with db:
        db.execute('UPDATE files SET present=0')
        for path in paths:
            rel = path.relative_to(root)
            try:
                before = path.stat()
                kind, embeddable, reason = classify(rel, before.st_size)
                # Streaming hash avoids loading large runtime databases in memory.
                hasher = hashlib.sha256()
                payload = bytearray() if embeddable else None
                with path.open('rb') as handle:
                    for part in iter(lambda: handle.read(1024*1024), b''):
                        hasher.update(part)
                        if payload is not None:
                            payload.extend(part)
                after = path.stat()
                if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                    raise ValueError('file changed during read; rerun inventory')
                sha = hasher.hexdigest()
                old = db.execute('SELECT * FROM files WHERE path=?', (str(path),)).fetchone()
                title, pieces, relations = '', [], []
                if embeddable:
                    title, pieces, relations = extract(bytes(payload), rel, titles, cfg)
                project = title.split('/')[1] if title else 'unassigned-assets' if 'assets' in rel.parts else 'workspace-internal'
                doc_id = path.stem if kind == 'document' and path.suffix == '.sy' else None
                extraction_key = VERSION + '/' + str(cfg['chunk_chars']) + '/' + str(cfg['overlap_chars'])
                if rel.suffix.lower() in {'.html', '.htm'}:
                    extraction_key += '/saved-article-v1'
                unchanged = old and old['sha256'] == sha and old['extraction_version'] == extraction_key and old['title_path'] == title and old['embeddable'] == embeddable
                status = old['status'] if unchanged else 'pending' if embeddable else 'excluded'
                db.execute('INSERT OR REPLACE INTO files VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                           (str(path), rel.as_posix(), sha, before.st_size, before.st_mtime_ns, kind, mimetypes.guess_type(path)[0] or 'application/octet-stream', project, doc_id, title, int(bool(doc_id)), int(embeddable), reason, status, 1, extraction_key, now))
                if not unchanged:
                    if old:
                        old_ids = [r[0] for r in db.execute('SELECT id FROM chunks WHERE path=?', (str(path),))]
                        if old_ids:
                            marks = ','.join('?' for _ in old_ids)
                            db.execute('DELETE FROM chunk_fts WHERE id IN (' + marks + ')', old_ids)
                        db.execute('DELETE FROM chunks WHERE path=?', (str(path),))
                        db.execute('DELETE FROM relations WHERE source_path=?', (str(path),))
                    for ordinal, (value, line_a, line_b, block_ids) in enumerate(pieces):
                        # Stable human-readable context is part of the embedding input.
                        text = (title or re.sub(r'-\d{14}-[a-z0-9]{7}(?=\.)', '', rel.name)) + '\n\n' + value
                        text_hash = digest(text.encode())
                        cid = digest((str(path) + '\0' + str(ordinal)).encode())
                        db.execute('INSERT INTO chunks VALUES (?,?,?,?,?,?,?,?,?)', (cid, str(path), ordinal, text, text_hash, line_a, line_b, json.dumps(block_ids), authority_for(title)))
                        db.execute('INSERT INTO chunk_fts VALUES (?,?)', (cid, text))
                    db.executemany('INSERT OR IGNORE INTO relations VALUES (?,?,?,?)', relations)
                counts['unchanged' if unchanged else 'updated'] += 1
                counts['embeddable' if embeddable else 'excluded'] += 1
                if sum(counts[x] for x in ('updated', 'unchanged')) % 250 == 0:
                    print(json.dumps({'inventoried': counts['updated'] + counts['unchanged'], 'total': len(paths)}), file=sys.stderr, flush=True)
            except (OSError, ValueError, KeyError, ET.ParseError) as exc:
                counts['errors'] += 1
                # Never leave a stale formerly-indexed file eligible after a failed read.
                try:
                    st = path.stat()
                    failed_size, failed_modified = st.st_size, st.st_mtime_ns
                except OSError:
                    failed_size, failed_modified = None, None
                db.execute('INSERT INTO files(path,relative_path,status,present,embeddable,reason,last_seen,size,modified_ns,kind) VALUES (?,?,?,1,0,?,?,?,?,?) ON CONFLICT(path) DO UPDATE SET present=1,embeddable=0,status=excluded.status,reason=excluded.reason,last_seen=excluded.last_seen,size=excluded.size,modified_ns=excluded.modified_ns,kind=excluded.kind', (str(path), rel.as_posix(), 'error', str(exc), now, failed_size, failed_modified, 'internal' if rel.parts[0] != 'data' else 'asset'))
        db.execute("UPDATE files SET status='missing' WHERE present=0")
        # Exact hash evidence connects imported support files to their source project.
        canonical = Path(cfg.get('canonical_city_hall', 'D:/.city_hall'))
        if canonical.is_dir():
            imported = collections.defaultdict(list)
            for row in db.execute("SELECT path,sha256 FROM files WHERE present=1 AND embeddable=1 AND document_id IS NULL"):
                imported[row['sha256']].append(row['path'])
            db.execute("DELETE FROM relations WHERE relation='exact_content_match'")
            for parent, dirs, names in os.walk(canonical, followlinks=False):
                dirs[:] = [d for d in dirs if d not in {'.git', 'node_modules', '__pycache__', 'target', 'dist', 'build', '.venv'} and not (Path(parent)/d).is_symlink() and not (hasattr(Path(parent)/d, 'is_junction') and (Path(parent)/d).is_junction())]
                for name in names:
                    source = Path(parent)/name
                    try:
                        if source.suffix.lower() not in TEXT | {'.pdf'} or source.stat().st_size > cfg['max_file_bytes']:
                            continue
                        for asset in imported.get(digest(source.read_bytes()), []):
                            db.execute('INSERT OR IGNORE INTO relations VALUES (?,?,?,?)', (asset, '', str(source), 'exact_content_match'))
                            db.execute("UPDATE files SET project='City-Hall' WHERE path=?", (asset,))
                    except OSError:
                        continue
        db.execute('INSERT OR REPLACE INTO metadata VALUES (?,?)', ('inventory_time', now))
    report = status_report(db)
    report['run'] = dict(counts)
    (BASE/'reports').mkdir(exist_ok=True)
    (BASE/'reports'/'inventory.json').write_text(json.dumps(report, indent=2), 'utf-8')
    print(json.dumps(report, indent=2))


def model_identity(cfg):
    models = request(cfg['ollama_url'] + '/api/tags')['models']
    model = next((m for m in models if m['name'] == cfg['embedding_model']), None)
    if not model:
        raise RuntimeError('Configured embedding model is not installed')
    info = request(cfg['ollama_url'] + '/api/show', {'model': cfg['embedding_model']})
    if 'embedding' not in info.get('capabilities', []):
        raise RuntimeError('Configured model does not support embeddings')
    return cfg['embedding_model'] + '@' + model['digest'] + '/ollama-embed-v1'


def embed_texts(cfg, texts):
    import numpy as np
    payload = {'model': cfg['embedding_model'], 'input': texts, 'truncate': False, 'keep_alive': '10m'}
    if cfg.get('request_options'):
        payload['options'] = cfg['request_options']
    result = request(cfg['ollama_url'] + '/api/embed', payload)
    vectors = np.asarray(result['embeddings'], dtype='<f4')
    if vectors.ndim != 2 or len(vectors) != len(texts) or not np.isfinite(vectors).all():
        raise ValueError('Invalid embedding response')
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    if (norms == 0).any():
        raise ValueError('Zero-length embedding')
    return vectors / norms


@single_writer
@database_session
def embed(limit=0, db=None):
    cfg = config()
    key = model_identity(cfg)
    # Switch atomically to this model identity; retrieval cannot mix old/new spaces.
    with db:
        db.execute('INSERT OR REPLACE INTO metadata VALUES (?,?)', ('model_key', key))
    pending = db.execute('''SELECT DISTINCT c.text_hash,c.text FROM chunks c JOIN files f ON f.path=c.path
      WHERE f.present=1 AND f.embeddable=1 AND NOT EXISTS
      (SELECT 1 FROM vectors v WHERE v.text_hash=c.text_hash AND v.model_key=?)''', (key,)).fetchall()
    if limit:
        pending = pending[:limit]
    print(json.dumps({'pending_unique_chunks': len(pending), 'model': key}), flush=True)
    start = time.monotonic()
    for offset in range(0, len(pending), cfg['batch_size']):
        batch = pending[offset:offset+cfg['batch_size']]
        vectors = embed_texts(cfg, [x['text'] for x in batch])
        with db:
            for row, vector in zip(batch, vectors):
                db.execute('INSERT OR REPLACE INTO vectors VALUES (?,?,?,?)', (row['text_hash'], key, len(vector), vector.tobytes()))
        print(json.dumps({'embedded': offset+len(batch), 'total': len(pending), 'elapsed_seconds': round(time.monotonic()-start, 1)}), flush=True)
    with db:
        db.execute('''UPDATE files SET status=CASE WHEN EXISTS (SELECT 1 FROM chunks c WHERE c.path=files.path
          AND NOT EXISTS (SELECT 1 FROM vectors v WHERE v.text_hash=c.text_hash AND v.model_key=?))
          THEN 'pending' ELSE 'embedded' END WHERE present=1 AND embeddable=1''', (key,))
    print(json.dumps(status_report(db), indent=2))


@database_session
def status_report(db=None):
    group = lambda sql: dict(db.execute(sql).fetchall())
    key = db.execute("SELECT value FROM metadata WHERE key='model_key'").fetchone()
    key = key[0] if key else ''
    file_states = dict(db.execute('''SELECT CASE WHEN f.present=0 THEN 'missing'
      WHEN f.embeddable=1 THEN CASE WHEN EXISTS (SELECT 1 FROM chunks c WHERE c.path=f.path
        AND NOT EXISTS (SELECT 1 FROM vectors v WHERE v.text_hash=c.text_hash AND v.model_key=?))
        THEN 'pending' ELSE 'embedded' END ELSE f.status END AS state,count(*)
      FROM files f GROUP BY state''', (key,)).fetchall())
    return {'files': file_states,
            'kinds': group('SELECT kind,count(*) FROM files WHERE present=1 GROUP BY kind'),
            'projects': group('SELECT project,count(*) FROM files WHERE present=1 AND embeddable=1 GROUP BY project'),
            'live_chunks': db.execute('SELECT count(*) FROM chunks c JOIN files f ON f.path=c.path WHERE f.present=1 AND f.embeddable=1').fetchone()[0],
            'embedded_live_chunks': db.execute('SELECT count(*) FROM chunks c JOIN files f ON f.path=c.path JOIN vectors v ON v.text_hash=c.text_hash AND v.model_key=? WHERE f.present=1 AND f.embeddable=1', (key,)).fetchone()[0],
            'explicit_relations': db.execute('SELECT count(*) FROM relations r JOIN files f ON f.path=r.source_path WHERE f.present=1 AND f.embeddable=1').fetchone()[0],
            'model_key': key,
            'inventory_time': (db.execute("SELECT value FROM metadata WHERE key='inventory_time'").fetchone() or ['never'])[0]}


@database_session
def search(query, top_k=6, project=None, db=None):
    import numpy as np
    if not isinstance(query, str) or not query.strip() or len(query) > 8000:
        raise ValueError('Query must contain 1-8000 characters')
    top_k = max(1, min(int(top_k), 20))
    cfg = config()
    key = model_identity(cfg)
    # Qwen recommends an instruction on queries, while documents are unprefixed.
    query_cfg = {**cfg, 'request_options': cfg.get('query_options', {})}
    vector = embed_texts(query_cfg, ['Instruct: Given a question, retrieve relevant passages from notes, standards, and source files.\nQuery: ' + query])[0]
    rows = db.execute('''SELECT c.*,f.sha256,f.project,f.title_path,f.document_id,f.relative_path,f.kind,f.last_seen,f.modified_ns,f.size,v.vector
      FROM chunks c JOIN files f ON f.path=c.path JOIN vectors v ON v.text_hash=c.text_hash AND v.model_key=?
      WHERE f.present=1 AND f.embeddable=1 AND (? IS NULL OR f.project=?)''', (key, project, project)).fetchall()
    if not rows:
        return {'query': query, 'results': [], 'warning': 'No embeddings for this model and scope. Run inventory and embed.'}
    matrix = np.stack([np.frombuffer(r['vector'], dtype='<f4') for r in rows])
    scores = matrix @ vector
    ranks = np.argsort(-scores)
    fused = {rows[i]['id']: 1/(60+rank+1) for rank, i in enumerate(ranks)}
    tokens = re.findall(r'\w+', query)[:32]
    if tokens:
        expression = ' OR '.join('"'+t+'"' for t in tokens)
        lexical = db.execute('''SELECT ft.id FROM chunk_fts ft JOIN chunks c ON c.id=ft.id JOIN files f ON f.path=c.path
          WHERE chunk_fts MATCH ? AND f.present=1 AND f.embeddable=1 AND (? IS NULL OR f.project=?) ORDER BY rank LIMIT 100''', (expression, project, project)).fetchall()
        for rank, row in enumerate(lexical):
            if row[0] in fused:
                fused[row[0]] += 1/(60+rank+1)
    order = sorted(range(len(rows)), key=lambda i: fused[rows[i]['id']], reverse=True)
    results, seen = [], set()
    for i in order:
        row = rows[i]
        if row['text_hash'] in seen:
            continue
        seen.add(row['text_hash'])
        blocks = json.loads(row['block_ids'])
        target = blocks[0] if blocks else row['document_id']
        matches = [r[0] for r in db.execute("SELECT target FROM relations WHERE source_path=? AND relation='exact_content_match'", (row['path'],))]
        try:
            st = Path(row['path']).stat()
            changed = st.st_mtime_ns != row['modified_ns'] or st.st_size != row['size']
        except OSError:
            changed = True
        authority = row['authority']
        if matches:
            authority = 'imported support file; exact City Hall source match at inventory time'
            if all('City Planning' in Path(p).parts for p in matches):
                authority = 'planning-or-history; non-governing (exact source match)'
        results.append({'chunk_id': row['id'], 'text': row['text'], 'path': row['path'], 'relative_path': row['relative_path'],
                        'sha256': row['sha256'], 'project': row['project'], 'kind': row['kind'], 'title_path': row['title_path'],
                        'document_id': row['document_id'], 'block_ids': blocks, 'uri': 'siyuan://blocks/'+target if target else Path(row['path']).as_uri(),
                        'line_start': row['line_start'], 'line_end': row['line_end'], 'authority': authority,
                        'chunk_number': row['ordinal']+1,
                        'chunk_count': db.execute('SELECT count(*) FROM chunks WHERE path=?', (row['path'],)).fetchone()[0],
                        'exact_source_matches_at_inventory': matches,
                        'indexed_at': row['last_seen'], 'source_changed_since_inventory': changed,
                        'cosine_similarity': round(float(scores[i]), 4)})
        if len(results) == top_k:
            break
    return {'query': query, 'results': results, 'note': 'Similarity is a retrieval signal, not proof of a relationship. Imported snapshots may differ from canonical sources.'}


@database_session
def relationships(target, top_k=30, db=None):
    return [dict(r) for r in db.execute('''SELECT r.* FROM relations r JOIN files f ON f.path=r.source_path
      WHERE f.present=1 AND f.embeddable=1 AND (r.source_path=? OR r.target=? OR r.source_block_id=?) LIMIT ?''',
      (target, target, target, max(1, min(int(top_k), 100))))]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('inventory')
    sub.add_parser('status')
    emb = sub.add_parser('embed')
    emb.add_argument('--limit', type=int, default=0)
    srch = sub.add_parser('search')
    srch.add_argument('query')
    srch.add_argument('--project')
    srch.add_argument('--top-k', type=int, default=6)
    args = parser.parse_args()
    if args.command == 'inventory':
        inventory()
    elif args.command == 'embed':
        embed(args.limit)
    elif args.command == 'search':
        print(json.dumps(search(args.query, args.top_k, args.project), ensure_ascii=False, indent=2))
    else:
        print(json.dumps(status_report(), indent=2))


if __name__ == '__main__':
    main()
