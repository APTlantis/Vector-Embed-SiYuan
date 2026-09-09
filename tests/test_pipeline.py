import json
from pathlib import Path
import unittest
import tempfile
import contextlib
import io
from unittest.mock import patch
import pipeline
import mcp_server


class PipelineTests(unittest.TestCase):
    def test_code_and_hidden_state_are_different(self):
        self.assertTrue(pipeline.classify(Path('data/assets/tool.py'), 100)[1])
        self.assertFalse(pipeline.classify(Path('conf/conf.json'), 100)[1])
        self.assertFalse(pipeline.classify(Path('data/assets/.env'), 100)[1])
        self.assertFalse(pipeline.classify(Path('history/note.sy'), 100)[1])

    def test_long_line_is_bounded_and_end_preserved(self):
        value = 'X' * 10000 + 'END'
        chunks = list(pipeline.split_text(value, 200, 20))
        self.assertTrue(all(len(c[0]) <= 200 for c in chunks))
        self.assertTrue(chunks[-1][0].endswith('END'))

    def test_block_text_and_explicit_links(self):
        node = {'ID': 'block', 'Type': 'NodeParagraph', 'Children': [
            {'Type': 'NodeText', 'Data': 'Use '},
            {'Type': 'NodeTextMark', 'TextMarkTextContent': 'D:\\city', 'TextMarkType': 'code'},
            {'Type': 'NodeLinkDest', 'Data': 'assets/tool.py'}]}
        self.assertIn('D:\\city', pipeline.node_text(node))
        self.assertEqual(list(pipeline.node_relations(node, 'file')), [('file', 'block', 'assets/tool.py', 'explicit_link')])

    def test_folder_title_and_block_provenance(self):
        doc, parent = '20260907143333-abcdefg', '20260907143333-hijklmn'
        node = {'ID': doc, 'Children': [{'ID': 'block', 'Type': 'NodeParagraph', 'Children': [{'Type': 'NodeText', 'Data': 'Hello'}]}]}
        title, chunks, _ = pipeline.extract(json.dumps(node).encode(), Path(f'data/20260907143333-opqrstu/{parent}/{doc}.sy'),
                                            {doc: 'Child', parent: 'City-Hall'}, pipeline.config())
        self.assertEqual(title, '/City-Hall/Child')
        self.assertEqual(chunks[0][3], ['block'])

    def test_mcp_has_no_write_tools(self):
        tools = mcp_server.dispatch({'method': 'tools/list'})['tools']
        self.assertTrue(all(t['annotations']['readOnlyHint'] for t in tools))
        result = mcp_server.dispatch({'method': 'tools/call', 'params': {'name': 'execute_shell'}})
        self.assertTrue(result['isError'])

    def test_planning_not_canonical(self):
        self.assertIn('non-governing', pipeline.authority_for('/City-Hall/City Planning/README'))
        self.assertIn('snapshot', pipeline.authority_for('/City-Hall/CTS/README'))

    def test_svg_embedded_image_is_not_embedded_as_text(self):
        svg = ('<svg><title>Operational diagram</title><metadata>source: City Hall</metadata><image href="data:image/png;base64,' + 'A'*10000 + '"/></svg>').encode()
        _, chunks, _ = pipeline.extract(svg, Path('data/assets/diagram.svg'), {}, pipeline.config())
        self.assertIn('Operational diagram', chunks[0][0])
        self.assertNotIn('AAAA', chunks[0][0])
        self.assertIsNone(chunks[0][1])

    def test_pdf_text_keeps_page_identity(self):
        from types import SimpleNamespace
        reader = SimpleNamespace(pages=[SimpleNamespace(extract_text=lambda: 'Archive verification'), SimpleNamespace(extract_text=lambda: '')])
        with patch('pypdf.PdfReader', return_value=reader):
            _, chunks, _ = pipeline.extract(b'placeholder', Path('data/assets/report.pdf'), {}, pipeline.config())
        self.assertEqual(chunks[0][0], '[PDF page 1]\nArchive verification')
        self.assertIsNone(chunks[0][1])

    def test_scanned_pdf_is_an_explicit_failure(self):
        from types import SimpleNamespace
        reader = SimpleNamespace(pages=[SimpleNamespace(extract_text=lambda: '')])
        with patch('pypdf.PdfReader', return_value=reader), self.assertRaisesRegex(ValueError, 'no extractable text'):
            pipeline.extract(b'placeholder', Path('data/assets/report.pdf'), {}, pipeline.config())

    def test_saved_article_omits_markup_and_navigation(self):
        html = b'<html><head><title>Sample - Wikipedia</title><style>NOISE</style></head><body><nav>Navigation</nav><div class="mw-parser-output"><p>Useful article.</p><script>NOISE</script></div><footer>Footer</footer></body></html>'
        _, chunks, _ = pipeline.extract(html, Path('data/assets/page.html'), {}, pipeline.config())
        self.assertEqual(chunks[0][0], 'Useful article.')
        self.assertIsNone(chunks[0][1])
        self.assertFalse(pipeline.classify(Path('data/assets/package-lock-20260907144104-w9ctylx.json'), 200)[1])

    def test_incremental_change_deletion_and_model_switch(self):
        import numpy as np
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base/'source'
            asset = root/'data'/'assets'/'example.py'
            asset.parent.mkdir(parents=True)
            asset.write_text('print("first")', 'utf-8')
            cfg = {**pipeline.config(), 'workspace': str(root), 'database': 'catalog.db', 'canonical_city_hall': str(base/'absent')}
            calls = []
            def fake_embeddings(cfg, texts):
                calls.extend(texts)
                return np.asarray([[1., 0.] for _ in texts], dtype='<f4')
            with patch.object(pipeline, 'BASE', base), patch.object(pipeline, 'config', return_value=cfg), \
                 patch.object(pipeline, 'model_identity', return_value='model-A') as model, \
                 patch.object(pipeline, 'embed_texts', side_effect=fake_embeddings), contextlib.redirect_stdout(io.StringIO()):
                pipeline.inventory()
                pipeline.embed()
                self.assertEqual(len(calls), 1)
                pipeline.inventory()
                pipeline.embed()
                self.assertEqual(len(calls), 1, 'Unchanged content must not be re-embedded')
                asset.write_text('print("second")', 'utf-8')
                pipeline.inventory()
                self.assertEqual(pipeline.search('first')['results'], [], 'Stale vectors must not retrieve changed chunks')
                pipeline.embed()
                self.assertEqual(len(calls), 3)  # one query plus the changed document
                model.return_value = 'model-B'
                self.assertEqual(pipeline.search('second')['results'], [], 'Different model spaces must not mix')
                pipeline.embed()
                self.assertEqual(len(calls), 5)
                asset.unlink()
                pipeline.inventory()
                self.assertEqual(pipeline.search('second')['results'], [], 'Missing files must not retrieve')
                self.assertEqual(pipeline.status_report()['files']['missing'], 1)


if __name__ == '__main__':
    unittest.main()
