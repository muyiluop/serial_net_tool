# 插件开发指南

本目录包含串口与网络调试工具的内置插件。插件框架支持两种展示形态：**Dock 工具**与**扩展窗口**。

## 目录

- [两种工具类型](#两种工具类型)
- [快速开始](#快速开始)
- [plugin.json（可选 manifest）](#pluginjson可选-manifest)
- [上下文 API（ctx）](#上下文-apictx)
- [通道（Channel）信号契约](#通道channel信号契约)
- [生命周期与资源释放](#生命周期与资源释放)
- [可复用的主程序能力](#可复用的主程序能力)
- [错误隔离](#错误隔离)
- [Dock 型布局建议](#dock-型布局建议)
- [打包与分发](#打包与分发)
- [内置插件](#内置插件)

## 两种工具类型

插件通过 `TOOL_TYPE`（模块属性或 manifest 字段）选择展示方式：

| TOOL_TYPE | 展示方式 | 适用场景 |
|-----------|----------|----------|
| `"dock"`（默认） | 嵌入右侧 Dock 面板 Tab | 简单工具，需适配 240–340px 窄宽度 |
| `"window"` | 由框架包装为独立非模态 QDialog | 复杂工具，需要更大展示空间 |

## 快速开始

### 1. 创建插件目录

在 `plugins/` 下创建包目录（内置插件），或在任意目录创建后通过
`PluginManager.discover(extra_dirs=[path])` 加载用户插件。

```
serial_net_tool/plugins/my_plugin/
├── __init__.py
└── plugin.json      # 可选
```

### 2. 实现 `__init__.py`

最小实现（Dock 型）：

```python
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel

NAME = "My Plugin"

def create_widget(ctx=None):
    """ctx 为 MainWindow 引用，可为 None（测试时）。"""
    w = QWidget()
    layout = QVBoxLayout(w)
    layout.addWidget(QLabel("Hello!"))
    return w
```

扩展窗口型，只需声明：

```python
TOOL_TYPE = "window"
```

框架会自动把该 widget 包进 `QDialog`（约 720×600），并管理窗口生命周期与多实例。

### 3. 重启应用

插件在启动时自动发现并加载；加载失败的插件会被隔离，不影响主程序。

## plugin.json（可选 manifest）

模块属性与 manifest 可二选一或同时使用，**模块属性优先**。

```json
{
  "id": "my_plugin",
  "name": "My Plugin",
  "version": "1.0",
  "author": "you",
  "description": "一句话描述",
  "tool_type": "dock",
  "entry": "create_widget",
  "min_app_version": "0.1.0"
}
```

| 字段 | 说明 |
|------|------|
| `id` | 唯一标识（默认为目录名），用于启用/禁用持久化 |
| `name` | 显示名（默认目录名） |
| `version` / `author` / `description` | 元信息，展示在插件管理面板 |
| `tool_type` | `dock` / `window` |
| `entry` | 入口函数名，默认 `create_widget` |
| `min_app_version` | 低于该版本则拒绝加载并记录错误 |

### 可用模块属性

| 属性 | 说明 |
|------|------|
| `NAME` | 插件显示名 |
| `VERSION` / `AUTHOR` / `DESCRIPTION` | 元信息 |
| `TOOL_TYPE` | `"dock"` 或 `"window"` |
| `ENABLE` | 默认是否启用（`False` 可出厂禁用） |
| `create_widget(ctx) -> QWidget` | 必需入口（或由 manifest `entry` 指定） |

## 上下文 API（ctx）

`create_widget(ctx)` 的 `ctx` 是 `MainWindow` 实例，提供：

| 方法 | 说明 |
|------|------|
| `ctx.get_active_sessions()` | 返回 `[(sid, name, kind, channel), ...]`，仅含已连接的会话 |
| `ctx.fill_send_text(text)` | 把文本填入当前活动会话的发送区 |

示例：复用已连接的串口/TCP 会话收发数据。

```python
def create_widget(ctx=None):
    if ctx:
        for sid, name, kind, channel in ctx.get_active_sessions():
            print(name, kind)          # channel 是 Channel 实例
            channel.received.connect(lambda data, meta: print("RX", data.hex()))
            channel.send(b"\x01\x03\x00\x00\x00\x01")
    ...
```

## 通道（Channel）信号契约

所有通道（串口/TCP/UDP/MQTT/Modbus）统一暴露以下信号与接口（`serial_net_tool/core/channel.py`）：

| 成员 | 类型 | 说明 |
|------|------|------|
| `received` | `Signal(bytes, dict)` | 收到数据；`meta` 可能含 `peer`（TCP 对端）或 `topic`（MQTT 主题） |
| `status_changed` | `Signal(ChannelStatus)` | 状态变化（CONNECTED / LISTENING / ERROR …） |
| `error_occurred` | `Signal(str)` | 错误描述 |
| `log_message` | `Signal(str, str)` | (级别, 消息) 日志 |
| `open(cfg)` / `close()` / `send(bytes)` | 方法 | 建立 / 关闭 / 发送 |

> 注意：`received` 由工作线程发出（MQTT 回调在 paho 网络线程），**不要在其中直接操作控件**；
> 通过 Qt 信号槽跨线程传递，或仅做数据累积。

## 生命周期与资源释放

若插件持有外部资源（订阅了信号、启动了定时器/线程），请提供 `shutdown()`：

```python
class MyWidget(QWidget):
    def shutdown(self):
        """幂等；窗口关闭/销毁时由框架调用。"""
        ...
```

框架在扩展窗口 `finished` / `destroyed` 时会调用 `widget.shutdown()`（若存在）。

## 可复用的主程序能力

```python
from serial_net_tool.tools.crc import PRESETS, crc, crc_hex, crc_custom
from serial_net_tool.tools.check import all_checksums        # SUM8/SUM16/XOR/LRC
from serial_net_tool.tools.conv import int_to_base, swap_endian, str_to_hex, hex_to_str
from serial_net_tool.core.utils import text_to_bytes, bytes_to_text, parse_int
from serial_net_tool.core.i18n import tr, set_language, get_language
from serial_net_tool.core.log_store import LogStore          # 结构化日志（可选复用）
```

国际化建议：在插件内维护本地 `_LANG` 字典，并依据 `get_language()` 取值，
避免污染主程序翻译表：

```python
from serial_net_tool.core.i18n import get_language
_LANG = {"zh": {"hello": "你好"}, "en": {"hello": "Hello"}}
def _t(k): return _LANG.get(get_language(), _LANG["en"]).get(k, k)
```

样式约定：主程序 QSS 通过 `objectName` 生效，常用值有 `accent`（强调按钮）、
`ghost`（次要按钮）、`card`（卡片容器）、`dim`（次要文字）、`mono`（等宽文本）、
`stat`（等宽统计）。优先复用这些 objectName 以与主题保持一致。

## 错误隔离

- **加载期**：`__init__.py` 抛异常或缺少入口 → 记录完整 traceback，插件标记为错误，
  不进入工具面板/菜单。可在「工具 → 插件管理」双击错误列查看详情。
- **实例化期**：`create_widget()` 抛异常 → 同样被隔离。
- 已启用插件可在插件管理面板勾选/取消，状态持久化到配置 `disabled_plugins`。

## Dock 型布局建议

- 目标宽度 240–340px：控件纵向排列，避免过多横向控件。
- 输入/结果区使用 `setObjectName("mono")` 以获得等宽字体。
- 长文本结果用 `QLabel` + `setWordWrap(True)` 或只读 `QPlainTextEdit`。

## 打包与分发

- 内置插件：放在本目录，随 `--collect-submodules serial_net_tool` 自动收集。
- 若插件目录含 `plugin.json`，打包时需将其加入 PyInstaller `datas`（见 `SerialNetTool.spec`）。
- 用户插件：分发目录 + 调用 `PluginManager.discover(extra_dirs=[...])` 即可加载。

## 内置插件

| 插件 | TOOL_TYPE | 说明 |
|------|-----------|------|
| `modbus_tool/` | `window` | Modbus 主站/从站工具：寄存器映射、按功能码轮询、帧解析、帧日志；复用串口/TCP 连接 |
| `reverse/` | `dock` | 字节反转 / 16 位字节序交换 / 位反转（manifest 示例） |
| `codec_tool/` | `window` | Base64 / URL / JSON 编解码（标准库实现，window 示例） |
