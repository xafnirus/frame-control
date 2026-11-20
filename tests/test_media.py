"""Owned media planning, eye isolation, decoder choice and fake-Frame ownership."""
import sandbox  # noqa: F401  (first: keeps tests off real data and services)
import argparse
import io
import json
import os
import signal
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'ui'))
import frame_media as media
import frame_media_player as player
import frame_media_remote as remote
import frame_splat as splat
import server


def stop_now():
    """What systemd's SIGTERM does to the player, without signalling the test process."""
    handler = signal.getsignal(signal.SIGTERM)
    if callable(handler):
        handler(signal.SIGTERM, None)


class Media(unittest.TestCase):
    def test_layout_evidence_and_override(self):
        for name, layout in [('film_SBS.mp4', 'sbs'), ('film.OU.mkv', 'ou'),
                             ('film_FSBS.mp4', 'full-sbs'), ('photo_TB.png', 'ou')]:
            self.assertEqual(media.plan(name)['layout'], layout)
        self.assertEqual(media.plan('film_SBS_OU.mp4', 'mono')['source'], 'explicit')
        self.assertEqual(media.plan('film.mkv', metadata={'stereo_mode': 'top_bottom'})['layout'], 'full-ou')
        for name in ('film.mp4', 'film_SBS_OU.mp4', 'businessbs.mp4'):
            with self.assertRaises(ValueError):
                media.plan(name)
        with self.assertRaises(ValueError):
            media.plan('film.mkv', metadata={'stereo_mode': 'checkerboard_rl'})

    def test_right_first_layout_selection_and_aspect(self):
        for mode, layout in [('right_left', 'full-sbs-rl'), ('bottom_top', 'full-ou-rl')]:
            with self.subTest(mode=mode):
                self.assertEqual(media.plan('film.mkv', metadata={'stereo_mode': mode}),
                                 {'kind': 'video', 'layout': layout, 'source': 'metadata'})
                self.assertEqual(media.plan('film.mkv', 'mono', {'stereo_mode': mode})['layout'], 'mono')
        for layout, aspect in [('sbs-rl', 2), ('ou-rl', .5), ('full-sbs-rl', 1), ('full-ou-rl', 1)]:
            with self.subTest(layout=layout):
                self.assertEqual(media.plan('photo.png', layout)['layout'], layout)
                self.assertEqual(media.geometry(1920, 1080, layout), (1920, 1080, aspect))
        for name in ('photo_RL.png', 'photo_SBS_RL.png', 'photo_BT.png', 'photo_OU_BT.png'):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'explicit'):
                media.plan(name)

    def test_right_first_pixels_normalize_each_eye_without_mirroring(self):
        # Asymmetric pixels and two rows distinguish swapping eyes from mirroring or flipping.
        def pixel(value):
            return bytes([value, 0, 0, 255])
        left = [pixel(1)+pixel(2), pixel(3)+pixel(4)]
        right = [pixel(5)+pixel(6), pixel(7)+pixel(8)]
        expected = b''.join(l+r for l, r in zip(left, right))
        for layout in ('sbs-rl', 'full-sbs-rl'):
            source = b''.join(r+l for l, r in zip(left, right))
            self.assertEqual(media.stereo_pixels(source, 4, 2, layout), (expected, 4, 2))
        for layout in ('ou-rl', 'full-ou-rl'):
            source = b''.join(right+left)
            self.assertEqual(media.stereo_pixels(source, 2, 4, layout), (expected, 4, 2))
        for width, height, layout in [(3, 2, 'sbs-rl'), (2, 3, 'ou-rl')]:
            with self.subTest(layout=layout), self.assertRaises(ValueError):
                media.stereo_pixels(bytes(width*height*4), width, height, layout)

    def test_unsupported_containers_do_not_flatten_spatial_photos(self):
        for name in ('spatial.HEIC', 'stereo.mpo', 'cloud.ply', 'cloud.spz', 'app.exe'):
            with self.assertRaises(ValueError):
                media.plan(name, 'sbs')

    def test_ou_pixels_keep_each_eye_and_row(self):
        a, b, c, d = [bytes([n])*8 for n in (1, 2, 3, 4)]
        data, width, height = media.stereo_pixels(a+b+c+d, 2, 4, 'ou')
        self.assertEqual((data, width, height), (a+c+b+d, 4, 2))
        with self.assertRaises(ValueError):
            media.stereo_pixels(b'bad', 2, 4, 'sbs')
        self.assertEqual(media.geometry(3840, 2160, 'sbs'), (1920, 1080, 2))
        self.assertEqual(media.geometry(1920, 1080, 'ou'), (1920, 1080, .5))

    def test_pixel_aspect_preserves_per_eye_shape_after_bounded_scaling(self):
        for layout, eye_factor in [('mono', 1), ('sbs', 1), ('ou', 1),
                                   ('full-sbs', .5), ('full-ou', 2),
                                   ('sbs-rl', 1), ('ou-rl', 1),
                                   ('full-sbs-rl', .5), ('full-ou-rl', 2)]:
            for width, height in [(720, 576), (3840, 2160), (1919, 1079)]:
                with self.subTest(layout=layout, dimensions=(width, height)):
                    w, h, aspect = media.geometry(width, height, layout, '64:45')
                    self.assertLessEqual(w, 1920)
                    self.assertLessEqual(h, 1080)
                    if layout.removesuffix('-rl') in ('ou', 'full-ou'):
                        eye_width, eye_height = w, h/2
                    else:
                        eye_width, eye_height = (w if layout == 'mono' else w/2), h
                    self.assertAlmostEqual(eye_width/eye_height*aspect,
                                           width/height*64/45*eye_factor)

    def test_unknown_pixel_aspect_defaults_to_square_and_invalid_ratios_fail(self):
        for ratio in (None, '', 'N/A', '0:1', '1:1'):
            with self.subTest(ratio=ratio):
                self.assertEqual(media.geometry(1920, 1080, 'sbs', ratio), (1920, 1080, 2))
        for ratio in ('1:0', '0:0', '-1:1', '1:-1', 'nan', 'inf', '1:2:3', 2):
            with self.subTest(ratio=ratio), self.assertRaisesRegex(ValueError, 'pixel aspect'):
                media.geometry(1920, 1080, 'mono', ratio)

    def test_decode_is_hardware_and_one_clock_for_audio(self):
        for codec, decoder in [('h264', 'h264_v4l2m2m'), ('hevc', 'hevc_v4l2m2m')]:
            cmd = player.decoder_command(Path('/tmp/a file.mp4'), {'index': 0, 'codec_name': codec}, 1280, 720, {'index': 1})
            self.assertIn(decoder, cmd)
            self.assertIn('-re', cmd)
            self.assertIn('pulse', cmd)
            self.assertIn(str(Path('/tmp/a file.mp4')), cmd)
        with self.assertRaises(ValueError):
            player.decoder_command(Path('x.webm'), {'index': 0, 'codec_name': 'vp9'}, 640, 480, None)
        cmd = player.decoder_command(Path('x.png'), {'index': 0, 'codec_name': 'png'}, 640, 480, None, True)
        self.assertNotIn('-re', cmd)
        self.assertIn('-frames:v', cmd)

    def test_movie_uses_default_video_instead_of_earlier_preview_or_cover(self):
        # Shape observed from a generated MKV: an MJPEG preview precedes its
        # default H.264 movie. An attached cover must never win either.
        preview = dict(index=0, codec_type='video', codec_name='mjpeg',
                       width=32, height=24, disposition={'default': 0})
        movie = dict(index=2, codec_type='video', codec_name='h264',
                     width=64, height=48, disposition={'default': 1})
        cover = dict(preview, index=3, disposition={'default': 1, 'attached_pic': 1})
        audio = dict(index=1, codec_type='audio', codec_name='aac')
        for streams in ([preview, audio, movie], [cover, audio, movie]):
            with self.subTest(streams=streams), patch.object(player.subprocess, 'run',
                    return_value=unittest.mock.Mock(returncode=0, stdout=json.dumps({'streams': streams}))):
                info, selected_audio = player.probe(Path('movie.mkv'))
                self.assertEqual(info, movie)
                self.assertEqual(selected_audio, audio)
                cmd = player.decoder_command(Path('movie.mkv'), info, 64, 48, selected_audio)
                self.assertEqual(cmd[cmd.index('-map')+1], '0:2')
                self.assertEqual(cmd[cmd.index('-c:2')+1], 'h264_v4l2m2m')
                self.assertIn('0:1', cmd)

    def test_movie_audio_follows_default_track_and_falls_back_to_first(self):
        video = dict(index=1, codec_type='video', codec_name='h264', width=64, height=48)
        first = dict(index=0, codec_type='audio', codec_name='aac', disposition={'default': 0})
        preferred = dict(first, index=2, disposition={'default': 1})
        later_default = dict(preferred, index=3)
        for streams, expected in [([first, video, preferred, later_default], preferred),
                                  ([first, video], first),
                                  ([video], None)]:
            with self.subTest(streams=streams), patch.object(player.subprocess, 'run',
                    return_value=unittest.mock.Mock(returncode=0, stdout=json.dumps({'streams': streams}))):
                info, audio = player.probe(Path('movie.mkv'))
                self.assertEqual(audio, expected)
                cmd = player.decoder_command(Path('movie.mkv'), info, 64, 48, audio)
                maps = [cmd[i+1] for i, v in enumerate(cmd) if v == '-map']
                self.assertEqual(maps, ['0:1'] + ([] if expected is None else ['0:%s' % expected['index']]))
                self.assertEqual('pulse' in cmd, expected is not None)
                # Photos never start audio, even if their container includes it.
                photo = player.decoder_command(Path('photo.png'), info, 64, 48, audio, photo=True)
                self.assertNotIn('pulse', photo)

    def test_probe_falls_back_to_first_video_and_keeps_standalone_photos(self):
        first = dict(index=1, codec_type='video', codec_name='png', width=4, height=2)
        second = dict(first, index=2)
        cover = dict(first, index=0, disposition={'attached_pic': 1})
        for streams in ([first], [cover, first, second]):
            with self.subTest(streams=streams), patch.object(player.subprocess, 'run',
                    return_value=unittest.mock.Mock(returncode=0, stdout=json.dumps({'streams': streams}))):
                info, audio = player.probe(Path('photo.png'))
                self.assertEqual(info, first)
                self.assertFalse(audio)
                cmd = player.decoder_command(Path('photo.png'), info, 4, 2, audio, photo=True)
                self.assertEqual(cmd[cmd.index('-map')+1], '0:1')
        with patch.object(player.subprocess, 'run', return_value=unittest.mock.Mock(
                returncode=0, stdout=json.dumps({'streams': [cover]}))):
            with self.assertRaisesRegex(ValueError, 'No image or video stream'):
                player.probe(Path('artwork.mp4'))

    def test_rotated_mono_uses_display_dimensions_and_reciprocal_pixel_aspect(self):
        for rotation in (90, -90, 270, 450):
            with self.subTest(rotation=rotation):
                created = []
                info = {'codec_name': 'h264', 'width': 4, 'height': 2,
                        'sample_aspect_ratio': '2:1',
                        'tags': {'rotate': '180'},  # matrix takes precedence over stale tags
                        'side_data_list': [{'side_data_type': 'Display Matrix', 'rotation': rotation}]}
                result, calls = self.play_with('portrait.mp4', info=info, layout='mono',
                                              on_create=lambda *a, **k: created.append(a))
                self.assertEqual(result['state'], 'ended')
                self.assertEqual(calls[-1], (1, 2, 4))
                self.assertEqual(created[-1][-1], .5)
        # A half turn keeps both dimensions and pixel shape.
        created = []
        self.play_with('portrait.mp4', info={**info, 'side_data_list': [], 'tags': {'rotate': '180'}},
                       layout='mono', on_create=lambda *a, **k: created.append(a))
        self.assertEqual(created[-1][-1], 2)

    def test_rotated_stereo_and_invalid_rotation_fail_before_openvr(self):
        def unexpected_overlay(*a, **k):
            self.fail('Invalid orientation reached OpenVR')
        for layout in media.LAYOUTS[2:]:
            with self.subTest(layout=layout), self.assertRaisesRegex(ValueError, 'rotated stereo'):
                self.play_with('stereo.mp4', layout=layout, on_create=unexpected_overlay,
                               info={'codec_name': 'h264', 'width': 4, 'height': 2,
                                     'side_data_list': [{'side_data_type': 'Display Matrix', 'rotation': 90}]})
        for rotation in (45, 'nan', 'inf', 'bad', None, True):
            with self.subTest(rotation=rotation), self.assertRaisesRegex(ValueError, 'rotation'):
                self.play_with('portrait.mp4', layout='mono', on_create=unexpected_overlay,
                               info={'codec_name': 'h264', 'width': 4, 'height': 2,
                                     'side_data_list': [{'side_data_type': 'Display Matrix', 'rotation': rotation}]})

    def play_with(self, name, busy=0, on_pixels=None, sleeps=None, info=None,
                  fail=None, layout='auto', on_create=None, on_call=None, frame=None, on_frame=None):
        """Run the player against a fake OpenVR; returns (status, pixels calls).

        Handle 0 is the theatre surround and 1 the screen. `fail(handle, n)` makes
        the n-th upload busy; every status written is kept in self.writes."""
        calls = []
        self.writes = []
        write_status = player.write_status

        def record(path, **values):
            self.writes.append(values)
            write_status(path, **values)

        class FakeOverlay:
            created = 0

            def create(self, *a, **k):
                # Handles in creation order: surround 0, then screen 1 (theatre).
                FakeOverlay.created += 1
                if on_create:
                    on_create(*a, **k)
                return FakeOverlay.created - 1

            def call(self, *a):
                if on_call:
                    on_call(*a)

            def pixels(self, handle, data, w, h):
                calls.append((handle, w, h))
                if on_frame:
                    on_frame(handle, data, w, h)
                if on_pixels:
                    on_pixels(len(calls))
                if len(calls) <= busy or (fail and fail(handle, len(calls))):
                    raise player.OverlayBusy('standby')

            def close(self):
                # A Stop landing during cleanup must be ignored, not become an error.
                # Call the installed handler directly: a real SIGTERM kills Windows.
                stop_now()

        frame = bytes(4*2*4) if frame is None else frame
        proc = unittest.mock.MagicMock()
        proc.stdout = io.BytesIO(frame*4)
        proc.wait.return_value = 0
        proc.poll.return_value = 0
        old = signal.getsignal(signal.SIGTERM), signal.getsignal(signal.SIGINT)
        with tempfile.TemporaryDirectory() as d, \
                patch.object(player, 'Overlay', FakeOverlay), \
                patch.object(player, 'probe', return_value=(dict(index=0, **(info or
                    {'codec_name': 'h264', 'width': 4, 'height': 2})), None)), \
                patch.object(player.subprocess, 'Popen', return_value=proc), \
                patch.object(player, 'write_status', side_effect=record), \
                patch.object(player.frame_splat, 'render', return_value=(bytes(4*4*2), 4, 2)), \
                patch.object(player.time, 'sleep', side_effect=sleeps):
            path = Path(d)/name
            path.write_bytes(b'x')
            status = Path(d)/'status.json'
            try:
                player.play(argparse.Namespace(file=str(path), layout=layout, theatre=True, status=str(status)))
            finally:
                signal.signal(signal.SIGTERM, old[0])
                signal.signal(signal.SIGINT, old[1])
            return json.loads(status.read_text()), calls

    def test_video_survives_standby_and_stop_after_end_stays_ended(self):
        # Verified 2026-09-29: an unworn Frame enters standby within seconds and
        # SetOverlayRaw then returns RequestFailed (23) until it wakes.
        result, calls = self.play_with('clip_SBS.mp4', busy=3)
        self.assertEqual((result['state'], result['frames']), ('ended', 4))
        # Two video frames were dropped; the surround (handle 0) waited and was re-sent.
        self.assertEqual(result['dropped'], 2)
        self.assertIn((0, 1, 1), calls[3:])

    def test_theatre_surround_failure_does_not_stop_playback(self):
        def fail_surround(n):
            if n == 1:  # the surround's upload is the first pixels call
                raise RuntimeError('OpenVR SetOverlayRaw failed: 11')
        result, _ = self.play_with('clip_SBS.mp4', on_pixels=fail_surround)
        self.assertEqual((result['state'], result['frames']), ('ended', 4))

    def test_theatre_surround_creation_and_setup_failures_are_cosmetic(self):
        def fail_create(key, *a, **k):
            if key.endswith('.surround'):
                raise RuntimeError('OpenVR CreateOverlay failed: 11')
        def fail_alpha(name, *a):
            if name == 'SetOverlayAlpha':
                raise RuntimeError('OpenVR SetOverlayAlpha failed: 11')
        for hooks in ({'on_create': fail_create}, {'on_call': fail_alpha}):
            with self.subTest(hooks=hooks), patch('builtins.print') as log:
                result, calls = self.play_with('clip_SBS.mp4', **hooks)
            self.assertEqual((result['state'], result['frames']), ('ended', 4))
            self.assertEqual(sum(h == 1 for h, w, hgt in calls), 4)
            self.assertIn('Theatre surround unavailable:', log.call_args.args[0])

    def test_theatre_surround_refusal_after_standby_is_not_retried(self):
        def refuse_retry(n):
            if n == 3:  # surround busy, screen accepted, surround retry refused
                raise RuntimeError('OpenVR SetOverlayRaw failed: 11')
        with patch('builtins.print') as log:
            result, calls = self.play_with('clip_SBS.mp4', busy=1, on_pixels=refuse_retry)
        self.assertEqual((result['state'], result['frames'], result['dropped']), ('ended', 4, 0))
        self.assertEqual(sum(h == 0 for h, w, hgt in calls), 2)
        self.assertIn('Theatre surround unavailable:', log.call_args.args[0])

    def test_screen_refusal_still_fails_playback(self):
        def refuse_screen(n):
            if n == 2:
                raise RuntimeError('OpenVR SetOverlayRaw failed: 11')
        with self.assertRaisesRegex(RuntimeError, 'SetOverlayRaw failed: 11'):
            self.play_with('clip_SBS.mp4', on_pixels=refuse_screen)

    def test_close_attempts_every_overlay_and_shuts_down_after_teardown_errors(self):
        for error in (RuntimeError('OpenVR error'), ValueError('bad handle'),
                      InterruptedError('late Stop')):
            with self.subTest(error=type(error).__name__):
                overlay = player.Overlay.__new__(player.Overlay)
                overlay.handles = [10, 20]
                overlay.vr = unittest.mock.Mock()
                overlay.call = unittest.mock.Mock(side_effect=[error, None])
                overlay.close()
                self.assertEqual(overlay.call.call_args_list, [
                    unittest.mock.call('DestroyOverlay', 20),
                    unittest.mock.call('DestroyOverlay', 10)])
                overlay.vr.VR_ShutdownInternal.assert_called_once_with()

    def test_stop_mid_video_reports_stopped(self):
        result, _ = self.play_with('clip_SBS.mp4', on_pixels=lambda n: n == 3 and stop_now())
        self.assertEqual(result['state'], 'stopped')

    def test_video_errors_when_steamvr_never_takes_frames(self):
        with patch.object(player, 'BUSY_LIMIT', -1), \
                self.assertRaisesRegex(RuntimeError, 'stopped accepting frames'):
            self.play_with('clip_SBS.mp4', busy=99)

    def test_still_waits_out_standby_without_a_limit(self):
        # Stills have no timeline: keep retrying (here past BUSY_LIMIT) until shown.
        ticks = iter(range(10))
        def sleep(_):
            if next(ticks) == 8:
                stop_now()
        with patch.object(player, 'BUSY_LIMIT', -1):
            result, calls = self.play_with('photo_SBS.png', busy=5, sleeps=sleep,
                                           info={'codec_name': 'png', 'width': 4, 'height': 2})
        self.assertEqual(result['state'], 'stopped')
        screen = [c for c in calls if c[0] == 1]
        self.assertGreater(len(screen), 1)  # retried through standby
        self.assertEqual(calls[-1], (0, 1, 1))  # surround drained once the screen took a frame

    def still_with_late_surround(self, name, **kw):
        # The screen takes its first frame while the surround is still refused
        # (its first upload, the drain right after the screen, and one retry).
        ticks = iter(range(10))
        def sleep(_):
            if next(ticks) == 5:
                stop_now()
        surround_tries = []
        def fail(handle, n):
            if handle == 0:
                surround_tries.append(n)
                return len(surround_tries) <= 3
            return False
        result, calls = self.play_with(name, sleeps=sleep, fail=fail, **kw)
        self.assertEqual(result['state'], 'stopped')
        screen = [c for c in calls if c[0] == 1]
        surround = [c for c in calls if c[0] == 0]
        self.assertEqual(len(screen), 1)  # shown once, not re-sent every second
        self.assertEqual(len(surround), 4)  # kept retrying after the screen, until it took
        self.assertEqual(calls[-1][0], 0)
        return calls

    def test_photo_surround_recovers_after_screen_is_shown(self):
        self.still_with_late_surround('photo_SBS.png',
                                      info={'codec_name': 'png', 'width': 4, 'height': 2})

    def test_splat_surround_recovers_after_screen_is_shown(self):
        self.still_with_late_surround('scene.splat')

    def test_video_standby_limit_is_five_minutes_without_an_accepted_frame(self):
        self.assertEqual(player.BUSY_LIMIT, 300)
        def run(times, busy):
            # Upload n happens at times[n] seconds on a fake clock; 1 is the surround.
            clock = [1000.0]
            def on_pixels(n):
                clock[0] = 1000.0 + times.get(n, times[max(times)])
            with patch.object(player.time, 'monotonic', side_effect=lambda: clock[0]):
                return self.play_with('clip_SBS.mp4', on_pixels=on_pixels,
                                      fail=lambda h, n: h == 1 and n in busy)
        # Busy for 299 s, then a frame lands: no error.
        result, _ = run({1: 0, 2: 0, 3: 299, 4: 299, 5: 299}, busy={2, 3})
        self.assertEqual((result['state'], result['dropped']), ('ended', 2))
        # An accepted frame resets the timer: 600 s busy in total, never 300 s in a row.
        result, _ = run({1: 0, 2: 0, 3: 200, 4: 250, 5: 450}, busy={2, 3, 5})
        self.assertEqual((result['state'], result['dropped']), ('ended', 3))
        # 301 s in a row without an accepted frame is an error.
        with self.assertRaisesRegex(RuntimeError, 'stopped accepting frames for 300 s'):
            run({1: 0, 2: 0, 3: 301}, busy={2, 3, 4, 5})

    def test_status_reports_where_the_layout_came_from(self):
        video = {'codec_name': 'h264', 'width': 4, 'height': 2}
        for name, layout, tags, expect in [
                ('clip_SBS.mp4', 'auto', None, ('sbs', 'filename')),
                ('clip.mkv', 'auto', {'stereo_mode': 'left_right'}, ('full-sbs', 'metadata')),
                ('clip.mkv', 'auto', {'stereo_mode': 'right_left'}, ('full-sbs-rl', 'metadata')),
                ('clip.mkv', 'auto', {'stereo_mode': 'bottom_top'}, ('full-ou-rl', 'metadata')),
                ('clip_OU.mp4', 'sbs-rl', None, ('sbs-rl', 'explicit')),
                ('clip_OU.mp4', 'sbs', None, ('sbs', 'explicit')),
                ('clip.mkv', 'mono', {'stereo_mode': 'left_right'}, ('mono', 'explicit'))]:
            with self.subTest(name=name, layout=layout):
                self.play_with(name, layout=layout, info=dict(video, tags=tags) if tags else video)
                playing = self.writes[0]
                self.assertEqual(playing['state'], 'playing')
                self.assertEqual((playing['layout'], playing['source']), expect)

    def test_player_submits_normalized_right_first_frames(self):
        left, right = bytes([10, 20, 30, 255])*2, bytes([40, 50, 60, 255])*2
        expected = (left+right)*2
        for layout in ('sbs-rl', 'full-sbs-rl', 'ou-rl', 'full-ou-rl'):
            packed_sbs = layout.startswith(('sbs', 'full-sbs'))
            source = (right+left)*2 if packed_sbs else right*2+left*2
            submitted, created = [], []
            with self.subTest(layout=layout):
                result, _ = self.play_with('clip.mp4', layout=layout, frame=source,
                    info={'codec_name': 'h264', 'width': 4 if packed_sbs else 2,
                          'height': 2 if packed_sbs else 4},
                    on_frame=lambda handle, data, w, h: submitted.append((data, w, h)) if handle == 1 else None,
                    on_create=lambda *args, **kw: created.append(args))
                self.assertEqual(result['state'], 'ended')
                self.assertEqual(submitted, [(expected, 4, 2)]*4)
                self.assertTrue(created[1][3])  # the owned screen is stereoscopic
                self.assertEqual(created[1][4], 1 if layout.startswith('full') else (2 if packed_sbs else .5))

    def test_player_uses_probed_pixel_aspect_for_the_screen(self):
        created = []
        result, _ = self.play_with('clip.mp4', layout='full-sbs-rl',
            info={'codec_name': 'h264', 'width': 4, 'height': 2, 'sample_aspect_ratio': '16:15'},
            on_create=lambda *args, **kw: created.append(args))
        self.assertEqual(result['state'], 'ended')
        self.assertAlmostEqual(created[1][4], 16/15)

    def test_fake_frame_library_and_traversal(self):
        with tempfile.TemporaryDirectory() as d, patch.object(remote, 'ROOT', Path(d)):
            identity = 'a'*32+'/space and quote\'.png'
            path = Path(d)/identity
            path.parent.mkdir()
            path.write_bytes(b'test')
            self.assertEqual(remote.media_path(identity), path.resolve())
            for bad in ('../../etc/passwd', '/etc/passwd', 'a'*32+'/..', 'a'*32+'/x/y', None):
                with self.assertRaises((ValueError, FileNotFoundError)):
                    remote.media_path(bad)
            link = path.parent/'link.png'
            link.symlink_to(path)
            with self.assertRaises(ValueError):
                remote.media_path('a'*32+'/link.png')
            with patch.object(remote, 'status', return_value={'state': 'idle'}):
                files = remote.run({'action': 'list'})['files']
                self.assertEqual([f['id'] for f in files], [identity])

    def test_server_rejects_bad_actions_before_ssh(self):
        with patch.object(server, 'ssh') as ssh:
            for body in ({'action': 'delete'}, {'action': 'play', 'id': '../x'},
                         {'action': 'play', 'id': 'a'*32+'/x', 'layout': 'invalid'},
                         {'action': 'play', 'id': 'a'*32+'/x', 'theatre': 'false'}):
                with self.assertRaises(server.Failure):
                    server.media(body)
            ssh.assert_not_called()

    def test_server_forwards_right_first_layouts_to_owned_runtime(self):
        for layout in ('sbs-rl', 'ou-rl', 'full-sbs-rl', 'full-ou-rl'):
            body = {'action': 'play', 'id': 'a'*32+'/photo.png', 'layout': layout}
            with self.subTest(layout=layout), patch.object(server, 'ssh', side_effect=['', '{}']) as ssh:
                server.media(body)
                self.assertEqual(json.loads(ssh.call_args.kwargs['stdin']), body)

    def test_fake_frame_stop_only_owns_our_unit(self):
        for rc in (0, 5):  # 5: already collected ("not loaded"), a no-op
            with patch.object(remote.subprocess, 'run') as run, patch.object(remote, 'status', return_value={'state': 'ended'}):
                run.return_value.returncode = rc
                self.assertEqual(remote.run({'action': 'stop'})['state'], 'ended')
                self.assertEqual(run.call_args.args[0], ['systemctl', '--user', 'stop', 'frame-control-media.service'])
        with patch.object(remote.subprocess, 'run') as run, patch.object(remote, 'status', return_value={}):
            run.return_value.returncode, run.return_value.stderr = 1, 'Access denied'
            with self.assertRaisesRegex(RuntimeError, 'Access denied'):
                remote.run({'action': 'stop'})

    def test_start_failure_reports_systemd_error(self):
        with tempfile.TemporaryDirectory() as d, patch.object(remote, 'ROOT', Path(d)), \
                patch.object(remote, 'STATUS', Path(d)/'status.json'), \
                patch.object(remote, 'active', return_value=False), \
                patch.object(remote.subprocess, 'run') as run:
            identity = 'b'*32+'/still_SBS.png'
            (Path(d)/identity).parent.mkdir()
            (Path(d)/identity).write_bytes(b'x')
            run.return_value.returncode, run.return_value.stderr = 1, 'Unit already exists'
            with patch.object(remote, 'probe', return_value=({}, False)), \
                    self.assertRaisesRegex(RuntimeError, 'Unit already exists'):
                remote.run({'action': 'play', 'id': identity})
            self.assertEqual(run.call_args.args[0][0], 'systemd-run')  # reset-failed's result is ignored

    def test_upload_rejects_unplayable_names_and_keeps_copy_error(self):
        with patch.object(server, 'ssh') as ssh, patch.object(server, 'push_file') as push:
            # On Windows a backslash is a separator, so such a name can't reach here.
            for name in ('.hidden.mp4',) + (('a\\b_SBS.mp4',) if os.sep == '/' else ()):
                with self.assertRaises(server.Failure):
                    server.push_media(Path('/tmp')/name)
            ssh.assert_not_called()
            push.side_effect = server.Failure('copy failed')
            ssh.side_effect = [None, server.Failure('link down')]
            with self.assertRaisesRegex(server.Failure, 'copy failed'):
                server.push_media(Path('/tmp/film_SBS.mp4'))

    def test_splat_invalid_records_and_stereo_parallax(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/'small.splat'
            path.write_bytes(struct.pack('<6f8B', 0, 0, 0, .001, .001, .001,
                                         255, 0, 0, 255, 255, 128, 128, 128))
            data, w, h = splat.render(path, 64, 48)
            self.assertEqual((len(data), w, h), (128*48*4, 128, 48))
            def centroid(eye):
                weights = [(x, data[(y*w+x+eye*64)*4]) for y in range(h) for x in range(64)]
                return sum(x*v for x,v in weights)/sum(v for x,v in weights)
            self.assertGreater(centroid(0), centroid(1))
            for bad in (b'', b'bad', struct.pack('<6f8B', float('nan'), 0, 0, 1, 1, 1, *([128]*8))):
                path.write_bytes(bad)
                with self.assertRaises(ValueError):
                    splat.read(path)


if __name__ == '__main__':
    unittest.main()
