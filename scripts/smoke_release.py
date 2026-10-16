"""Check a packaged player without Python/FFmpeg on PATH or an Arduino attached."""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile
import wave


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('executable', type=Path)
    args = parser.parse_args()
    executable = args.executable.resolve()
    with tempfile.TemporaryDirectory(prefix='player-smoke-') as directory:
        root = Path(directory)
        temp = root / 'temporary'
        temp.mkdir()
        audio_dir = root / '音乐 files'
        audio_dir.mkdir()
        source = audio_dir / '测试.wav'
        with wave.open(str(source), 'wb') as output:
            output.setparams((1, 1, 8000, 0, 'NONE', 'not compressed'))
            output.writeframes(bytes([128, 170, 200, 170, 128, 86, 56, 86]) * 1000)
        env = dict(os.environ)
        env.pop('IMAGEIO_FFMPEG_EXE', None)
        env['PATH'] = ''
        env.update(TMPDIR=str(temp), TMP=str(temp), TEMP=str(temp), PYTHONUTF8='1')
        for option in ['--help', '--version', '--ffmpeg-info']:
            subprocess.run([str(executable), option], cwd=root, env=env, check=True,
                           capture_output=True, timeout=30)
        # Force a serial-open failure AFTER actual bundled-FFmpeg conversion.
        port = 'COM9999' if os.name == 'nt' else '/dev/arduino-music-nonexistent'
        result = subprocess.run([
            str(executable), '--directory', str(audio_dir), '--port', port, '--semitones', '3',
        ], cwd=root, env=env, capture_output=True, text=True, encoding='utf-8', timeout=60)
        if result.returncode != 1 or '转换完成：' not in result.stdout or '失败：' not in result.stderr:
            raise RuntimeError(f'Packaged conversion/serial test failed:\n{result.stdout}\n{result.stderr}')
        if list(temp.iterdir()) or not source.is_file():
            raise RuntimeError('Temporary PCM cleanup or original-file preservation failed.')
    print('PASS: packaged CLI, bundled FFmpeg, Unicode paths, conversion and error cleanup.')


if __name__ == '__main__':
    main()
