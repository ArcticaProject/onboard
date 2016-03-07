# -*- coding: utf-8 -*-

# Copyright © 2010 Chris Jones <tortoise@tortuga>
# Copyright © 2010 Francesco Fumanti <francesco.fumanti@gmx.net>
# Copyright © 2011-2015 marmuta <marmvta@gmail.com>
#
# This file is part of Onboard.
#
# Onboard is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# Onboard is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.

from __future__ import division, print_function, unicode_literals

import os
import subprocess

try:
    import dbus
    from Onboard.DBusUtils import ServiceBase, dbus_property
except ImportError:
    pass

from Onboard.Version import require_gi_versions
require_gi_versions()
from gi.repository import GObject, Gtk

from Onboard.definitions import StatusIconProviderEnum
from Onboard.utils import unicode_str, run_script

import logging
_logger = logging.getLogger("Indicator")

from Onboard.Config import Config
config = Config()


class ContextMenu(GObject.GObject):
    __gsignals__ = {
        str('quit-onboard') : (GObject.SignalFlags.RUN_LAST,
                               GObject.TYPE_NONE, ())
    }

    def __init__(self, keyboard=None):
        GObject.GObject.__init__(self)

        self._keyboard = keyboard

        self._show_label = _("_Show Onboard")
        self._hide_label = _("_Hide Onboard")

        self._menu = self.create_menu()

    def set_keyboard(self, keyboard):
        self._keyboard = keyboard

    def get_gtk_menu(self):
        return self._menu

    def create_menu(self):
        menu = Gtk.Menu()

        # This updates the menu in gnome-shell and gnome-classic,
        # but not in unity or unity2D.
        menu.connect_object("show", ContextMenu.update_items, self)

        show_item = Gtk.MenuItem.new_with_label(self._show_label)
        show_item.set_use_underline(True)
        show_item.connect_object("activate",
                                 ContextMenu.on_show_keyboard_toggle, self)
        menu.append(show_item)

        if not config.lockdown.disable_preferences:
            # Translators: label of a menu item. It used to be stock item
            # STOCK_PREFERENCES until Gtk 3.10 deprecated those.
            settings_item = Gtk.MenuItem.new_with_label(_("_Preferences"))
            settings_item.set_use_underline(True)
            settings_item.connect("activate", self._on_settings_clicked)
            menu.append(settings_item)

        item = Gtk.SeparatorMenuItem.new()
        menu.append(item)

        help_item = Gtk.MenuItem.new_with_label(_("_Help"))
        help_item.set_use_underline(True)
        help_item.connect("activate", self._on_help)
        menu.append(help_item)

        if not config.lockdown.disable_quit:
            item = Gtk.SeparatorMenuItem.new()
            menu.append(item)

            # Translators: label of a menu item. It used to be stock item
            # STOCK_QUIT until Gtk 3.10 deprecated those.
            quit_item = Gtk.MenuItem.new_with_label(_("_Quit"))
            quit_item.set_use_underline(True)
            quit_item.connect("activate", self._on_quit)
            menu.append(quit_item)

        menu.show_all()

        return menu

    def popup(self, button, activate_time,
              data=None, menu_position_func=None):
        """
        Callback called when status icon right clicked.  Produces menu.
        """
        self._menu.popup(None, None,
                         menu_position_func, data,
                         button, activate_time)

    def update_items(self):
        if self._keyboard:
            if self._keyboard.is_visible():
                self._menu.get_children()[0].set_label(self._hide_label)
            else:
                self._menu.get_children()[0].set_label(self._show_label)

    def _on_settings_clicked(self, widget):
        run_script("sokSettings")

    def on_show_keyboard_toggle(self):
        self._keyboard.toggle_visible()

    def _on_help(self, data=None):
        subprocess.Popen(["/usr/bin/yelp", "help:onboard"])

    def _on_quit(self, data=None):
        _logger.debug("Entered _on_quit")
        self.emit("quit-onboard")


class Indicator():

    "Keyboard window managed by this indicator"
    _keyboard = None

    "Menu attached to backend"
    _menu = None

    def __new__(cls, *args, **kwargs):
        """
        Singleton magic.
        """
        if not hasattr(cls, "self"):
            cls.self = object.__new__(cls, *args, **kwargs)
            cls.self.init()
        return cls.self

    def __init__(self):
        """
        This constructor is still called multiple times.
        Do nothing here and use the singleton constructor "init()" instead.
        """
        pass

    def init(self):

        self._menu = ContextMenu()

        sip = config.status_icon_provider

        if sip == StatusIconProviderEnum.GtkStatusIcon:
            backends = [BackendGtkStatusIcon]
        elif sip == StatusIconProviderEnum.AppIndicator:
            backends = [BackendAppIndicator]
        elif sip == StatusIconProviderEnum.StatusNotifier:
            backends = [BackendStatusNotifier]
        else:
            backends = [BackendStatusNotifier,
                        BackendAppIndicator,
                        BackendGtkStatusIcon]

        self._backend = None
        for backend in backends:
            try:
                self._backend = backend(self._menu)
                break
            except RuntimeError as ex:
                _logger.info("Status icon provider: '{}' unavailable: {}"
                             .format(backend.__name__, unicode_str(ex)))

        _logger.info("Status icon provider: '{}' selected"
                     .format(backend.__name__))

        if self._backend:
            self._backend.set_visible(False)

    def set_keyboard(self, keyboard):
        self._keyboard = keyboard
        self._menu.set_keyboard(keyboard)

    def get_menu(self):
        return self._menu

    def update_menu_items(self):
        self._menu.update_items()

    def set_visible(self, visible):
        self._backend.set_visible(visible)


class BackendBase():

    _menu = None

    category = "ApplicationStatus"
    icon_desc = _("Onboard on-screen keyboard")
    icon_name = "onboard"
    id = "Onboard"
    title = _("Onboard on-screen keyboard")

    def __init__(self, menu):
        self._menu = menu

    def get_menu(self):
        return self._menu


class BackendGtkStatusIcon(BackendBase):

    _status_icon = None

    def __init__(self, menu):
        BackendBase.__init__(self, menu)

        self._status_icon = Gtk.StatusIcon(icon_name=self.icon_name)
        self._status_icon.connect("activate",
                                  lambda x:
                                  self._menu.on_show_keyboard_toggle())
        self._status_icon.connect("popup-menu",
                                  self._on_status_icon_popup_menu)

    def set_visible(self, visible):
        self._status_icon.set_visible(visible)

    def _on_status_icon_popup_menu(self, status_icon, button, activate_time):
        """
        Callback called when status icon right clicked.  Produces menu.
        """
        self._menu.popup(button, activate_time,
                         status_icon, self._menu_position_func)

    def _menu_position_func(self, menu, *args):
        gtk_menu = self._menu.get_gtk_menu()

        # Work around gi annotation bug in gtk-3.0:
        # gtk_status_icon_position_menu() doesn't mark 'push_in' as inout
        # which is required for any (*GtkMenuPositionFunc)
        # Precise: args = (status_icon,)
        if len(args) == 1:    # in Precise
            status_icon, = args
            return Gtk.StatusIcon.position_menu(gtk_menu, status_icon)
        elif len(args) == 2:  # in <=Oneiric?
            push_in, status_icon = args
            return Gtk.StatusIcon.position_menu(gtk_menu, status_icon)
        elif len(args) == 3:  # in <=Xenial?
            x, y, status_icon = args
            return Gtk.StatusIcon.position_menu(gtk_menu, x, y, status_icon)


class BackendAppIndicator(BackendBase):

    _indicator = None

    def __init__(self, menu):
        BackendBase.__init__(self, menu)

        try:
            from gi.repository import AppIndicator3 as AppIndicator
        except ImportError as ex:
            raise RuntimeError(ex)

        self._indicator = AppIndicator.Indicator.new(
            self.id,
            self.icon_name,
            AppIndicator.IndicatorCategory.APPLICATION_STATUS)
        self._indicator.set_icon_full(self.icon_name,
                                      self.icon_desc)

        self._indicator.set_menu(menu._menu)
        self._indicator.set_secondary_activate_target(
            menu._menu.get_children()[0])

    def set_visible(self, visible):
        self._set_indicator_active(visible)

    def _set_indicator_active(self, active):
        try:
            from gi.repository import AppIndicator3 as AppIndicator
        except ImportError:
            pass
        else:
            if active:
                self._indicator.set_status(
                    AppIndicator.IndicatorStatus.ACTIVE)
            else:
                self._indicator.set_status(
                    AppIndicator.IndicatorStatus.PASSIVE)


class BackendStatusNotifier(BackendBase):
    """
    Direct D-Bus implementation of a KDE StatusNotifier.
    Very similar to AppIndicator, but with support for
    left-click activation in KDE Plasma.

    References:
    https://www.freedesktop.org/wiki/Specifications/StatusNotifierItem
    """

    WATCHER_NAME = "org.kde.StatusNotifierWatcher"
    WATCHER_OBJECT = "/StatusNotifierWatcher"
    WATCHER_INTERFACE = "org.kde.StatusNotifierWatcher"

    def __init__(self, menu):
        BackendBase.__init__(self, menu)

        if "dbus" not in globals():
            raise RuntimeError("python-dbus unavailable")

        try:
            self._bus = dbus.SessionBus()
        except dbus.exceptions.DBusException as ex:
            raise RuntimeError("D-Bus session bus unavailable: " +
                               unicode_str(ex))

        self._service = ServiceNotificationItem(self)

        self._bus.add_signal_receiver(self._on_name_owner_changed,
                                      "NameOwnerChanged",
                                      dbus.BUS_DAEMON_IFACE,
                                      arg0=self.WATCHER_NAME)

        proxy = self._bus.get_object(dbus.BUS_DAEMON_NAME, dbus.BUS_DAEMON_PATH)
        result = proxy.NameHasOwner(self.WATCHER_NAME, dbus_interface=dbus.BUS_DAEMON_IFACE)
        self._set_connection(bool(result))

    def _on_name_owner_changed(self, name, old, new):
        active = old == ""
        if active:
            self.launcher.stop()
        self._set_connection(active)

    def _set_connection(self, active):
        if active:
            proxy = self._bus.get_object(self.WATCHER_NAME, self.WATCHER_OBJECT)
            proxy.RegisterStatusNotifierItem(self._service.bus_name)
        else:
            self._iface = None

    def set_visible(self, visible):
        pass


if "dbus" in globals():
    class ServiceNotificationItem(ServiceBase):

        ITEM_NAME = "org.kde.StatusNotifierItem"
        ITEM_OBJECT = "/StatusNotifierItem"
        ITEM_IFACE = "org.kde.StatusNotifierItem"

        def __init__(self, backend):
            self._backend = backend

            # Bus name according to
            # https://www.freedesktop.org/wiki/Specifications/StatusNotifierItem
            pid = os.getpid()
            id_ = 1
            self.bus_name = "{}-{}-{}".format(self.ITEM_NAME, pid, id_)

            ServiceBase.__init__(self, self.bus_name, self.ITEM_OBJECT)

        @dbus.service.method(dbus_interface=ITEM_IFACE, in_signature="ii")
        def Activate(self, x, y):  # noqa: flake8
            menu = self._backend.get_menu()
            menu.on_show_keyboard_toggle()

        @dbus_property(dbus_interface=ITEM_IFACE, signature="s")
        def Category(self):  # noqa: flake8
            return self._backend.category

        @dbus_property(dbus_interface=ITEM_IFACE, signature="s")
        def IconName(self):  # noqa: flake8
            return self._backend.icon_name

        @dbus_property(dbus_interface=ITEM_IFACE, signature="s")
        def Id(self):  # noqa: flake8
            return self._backend.id

        @dbus_property(dbus_interface=ITEM_IFACE, signature="b")
        def ItemIsMenu(self):  # noqa: flake8
            return False

        #@dbus_property(dbus_interface=ITEM_IFACE, signature="o")
        #def Menu(self):  # noqa: flake8
        #    return "/StatusNotifierItem/menu"

        @dbus_property(dbus_interface=ITEM_IFACE, signature="s")
        def Title(self):  # noqa: flake8
            return self._backend.title

        if 0:
            @dbus_property(dbus_interface=ITEM_IFACE, signature="(sa(iiay)ss)")
            def ToolTip(self):  # noqa: flake8
                return (self._backend.icon_name,
                        [],
                        "",
                        "")

