"""Build a portable player with its Python runtime and bundled FFmpeg."""
import argparse
import importlib.metadata
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import sysconfig

import imageio_ffmpeg

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--platform', required=True, choices=['windows-x64', 'linux-x64'])
    parser.add_argument('--version', default=os.environ.get('RELEASE_TAG', 'dev'))
    args = parser.parse_args()
    if sys.platform not in {'win32', 'linux'} or platform.machine().lower() not in {'x86_64', 'amd64'}:
        parser.error('Release builds currently support Windows/Linux x64 only.')
    expected = 'windows-x64' if sys.platform == 'win32' else 'linux-x64'
    if args.platform != expected:
        parser.error('PyInstaller must run on the target operating system.')
    subprocess.run([
        sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir',
        '--name', 'arduino-music', '--collect-all', 'imageio_ffmpeg',
        '--distpath', str(ROOT / 'dist'), '--workpath', str(ROOT / 'build' / 'player'),
        '--specpath', str(ROOT / 'build'), str(ROOT / 'main.py'),
    ], cwd=ROOT, check=True, env={
        **os.environ, 'PYINSTALLER_CONFIG_DIR': str(ROOT / 'build' / 'pyinstaller-cache'),
    })
    bundle = ROOT / 'dist' / 'arduino-music'
    for name in ['README.md', 'LICENSE', 'THIRD_PARTY_NOTICES.md']:
        shutil.copy2(ROOT / name, bundle / name)
    (bundle / 'VERSION').write_text(args.version + '\n', encoding='utf-8')
    licenses = bundle / 'licenses'
    licenses.mkdir(exist_ok=True)
    # pySerial's wheel omits the full license text; keep the upstream notice in source.
    shutil.copytree(ROOT / 'licenses', licenses, dirs_exist_ok=True)
    python_license = next((path for path in [
        Path(sysconfig.get_path('stdlib')) / 'LICENSE.txt',
        Path(sys.base_prefix) / 'LICENSE.txt',
    ] if path.is_file()), None)
    if python_license is None:
        raise RuntimeError('Cannot locate the Python runtime LICENSE.txt for distribution.')
    shutil.copy2(python_license, licenses / 'PYTHON-LICENSE.txt')
    for name in ['pyserial', 'imageio-ffmpeg', 'pyinstaller']:
        package = importlib.metadata.distribution(name)
        for entry in package.files or []:
            if 'license' in Path(entry).name.lower() or 'copying' in Path(entry).name.lower():
                source = Path(package.locate_file(entry))
                if source.is_file():
                    target = licenses / name / source.name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
    for flag, name in [('-L', 'FFMPEG-LICENSE.txt'), ('-version', 'FFMPEG-BUILD.txt')]:
        result = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), flag], check=True,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        (licenses / name).write_bytes(result.stdout)
    release = ROOT / 'release'
    release.mkdir(exist_ok=True)
    archive_format = 'zip' if sys.platform == 'win32' else 'gztar'
    archive = shutil.make_archive(str(release / f'arduino-music-{args.platform}'),
                                  archive_format, root_dir=bundle.parent, base_dir=bundle.name)
    print(f'Created {archive}')


if __name__ == '__main__':
    main()
