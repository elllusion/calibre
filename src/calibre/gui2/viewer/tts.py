#!/usr/bin/env python
# License: GPL v3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>

from qt.core import QDialog, QDialogButtonBox, QObject, QVBoxLayout, pyqtSignal

from calibre.gui2 import error_dialog
from calibre.gui2.viewer.config import get_pref_group, vprefs
from calibre.gui2.widgets2 import Dialog

import edge_tts
import asyncio
import tempfile
import sys,os

def set_sync_override(allowed):
    from calibre.gui2.viewer.lookup import set_sync_override
    set_sync_override(allowed)


class Config(Dialog):

    def __init__(self, tts_client, ui_settings, backend_settings, parent):
        self.tts_client = tts_client
        self.ui_settings = ui_settings
        self.backend_settings = backend_settings
        Dialog.__init__(self, _('Configure Read aloud'), 'read-aloud-config', parent, prefs=vprefs)

    def setup_ui(self):
        self.l = l = QVBoxLayout(self)
        self.config_widget = self.tts_client.config_widget(self.backend_settings, self)
        l.addWidget(self.config_widget)
        l.addWidget(self.bb)
        self.config_widget.restore_to_defaults
        b = self.bb.addButton(QDialogButtonBox.StandardButton.RestoreDefaults)
        b.clicked.connect(self.restore_to_defaults)
        self.config_widget.restore_state(vprefs)

    def save_state(self):
        self.config_widget.save_state(vprefs)

    def restore_to_defaults(self):
        self.config_widget.restore_to_defaults()

    def accept(self):
        self.backend_settings = self.config_widget.backend_settings
        return super().accept()


class TTS(QObject):

    dispatch_on_main_thread_signal = pyqtSignal(object)
    event_received = pyqtSignal(object, object)
    settings_changed = pyqtSignal(object)

    def __init__(self, parent=None):
        QObject.__init__(self, parent)
        self._tts_client = None
        self.media = None
        self.voice = None
        self.dispatch_on_main_thread_signal.connect(self.dispatch_on_main_thread)

    def dispatch_on_main_thread(self, func):
        try:
            func()
        except Exception:
            import traceback
            traceback.print_exc()

    @property
    def tts_client_class(self):
        from calibre.gui2.tts.implementation import Client
        return Client

    @property
    def tts_client(self):
        if self._tts_client is None:
            settings = self.backend_settings
            self._tts_client = self.tts_client_class(settings, self.dispatch_on_main_thread_signal.emit)
            if self._tts_client.settings != settings:
                self.backend_settings = self._tts_client.settings
        return self._tts_client

    def shutdown(self):
        if self._tts_client is not None:
            self._tts_client.shutdown()
            self._tts_client = None

    def speak_simple_text(self, text):
        from calibre.gui2.tts.errors import TTSSystemUnavailable
        try:
            self.tts_client.speak_simple_text(text)
        except TTSSystemUnavailable as err:
            #return error_dialog(self.parent(), _('Text-to-Speech unavailable'), str(err), show=True)
            
            asyncio.get_event_loop().run_until_complete(self.get_tts_media(text))
            track = self.tts_client.music_player.load(self.media.name)
            self.tts_client.music_player.play()

    def action(self, action, data):
        from calibre.gui2.tts.errors import TTSSystemUnavailable
        try:
            getattr(self, action)(data)
        except TTSSystemUnavailable as err:
            #return error_dialog(self.parent(), _('Text-to-Speech unavailable'), str(err), show=True)

            buf=[]
            for x in data['marked_text']:
                if isinstance(x, str):
                    buf.append(x)
            text=''.join(buf).strip()

            asyncio.get_event_loop().run_until_complete(self.get_tts_media(text))
            track = self.tts_client.music_player.load(self.media.name)
            self.tts_client.music_player.play()

    async def get_tts_media(self, text) -> None:
        print("----------> {} -> {}:{}".format(self.__class__.__name__, sys._getframe().f_code.co_name, text))
        self.voice = "zh-CN-XiaoxiaoNeural"
        self.media = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
        self.media.close()
        communicate = edge_tts.Communicate('\"'+text+'\"', self.voice)
        await communicate.save(self.media.name)

    def play(self, data):
        set_sync_override(False)
        self.tts_client.speak_marked_text(data['marked_text'], self.callback)

    def pause(self, data):
        set_sync_override(True)
        #self.tts_client.pause()
        self.tts_client.music_player.pause()

    def resume(self, data):
        set_sync_override(False)
        self.tts_client.resume()

    def resume_after_configure(self, data):
        set_sync_override(False)
        self.tts_client.resume_after_configure()

    def callback(self, event):
        data = event.data
        if event.type is event.type.mark:
            data = int(data)
        self.event_received.emit(event.type.name, data)

    def stop(self, data):
        set_sync_override(True)
        #self.tts_client.stop()
        self.tts_client.music_player.stop()

    @property
    def backend_settings(self):
        key = 'tts_' + self.tts_client_class.name
        return vprefs.get(key) or {}

    @backend_settings.setter
    def backend_settings(self, val):
        key = 'tts_' + self.tts_client_class.name
        vprefs.set(key, val or {})

    def configure(self, data):
        ui_settings = get_pref_group('tts').copy()
        d = Config(self.tts_client, ui_settings, self.backend_settings, parent=self.parent())
        if d.exec() == QDialog.DialogCode.Accepted:
            s = d.backend_settings
            self.backend_settings = s
            self.tts_client.apply_settings(s)
            self.settings_changed.emit(d.ui_settings)
        else:
            self.settings_changed.emit(None)
        d.save_state()

    def slower(self, data):
        settings = self.tts_client.change_rate(steps=-1)
        if settings is not None:
            self.backend_settings = settings

    def faster(self, data):
        settings = self.tts_client.change_rate(steps=1)
        if settings is not None:
            self.backend_settings = settings
