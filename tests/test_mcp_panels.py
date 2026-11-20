"""MCP panel listing and approved focus through the actual loopback API.

The SSH boundary runs the existing panel helper against a private vrcmd fixture.
No real headset, input or process is used.
"""
import sandbox  # noqa: F401
from contextlib import ExitStack
import json
from pathlib import Path
import shlex
import sys
import threading
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'ui'))
import frame_agent as agent
import frame_mcp as mcp
import frame_panels as panels
import server

KEY = 'valve.steam.desktopgame.2000999031'
OTHER = 'valve.steam.desktop'
OVERLAYS = """---- OVERLAYS ----
'valve.steam.desktopgame.2000999031' -- 'Notes <untrusted app title>', not_visible VROverlayType_Dashboard_Main
'valve.steam.desktop' -- 'Desktop', visible VROverlayType_Dashboard_Main
"""


class PanelTools(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.stack.enter_context(mock.patch.object(agent, 'approvals', agent.Approvals()))
        self.stack.enter_context(mock.patch.object(server, 'LINK', None))
        self.stack.enter_context(mock.patch.object(server.Handler, 'log_message'))
        self.overlays = OVERLAYS
        self.commands = []

        def vrcmd(args):
            self.commands.append(args)
            if args == [panels.VRCMD, '--overlays']:
                return self.overlays
            self.assertEqual(args[:2], [panels.VRCMD, '--showdashboard'])
            return ''  # dispatch acknowledgement, not proof of final focus

        def ssh(command, *, stdin, timeout, retry):
            self.assertEqual(stdin, Path(panels.__file__).read_text())
            self.assertEqual(timeout, 45)
            try:
                if command == 'python3 -':
                    self.assertTrue(retry)
                    return json.dumps(panels.state())
                self.assertFalse(retry)
                self.assertEqual(shlex.split(command)[:3], ['python3', '-', '--focus'])
                return json.dumps(panels.focus(shlex.split(command)[3]))
            except panels.PanelError as error:
                return json.dumps({'error': str(error)})

        self.stack.enter_context(mock.patch.object(panels, 'run', side_effect=vrcmd))
        self.remote = self.stack.enter_context(mock.patch.object(server, 'ssh', side_effect=ssh))
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
        # A separate HTTP request simulates the human page in this private fixture.
        self.client.request('/api/agent/approval', {
            'confirmation': proposal['confirmation'], 'accept': accept})

    def test_panels_observes_existing_keys_and_titles_without_approval(self):
        result = self.call('panels', {})
        self.assertEqual(result, {'panels': [
            {'key': KEY, 'title': 'Notes <untrusted app title>', 'visible': False},
            {'key': OTHER, 'title': 'Desktop', 'visible': True}]})
        self.assertEqual(self.commands, [[panels.VRCMD, '--overlays']])
        self.assertEqual(agent.approvals.pending, {})
        spec = next(t for t in mcp.TOOLS if t['name'] == 'panels')
        self.assertTrue(spec['annotations']['readOnlyHint'])
        self.assertFalse(spec['annotations']['destructiveHint'])

    def test_focus_binds_exact_key_and_target_and_consumes_one_approval(self):
        proposal = self.call('focus_panel', {'key': KEY})
        token = proposal['confirmation']
        self.assertEqual(proposal['action']['arguments'], {'key': KEY})
        self.assertIn('/assistant#confirm=', proposal['approvalUrl'])
        reviewed = self.client.request('/api/agent/approval?confirmation=' + token)
        self.assertEqual(reviewed['action'], proposal['action'])
        with self.assertRaisesRegex(ValueError, 'needs approval'):
            self.call('focus_panel', {'key': KEY, 'confirmation': token})
        self.decide(proposal)
        with self.assertRaisesRegex(ValueError, 'needs approval'):
            self.call('focus_panel', {'key': OTHER, 'confirmation': token})
        with mock.patch.object(server, 'agent_target', return_value={'id': 'other', 'name': 'Other Frame'}):
            with self.assertRaisesRegex(ValueError, 'needs approval'):
                self.call('focus_panel', {'key': KEY, 'confirmation': token})
        self.remote.assert_not_called()
        result = self.call('focus_panel', {'key': KEY, 'confirmation': token})
        self.assertEqual(result, {'requested': KEY, 'message': 'Asked SteamVR to show the panel.'})
        self.assertEqual(self.commands, [[panels.VRCMD, '--overlays'],
                                         [panels.VRCMD, '--showdashboard', KEY]])
        self.remote.reset_mock()
        with self.assertRaisesRegex(ValueError, 'expired or unknown'):
            self.call('focus_panel', {'key': KEY, 'confirmation': token})
        self.remote.assert_not_called()

    def test_closed_panel_refuses_dispatch_and_still_consumes_approval(self):
        proposal = self.call('focus_panel', {'key': KEY})
        self.decide(proposal)
        self.overlays = '---- OVERLAYS ----'
        with self.assertRaisesRegex(ValueError, 'panel has closed'):
            self.call('focus_panel', {'key': KEY, 'confirmation': proposal['confirmation']})
        self.assertEqual(self.commands, [[panels.VRCMD, '--overlays']])
        self.remote.reset_mock()
        with self.assertRaisesRegex(ValueError, 'expired or unknown'):
            self.call('focus_panel', {'key': KEY, 'confirmation': proposal['confirmation']})
        self.remote.assert_not_called()

    def test_rejected_and_expired_approvals_never_reach_the_headset(self):
        rejected = self.call('focus_panel', {'key': KEY})
        self.decide(rejected, False)
        with self.assertRaisesRegex(ValueError, 'expired or unknown'):
            self.call('focus_panel', {'key': KEY, 'confirmation': rejected['confirmation']})
        expired = self.call('focus_panel', {'key': KEY})
        self.decide(expired)
        agent.approvals.pending[expired['confirmation']]['expires'] = 0
        with self.assertRaisesRegex(ValueError, 'expired or unknown'):
            self.call('focus_panel', {'key': KEY, 'confirmation': expired['confirmation']})
        self.remote.assert_not_called()

    def test_invalid_keys_and_extra_arguments_fail_before_approval_or_ssh(self):
        for key in ('', 'a'*201, KEY+'\n', KEY+';reboot', 42):
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.call('focus_panel', {'key': key})
        for name, args in [('focus_panel', {'key': KEY, 'action': 'open'}),
                           ('panels', {'action': 'focus'}), ('panels', {'confirmation': 'token'}),
                           ('approve', {'confirmation': 'token'})]:
            with self.subTest(name=name, args=args), self.assertRaises(ValueError):
                self.call(name, args)
        self.assertEqual(agent.approvals.pending, {})
        self.remote.assert_not_called()


if __name__ == '__main__':
    unittest.main()
