# 插件开发指南

本目录包含串口与网络调试工具的内置插件。插件框架支持双层分类：**Dock 工具**和**扩展工具**。

## 双层分类

插件通过 `TOOL_TYPE` 属性选择展示方式：

| TOOL_TYPE | 展示方式 | 适用场景 |
|-----------|----------|----------|
| `"dock"`（默认） | 嵌入右侧 Dock 面板 Tab | 简单工具，适配 240-340px 窄宽度 |
| `"window"` | 由框架包装为独立非模态 QDialog | 复杂工具，需要更大展示空间 |

## 快速开始

### 1. 创建插件目录

在 `plugins/` 下创建一个新的 Python 包目录：

```
serial_net_tool/plugins/my_plugin/
└── __init__.py
```

### 2. 实现 `__init__.py`

#### Dock 型插件（简单工具）

```python
"""我的插件：简单工具。"""
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel

NAME = "My Plugin"
TOOL_TYPE = "dock"  # 默认值，可省略

def create_widget(ctx=None):
    """ctx 为 MainWindow 引用，可用于获取活跃会话等。"""
    w = QWidget()
    layout = QVBoxLayout(w)
    layout.addWidget(QLabel("Hello!"))
    return w
```

#### Window 型插件（复杂工具）

```python
"""我的插件：复杂工具。"""
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel

NAME = "My Complex Tool"
TOOL_TYPE = "window"  # 以独立窗口形式打开

def create_widget(ctx=None):
    """ctx 为 MainWindow 引用。"""
    w = QWidget()
    layout = QVBoxLayout(w)
    layout.addWidget(QLabel("Full window!"))
    return w
```

框架会自动将 `window` 型插件的 widget 包装进 `QDialog`（720x560），并管理窗口生命周期。

### 3. 重启应用

插件会在应用启动时自动发现并加载。加载失败的插件会被隔离，不影响主程序运行。

## 扩展点

| 属性/方法 | 说明 |
|-----------|------|
| `NAME` | 插件显示名（必须） |
| `TOOL_TYPE` | `"dock"` 或 `"window"`（可选，默认 `"dock"`） |
| `VERSION` | 版本号（可选） |
| `DESCRIPTION` | 描述（可选） |
| `create_widget(ctx) -> QWidget` | 创建 widget（必须），`ctx` 为 MainWindow 引用 |

## 上下文 API

`create_widget(ctx)` 的 `ctx` 参数是 `MainWindow` 实例，提供以下方法：

### 获取活跃会话

```python
def create_widget(ctx=None):
    if ctx:
        sessions = ctx.get_active_sessions()
        # 返回 [(sid, name, kind, channel), ...]
        for sid, name, kind, channel in sessions:
            print(f"{name} [{kind}]")
    ...
```

`channel` 是已连接的 `Channel` 实例，可直接连接其 `received` 信号收发数据。

## 可用 API

插件可以访问主程序的以下模块：

### CRC 计算
```python
from serial_net_tool.tools.crc import PRESETS, crc_hex
result = crc_hex("CRC-16/Modbus", b"\x01\x02\x03")
```

### 校验和
```python
from serial_net_tool.tools.check import all_checksums
result = all_checksums(b"\x01\x02\x03")  # 返回 dict: SUM8/SUM16/XOR/LRC
```

### 进制转换
```python
from serial_net_tool.tools.conv import int_to_base, swap_endian, str_to_hex, hex_to_str
```

### 文本/字节转换
```python
from serial_net_tool.core.utils import text_to_bytes, bytes_to_text
data = text_to_bytes("01 AB CD", "hex")
text = bytes_to_text(data, "hex")
```

### 国际化
```python
from serial_net_tool.core.i18n import tr, set_language
label = tr("my_key")  # 获取翻译文本
```

### 配置访问
```python
from serial_net_tool.core.config import Config
config = Config()
encoding = config.get("default_encoding", "utf-8")
```

## 当前插件

| 插件 | TOOL_TYPE | 说明 |
|------|-----------|------|
| `modbus_tool/` | `window` | Modbus 主站/从站工具，复用串口/TCP 连接 |

## 用户插件

用户也可以在应用外放置插件。将插件目录放在指定路径下，然后通过 `PluginManager.discover(extra_dirs=[path])` 加载。

## 错误隔离

插件加载时发生的任何异常都会被捕获，错误信息会显示在插件管理面板中。主程序不受影响。

## 注意事项

1. 插件中不要直接操作主窗口或通道，应通过 Qt 信号槽机制通信
2. 插件中的耗时操作应放到 QThread 中执行，避免阻塞 UI
3. 插件中可以使用 PySide6 的所有组件，但不要假设主窗口的样式
4. Dock 型插件需适配 240-340px 的窄宽度，避免过多横向控件
5. Window 型插件不受宽度限制，可自由设计布局
