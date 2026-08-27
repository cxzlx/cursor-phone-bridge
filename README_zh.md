# 手机传 Cursor · Phone to Cursor

[English](README.md) | **中文**

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Platform: Windows](https://img.shields.io/badge/Platform-Windows-blue.svg)]()
[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-yellow.svg)]()

Windows 轻量工具：**手机浏览器 → 同一 WiFi 内网 → 自动粘贴到 Cursor / Codex / ChatGPT 输入框**。

适合手机语音输入、电脑继续写代码/对话；无需安装手机 App。

---

## 功能

- 手机端零安装，浏览器打开内网地址即可
- 预设 Cursor、Codex、ChatGPT，支持自定义窗口标题
- 可选聚焦快捷键、粘贴后自动 Enter / Ctrl+Enter
- 系统托盘、开机自启、单实例

---

## 快速开始

1. 在 [Releases](../../releases) 下载 `PhoneToCursor.exe`
2. 运行并允许防火墙 **专用网络** 访问
3. 手机与电脑同一 WiFi，打开应用显示的地址
4. 在电脑上先点击 Cursor 输入框
5. 手机输入后点发送

源码运行：

```powershell
git clone https://github.com/cxzlx/cursor-phone-bridge.git
cd cursor-phone-bridge
python -m pip install -r requirements.txt
python main.py
```

---

## 安全提示

- 监听 `0.0.0.0:8765`，同局域网设备可访问
- **无鉴权**，请勿在不可信公共 WiFi 长期开启

---

## 协议

[MIT](LICENSE)
