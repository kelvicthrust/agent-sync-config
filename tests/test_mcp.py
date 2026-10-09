"""Native MCP sharing has no custom source or historical conflict inference."""
import json
import unittest
import test_sync as fixtures
from test_sync import snapshot, sync


class NativeMCPTests(unittest.TestCase):
    setUp = fixtures.ConfigurationTests.setUp
    write = fixtures.ConfigurationTests.write
    run_tool = fixtures.ConfigurationTests.run_tool

    def native(self, servers, home=False):
        return self.write('.claude.json' if home else '.mcp.json', json.dumps({'mcpServers': servers}), home)

    def test_claude_adoption_no_custom_file_and_roundtrip(self):
        self.native({'local': {'command': 'python3', 'args': ['server.py'], 'env': {'Z_TOKEN': '${Z_TOKEN}', 'A_TOKEN': '${A_TOKEN}', 'DEBUG': '1'}},
                     'remote': {'type': 'http', 'url': 'https://example.com/mcp', 'headers': {'Authorization': 'Bearer ${SERVICE_TOKEN}', 'X-User': '${USER_NAME}'}}})
        self.run_tool()
        codex = sync.read_toml(self.repo / '.codex/config.toml')
        self.assertEqual(list(codex['mcp_servers']['local']['env_vars']), ['A_TOKEN', 'Z_TOKEN'])
        self.assertEqual(codex['mcp_servers']['remote']['bearer_token_env_var'], 'SERVICE_TOKEN')
        self.assertFalse((self.repo / '.agents').exists())
        self.assertEqual(self.run_tool()['changes'], [])
        self.run_tool('check')

    def test_codex_adoption_and_preserved_comments(self):
        path = self.write('.codex/config.toml', '# top comment\nmodel="existing"\n[mcp_servers.local]\ncommand="python3" # interpreter\n')
        before = path.read_text()
        self.run_tool()
        self.assertEqual(path.read_text(), before)
        self.assertEqual(json.loads((self.repo / '.mcp.json').read_text())['mcpServers']['local']['command'], 'python3')

    def test_differing_native_definitions_need_explicit_source(self):
        path = self.native({'local': {'command': 'python3'}})
        self.run_tool()
        doc = json.loads(path.read_text()); doc['mcpServers']['local']['command'] = 'node'; path.write_text(json.dumps(doc))
        before = snapshot(self.base)
        report = self.run_tool(expected=1)
        self.assertIn('--mcp-source', report['issues'][0])
        self.assertEqual(snapshot(self.base), before)
        self.run_tool('--mcp-source', 'claude')
        self.assertEqual(sync.read_toml(self.repo / '.codex/config.toml')['mcp_servers']['local']['command'], 'node')
        self.run_tool('check')
        self.assertEqual(self.run_tool()['changes'], [])
        self.write('.codex/config.toml', '[mcp_servers.local]\ncommand="python3"\n')
        self.run_tool('--mcp-source', 'codex')
        self.assertEqual(json.loads(path.read_text())['mcpServers']['local']['command'], 'python3')

    def test_explicit_source_preserves_toml_inline_comments(self):
        path = self.write('.codex/config.toml', '[mcp_servers.local]\n# keep\ncommand="python3" # interpreter\n')
        self.native({'local': {'command': 'node'}})
        self.run_tool('--mcp-source', 'claude')
        self.assertIn('# keep', path.read_text())
        self.assertIn('command="node" # interpreter', path.read_text())

    def test_explicit_native_import_resolves_conflict_and_preserves_source(self):
        self.native({'local': {'command': 'python3'}}); self.run_tool()
        imported = self.base / 'import.json'; imported.write_text(json.dumps({'mcpServers': {'local': {'command': 'node'}}}))
        before = imported.read_bytes()
        self.run_tool('--import-mcp', str(imported))
        self.assertEqual(imported.read_bytes(), before)
        self.assertEqual(sync.read_toml(self.repo / '.codex/config.toml')['mcp_servers']['local']['command'], 'node')
        self.run_tool('check')

    def test_provider_options_and_credentials_preserved_not_copied(self):
        path = self.native({'unsupported': {'command': 'node', 'timeout': 9},
                            'secret': {'command': 'node', 'env': {'API_KEY': 'fixture-private-value'}}})
        before = path.read_bytes()
        report = self.run_tool(expected=1)
        self.assertEqual(path.read_bytes(), before)
        self.assertNotIn('fixture-private-value', json.dumps(report))
        self.assertFalse((self.repo / '.codex').exists())
        self.assertFalse((self.repo / '.agents').exists())

    def test_missing_one_side_is_adopted_not_interpreted_as_history(self):
        self.native({'local': {'command': 'python3'}}); self.run_tool()
        path = self.repo / '.codex/config.toml'; path.unlink()
        self.run_tool()
        self.assertTrue(path.exists())

    def test_unrelated_global_settings_and_private_project_entries_preserved(self):
        path = self.write('.claude.json', json.dumps({'theme': 'dark', 'projects': {'/other': {'mcpServers': {'private': {'command': 'node'}}}},
                                                    'mcpServers': {'remote': {'type': 'http', 'url': 'https://example.com/mcp'}}}), home=True)
        before = path.read_bytes()
        project = snapshot(self.repo)
        self.run_tool(scope='global')
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(snapshot(self.repo), project)
        self.assertTrue((self.home / '.codex/config.toml').exists())
        self.assertFalse((self.home / '.agents/mcp.json').exists())

    def test_empty_native_mcp_does_not_create_other_provider_file(self):
        self.native({}); self.run_tool()
        self.assertFalse((self.repo / '.codex').exists())

    def test_native_formats_malformed_fail_before_changes(self):
        for filename, contents in (('.mcp.json', '{bad'), ('.mcp.json', '{"mcpServers":[]}'), ('.codex/config.toml', 'not valid toml')):
            with self.subTest(filename=filename):
                path = self.write(filename, contents)
                before = snapshot(self.base)
                self.run_tool(expected=2)
                self.assertEqual(snapshot(self.base), before)
                path.unlink()
        self.run_tool('--import-mcp', str(self.base / 'missing'), expected=2)

    def test_sse_aliases_and_cwd_are_not_portable(self):
        self.native({'sse': {'type': 'sse', 'url': 'https://example.com'}, 'alias': {'command': 'node', 'env': {'A': '${B}'}}})
        self.run_tool(expected=1)
        self.assertFalse((self.repo / '.codex/config.toml').exists())
        self.write('.codex/config.toml', '[mcp_servers.local]\ncommand="node"\ncwd="/example"\n')
        self.run_tool(expected=1)
        self.assertNotIn('local', json.loads((self.repo / '.mcp.json').read_text())['mcpServers'])

    def test_native_file_symlink_is_not_overwritten(self):
        outside = self.base / 'native.json'; outside.write_text('{"mcpServers":{"local":{"command":"node"}}}')
        (self.repo / '.mcp.json').symlink_to(outside)
        before = outside.read_bytes()
        self.run_tool()
        self.assertEqual(outside.read_bytes(), before)
        self.assertTrue((self.repo / '.mcp.json').is_symlink())
