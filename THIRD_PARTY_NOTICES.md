# Third-party components

Arduino Music uses the following independently licensed components. Their license terms remain applicable to the files distributed with the player.

| Component | Source and notices |
| --- | --- |
| Python runtime | https://www.python.org/ — PSF License; copied into `licenses/PYTHON-LICENSE.txt`. |
| pySerial 3.5 | https://github.com/pyserial/pyserial/tree/v3.5 — BSD license; copied into `licenses/pyserial/`. |
| imageio-ffmpeg 0.6.0 | https://github.com/imageio/imageio-ffmpeg/tree/v0.6.0 — BSD-2-Clause; copied into `licenses/imageio-ffmpeg/`. |
| FFmpeg executable from the imageio-ffmpeg wheel | https://github.com/imageio/imageio-binaries/tree/master/ffmpeg — upstream binary provenance and build/source references. FFmpeg sources: https://ffmpeg.org/download.html . The exact executable's license and build configuration are included as `licenses/FFMPEG-LICENSE.txt` and `licenses/FFMPEG-BUILD.txt`. |
| PyInstaller bootloader | https://github.com/pyinstaller/pyinstaller/tree/v6.16.0 — GPL with the PyInstaller distribution exception; copied into `licenses/pyinstaller/`. |

The player calls the bundled FFmpeg executable as a subprocess. `IMAGEIO_FFMPEG_EXE` can select a separately supplied executable. A custom FFmpeg build can have different enabled libraries and license terms.

Project source for each release is supplied as `arduino-music-source.zip` and is also available at https://github.com/ZeroWolf233/arduino_music .
