"""插件管理器：发现、崩溃隔离、启用状态。"""
import os

from serial_net_tool.core.plugin_manager import PluginManager


_GOOD = '''
NAME = "Good Plugin"
VERSION = "1.0"
TOOL_TYPE = "dock"

def create_widget(ctx=None):
    return None
'''

_BROKEN = '''
raise RuntimeError("boom at import")
'''


def _write_plugin(root, pid, source):
    d = os.path.join(root, pid)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "__init__.py"), "w", encoding="utf-8") as f:
        f.write(source)
    return d


def _entry(pm, pid):
    return next(p for p in pm.plugins if p["id"] == pid)


def test_discover_good_and_broken(qt_app, tmp_path, tmp_config):
    root = str(tmp_path / "plugins")
    _write_plugin(root, "good", _GOOD)
    _write_plugin(root, "broken", _BROKEN)

    pm = PluginManager(tmp_config)
    pm.discover(extra_dirs=[root])

    good = _entry(pm, "good")
    assert good["error"] is None
    assert good["name"] == "Good Plugin"
    assert good["tool_type"] == "dock"
    assert callable(good["widget_factory"])

    bad = _entry(pm, "broken")
    assert bad["error"]  # 异常被隔离并记录
    # 好插件仍可实例化（构建 QWidget 需要 QApplication，故用 qt_app fixture）
    assert any(name == "Good Plugin" for name, _ in pm.dock_widgets())


def test_disabled_state_restored(qt_app, tmp_path, tmp_config):
    root = str(tmp_path / "plugins")
    _write_plugin(root, "good", _GOOD)
    tmp_config.set("disabled_plugins", ["good"])

    pm = PluginManager(tmp_config)
    pm.discover(extra_dirs=[root])
    assert _entry(pm, "good")["enabled"] is False
    assert all(name != "Good Plugin" for name, _ in pm.dock_widgets())


def test_manifest_provides_metadata(tmp_path, tmp_config):
    root = str(tmp_path / "plugins")
    d = _write_plugin(root, "manifested", 'def create_widget(ctx=None):\n    return None\n')
    with open(os.path.join(d, "plugin.json"), "w", encoding="utf-8") as f:
        f.write(
            '{"id": "mp", "name": "Manifested", "version": "2.1", '
            '"author": "tester", "description": "d", "tool_type": "window"}'
        )
    pm = PluginManager(tmp_config)
    pm.discover(extra_dirs=[root])
    # manifest 的 id 覆盖目录名
    p = _entry(pm, "mp")
    assert p["name"] == "Manifested"
    assert p["version"] == "2.1"
    assert p["author"] == "tester"
    assert p["tool_type"] == "window"
    assert p["error"] is None


def test_manifest_module_attrs_take_priority(tmp_path, tmp_config):
    root = str(tmp_path / "plugins")
    d = _write_plugin(root, "over", 'NAME = "FromModule"\nTOOL_TYPE = "dock"\n'
                                    'def create_widget(ctx=None):\n    return None\n')
    with open(os.path.join(d, "plugin.json"), "w", encoding="utf-8") as f:
        f.write('{"name": "FromManifest", "tool_type": "window"}')
    pm = PluginManager(tmp_config)
    pm.discover(extra_dirs=[root])
    p = _entry(pm, "over")
    assert p["name"] == "FromModule"
    assert p["tool_type"] == "dock"


def test_manifest_min_app_version_gate(tmp_path, tmp_config):
    root = str(tmp_path / "plugins")
    d = _write_plugin(root, "future", 'def create_widget(ctx=None):\n    return None\n')
    with open(os.path.join(d, "plugin.json"), "w", encoding="utf-8") as f:
        f.write('{"name": "Future", "min_app_version": "999.0.0"}')
    pm = PluginManager(tmp_config)
    pm.discover(extra_dirs=[root])
    assert _entry(pm, "future")["error"]

def test_missing_create_widget_flagged(tmp_path, tmp_config):
    root = str(tmp_path / "plugins")
    _write_plugin(root, "nofunc", 'NAME = "No Func"\n')
    pm = PluginManager(tmp_config)
    pm.discover(extra_dirs=[root])
    assert _entry(pm, "nofunc")["error"]
