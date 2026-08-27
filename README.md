# 手机传 Cursor · Phone to Cursor

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Platform: Windows](https://img.shields.io/badge/Platform-Windows-blue.svg)]()
[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-yellow.svg)]()

在 Windows 上运行的轻量工具：**手机浏览器 → 同一 WiFi 内网 → 自动粘贴到 Cursor / Codex / ChatGPT 输入框**。

适合「手机语音输入、电脑继续写代码/对话」的场景，无需安装手机 App，打开网页即可发送。

---

## 功能亮点

- **零手机端安装**：电脑启动服务后，手机浏览器访问内网地址即可
- **多目标预设**：Cursor、Codex、ChatGPT，也支持自定义窗口标题关键词
- **自动聚焦 + 粘贴**：可选聚焦快捷键（Ctrl+L / Ctrl+I）、粘贴后自动 Enter / Ctrl+Enter
- **系统托盘 + 开机自启**：常驻后台，不占任务栏
- **单实例运行**：避免端口冲突
- **配置持久化**：目标应用、快捷键等写入本地 `phone_bridge_config.json`

---

## 快速开始

### 方式一：下载 Release（推荐）

1. 在 [Releases](../../releases) 下载 `PhoneToCursor.exe`（或 `手机传Cursor.exe`）
2. 双击运行，允许防火墙访问 **专用网络**
3. 电脑与手机连接 **同一 WiFi**
4. 手机浏览器打开窗口显示的地址，例如：`http://192.168.1.10:8765`
5. 在电脑上 **先点击** Cursor 聊天输入框（或依赖自动聚焦）
6. 手机输入文字，点「发送到 Cursor」

可选：勾选「粘贴后自动回车发送」。

### 方式二：源码运行

```powershell
git clone https://github.com/cxzlx/cursor-phone-bridge.git
cd cursor-phone-bridge
python -m pip install -r requirements.txt
python main.py
```

### 打包 exe

```powershell
python -m PyInstaller --noconfirm phone_bridge.spec
# 产物：dist/PhoneToCursor.exe
```

---

## 使用示意

```
┌─────────────┐     同一 WiFi      ┌──────────────────┐     剪贴板+键盘     ┌─────────┐
│  手机浏览器  │ ── HTTP POST ──▶ │  Windows 本机服务  │ ── 粘贴到目标窗口 ──▶ │ Cursor  │
│  语音/打字   │    :8765         │  (本工具)          │                     │ Codex…  │
└─────────────┘                  └──────────────────┘                     └─────────┘
```

---

## 配置说明

| 项 | 说明 |
|----|------|
| 目标应用 | 预设或自定义窗口标题关键词 |
| 发送键 | Enter / Ctrl+Enter / 不自动发送 |
| 聚焦快捷键 | Ctrl+L（聊天）/ Ctrl+I（Composer）/ 无 |
| 启动路径 | 可选指定 `.exe` 或快捷方式，用于一键启动目标应用 |

配置文件位于 exe 同目录：`phone_bridge_config.json`（首次运行后自动生成）。

---

## 安全提示

- 服务监听 `0.0.0.0:8765`，**同一局域网内**其他设备理论上可访问
- **无鉴权**：请勿在公共 WiFi、公司不可信网络下长期开启
- 数据仅在局域网传输，不经过外网服务器
- 若粘贴位置不对：先在目标应用里 **手动点一下输入框** 再发送

---

## 技术栈

- Python 3.11+
- CustomTkinter（桌面 UI）
- 标准库 `http.server`（内网 Web 服务）
- Win32 API（窗口查找、剪贴板、模拟按键）
- PyInstaller（打包）

---

## 常见问题

**Q：手机打不开页面？**  
检查是否同一 WiFi、Windows 防火墙是否放行、杀毒软件是否拦截。

**Q：粘贴到了错误窗口？**  
先聚焦 Cursor 输入框；或在设置里调整窗口标题关键词 / 聚焦快捷键。

**Q：和「提醒工具」冲突吗？**  
不冲突，两个独立程序，端口与职责不同。

---

## 开源协议

[MIT License](LICENSE)

---

## 作者

[cxzlx](https://github.com/cxzlx)

欢迎 Issue / PR。
