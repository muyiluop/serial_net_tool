"""寄存器配置与值解析。

RegisterConfig: 单个寄存器配置项
  - name: 名称
  - address: 起始地址
  - reg_type: 数据类型 (uint16/int16/uint32_be/uint32_le/int32_be/int32_le/float32_be/float32_le)
  - description: 描述

RegisterMap: 管理所有寄存器配置和当前值
  - add/remove/update: 增删改
  - set_raw_values(addr, values): 从 Modbus 响应写入原始寄存器值，自动更新所有映射到此地址的配置项
  - get_values_for_read: 生成主站轮询的地址块列表
  - get_raw_values(addr, count): 从站模式返回寄存器值
  - set_raw_value(addr, value): 从站模式写入寄存器值
"""
import struct
from dataclasses import dataclass, field
from typing import Optional

# 数据类型定义：(字节数, 寄存器数, struct格式符, 是否大端)
REG_TYPES = {
    "uint16":     (2, 1, ">H",  True),
    "int16":      (2, 1, ">h",  True),
    "uint32_be":  (4, 2, ">I",  True),
    "uint32_le":  (4, 2, "<I",  False),
    "int32_be":   (4, 2, ">i",  True),
    "int32_le":   (4, 2, "<i",  False),
    "float32_be": (4, 2, ">f",  True),
    "float32_le": (4, 2, "<f",  False),
}

REG_TYPE_NAMES = list(REG_TYPES.keys())


def reg_count_for_type(reg_type: str) -> int:
    """返回该类型占用的寄存器数量。"""
    info = REG_TYPES.get(reg_type)
    return info[1] if info else 1


@dataclass
class RegisterConfig:
    """单个寄存器配置项。"""
    name: str = ""
    address: int = 0
    reg_type: str = "uint16"
    description: str = ""
    # 读取该地址块使用的 Modbus 功能码（0x01 线圈 / 0x02 离散输入 / 0x03 保持 / 0x04 输入）
    func_code: int = 0x03
    # 当前值（解析后的人类可读值）
    value: float | int = 0
    # 原始寄存器值（用于从站模式）
    raw_values: list = field(default_factory=list)


class RegisterMap:
    """寄存器映射管理。

    内部维护两个结构：
    - configs: list[RegisterConfig]，用户配置的寄存器列表
    - _raw_store: dict[int, int]，地址→16位寄存器值，存储所有原始数据
    """

    def __init__(self):
        self.configs: list[RegisterConfig] = []
        self._raw_store: dict[int, int] = {}  # addr -> uint16 value

    # ==================== 配置管理 ====================

    def add(
        self,
        name: str,
        address: int,
        reg_type: str = "uint16",
        description: str = "",
        func_code: int = 0x03,
    ) -> RegisterConfig:
        cfg = RegisterConfig(
            name=name,
            address=address,
            reg_type=reg_type,
            description=description,
            func_code=func_code,
        )
        self.configs.append(cfg)
        return cfg

    def remove(self, index: int):
        if 0 <= index < len(self.configs):
            self.configs.pop(index)

    def get(self, index: int) -> Optional[RegisterConfig]:
        if 0 <= index < len(self.configs):
            return self.configs[index]
        return None

    def clear(self):
        self.configs.clear()
        self._raw_store.clear()

    # ==================== 原始寄存器存储 ====================

    def set_raw_values(self, start_addr: int, values: list):
        """写入原始 16 位寄存器值，并更新所有映射到这些地址的配置项。"""
        for i, v in enumerate(values):
            self._raw_store[start_addr + i] = v & 0xFFFF
        # 更新所有已有足够原始数据的配置项
        for cfg in self.configs:
            end = cfg.address + reg_count_for_type(cfg.reg_type)
            if all(a in self._raw_store for a in range(cfg.address, end)):
                self._update_config_value(cfg)

    def get_raw_values(self, start_addr: int, count: int) -> list:
        """读取原始 16 位寄存器值（从站模式）。"""
        return [self._raw_store.get(start_addr + i, 0) for i in range(count)]

    def set_raw_value(self, addr: int, value: int):
        """写入单个原始寄存器值（从站模式被主站写入时）。"""
        self._raw_store[addr] = value & 0xFFFF
        # 更新映射到此地址的配置项
        for cfg in self.configs:
            end = cfg.address + reg_count_for_type(cfg.reg_type)
            if cfg.address <= addr < end:
                self._update_config_value(cfg)

    def _update_config_value(self, cfg: RegisterConfig):
        """根据原始寄存器值更新配置项的解析值。"""
        reg_count = reg_count_for_type(cfg.reg_type)
        raw = [self._raw_store.get(cfg.address + i, 0) for i in range(reg_count)]
        cfg.raw_values = raw
        cfg.value = parse_value(raw, cfg.reg_type)

    # ==================== 主站轮询地址块生成 ====================

    def get_poll_blocks(self) -> list:
        """生成主站轮询的地址块列表。

        返回 [(func_code, start_addr, count), ...]，按功能码分组，组内合并连续地址
        以减少请求数（允许小间隙合并）。
        """
        if not self.configs:
            return []
        by_fc: dict = {}
        for cfg in self.configs:
            by_fc.setdefault(int(cfg.func_code), []).append(
                (cfg.address, reg_count_for_type(cfg.reg_type))
            )
        blocks = []
        for fc in sorted(by_fc):
            ranges = sorted(by_fc[fc], key=lambda x: x[0])
            cur_start, cur_end = ranges[0][0], ranges[0][0] + ranges[0][1]
            for addr, cnt in ranges[1:]:
                if addr <= cur_end + 5:  # 允许小间隙合并
                    cur_end = max(cur_end, addr + cnt)
                else:
                    blocks.append((fc, cur_start, cur_end - cur_start))
                    cur_start, cur_end = addr, addr + cnt
            blocks.append((fc, cur_start, cur_end - cur_start))
        return blocks

    # ==================== 导入/导出 ====================

    def to_list(self) -> list:
        """导出为可序列化的列表。"""
        return [
            {
                "name": c.name,
                "address": c.address,
                "reg_type": c.reg_type,
                "description": c.description,
                "func_code": c.func_code,
            }
            for c in self.configs
        ]

    def from_list(self, data: list):
        """从列表导入。"""
        self.clear()
        for item in data:
            try:
                fc = int(item.get("func_code", 0x03))
            except (TypeError, ValueError):
                fc = 0x03
            self.add(
                name=item.get("name", ""),
                address=item.get("address", 0),
                reg_type=item.get("reg_type", "uint16"),
                description=item.get("description", ""),
                func_code=fc,
            )


def parse_value(raw_values: list, reg_type: str) -> float | int:
    """将原始 16 位寄存器值列表解析为目标数据类型的值。"""
    info = REG_TYPES.get(reg_type)
    if not info:
        return 0
    byte_count, reg_count, fmt, _ = info
    # 将 16 位值列表转为字节
    data = b""
    for v in raw_values[:reg_count]:
        data += struct.pack(">H", v & 0xFFFF)
    if len(data) < byte_count:
        return 0
    try:
        result = struct.unpack(fmt, data[:byte_count])[0]
        # 浮点数保留 4 位小数
        if reg_type.startswith("float"):
            return round(result, 4)
        return result
    except (struct.error, ValueError):
        return 0


def encode_value(value: float | int, reg_type: str) -> list:
    """将值编码为 16 位寄存器值列表（从站模式设置初始值时用）。"""
    info = REG_TYPES.get(reg_type)
    if not info:
        return [int(value) & 0xFFFF]
    byte_count, reg_count, fmt, _ = info
    try:
        data = struct.pack(fmt, value)
    except (struct.error, ValueError):
        return [0] * reg_count
    result = []
    for i in range(0, byte_count, 2):
        result.append(struct.unpack(">H", data[i:i + 2])[0])
    return result
