# Arduino Music

通过 USB 把电脑上的音乐发送给 **Arduino Uno R3 / ATmega328P**，由 **D5** 驱动无源压电蜂鸣器播放。

支持 Windows 和 Linux，自动发现音频、转换 PCM、调整音量与音调。播放器使用 `imageio-ffmpeg` 提供的 FFmpeg，常用平台无需另行安装系统 FFmpeg。

> 本项目是蜂鸣器音频播放实验：8000 Hz、单声道、无符号 8 位 PCM，不是高保真音响。

## 接线与固件

| 设备 | Arduino Uno |
| --- | --- |
| 无源压电蜂鸣器正极 | 经 220Ω 电阻接 **D5** |
| 无源压电蜂鸣器负极 | GND |
| 电脑 | USB 接口 |

有源蜂鸣器不能完整还原音乐；普通低阻喇叭需要音频功放。固件固定使用 D5 的硬件 PWM，**仅修改 `BUZZER_PIN` 不能迁移输出引脚**。

使用 Arduino IDE 打开 `arduino_music.ino`，选择 **Arduino Uno** 和对应串口后上传。草图目录应命名为 `arduino_music`；Release 的源码压缩包已经按此结构组织。上传成功后关闭 IDE 的串口监视器，释放串口给播放器。

也可使用 Arduino CLI（在项目根目录运行）：

```bash
arduino-cli core update-index
arduino-cli core install arduino:avr@1.8.6
arduino-cli compile --fqbn arduino:avr:uno .
arduino-cli upload --fqbn arduino:avr:uno --port COM3 .
```

Linux 将 `COM3` 换为 `/dev/ttyUSB0` 或 `/dev/ttyACM0`。Release 中的 `arduino-music-uno.hex` 是应用固件、不含 bootloader，可用已配置好的 Arduino CLI 上传：

```bash
arduino-cli upload --fqbn arduino:avr:uno --port COM3 --input-file arduino-music-uno.hex
```

## 从 Release 使用（无需安装 Python）

在 [Releases](https://github.com/ZeroWolf233/arduino_music/releases) 下载对应压缩包，并**完整解压**：

| 文件 | 用途 |
| --- | --- |
| `arduino-music-windows-x64.zip` | Windows 10/11 x64 播放器，包含 Python 运行时和 FFmpeg |
| `arduino-music-linux-x64.tar.gz` | Linux x64 播放器，构建于 Ubuntu 22.04；需要 glibc 2.35 或更新版本 |
| `arduino-music-uno.hex` | Arduino Uno D5 固件 |
| `arduino-music-source.zip` | 该 tag 的完整项目源码 |
| `SHA256SUMS.txt` | 下载文件的 SHA-256 校验值 |

把音乐放到 `arduino-music.exe` / `arduino-music` 所在目录。保留旁边的 `_internal` 目录，它包含运行依赖。

Windows PowerShell：

```powershell
.\arduino-music.exe --list-ports
.\arduino-music.exe --port COM3
```

Linux 终端：

```bash
./arduino-music --list-ports
./arduino-music --port /dev/ttyUSB0
```

只有一个 USB 串口时，可省略 `--port` 自动选择。多个串口时程序会列出候选并要求指定，避免向错误设备发送数据。播放过程中按 **Ctrl+C** 停止。

## 从源码运行

使用 **Python 3.11 或更新版本**，推荐 Python 3.12。首次安装依赖需要网络，后续转换和播放在本地完成。

Windows PowerShell：

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py --list-ports
.\.venv\Scripts\python.exe main.py --port COM3
```

Linux：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python main.py --list-ports
.venv/bin/python main.py --port /dev/ttyUSB0
```

如果 Python 已安装项目依赖，也可以直接运行：

```bash
python main.py
```

## 音频发现、转换与清理

- 默认扫描 `main.py` 所在目录；Release 版本扫描可执行文件所在目录，不受启动终端的当前目录影响。
- 支持 MP3、FLAC、WAV、M4A、AAC、OGG、Opus、WMA、AIF、AIFF，按文件名排序依次播放，不递归扫描子目录。实际解码能力取决于 FFmpeg 构建和输入文件。
- 有原音频时忽略同目录 PCM，避免重复播放；目录中只有 PCM 时可直接播放。
- 每首原音频转换到独立的**系统临时目录**。播放结束、转换/串口报错、Ctrl+C 都会清理本次临时 PCM。
- 原始音乐，以及用户通过 `--pcm` 或自动扫描提供的 PCM 都属于输入文件，**不会删除**。旧版的 `pcm/` 缓存不会被扫描或自动清空。
- 强制杀死进程或断电可能留下系统临时目录；正常停止请使用 Ctrl+C。

### 常用参数

下面以源码命令为例；使用 Release 时把 `python main.py` 换成相应播放器命令即可。

```bash
# 指定音乐目录
python main.py --directory "D:\Music" --port COM3

# 只播放指定文件
python main.py --input "music.mp3" --port COM3

# 音量增益 2 倍，升高 3 个半音，每首试听 10 秒
python main.py --volume 2 --semitones 3 --seconds 10

# 直接播放已有 PCM（8000 Hz / 单声道 / 无符号 8 位 / 无文件头）
python main.py --pcm "music.pcm"

# 查看 FFmpeg 路径和版本
python main.py --ffmpeg-info
```

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `--port` | 自动检测 | Windows 如 `COM3`，Linux 如 `/dev/ttyUSB0` |
| `--directory` | 程序所在目录 | 自动扫描的音频目录 |
| `--input` | 无 | 只转换并播放指定音频，与 `--pcm` 互斥 |
| `--pcm` | 无 | 直接发送原始 PCM，不再次转换、调音量或升调 |
| `--seconds` | `0` | 每首播放秒数，0 表示整首 |
| `--volume` | `1` | 转换时的音量倍数，过大可能失真 |
| `--semitones` | `0` | 升降半音数，范围 -24 到 24，尽量保持原播放速度 |
| `--list-ports` | — | 列出串口后退出 |
| `--ffmpeg-info` | — | 显示 FFmpeg 路径和版本 |
| `--version` | — | 显示 Release tag；源码开发版显示 `dev` |

音调处理使用 FFmpeg 自带的 `asetrate` / `aresample` / `atempo`，不依赖额外的 Rubber Band 库。

## Python 与 FFmpeg

本项目使用 [`imageio-ffmpeg`](https://github.com/imageio/imageio-ffmpeg)，其常用平台的 PyPI wheel 包含 FFmpeg 可执行文件，程序通过 `imageio_ffmpeg.get_ffmpeg_exe()` 获取并调用。Release 也会把该文件一起打包。

这不需要用户预先安装系统 FFmpeg，但转换过程仍会启动随包提供的 FFmpeg 子进程。`ffmpeg-python` 是另一种命令封装，本身不会附带 FFmpeg，因此没有选用它。

如需使用自定义 FFmpeg，可设置 `IMAGEIO_FFMPEG_EXE` 为其完整路径。安装源码包、Conda 包或不受 wheel 支持的架构时，可能仍需自行提供 FFmpeg。当前 Release 目标为 Windows/Linux x64。

## GitHub Actions 与发布

工作流位于 [`.github/workflows/release.yml`](.github/workflows/release.yml)，触发条件是**向 GitHub 推送新 tag**，不限于 `v` 前缀。仅创建本地 tag 不会触发；移动或删除已有 tag 不会执行构建发布任务。

先将本次代码（包括工作流）提交并推送到仓库，再执行：

```bash
git tag v0.1.0
git push origin v0.1.0
```

Actions 会：

1. 在 Windows 和 Linux 分别运行测试，检查真实音频转换、串口选项、PCM 清理。
2. 使用 PyInstaller 打包播放器和 FFmpeg，并在系统 PATH 中没有 FFmpeg 的条件下验证打包结果。
3. 编译 Arduino Uno 固件，生成源码压缩包。
4. 全部成功后创建 GitHub Release，附加构建文件和 SHA-256 校验值。

工作流使用仓库自带的 `GITHUB_TOKEN`；仅发布任务申请 `contents: write`，无需额外配置个人 token。仓库或组织需要允许 GitHub Actions 运行，并允许该工作流写入 Releases。

### 本地开发与打包

安装开发依赖并测试：

```bash
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
```

在对应操作系统打包（不支持跨系统生成可执行文件）：

```bash
# Windows
python scripts/build_release.py --platform windows-x64 --version v0.1.0
python scripts/smoke_release.py dist/arduino-music/arduino-music.exe

# Linux
python scripts/build_release.py --platform linux-x64 --version v0.1.0
python scripts/smoke_release.py dist/arduino-music/arduino-music
```

压缩包在 `release/`，构建目录与音频文件均由 `.gitignore` 排除。自动化测试无需连接 Arduino，实际声音效果仍取决于蜂鸣器和接线。

## 常见问题

**串口被占用：** 关闭 Arduino IDE 的串口监视器、串口绘图器和其他播放器进程。

**Windows 没有 COM 设备：** 检查 USB 数据线和设备管理器；部分兼容板需要安装对应 USB 串口芯片驱动。

**Linux 无权打开串口：** 检查设备权限。在使用 `dialout` 组的发行版（如 Ubuntu/Debian）中，可将用户加入该组，重新登录后再试。

**蜂鸣器不响：** 确认上传的是本项目 Uno 固件，信号接数字 **D5** 而非 A5，GND 共地，并使用无源压电蜂鸣器。仅修改引脚常量不足以切换硬件 PWM。

**音乐低音弱或失真：** 蜂鸣器和 8 位/8kHz PCM 的音质有限，增大 `--volume` 不能增加硬件输出能力。需要更好音质时，应使用合适的喇叭、功放及音频输出电路。

**固件的计时函数异常：** 固件占用 Timer0 产生 62.5kHz PWM，Timer1 产生 8kHz 采样中断，因此不能依赖 `millis()`、`micros()`、`delay()`，也不能同时使用 Servo 或这些定时器对应的其他 PWM 输出。

## 许可证

项目许可证见 [LICENSE](LICENSE)（GNU GPL v3）。随播放器分发的第三方组件保留各自许可证，见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) 和 Release 内的 `licenses/`。
