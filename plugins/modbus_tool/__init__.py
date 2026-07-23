"""Modbus 插件：可复用串口/TCP 连接的 Modbus 主站/从站工具。

功能：
- 复用已有串口/TCP 会话的通信连接，无需单独建立连接
- 寄存器配置：名称/地址/数据类型/描述
- 数据类型支持：uint16/int16/uint32_be/uint32_le/int32_be/int32_le/float32_be/float32_le
- 主站模式：定时轮询寄存器，自动解析响应并映射到配置项
- 从站模式：自动响应主站的读/写请求
- 支持 RTU 和 TCP (MBAP) 两种帧格式
"""

from .panel import ModbusToolWidget

NAME = "Modbus"
VERSION = "1.0"
DESCRIPTION = "Modbus master/slave tool reusing serial/TCP connections"
TOOL_TYPE = "window"  # 以独立窗口形式打开
ENABLE = False


def create_widget(ctx=None):
    """创建插件界面。
    ctx 为 MainWindow 引用，用于获取活跃会话列表。
    """
    return ModbusToolWidget(main_window=ctx)
