# 串口与网络调试工具（Serial & Network Debug Tool）

一体化、可扩展、跨平台的通信调试工具，基于 **PySide6（Python + Qt）**。把「串口 + 网络（TCP/UDP/MQTT 客户端/服务端）+ 协议与计算扩展工具」收敛到同一界面，并通过插件化架构预留扩展空间。


## 功能一览

- **多会话同屏**：串口 / TCP 客户端 / TCP 服务端 / UDP / MQTT 客户端 / Modbus，各自独立配置与视图。
- **通用收发**：ASCII/HEX 切换、定时发送、流量统计、时间戳、日志导出、粘包处理（TCP/Modbus）。
- **计算工具**：CRC8/16/32（多算法、参数可调）、校验和（SUM8/SUM16/XOR/LRC）、进制与字节序转换。
- **自动回复**：规则式（精确/包含/前缀/正则匹配），支持延时/限频，规则集可导入导出。
- **Modbus**：RTU/TCP 主站读写保持/输入寄存器与线圈，结果以表格展示，异常码提示。
- **插件框架**：内置「字节反转」示例插件；第三方可实现 `create_widget` 扩展工具面板（崩溃隔离）。
- **体验**：中/英文切换、深色（默认）/浅色主题、隐私优先（默认零遥测）。

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


## 模块结构

```
serial_net_tool/
  main.py              入口
  main_window.py       主窗口（会话树/收发区/工具面板/状态栏）
  core/
    channel.py         通道统一抽象与状态
    channel_factory.py 通道工厂
    serial_channel.py  pyserial 实现
    tcpudp_channel.py  TCP/UDP 实现
    mqtt_channel.py    paho-mqtt 客户端
    modbus_channel.py  Modbus 会话
    autoreply.py       自动回复引擎
    config.py          配置持久化（JSON）
    i18n.py / theme.py 国际化 / 主题
    plugin_manager.py  插件发现与隔离
    utils.py           编码与字节工具
  tools/               CRC / 校验和 / 进制计算
  proto/modbus.py      Modbus 主站封装
  ui/                  配置表单、收发面板、工具面板、Modbus 面板、插件面板、设置
  plugins/             内置插件（示例：reverse）
```

## 插件开发

在插件目录（内置 `plugins/<id>/__init__.py`，或用户插件目录）实现：

```python
from PySide6.QtWidgets import QWidget

NAME = "我的工具"

def create_widget(parent=None) -> QWidget:
    w = QWidget(parent)
    # 构建你的工具 UI ...
    return w
```

`PluginManager.discover()` 会自动加载，启用插件的 `create_widget` 会出现在右侧工具面板标签页。加载失败会被隔离并记录，不影响主程序。
。

## 隐私

默认**不收集任何数据**；如开启「匿名使用统计」，仅上报功能模块使用计数，**绝不发送任何通信报文**。

