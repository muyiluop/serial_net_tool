# 串口与网络调试工具（Serial & Network Debug Tool）

一体化、可扩展、跨平台的通信调试工具，基于 **PySide6（Python + Qt）**。把「串口 + 网络（TCP/UDP/MQTT 客户端/服务端）+ 协议与计算扩展工具」收敛到同一界面，并通过插件化架构预留扩展空间。

## 功能一览

- **多会话同屏**：串口 / TCP 客户端 / TCP 服务端 / UDP / MQTT，各自独立配置与视图，状态实时可视化（彩色圆点 + 胶囊徽标）。
- **通用收发**：ASCII/HEX 切换、定时发送、文件分块发送、流量统计、时间戳。
- **通信日志**：结构化存储（有界上限）、按方向着色、暂停/继续、关键字高亮搜索、方向筛选、自动换行。
- **日志导出**：TXT / CSV / Hex dump 三种格式，支持 TX/RX 筛选、时间范围、前 50 行预览。
- **计算工具**：CRC8/16/32（多算法 + 自定义多项式/初值/反转/异或）、校验和（SUM8/SUM16/XOR/LRC）、进制与字节序转换、字符串↔Hex、Hex 转文件。
- **自动回复**：规则式（精确/包含/前缀/正则），支持延时/限频；规则实时校验，非法规则高亮且不生效；规则集可导入导出。
- **MQTT**：发布（主题/QoS/保留）、运行期订阅管理（`+`/`#` 通配符）、遗嘱（LWT）、退避重连、订阅随会话持久化。
- **UDP**：单播 / 广播 / 组播（`IP_ADD_MEMBERSHIP`）。
- **Modbus 插件**：复用串口/TCP 连接的主站/从站工具，寄存器映射、按功能码轮询（0x01/02/03/04）、帧解析视图、帧日志、异常码提示。
- **插件框架**：可选 `plugin.json` manifest、Dock/窗口两种工具形态、崩溃隔离、启用/禁用持久化；内置 3 个插件示例。
- **界面**：自绘 SVG 线性图标（随主题着色）、紧凑工程感（小圆角/低描边/高密度）、会话列表状态圆点、
  下划线式 Tab、工具面板下拉导航、四档按钮层级。
- **体验**：中/英文切换、深色（默认）/浅色/跟随系统主题（系统深浅色变化实时生效）、隐私优先（默认零遥测）。

## 安装

```bash
pip install -r requirements.txt
```

建议 Python ≥ 3.9，使用虚拟环境。

## 运行

```bash
python main.py
```

无显示环境（CI/容器）可用：

```bash
QT_QPA_PLATFORM=offscreen python main.py
```

## 测试

```bash
pip install -r requirements-dev.txt
python -m pytest          # 无头运行，覆盖纯逻辑模块与界面冒烟
```

## 模块结构

```
serial_net_tool/
  main.py              入口（主题/语言/插件初始化、跟随系统主题）
  main_window.py       主窗口（会话列表 / 可折叠配置 / 收发区 / 工具面板 Dock / 状态栏）
  core/
    channel.py         通道统一抽象与状态机
    channel_factory.py 通道工厂
    serial_channel.py  pyserial 实现（含热插拔刷新）
    tcpudp_channel.py  TCP/UDP 实现（含粘包重组、UDP 组播）
    mqtt_channel.py    paho-mqtt 客户端（发布/订阅/LWT/退避重连）
    log_store.py       结构化日志存储与导出
    autoreply.py       自动回复引擎与规则校验
    packet_reassembler.py 粘包重组（timeout/delimiter/length_prefix）
    config.py          配置持久化（JSON）
    i18n.py / theme.py 国际化 / 主题与设计令牌
    icons.py           自绘 SVG 线性图标集（随主题着色）
    plugin_manager.py  插件发现与隔离（支持 plugin.json）
    telemetry.py       隐私遥测（默认关闭）
    utils.py           编码与字节工具
  tools/               CRC / 校验和 / 进制计算 / gen_icon.py（生成多尺寸应用图标）
  ui/                  会话配置、收发面板、MQTT 面板、工具面板、日志导出、插件面板、设置
  plugins/             内置插件（modbus_tool / reverse / codec_tool）
  tests/               pytest 测试
```

## 插件开发

在插件目录（内置 `plugins/<id>/`，或用户插件目录）实现：

```python
from PySide6.QtWidgets import QWidget

NAME = "我的工具"
TOOL_TYPE = "dock"          # 或 "window"（独立窗口）

def create_widget(ctx=None) -> QWidget:
    """ctx 为 MainWindow 引用，可用于获取活跃会话、填充发送区等。"""
    w = QWidget()
    # 构建你的工具 UI ...
    return w
```

可选放置 `plugin.json` 声明元信息（版本/作者/入口函数/最低应用版本）。`PluginManager.discover()`
启动时自动加载，启用插件的 `create_widget` 会出现在工具面板或 Tools 菜单。加载失败会被隔离并记录，不影响主程序。

详见 [插件开发指南](plugins/README.md)。

## 隐私

默认**不收集任何数据**；如开启「匿名使用统计」，仅上报功能模块使用计数，**绝不发送任何通信报文**。
