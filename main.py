#!/usr/bin/env python3
"""Stream automatically converted audio to an Arduino Uno over USB serial."""

import argparse
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

import imageio_ffmpeg
import serial
from serial.tools import list_ports


SAMPLE_RATE = 8000
BAUD_RATE = 115200
BLOCK_SIZE = 80
AUDIO_EXTENSIONS = {'.mp3', '.flac', '.wav', '.m4a', '.aac', '.ogg', '.opus', '.wma', '.aif', '.aiff'}


def application_root():
    """Find music beside the executable, including PyInstaller releases."""
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def application_version():
    version_file = application_root() / 'VERSION'
    return version_file.read_text(encoding='utf-8').strip() if version_file.is_file() else 'dev'


def find_audio_files(root, selected=None):
    if selected is not None:
        selected = selected.expanduser().resolve()
        if not selected.is_file():
            raise ValueError(f'找不到音频文件：{selected}')
        return [selected]
    if not root.is_dir():
        raise ValueError(f'音频目录不存在：{root}')
    files = sorted((p for p in root.iterdir() if p.is_file()), key=lambda p: p.name.casefold())
    sources = [p for p in files if p.suffix.lower() in AUDIO_EXTENSIONS]
    # 有原音频时忽略已有 PCM，避免同一首歌重复播放。
    return sources or [p for p in files if p.suffix.lower() == '.pcm']


def resolve_port(requested=None):
    if requested:
        return requested
    ports = list(list_ports.comports())
    usb_ports = [port for port in ports if port.vid is not None]
    candidates = usb_ports or ports
    if len(candidates) == 1:
        return candidates[0].device
    if not candidates:
        raise ValueError('没有检测到串口，请连接 Arduino；可用 --list-ports 查看，或用 --port 指定。')
    names = ', '.join(port.device for port in candidates)
    raise ValueError(f'检测到多个串口：{names}。请使用 --port 指定 Arduino 串口。')


def serial_options(port_name, platform=None):
    platform = os.name if platform is None else platform
    options = dict(port=port_name, baudrate=BAUD_RATE, timeout=1, write_timeout=2)
    # exclusive 是 POSIX 功能，Windows 的 COM 串口不传这个参数。
    if platform == 'posix':
        options['exclusive'] = True
    return options


def audio_filters(volume, semitones):
    filters = ['aformat=channel_layouts=mono']
    if semitones != 0:
        pitch_rate = round(48000 * 2 ** (semitones / 12))
        filters.extend(['aresample=48000', f'asetrate={pitch_rate}', 'aresample=48000'])
        # 使用 FFmpeg 自带滤镜，避免依赖部分 Windows 构建没有的 librubberband。
        tempo = 48000 / pitch_rate
        while tempo < 0.5:
            filters.append('atempo=0.5')
            tempo /= 0.5
        while tempo > 2:
            filters.append('atempo=2')
            tempo /= 2
        filters.append(f'atempo={tempo:.12g}')
    filters.extend([
        f'aresample={SAMPLE_RATE}', f'volume={volume:.12g}',
        'alimiter=limit=0.95:level=false:latency=true',
    ])
    return ','.join(filters)


def convert_to_pcm(source, output_dir, volume, semitones):
    """Convert into a caller-owned temporary directory; never overwrite input."""
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / 'audio.pcm'
    print(f'转换：{source.name}', flush=True)
    options = {}
    if os.name == 'nt':
        options['creationflags'] = subprocess.CREATE_NO_WINDOW
    subprocess.run([
        ffmpeg, '-nostdin', '-hide_banner', '-loglevel', 'error', '-y',
        '-i', str(source), '-map', '0:a:0', '-af', audio_filters(volume, semitones),
        '-ar', str(SAMPLE_RATE), '-ac', '1', '-c:a', 'pcm_u8', '-f', 'u8', str(output),
    ], check=True, capture_output=True, text=True, encoding='utf-8', errors='replace', **options)
    if output.stat().st_size == 0:
        raise ValueError(f'转换后没有音频数据：{source.name}')
    print(f'转换完成：{output.stat().st_size} 字节 PCM。', flush=True)
    return output


def play_pcm(path, port_name, seconds):
    total = path.stat().st_size
    if seconds > 0:
        total = min(total, int(seconds * SAMPLE_RATE))
    if total == 0:
        raise ValueError(f'没有可播放的 PCM 数据：{path}')
    print(f'打开 {port_name}，{BAUD_RATE} 波特率；播放 {total / SAMPLE_RATE:.3f} 秒。按 Ctrl+C 停止。', flush=True)
    with path.open('rb') as audio, serial.Serial(**serial_options(port_name)) as port:
        time.sleep(2)  # 等待 Uno 打开串口后自动复位完成。
        port.reset_input_buffer()
        port.reset_output_buffer()
        started = time.monotonic()
        deadline = started
        report_at = started + 10
        largest_lag = 0.0
        sent = 0
        while sent < total:
            block = audio.read(min(BLOCK_SIZE, total - sent))
            if not block:
                raise OSError('PCM 文件在播放过程中被截断。')
            largest_lag = max(largest_lag, time.monotonic() - deadline)
            written = port.write(block)
            if written != len(block):
                raise RuntimeError(f'串口写入不完整：{written}/{len(block)}')
            # Windows 的 flush() 会轮询发送队列，逐块调用可能引入较长停顿。
            # 依靠采样率控制发送节奏，只在最后等待串口排空。
            sent += written
            deadline += written / SAMPLE_RATE
            time.sleep(max(0, deadline - time.monotonic()))
            now = time.monotonic()
            if now >= report_at:
                print(f'已发送 {sent}/{total} 字节（{sent / SAMPLE_RATE:.1f} 秒），最大调度延迟 {largest_lag * 1000:.2f} ms。', flush=True)
                report_at = now + 10
        port.flush()
        time.sleep(0.1)
        print(f'发送完成：{sent} 字节，耗时 {time.monotonic() - started:.3f} 秒。', flush=True)


def play_source(source, port_name, seconds, volume, semitones, raw_pcm=False):
    if raw_pcm or source.suffix.lower() == '.pcm':
        play_pcm(source, port_name, seconds)
        return  # 用户提供的 PCM 是输入文件，不删除。
    # 正常结束、串口失败或 Ctrl+C 都由上下文管理器清理本次生成的 PCM。
    with tempfile.TemporaryDirectory(prefix='arduino-music-') as directory:
        pcm = convert_to_pcm(source, Path(directory), volume, semitones)
        play_pcm(pcm, port_name, seconds)
    print('临时 PCM 已清理。', flush=True)


def make_parser():
    parser = argparse.ArgumentParser(description='自动转换音频为 PCM，并通过 Arduino Uno 的 D5 播放。')
    parser.add_argument('--version', action='version', version=f'Arduino Music {application_version()}')
    parser.add_argument('--port', help='Arduino 串口，如 COM3 或 /dev/ttyUSB0；默认自动检测')
    parser.add_argument('--list-ports', action='store_true', help='列出串口后退出')
    parser.add_argument('--ffmpeg-info', action='store_true', help='显示所用 FFmpeg 的路径和版本后退出')
    parser.add_argument('--directory', type=Path, default=application_root(), help='音频目录；默认 main.py 或可执行文件所在目录')
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument('--input', type=Path, help='只转换并播放指定的音频文件')
    selection.add_argument('--pcm', type=Path, help='直接播放指定的 8kHz/单声道/无符号8位原始 PCM')
    parser.add_argument('--seconds', type=float, default=0, help='每首最多播放多少秒；0 表示整首')
    parser.add_argument('--volume', type=float, default=1.0, help='转换时的音量倍数，默认 1')
    parser.add_argument('--semitones', type=float, default=0.0, help='转换时升降的半音数，默认 0，范围 -24 到 24')
    return parser


def main(argv=None):
    # 保证 Windows 终端重定向日志和中文文件名也可正常显示。
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')
    parser = make_parser()
    args = parser.parse_args(argv)
    if not math.isfinite(args.seconds) or args.seconds < 0:
        parser.error('--seconds 必须是大于或等于 0 的有限数值。')
    if not math.isfinite(args.volume) or args.volume < 0:
        parser.error('--volume 必须是大于或等于 0 的有限数值。')
    if not math.isfinite(args.semitones) or not -24 <= args.semitones <= 24:
        parser.error('--semitones 必须在 -24 到 24 之间。')
    try:
        if args.list_ports:
            ports = list(list_ports.comports())
            for port in ports:
                print(f'{port.device}: {port.description}')
            if not ports:
                print('没有检测到串口。')
            return 0
        if args.ffmpeg_info:
            print(f'FFmpeg: {imageio_ffmpeg.get_ffmpeg_exe()}')
            print(f'Version: {imageio_ffmpeg.get_ffmpeg_version()}')
            return 0
        selected = args.input if args.input is not None else args.pcm
        sources = find_audio_files(args.directory.expanduser().resolve(), selected)
        if not sources:
            raise ValueError(f'目录中没有音频文件：{args.directory}')
        port_name = resolve_port(args.port)
        print(f'找到 {len(sources)} 个音频文件；音量 {args.volume:g} 倍，升调 {args.semitones:g} 个半音。', flush=True)
        for index, source in enumerate(sources, 1):
            print(f'[{index}/{len(sources)}] {source.name}', flush=True)
            play_source(source, port_name, args.seconds, args.volume, args.semitones, raw_pcm=args.pcm is not None)
        return 0
    except KeyboardInterrupt:
        print('播放已停止；本次生成的临时 PCM 已清理。', file=sys.stderr)
        return 130
    except subprocess.CalledProcessError as exc:
        print(f'音频转换失败：{exc.stderr or exc}', file=sys.stderr)
        return 1
    except (serial.SerialException, OSError, ValueError, RuntimeError) as exc:
        print(f'失败：{exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
