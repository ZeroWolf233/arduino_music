import contextlib
import io
import math
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch
import wave

import imageio_ffmpeg
import serial
import main as player


def make_wav(path):
    with wave.open(str(path), 'wb') as output:
        output.setparams((1, 1, 8000, 0, 'NONE', 'not compressed'))
        output.writeframes(bytes(round(128 + 60 * math.sin(2 * math.pi * 440 * n / 8000)) for n in range(8000)))


class PlayerTests(unittest.TestCase):
    def test_discovery_prefers_originals_and_only_scans_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ['b.MP3', 'a.flac', 'a.pcm', 'notes.txt']:
                (root / name).touch()
            (root / 'nested').mkdir()
            (root / 'nested' / 'hidden.mp3').touch()
            self.assertEqual([p.name for p in player.find_audio_files(root)], ['a.flac', 'b.MP3'])
            self.assertEqual(player.find_audio_files(root, root / 'a.pcm'), [root / 'a.pcm'])

    def test_raw_pcm_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'song.PCM').touch()
            self.assertEqual(player.find_audio_files(root), [root / 'song.PCM'])

    def test_frozen_root_is_executable_directory(self):
        executable = Path(tempfile.gettempdir()) / 'player' / 'arduino-music.exe'
        with patch.object(player.sys, 'frozen', True, create=True), patch.object(player.sys, 'executable', str(executable)):
            self.assertEqual(player.application_root(), executable.parent.resolve())

    def test_auto_port_prefers_single_usb_device(self):
        ports = [SimpleNamespace(device='COM1', vid=None), SimpleNamespace(device='COM12', vid=0x1A86)]
        with patch.object(player.list_ports, 'comports', return_value=ports):
            self.assertEqual(player.resolve_port(), 'COM12')
            self.assertEqual(player.resolve_port('COM9'), 'COM9')

    def test_auto_port_rejects_ambiguous_or_missing_devices(self):
        ports = [SimpleNamespace(device='COM3', vid=1), SimpleNamespace(device='COM4', vid=2)]
        with patch.object(player.list_ports, 'comports', return_value=ports):
            with self.assertRaisesRegex(ValueError, '多个串口'):
                player.resolve_port()
        with patch.object(player.list_ports, 'comports', return_value=[]):
            with self.assertRaisesRegex(ValueError, '没有检测到串口'):
                player.resolve_port()

    def test_windows_and_posix_serial_options(self):
        self.assertNotIn('exclusive', player.serial_options('COM12', 'nt'))
        self.assertTrue(player.serial_options('/dev/ttyUSB0', 'posix')['exclusive'])

    def test_generated_pcm_removed_on_success_error_and_interrupt(self):
        for failure in [None, serial.SerialException('disconnected'), KeyboardInterrupt()]:
            with self.subTest(failure=type(failure).__name__), tempfile.TemporaryDirectory() as directory:
                source = Path(directory) / 'song.mp3'
                source.write_bytes(b'original')
                generated = []

                def convert(source, output_dir, volume, semitones):
                    pcm = output_dir / 'audio.pcm'
                    pcm.write_bytes(b'\x80' * 160)
                    generated.append(pcm)
                    return pcm

                with patch.object(player, 'convert_to_pcm', side_effect=convert), patch.object(player, 'play_pcm', side_effect=failure), contextlib.redirect_stdout(io.StringIO()):
                    if failure is None:
                        player.play_source(source, 'COM3', 0, 1, 0)
                    else:
                        with self.assertRaises(type(failure)):
                            player.play_source(source, 'COM3', 0, 1, 0)
                self.assertFalse(generated[0].parent.exists())
                self.assertEqual(source.read_bytes(), b'original')

    def test_partial_conversion_is_removed_on_failure(self):
        generated = []

        def convert(source, output_dir, volume, semitones):
            pcm = output_dir / 'audio.pcm'
            pcm.write_bytes(b'partial')
            generated.append(pcm)
            raise subprocess.CalledProcessError(1, ['ffmpeg'])

        with patch.object(player, 'convert_to_pcm', side_effect=convert):
            with self.assertRaises(subprocess.CalledProcessError):
                player.play_source(Path('invalid.mp3'), 'COM3', 0, 1, 0)
        self.assertFalse(generated[0].parent.exists())

    def test_input_pcm_is_never_deleted(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'original.pcm'
            source.write_bytes(b'\x80' * 160)
            with patch.object(player, 'play_pcm', side_effect=KeyboardInterrupt()):
                with self.assertRaises(KeyboardInterrupt):
                    player.play_source(source, 'COM3', 0, 1, 0)
            self.assertEqual(source.stat().st_size, 160)

    def test_serial_payload_and_partial_last_block(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'audio.pcm'
            data = bytes(range(256)) * 3
            path.write_bytes(data)
            port = MagicMock()
            port.__enter__.return_value = port
            port.write.side_effect = len
            with patch.object(player.serial, 'Serial', return_value=port), patch.object(player.time, 'sleep'), contextlib.redirect_stdout(io.StringIO()):
                player.play_pcm(path, 'COM12', 0.021)
            sent = b''.join(call.args[0] for call in port.write.call_args_list)
            self.assertEqual(sent, data[:168])
            port.__exit__.assert_called_once()

    def test_slow_windows_flush_does_not_pause_between_audio_blocks(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'audio.pcm'
            path.write_bytes(b'\x80' * 1600)
            clock = [0.0]
            writes = []

            def sleep(seconds):
                clock[0] += seconds

            def write(block):
                writes.append(clock[0])
                return len(block)

            port = MagicMock()
            port.__enter__.return_value = port
            port.write.side_effect = write
            port.flush.side_effect = lambda: sleep(0.05)
            with patch.object(player.serial, 'Serial', return_value=port), patch.object(player.time, 'sleep', side_effect=sleep), patch.object(player.time, 'monotonic', side_effect=lambda: clock[0]), contextlib.redirect_stdout(io.StringIO()):
                player.play_pcm(path, 'COM3', 0)
            self.assertEqual(len(writes), 20)
            self.assertLess(writes[-1] - writes[0], 0.22)


class ConversionTests(unittest.TestCase):
    def test_bundled_ffmpeg_and_pitch_without_system_path(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'PATH': '', 'IMAGEIO_FFMPEG_EXE': ''}):
            executable = Path(imageio_ffmpeg.get_ffmpeg_exe()).resolve()
            self.assertTrue(executable.is_relative_to(Path(imageio_ffmpeg.__file__).resolve().parent))
            source = Path(directory) / '测试 tone.wav'
            make_wav(source)
            for semitones in [-24, 0, 3, 24]:
                with self.subTest(semitones=semitones), contextlib.redirect_stdout(io.StringIO()):
                    pcm = player.convert_to_pcm(source, Path(directory) / str(semitones), 1, semitones)
                    data = pcm.read_bytes()
                    self.assertGreater(len(data), 5000)
                    self.assertLess(len(data), 10000)
                    self.assertLess(min(data), 128)
                    self.assertGreater(max(data), 128)
                    if semitones == 0:
                        self.assertEqual(len(data), 8000)

    def test_real_mp3_conversion(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'source.wav'
            make_wav(source)
            mp3 = root / 'music.mp3'
            subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), '-nostdin', '-v', 'error', '-i', str(source), str(mp3)], check=True)
            with contextlib.redirect_stdout(io.StringIO()):
                pcm = player.convert_to_pcm(mp3, root / 'converted', 1, 0)
            self.assertEqual(pcm.stat().st_size, 8000)


if __name__ == '__main__':
    unittest.main()
