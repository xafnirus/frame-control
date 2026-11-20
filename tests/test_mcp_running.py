"""MCP running-game reads and approved quits through the real loopback HTTP API.

Only the remote running-game helper is stubbed; no headset or user process is used.
"""
import sandbox  # noqa: F401
from contextlib import ExitStack
import json
from pathlib import Path
import sys
import threading
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'ui'))
import frame_agent as agent
import frame_mcp as mcp
import server


class RunningTools(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.stack.enter_context(mock.patch.object(agent, 'approvals', agent.Approvals()))
        self.stack.enter_context(mock.patch.object(server, 'LINK', None))
        self.stack.enter_context(mock.patch.object(server, 'ssh', side_effect=AssertionError('No real SSH')))
        self.stack.enter_context(mock.patch.object(server.Handler, 'log_message'))
        self.remote = self.stack.enter_context(mock.patch.object(server, 'running_frame'))
        self.remote.side_effect = lambda *args, **kwargs: (
            {'running': [{'appid': 620, 'name': 'Portal 2', 'kind': 'steam'}]}
            if args == ('list',) else {'method': 'steam', 'message': 'Quit Portal 2'})
        self.httpd = server.LoopbackServer(('127.0.0.1', 0), server.Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.client = mcp.Client('http://127.0.0.1:%d' % self.httpd.server_port, server.UI_KEY)

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join()
        self.stack.close()

    def call(self, name, args):
        return json.loads(mcp.call(self.client, name, args)['content'][0]['text'])

    def decide(self, proposal, accept=True):
        # Separate HTTP request stands in for the human approval page, never an MCP tool.
        self.client.request('/api/agent/approval', {
            'confirmation': proposal['confirmation'], 'accept': accept})

    def test_running_is_read_only_and_returns_existing_helper_result(self):
        result = self.call('running', {})
        self.assertEqual(result['running'][0]['appid'], 620)
        self.remote.assert_called_once_with('list')
        self.assertEqual(agent.approvals.pending, {})
        spec = next(t for t in mcp.TOOLS if t['name'] == 'running')
        self.assertTrue(spec['annotations']['readOnlyHint'])
        self.assertFalse(spec['annotations']['destructiveHint'])

    def test_quit_requires_exact_approval_then_consumes_it_once(self):
        proposal = self.call('quit', {'appid': '620'})
        self.assertEqual(proposal['action']['name'], 'quit')
        self.assertEqual(proposal['action']['arguments'], {'appid': '620'})
        self.assertIn('Unsaved progress may be lost', proposal['action']['warning'])
        self.assertIn('/assistant#confirm=', proposal['approvalUrl'])
        token = proposal['confirmation']
        reviewed = self.client.request('/api/agent/approval?confirmation=' + token)
        self.assertEqual(reviewed['action'], proposal['action'])
        with self.assertRaisesRegex(ValueError, 'needs approval'):
            self.call('quit', {'appid': '620', 'confirmation': token})
        self.decide(proposal)
        for name, args in [('quit', {'appid': '440'}), ('launch', {'appid': '620'})]:
            with self.assertRaisesRegex(ValueError, 'needs approval'):
                self.call(name, {**args, 'confirmation': token})
        self.remote.assert_not_called()
        result = self.call('quit', {'appid': '620', 'confirmation': token})
        self.assertEqual((result['appid'], result['method']), (620, 'steam'))
        self.assertEqual(self.remote.call_args_list, [mock.call('list'), mock.call('quit', '620', timeout=60)])
        self.remote.reset_mock()
        with self.assertRaisesRegex(ValueError, 'expired or unknown'):
            self.call('quit', {'appid': '620', 'confirmation': token})
        self.remote.assert_not_called()

    def test_rejection_and_changed_headset_never_quit(self):
        rejected = self.call('quit', {'appid': '620'})
        self.decide(rejected, False)
        with self.assertRaisesRegex(ValueError, 'expired or unknown'):
            self.call('quit', {'appid': '620', 'confirmation': rejected['confirmation']})
        changed = self.call('quit', {'appid': '620'})
        self.decide(changed)
        with mock.patch.object(server, 'agent_target', return_value={'id': 'other', 'name': 'Other Frame'}):
            with self.assertRaisesRegex(ValueError, 'needs approval'):
                self.call('quit', {'appid': '620', 'confirmation': changed['confirmation']})
        self.remote.assert_not_called()

    def test_failed_quit_does_not_reuse_approval(self):
        proposal = self.call('quit', {'appid': '620'})
        self.decide(proposal)
        self.remote.return_value = {'running': []}
        self.remote.side_effect = None
        with self.assertRaisesRegex(ValueError, "isn't running any more"):
            self.call('quit', {'appid': '620', 'confirmation': proposal['confirmation']})
        self.remote.assert_called_once_with('list')
        self.remote.reset_mock()
        with self.assertRaisesRegex(ValueError, 'expired or unknown'):
            self.call('quit', {'appid': '620', 'confirmation': proposal['confirmation']})
        self.remote.assert_not_called()

    def test_invalid_quit_inputs_fail_before_approval_or_remote_calls(self):
        for appid in ('', '620; reboot', '620\n', '12345678901', 620):
            with self.subTest(appid=appid), self.assertRaises(ValueError):
                self.call('quit', {'appid': appid})
        for name, args in [('quit', {'appid': '620', 'action': 'kill'}), ('running', {'appid': '620'})]:
            with self.assertRaises(ValueError):
                self.call(name, args)
        with self.assertRaises(ValueError):
            self.call('approve', {'confirmation': 'not-an-MCP-action'})
        self.assertEqual(agent.approvals.pending, {})
        self.remote.assert_not_called()


if __name__ == '__main__':
    unittest.main()
