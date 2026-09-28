#!/usr/bin/env python
"""本地/CI 通用的打包脚本（PyInstaller）。

把原先散落在 `.github/workflows/build.yml` 里的 PyInstaller 参数收敛到一处，
本地与 CI 使用同一条命令，避免两边参数漂移。

用法：
    python tools/build.py                      # 单文件、无控制台（按当前平台）
    python tools/build.py --console            # 保留控制台窗口（便于排错）
    python tools/build.py --onedir             # 输出目录形式（启动更快）
    python tools/build.py --gen-icon           # 先重绘图标再打包
    python tools/build.py --version v0.3.0    # 额外产出带版本号的文件名
    python tools/build.py --zip                # 额外打包成 zip 便于分发
    python tools/build.py --dry-run            # 只打印将要执行的命令

依赖：
    pip install -r requirements-build.txt
"""
import argparse
import glob
import os
import platform
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 包所在目录的**父目录**：项目根目录本身就是 `serial_net_tool` 包，
# 因此只有在 sys.path 上加入父目录，PyInstaller 才能导入该包，
# `--collect-submodules` 才会真正生效（否则返回空，动态加载的插件会缺失）。
PARENT = os.path.dirname(ROOT)
DIST = os.path.join(ROOT, "dist")
WORK = os.path.join(ROOT, "build")

APP_NAME_DEFAULT = "SerialNetTool"
ENTRY = "launch.py"
PACKAGE = "serial_net_tool"
ICON_WIN = os.path.join("resources", "icon.ico")
ICON_MAC = os.path.join("resources", "icon.icns")

# 运行期依赖的隐藏导入（与 requirements 对应）
HIDDEN_IMPORTS = [
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
    "paho.mqtt.client",
    "serial",
]


def plugin_packages() -> list:
    """扫描 plugins/ 下的插件包，返回其完整模块名。

    PluginManager 通过 importlib 动态导入插件，静态分析看不到这些 import，
    必须显式声明为 hidden import，否则打包后插件会加载失败。
    """
    out = []
    for path in sorted(glob.glob(os.path.join(ROOT, "plugins", "*"))):
        if os.path.isdir(path) and os.path.exists(os.path.join(path, "__init__.py")):
            out.append(f"{PACKAGE}.plugins.{os.path.basename(path)}")
    return out


def _data_sep() -> str:
    """PyInstaller --add-data 的路径分隔符（Windows 用 ';'）。"""
    return ";" if os.name == "nt" else ":"


def collect_data_args() -> list:
    """收集需要随包分发的数据文件（图标 + 插件 manifest）。"""
    sep = _data_sep()
    args = []
    if os.path.exists(os.path.join(ROOT, ICON_WIN)):
        args += ["--add-data", f"{ICON_WIN}{sep}resources"]
    # 插件 manifest（PluginManager 依据 __file__ 定位到 serial_net_tool/plugins/<id>/）
    for path in sorted(glob.glob(os.path.join("plugins", "*", "plugin.json"))):
        plugin_dir = os.path.dirname(path).replace("\\", "/")
        target = f"serial_net_tool/{plugin_dir}"
        args += ["--add-data", f"{path}{sep}{target}"]
    return args


def pick_icon() -> str:
    """按平台选择图标文件。"""
    if sys.platform == "darwin" and os.path.exists(os.path.join(ROOT, ICON_MAC)):
        return ICON_MAC
    if os.path.exists(os.path.join(ROOT, ICON_WIN)):
        return ICON_WIN
    return ""


def build_command(args) -> list:
    """组装 PyInstaller 命令行。"""
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--name", args.name,
        "--onefile" if args.onefile else "--onedir",
        "--windowed" if not args.console else "--console",
        "--clean",
        "--noconfirm",
        "--paths", PARENT,               # 让分析阶段能解析 serial_net_tool 包
        "--collect-submodules", PACKAGE,
    ]
    for imp in HIDDEN_IMPORTS:
        cmd += ["--hidden-import", imp]
    for pkg in plugin_packages():         # 动态加载的插件需显式声明
        cmd += ["--hidden-import", pkg]
    cmd += collect_data_args()
    icon = pick_icon()
    if icon and not args.no_icon:
        cmd += ["--icon", icon]
    if args.debug:
        cmd.append("--debug=all")
    cmd.append(ENTRY)
    return cmd


def build_env() -> dict:
    """构造子进程环境：把包所在父目录加入 PYTHONPATH。

    `--collect-submodules` 在 PyInstaller 处理参数阶段就会导入该包，
    因此必须让构建进程本身可导入 `serial_net_tool`（仅 `--paths` 不够）。
    """
    env = dict(os.environ)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = PARENT + (os.pathsep + existing if existing else "")
    return env


def check_env():
    """检查 PyInstaller 与入口文件是否就绪。"""
    if not os.path.exists(os.path.join(ROOT, ENTRY)):
        sys.exit(f"[build] 未找到入口文件 {ENTRY}（请在项目根目录运行）")
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        sys.exit(
            "[build] 未安装 PyInstaller，请先执行：\n"
            "        pip install -r requirements-build.txt"
        )


def regenerate_icon():
    """重新生成多尺寸图标（需要 Pillow，仅生成期使用）。"""
    script = os.path.join(ROOT, "tools", "gen_icon.py")
    print("[build] 重新生成图标 …")
    subprocess.run([sys.executable, script], cwd=ROOT, check=True)


def artifact_path(name: str) -> str:
    """打包产物路径（区分文件/目录形式与平台后缀）。"""
    if os.name == "nt":
        suffix = ".exe"
    elif sys.platform == "darwin":
        suffix = ".app"
    else:
        suffix = ""
    if not os.path.isfile(os.path.join(DIST, name + suffix)) and not os.path.isdir(
        os.path.join(DIST, name + suffix)
    ):
        # 目录形式在 macOS 为 .app，其它平台无后缀
        if os.path.isdir(os.path.join(DIST, name)):
            return os.path.join(DIST, name)
    return os.path.join(DIST, name + suffix)


def _arch() -> str:
    """归一化架构名（与 CI 的 matrix.arch 保持一致，如 x64）。"""
    machine = (platform.machine() or "").lower()
    return {
        "amd64": "x64",
        "x86_64": "x64",
        "i386": "x86",
        "i686": "x86",
        "aarch64": "arm64",
        "arm64": "arm64",
    }.get(machine, machine or "x64")


def rename_with_version(name: str, version: str) -> str:
    """按 CI 约定重命名产物：<Name>-<version>-<OS>-<arch><ext>。"""
    src = artifact_path(name)
    if not version or not os.path.exists(src):
        return src
    base, ext = os.path.splitext(src)
    os_name = platform.system().lower()
    dst = f"{base}-{version}-{os_name}-{_arch()}{ext}"
    if os.path.exists(dst):
        if os.path.isdir(dst):
            shutil.rmtree(dst)
        else:
            os.remove(dst)
    shutil.move(src, dst)
    return dst


def make_zip(path: str) -> str:
    """把产物压缩为 zip（目录形式整体打包）。"""
    archive = shutil.make_archive(path, "zip", root_dir=os.path.dirname(path),
                                  base_dir=os.path.basename(path))
    return archive


def human_size(path: str) -> str:
    if os.path.isdir(path):
        total = sum(
            os.path.getsize(os.path.join(dp, f))
            for dp, _dn, fn in os.walk(path)
            for f in fn
        )
    else:
        total = os.path.getsize(path)
    for unit in ("B", "KB", "MB", "GB"):
        if total < 1024 or unit == "GB":
            return f"{total:.1f} {unit}"
        total /= 1024
    return f"{total:.1f} GB"


def main():
    parser = argparse.ArgumentParser(
        description="打包串口与网络调试工具（本地与 CI 通用）"
    )
    parser.add_argument("--name", default=APP_NAME_DEFAULT, help="可执行文件名")
    parser.add_argument("--console", action="store_true", help="保留控制台窗口")
    parser.add_argument("--onedir", dest="onefile", action="store_false",
                        help="输出目录形式（默认单文件）")
    parser.add_argument("--debug", action="store_true", help="打开 PyInstaller 调试输出")
    parser.add_argument("--no-icon", action="store_true", help="不设置可执行文件图标")
    parser.add_argument("--gen-icon", action="store_true", help="打包前重绘图标")
    parser.add_argument("--version", default="", help="额外产出带版本号的产物名")
    parser.add_argument("--zip", action="store_true", help="额外压缩为 zip")
    parser.add_argument("--dry-run", action="store_true", help="只打印命令不执行")
    parser.set_defaults(onefile=True)
    args = parser.parse_args()

    os.chdir(ROOT)
    cmd = build_command(args)

    if args.dry_run:
        print("[build] 工作目录:", ROOT)
        print("[build] 命令:")
        print("  " + " ".join(cmd))
        return

    check_env()
    if args.gen_icon:
        regenerate_icon()

    print(f"[build] 目标平台: {platform.system()} {platform.machine()}")
    print(f"[build] 输出形式: {'单文件' if args.onefile else '目录'}"
          f"{'，保留控制台' if args.console else ''}")
    icon = pick_icon()
    print(f"[build] 应用图标: {icon or '(未设置)'}")
    print(f"[build] 插件包: {', '.join(plugin_packages()) or '(无)'}")
    print("[build] 开始打包（首次执行需要几分钟）…")

    started = time.time()
    result = subprocess.run(cmd, cwd=ROOT, env=build_env())
    if result.returncode != 0:
        sys.exit(f"[build] 打包失败，退出码 {result.returncode}")

    out = artifact_path(args.name)
    if not os.path.exists(out):
        sys.exit(f"[build] 未找到产物: {out}")

    print(f"[build] 完成，用时 {time.time() - started:.0f}s")
    print(f"[build] 产物: {out}  ({human_size(out)})")

    if args.version:
        out = rename_with_version(args.name, args.version)
        print(f"[build] 重命名: {out}")

    if args.zip:
        archive = make_zip(out)
        print(f"[build] 压缩包: {archive}  ({human_size(archive)})")


if __name__ == "__main__":
    main()
