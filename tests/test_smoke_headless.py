"""无头冒烟测试：构建主窗口、逐类型建会话、开关通道。"""
import pytest

from serial_net_tool.core.channel import Channel, ChannelStatus


class FakeChannel(Channel):
    """不产生任何真实 I/O 的测试通道。"""

    def __init__(self, session_id):
        super().__init__(session_id)
        self.opened = False

    def open(self, cfg):
        self.opened = True
        self.status = ChannelStatus.CONNECTED

    def close(self):
        self.opened = False
        self.status = ChannelStatus.DISCONNECTED

    def send(self, data):
        self.emit_received(b"echo", {"dir": "in"})


@pytest.fixture
def main_window(qt_app, tmp_config, monkeypatch):
    import serial_net_tool.main_window as mwmod
    from serial_net_tool.core.autoreply import AutoReplyEngine
    from serial_net_tool.core.plugin_manager import PluginManager

    created = []

    def fake_create(kind, sid):
        ch = FakeChannel(sid)
        created.append(ch)
        return ch

    monkeypatch.setattr(mwmod, "create_channel", fake_create)

    autoreply = AutoReplyEngine()
    plugins = PluginManager(tmp_config)
    plugins.discover()
    win = mwmod.MainWindow(tmp_config, autoreply, plugins)
    win._created_channels = created
    yield win
    win.close()


def test_build_window(main_window):
    assert main_window.windowTitle()
    assert main_window.tree.count() == 0  # 无持久化会话


@pytest.mark.parametrize("kind", ["serial", "tcp_client", "tcp_server", "udp", "mqtt"])
def test_add_and_toggle_session(main_window, kind):
    main_window._add_view({"id": kind, "kind": kind, "name": f"T-{kind}", "cfg": {}})
    assert main_window.tree.count() >= 1

    from serial_net_tool.core.i18n import tr

    view = main_window.views[kind]
    view.open_channel(main_window)
    assert view.channel is not None
    assert view.toggle_btn.text() == tr("close")

    # 启动定时发送后关闭，定时器必须停止
    view.body.periodic.setChecked(True)
    view.body._timer.start(1000)
    view.close_channel()
    assert view.channel is None
    assert not view.body._timer.isActive()
    assert view.toggle_btn.text() == tr("open")


def test_rename_keeps_icon(main_window):
    from serial_net_tool.main_window import KIND_ICONS

    main_window._add_view({"id": "s1", "kind": "serial", "name": "orig", "cfg": {}})
    item = main_window.tree.item(0)
    label = main_window._item_label("serial", "renamed")
    assert label.startswith(KIND_ICONS["serial"])
    assert "renamed" in label


def test_tools_panel_tabs_built(main_window):
    # 右侧工具面板内置 Tab 已构建
    assert main_window.tools.tabs.count() >= 6
