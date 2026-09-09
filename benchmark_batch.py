"""Compare a processing-batch option against eight already stored long passages."""
import contextlib
import json
import time
import numpy as np
import pipeline

cfg = pipeline.config()
with contextlib.closing(pipeline.connect()) as db:
    key = pipeline.model_identity(cfg)
    rows = db.execute('''SELECT c.text,v.vector FROM chunks c JOIN vectors v ON c.text_hash=v.text_hash
                        WHERE v.model_key=? GROUP BY c.text_hash ORDER BY length(c.text) DESC LIMIT 8''', (key,)).fetchall()
    start = time.monotonic()
    result = pipeline.request(cfg['ollama_url']+'/api/embed', {'model': cfg['embedding_model'], 'input': [r['text'] for r in rows],
                              'truncate': False, 'options': {'num_batch': 2048}, 'keep_alive': '10m'})
    new = np.asarray(result['embeddings'], dtype='<f4')
    new /= np.linalg.norm(new, axis=1, keepdims=True)
    old = np.stack([np.frombuffer(r['vector'], dtype='<f4') for r in rows])
    report = {'num_batch': 2048, 'texts': len(rows), 'characters': sum(len(r['text']) for r in rows),
              'seconds': time.monotonic()-start, 'total_duration_ns': result['total_duration'],
              'load_duration_ns': result.get('load_duration'), 'tokens': result['prompt_eval_count'],
              'minimum_cosine_to_original': float(np.min(np.sum(new*old, axis=1)))}
    (pipeline.BASE/'reports'/'batch-benchmark.json').write_text(json.dumps(report, indent=2), 'utf-8')
    print(json.dumps(report, indent=2))
