#!/usr/bin/env python3
"""TP-7 system tray helper for Linux — connect/disconnect with one click."""

import os
import sys
import threading
import subprocess
import time

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('AyatanaAppIndicator3', '0.1')
from gi.repository import Gtk, GLib, AyatanaAppIndicator3

from pyudev import Context, Monitor, MonitorObserver

# Import the existing TP-7 logic
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tp7_linux


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

ICONS = {
    "disconnected": "icon_dim",
    "midi": "icon_active",
    "mtp": "icon_active",
}

LABELS = {
    "disconnected": "TP-7: Not connected",
    "midi": "TP-7: Connected (MIDI mode)",
    "mtp": "TP-7: Connected (MTP mode)",
}


class TP7Tray:
    def __init__(self):
        self.state = "disconnected"
        self._worker = None  # track the active worker thread
        self._last_busy = False

        self.indicator = AyatanaAppIndicator3.Indicator.new_with_path(
            "tp7-tray",
            ICONS["disconnected"],
            AyatanaAppIndicator3.IndicatorCategory.HARDWARE,
            SCRIPT_DIR,
        )
        self.indicator.set_status(AyatanaAppIndicator3.IndicatorStatus.ACTIVE)
        self.indicator.set_title("TP-7")

        self.menu = Gtk.Menu()
        self.indicator.set_menu(self.menu)

        # Initial device check
        GLib.idle_add(self._update_once)

        # USB hotplug monitoring
        self._start_usb_monitor()

        # Poll every 3 seconds
        GLib.timeout_add_seconds(3, self._update)

    # ── UI ────────────────────────────────────────────────────────

    @property
    def busy(self):
        return self._worker is not None and self._worker.is_alive()

    def _update(self):
        """Poll device state and rebuild menu only on change."""
        try:
            dev, mode = tp7_linux.find_tp7()
        except Exception:
            dev, mode = None, None

        if not dev:
            new_state = "disconnected"
        elif mode == "mtp":
            new_state = "mtp"
        else:
            new_state = "midi"

        was_busy = self._last_busy
        is_busy = self.busy
        self._last_busy = is_busy

        if new_state != self.state or was_busy != is_busy:
            self.state = new_state
            self.indicator.set_icon_full(ICONS[self.state], LABELS[self.state])
            self._build_menu()

        return True  # keep timer alive

    def _build_menu(self):
        for child in self.menu.get_children():
            self.menu.remove(child)

        # Status label
        status = Gtk.MenuItem(label=LABELS[self.state])
        status.set_sensitive(False)
        self.menu.append(status)
        self.menu.append(Gtk.SeparatorMenuItem())

        if self.busy:
            item = Gtk.MenuItem(label="Working...")
            item.set_sensitive(False)
            self.menu.append(item)
        elif self.state == "midi":
            connect = Gtk.MenuItem(label="Connect (switch to MTP)")
            connect.connect("activate", self._on_connect)
            self.menu.append(connect)
        elif self.state == "mtp":
            gvfs_path = tp7_linux.find_gvfs_mount()
            if gvfs_path:
                try:
                    subdirs = os.listdir(gvfs_path)
                    mount = os.path.join(gvfs_path, subdirs[0]) if subdirs else gvfs_path
                except OSError:
                    mount = gvfs_path
                open_item = Gtk.MenuItem(label="Open Files")
                open_item.connect("activate", lambda _, p=mount: subprocess.Popen(["xdg-open", p]))
                self.menu.append(open_item)

            disconnect = Gtk.MenuItem(label="Disconnect")
            disconnect.connect("activate", self._on_disconnect)
            self.menu.append(disconnect)

        self.menu.append(Gtk.SeparatorMenuItem())
        quit_item = Gtk.MenuItem(label="Quit")
        quit_item.connect("activate", lambda _: Gtk.main_quit())
        self.menu.append(quit_item)
        self.menu.show_all()

    # ── Actions ───────────────────────────────────────────────────

    def _on_connect(self, _):
        if self.busy:
            return
        self._worker = threading.Thread(target=self._do_connect, daemon=True)
        self._worker.start()

    def _do_connect(self):
        try:
            dev, mode = tp7_linux.find_tp7()
            if dev and mode == "midi":
                tp7_linux.switch_to_mtp(dev)
                time.sleep(2)
                tp7_linux.wait_for_mtp(timeout=8)
        except Exception as e:
            print(f"Connect error: {e}", flush=True)

    def _on_disconnect(self, _):
        if self.busy:
            return
        self._worker = threading.Thread(target=self._do_disconnect, daemon=True)
        self._worker.start()

    def _do_disconnect(self):
        try:
            tp7_linux.unmount_gvfs()
            time.sleep(2)
            dev, mode = tp7_linux.find_tp7()
            if dev and mode == "mtp":
                tp7_linux.switch_to_midi(dev)
                time.sleep(2)
                tp7_linux.wait_for_midi(timeout=8)
        except Exception as e:
            print(f"Disconnect error: {e}", flush=True)

    def _update_once(self):
        """One-shot update triggered by USB events. Does not repeat."""
        self._update()
        return False

    # ── USB hotplug ───────────────────────────────────────────────

    def _start_usb_monitor(self):
        ctx = Context()
        mon = Monitor.from_netlink(ctx)
        mon.filter_by(subsystem='usb')

        def on_event(device):
            vendor = device.get('ID_VENDOR_ID', '')
            product = device.get('ID_MODEL_ID', '')
            if vendor == '2367' and product == '0019':
                GLib.timeout_add(1500, self._update_once)

        self._observer = MonitorObserver(mon, callback=on_event)
        self._observer.daemon = True
        self._observer.start()


def main():
    app = TP7Tray()
    try:
        Gtk.main()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
