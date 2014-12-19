# -*- coding: utf-8 -*-

from __future__ import division, print_function, unicode_literals

from gi.repository import GObject, Gtk

from Onboard.definitions import StatusIconProviderEnum
import Onboard.utils as utils

### Logging ###
import logging
_logger = logging.getLogger("Indicator")
###############

### Config Singleton ###
from Onboard.Config import Config
config = Config()
########################


class ContextMenu(GObject.GObject):
    __gsignals__ = {
        str('quit-onboard') : (GObject.SIGNAL_RUN_LAST, GObject.TYPE_NONE, ())
    }

    def __init__(self, keyboard=None):
        GObject.GObject.__init__(self)

        self._keyboard = keyboard

        self._show_label = _("_Show Onboard")
        self._hide_label = _("_Hide Onboard")

        self._menu = self.create_menu()

    def set_keyboard(self, keyboard):
        self._keyboard = keyboard

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
        utils.run_script("sokSettings")

    def on_show_keyboard_toggle(self):
        self._keyboard.toggle_visible()

    def _on_quit(self, data=None):
        _logger.debug("Entered _on_quit")
        self.emit("quit-onboard")


class Indicator():

    "Keyboard window managed by this indicator"
    _keyboard = None

    "Encapsulated appindicator instance"
    _indicator = None

    "Encapsulated GtkStatusIcon instance"
    _status_icon = None

    "Menu attached to indicator"
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

        if config.status_icon_provider == StatusIconProviderEnum.GtkStatusIcon:
            self._init_status_icon()
        else:
            try:
                self._init_indicator()
            except ImportError as ex:
                _logger.info("AppIndicator not available, falling back on"
                             " GtkStatusIcon:" + utils.unicode_str(ex))
                self._init_status_icon()
        self.set_visible(False)

    def set_keyboard(self, keyboard):
        self._keyboard = keyboard
        self._menu.set_keyboard(keyboard)

    def get_menu(self):
        return self._menu

    def _init_indicator(self):
        from gi.repository import AppIndicator3 as AppIndicator
        self._indicator = AppIndicator.Indicator.new(
            "Onboard",
            "onboard",
            AppIndicator.IndicatorCategory.APPLICATION_STATUS)
        self._indicator.set_icon_full("onboard", _("Onboard on-screen keyboard"))

        self._indicator.set_menu(self._menu._menu)
        self._indicator.set_secondary_activate_target( \
                                                self._menu._menu.get_children()[0])

    def _init_status_icon(self):
        self._status_icon = Gtk.StatusIcon(icon_name="onboard")
        self._status_icon.connect("activate",
                                  self._menu.on_show_keyboard_toggle)
        self._status_icon.connect("popup-menu",
                                  self._on_status_icon_popup_menu)

    def update_menu_items(self):
        self._menu.update_items()

    def _menu_position_func(self, menu, *args):
        # Work around gi annotation bug in gtk-3.0:
        # gtk_status_icon_position_menu() doesn't mark 'push_in' as inout
        # which is required for any (*GtkMenuPositionFunc)
        if len(args) == 1:    # in Precise
            status_icon, = args
        elif len(args) == 2:  # in <=Oneiric?
            push_in, status_icon = args
        return Gtk.StatusIcon.position_menu(self._menu, status_icon)

    def set_visible(self, visible):
        if self._status_icon:
            # Then we've falled back to using GtkStatusIcon
            self._status_icon.set_visible(visible)
        else:
            self._set_indicator_active(visible)

    def _on_status_icon_popup_menu(self, status_icon, button, activate_time):
        """
        Callback called when status icon right clicked.  Produces menu.
        """
        self._menu.popup(button, activate_time,
                         status_icon, self._menu_position_func)

    def _set_indicator_active(self, active):
        try:
            from gi.repository import AppIndicator3 as AppIndicator
        except ImportError:
            pass
        else:
            if active:
                self._indicator.set_status(AppIndicator.IndicatorStatus.ACTIVE)
            else:
                self._indicator.set_status(AppIndicator.IndicatorStatus.PASSIVE)

    def is_appindicator(self):
        if self._indicator:
            return True
        else:
            return False

