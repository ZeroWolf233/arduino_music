#!/usr/bin/env python3
import argparse
import math
import pathlib
import shutil
import subprocess
import tempfile
import time

import serial


ROOT = pathlib.Path(__file__).resolve().parent
SAMPLE_RATE = 8000
AUDIO_EXTENSIONS = {'.mp3', '.flac', '.wav', '.m4a', '.aac', '.ogg', '.opus', '.wma', '.aif', '.aiff'}


def find_audio_files(root, selected=None):
    if selected is not None:
        selected = selected.expanduser().resolve()
        if not selected.is_file():
            raise ValueError(f'找不到音频文件：{selected}')
        return [selected]

    files = sorted((p for p in root.iterdir() if p.is_file()), key=lambda p: p.name.casefold())
    sources = [p for p in files if p.suffix.lower() in AUDIO_EXTENSIONS]
    # 有原音频时忽略根目录中已有的 PCM，避免同一首歌重复播放。
    return sources or [p for p in files if p.suffix.lower() == '.pcm']


def convert_to_pcm(source, output_dir, volume, semitones):
    ffmpeg = shutil.which('ffmpeg')
    if ffmpeg is None:
        raise ValueError('找不到 ffmpeg，请先安装 FFmpeg 并将其加入 PATH。')

    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / (source.name + '.pcm')
    filters = ['aformat=channel_layouts=mono']
    if semitones != 0:
        pitch = 2 ** (semitones / 12)
        filters.append(f'rubberband=tempo=1:pitch={pitch:.12g}:pitchq=quality')
    filters.extend([
        f'aresample={SAMPLE_RATE}',
        f'volume={volume:.12g}',
        'alimiter=limit=0.95:level=false:latency=true',
    ])

    # 先转换到临时文件，成功后再替换，避免留下不完整的 PCM。
    with tempfile.NamedTemporaryFile(dir=output_dir, prefix='.converting-', delete=False) as temp:
        temporary = pathlib.Path(temp.name)
    try:
        print(f'转换：{source.name} -> {output}', flush=True)
        subprocess.run([
            ffmpeg, '-nostdin', '-hide_banner', '-loglevel', 'error', '-y',
            '-i', str(source), '-map', '0:a:0', '-af', ','.join(filters),
            '-ar', str(SAMPLE_RATE), '-ac', '1', '-c:a', 'pcm_u8', '-f', 'u8', str(temporary),
        ], check=True)
        if temporary.stat().st_size == 0:
            raise ValueError(f'转换后没有音频数据：{source.name}')
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    return output


def play_pcm(path, port_name, seconds):
    audio = path.read_bytes()
    if seconds > 0:
        audio = audio[:int(seconds * SAMPLE_RATE)]
    if not audio:
        raise ValueError(f'没有可播放的 PCM 数据：{path}')

    print(f'打开 {port_name}，115200 波特率；播放 {len(audio) / SAMPLE_RATE:.3f} 秒。按 Ctrl+C 停止。', flush=True)
    with serial.Serial(port_name, 115200, timeout=1, write_timeout=2, exclusive=True) as port:
        time.sleep(2)  # 等待 Uno 打开串口后自动复位完成。
        port.reset_input_buffer()
        port.reset_output_buffer()
        started = time.monotonic()
        deadline = started
        report_at = started + 10
        largest_lag = 0.0
        sent = 0
        for offset in range(0, len(audio), 80):
            block = audio[offset:offset + 80]
            now = time.monotonic()
            largest_lag = max(largest_lag, now - deadline)
            written = port.write(block)
            if written != len(block):
                raise RuntimeError(f'串口写入不完整：{written}/{len(block)}')
            port.flush()
            sent += written
            deadline += written / SAMPLE_RATE
            time.sleep(max(0, deadline - time.monotonic()))
            now = time.monotonic()
            if now >= report_at:
                print(f'已发送 {sent}/{len(audio)} 字节（{sent / SAMPLE_RATE:.1f} 秒），最大调度延迟 {largest_lag * 1000:.2f} ms。', flush=True)
                report_at = now + 10
        time.sleep(0.1)
        print(f'发送完成：{sent} 字节，耗时 {time.monotonic() - started:.3f} 秒。', flush=True)


def main():
    parser = argparse.ArgumentParser(description='自动转换项目根目录的音频为 PCM，并发送到 Arduino Uno 播放。')
    parser.add_argument('--port', default='/dev/ttyUSB0', help='Arduino 串口（默认：/dev/ttyUSB0）')
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument('--input', type=pathlib.Path, help='只转换并播放指定的音频文件')
    selection.add_argument('--pcm', type=pathlib.Path, help='直接播放指定的原始 PCM，跳过转换')
    parser.add_argument('--seconds', type=float, default=0, help='每首最多播放多少秒；0 表示整首')
    # 在这里修改默认音量和音调，也可以通过命令行参数覆盖。
    parser.add_argument('--volume', type=float, default=1.0, help='转换时的音量倍数；1 为原音量，默认 1')
    parser.add_argument('--semitones', type=float, default=0.0, help='转换时升降的半音数；0 为原调，默认升高 0')
    args = parser.parse_args()
    if not math.isfinite(args.seconds) or args.seconds < 0:
        parser.error('--seconds 必须是大于或等于 0 的有限数值。')
    if not math.isfinite(args.volume) or args.volume < 0:
        parser.error('--volume 必须是大于或等于 0 的有限数值。')
    if not math.isfinite(args.semitones) or not -24 <= args.semitones <= 24:
        parser.error('--semitones 必须在 -24 到 24 之间。')

    try:
        sources = find_audio_files(ROOT, args.input if args.input is not None else args.pcm)
        if not sources:
            raise ValueError(f'目录中没有音频文件：{ROOT}')
        print(f'找到 {len(sources)} 个音频文件；转换设置：音量 {args.volume:g} 倍，升调 {args.semitones:g} 个半音。', flush=True)
        for index, source in enumerate(sources, 1):
            print(f'[{index}/{len(sources)}] {source.name}', flush=True)
            if args.pcm is not None or source.suffix.lower() == '.pcm':
                pcm = source  # 原始 PCM 须已是 8000 Hz、单声道、无符号 8 位。
            else:
                pcm = convert_to_pcm(source, ROOT / 'pcm', args.volume, args.semitones)
            play_pcm(pcm, args.port, args.seconds)
    except KeyboardInterrupt:
        raise SystemExit('播放已停止。')
    except subprocess.CalledProcessError:
        raise SystemExit('音频转换失败；请检查上方 FFmpeg 错误。升调需要 FFmpeg 支持 rubberband，可用 --semitones 0 跳过升调。')
    except (serial.SerialException, OSError, ValueError, RuntimeError) as exc:
        raise SystemExit(f'失败：{exc}')


if __name__ == '__main__':
    main()
