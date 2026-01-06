========================================
        使用说明 - main.exe
========================================

1. 前置条件

首先请确保安装了Python，需要安装whisper和opencc的库

为了让程序正常录音，需要安装 VB-Audio Virtual Cable。
官方下载地址：
https://vb-audio.com/Cable/

2. 安装 VB-Audio Virtual Cable

1) 打开上面链接，下载 VB-CABLE Driver 压缩包。
2) 解压压缩包，找到：
   - VBCABLE_Setup.exe       （32位系统）
   - VBCABLE_Setup_x64.exe   （64位系统）
3) 右键以管理员身份运行安装程序。
4) 安装完成后建议重启电脑。
5) 安装成功后，在 Windows 的录音设备列表中会看到：
   CABLE Output (VB-Audio Virtual Cable)

注意：程序默认使用该虚拟音频设备作为录音输入。

3. 使用程序

1) 将程序解压到任意文件夹，例如 D:\Programme\test
2) 双击运行 main.exe
3) 输入录音时长（秒），例如：
   Enter recording duration in seconds: 2
4) 程序将依次完成：
   - 录音
   - 转写（生成音频文本）
   - 自动总结
   - 生成 Markdown 文件
5) 所有输出文件会保存在程序目录下的 records\YYYY-MM-DD_HH-MM\ 文件夹内

4. 常见问题

- 如果程序报 I/O error 或找不到音频设备：
  - 确认 VB-Cable 是否安装成功
  - 确认设备名是 CABLE Output (VB-Audio Virtual Cable)
  - 如果电脑有多个音频设备，确保虚拟音频设备被正确选择

5. 文件结构示例

test\
  main.exe
  record.exe
  transcribe_s.py
  summarize.exe
  make_md.exe
  records\
    2026-01-06_04-00\
      audio.wav
      audio.txt
      audio.s.txt
  README.txt
