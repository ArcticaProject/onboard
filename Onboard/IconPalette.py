#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Copyright © 2008 Francesco Fumanti <francesco.fumanti@gmx.net>
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

from os.path import join
from traceback import print_exc

from gi.repository import GObject, Gdk, Gtk

import cairo
import math

from Onboard.utils import WindowManipulator, round_corners

### Logging ###
import logging
_logger = logging.getLogger("IconPalette")
###############

### Config Singleton ###
from Onboard.Config import Config
config = Config()
########################

from gettext import gettext as _

class IconPalette(Gtk.Window, WindowManipulator):
    """
    Class that creates a movable and resizable floating window without
    decorations. The window shows the icon of onboard scaled to fit to the
    window and a resize grip that honors the desktop theme in use.

    Onboard offers an option to the user to make the window appear
    whenever the user hides the onscreen keyboard. The user can then
    click on the window to hide it and make the onscreen keyboard
    reappear.
    """

    __gsignals__ = {
        'activated' : (GObject.SIGNAL_RUN_LAST, GObject.TYPE_NONE, ())
    }

    """ Minimum size of the IconPalette """
    MINIMUM_SIZE = 20

    def __init__(self):

        self._last_pos = None
        Gtk.Window.__init__(self,
                            skip_taskbar_hint=True,
                            skip_pager_hint=True,
                            decorated=False,
                            accept_focus=False,
                            opacity=0.75,
                            width_request=self.MINIMUM_SIZE,
                            height_request=self.MINIMUM_SIZE)
        WindowManipulator.__init__(self)

        self.set_keep_above(True)
        self.set_has_resize_grip(False)

        # use transparency if available
        visual = Gdk.Screen.get_default().get_rgba_visual()
        if visual:
            self.set_visual(visual)

        # set up event handling
        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK |
                        Gdk.EventMask.BUTTON_RELEASE_MASK |
                        Gdk.EventMask.POINTER_MOTION_MASK)

        self.connect("button-press-event",   self._cb_button_press_event)
        self.connect("motion-notify-event",  self._cb_motion_notify_event)
        self.connect("button-release-event", self._cb_button_release_event)
        self.connect("draw",                 self._cb_draw)

        # create Gdk resources before moving or resizing the window
        self.realize()

        # default coordinates of the iconpalette on the screen
        self.move(config.icp.x, config.icp.y)
        self.resize(config.icp.width, config.icp.height)

        config.icp.size_notify_add(lambda x:
            self.resize(config.icp.width, config.icp.height))
        config.icp.position_notify_add(lambda x:
            self.move(config.icp.x, config.icp.y))

        # load the onboard icon
        self.icon = self._load_icon()

        # don't get resized by compiz grid plugin (LP: 893644)
        self.set_type_hint(Gdk.WindowTypeHint.UTILITY)

        self.update_sticky_state()

    def update_sticky_state(self):
        if not config.xid_mode:
            if config.window_state_sticky:
                self.stick()
            else:
                self.unstick()

    def _load_icon(self):
        """
        Load the onboard icon and create a cairo surface.
        """
        theme = Gtk.IconTheme.get_default()
        pixbuf = None

        if theme.has_icon("onboard"):
            try:
                pixbuf = theme.load_icon("onboard", 192, 0)
            except:
                print_exc() # bug in oneiric: unsupported icon format svg
                _logger.error(_("Failed to load Onboard icon."))

        if not pixbuf:
            pixbuf = self.render_icon_pixbuf(Gtk.STOCK_MISSING_IMAGE,
                                             Gtk.IconSize.DIALOG)

        self.icon_size = (pixbuf.get_width(), pixbuf.get_height())

        icon = self.get_window().create_similar_surface(cairo.CONTENT_COLOR_ALPHA,
                                                        self.icon_size[0],
                                                        self.icon_size[1])
        cr = cairo.Context(icon)
        Gdk.cairo_set_source_pixbuf(cr, pixbuf, 0, 0)
        cr.paint()

        return icon

    def _cb_button_press_event(self, widget, event):
        """
        Save the pointer position.
        """
        if event.button == 1 and event.window == self.get_window():
            self.enable_drag_protection(True)
            self.handle_press(event, move_on_background = True)
            if self.is_moving():
                self.reset_drag_protection() # force threshold
        return False

    def _cb_motion_notify_event(self, widget, event):
        """
        Move the window if the pointer has moved more than the DND threshold.
        """
        self.handle_motion(event)
        self.set_drag_cursor_at((event.x, event.y))
        return False

    def _cb_button_release_event(self, widget, event):
        """
        Save the window geometry, hide the IconPalette and
        emit the "activated" signal.
        """
        result = False

        if event.button == 1 and \
           event.window == self.get_window() and \
           not self.is_drag_active():
            self.emit("activated")
            result = True

        self.stop_drag()
        self.set_drag_cursor_at((event.x, event.y))

        return result

    def _cb_draw(self, widget, cr):
        """
        Draw the onboard icon.
        """
        if Gtk.cairo_should_draw_window(cr, self.get_window()):
            width = float(self.get_allocated_width())
            height = float(self.get_allocated_height())

            cr.save()
            cr.scale(width / self.icon_size[0], height / self.icon_size[1])
            cr.set_source_surface(self.icon, 0, 0)
            cr.paint()
            cr.restore()

            if Gdk.Screen.get_default().is_composited():
                cr.set_operator(cairo.OPERATOR_CLEAR)
                round_corners(cr, 8, 0, 0, width, height)
                cr.set_operator(cairo.OPERATOR_OVER)

            return True
        return False

    def show(self):
        """
        Override Gtk.Widget.hide() to save the window geometry.
        """
        Gtk.Window.show(self)
        self.update_sticky_state()

    def hide(self):
        """
        Override Gtk.Widget.hide() to save the window geometry.
        """
        if Gtk.Window.get_visible(self):
            config.icp.width, config.icp.height = self.get_size()
            config.icp.x, config.icp.y = self.get_position()
            Gtk.Window.hide(self)


def icp_activated(self):
    Gtk.main_quit()

if __name__ == "__main__":
    icp = IconPalette()
    icp.show()
    icp.connect("activated", icp_activated)
    Gtk.main()


