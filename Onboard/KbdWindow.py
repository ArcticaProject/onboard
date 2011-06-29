
from gi.repository       import GObject, Gdk, Gtk
from Onboard.IconPalette import IconPalette

from gettext import gettext as _

### Logging ###
import logging
_logger = logging.getLogger("KbdWindow")
###############

### Config Singleton ###
from Onboard.Config import Config
config = Config()
########################
class KbdWindowBase:
    """
    Very messy class holds the keyboard widget. The mess is the docked
    window support which is disable because of numerous metacity bugs.
    """
    def __init__(self):
        Gtk.Window.__init__(self)
        _logger.debug("Entered in __init__")
        self.keyboard = None
        self.set_accept_focus(False)
        self.grab_remove()
        self.set_keep_above(True)

        Gtk.Window.set_default_icon_name("onboard")
        self.set_title(_("Onboard"))

        config.geometry_notify_add(lambda x: self.resize(config.width, config.height))
        self.set_default_size(config.width, config.height)
        config.position_notify_add(lambda x: self.move(config.x, config.y))
        self.move(config.x, config.y)

        self.connect("window-state-event", self.cb_state_change)

        self.icp = IconPalette()
        self.icp.connect_object("activated", Gtk.Window.deiconify, self)

        self.show_all()
        if config.start_minimized: self.iconify()
        _logger.debug("Leaving __init__")

    def on_deiconify(self, widget=None):
        self.icp.hide()
        self.move(config.x, config.y) # to be sure that the window manager places it correctly

    def on_iconify(self):
        if config.icp_in_use: self.icp.show()

    def set_keyboard(self, keyboard):
        _logger.debug("Entered in set_keyboard")
        if self.keyboard:
            self.remove(self.keyboard)
        self.keyboard = keyboard
        self.add(self.keyboard)
        self.keyboard.show()
        self.queue_draw()

    def do_set_layout(self, client, cxion_id, entry, user_data):
        _logger.debug("Entered in do_set_layout")
        return

    def do_set_gravity(self, edgeGravity):
        '''
        This will place the window on the edge corresponding to the edge gravity
        '''
        _logger.debug("Entered in do_set_gravity")
        self.edgeGravity = edgeGravity
        width, height = self.get_size()

        geom = self.get_screen().get_monitor_geometry(0)
        eg = self.edgeGravity

        x = 0
        y = 0
        if eg == Gdk.Gravity.SOUTH:
            y = geom.height - height
            y += 29 #to account for panel.

        self.move(x, y)

        GObject.idle_add(self.do_set_strut)

    def do_set_strut(self):
        _logger.debug("Entered in do_set_strut")
        propvals = [0,0,0,0,0,0,0,0,0,0,0,0]
        """propvals = [0,#left
                0, #right
                0, #top
                300,#bottom
                0,#left_start_y
                0,#left_end_y
                0,#right_start_y
                0,#right_end_y
                0,#top_start_x
                0,#top_end_x
                0,#bottom_start_x
                3000]#bottom_end_x"""

        screen = self.get_screen()
        biggestHeight = 0
        for n in range(screen.get_n_monitors()):
            tempHeight = screen.get_monitor_geometry(n).height
            if biggestHeight < tempHeight:
                biggestHeight = tempHeight

        geom = self.get_screen().get_monitor_geometry(0)
        eg = self.edgeGravity
        x, y = self.window.get_origin()

        width,height = self.get_size()

        if eg == Gdk.Gravity.NORTH:
            propvals[2] = height + y
            propvals[9] = width
        elif eg == Gdk.Gravity.SOUTH and y != 0:
            #propvals[2] = y
            #propvals[9] = geom.width - 1
            propvals[3] = biggestHeight - y
            propvals[11] = width - 1

            # tell window manager to not overlap buttons with maximized window
            self.window.property_change("_NET_WM_STRUT_PARTIAL",
                                        "CARDINAL",
                                        32,
                                        Gdk.PropMode.REPLACE,
                                        propvals)
        self.queue_resize_no_redraw()


    def cb_state_change(self, widget, event):
        """
        This is the callback that gets executed when the user hides the
        onscreen keyboard by using the minimize button in the decoration
        of the window.
        """
        _logger.debug("Entered in cb_state_change")
        if event.changed_mask & Gdk.WindowState.ICONIFIED:
            if event.new_window_state & Gdk.WindowState.ICONIFIED:
                self.on_iconify()
            else:
                self.on_deiconify()

    def _hidden(self):
        return self.get_window().get_state() & Gdk.WindowState.ICONIFIED != 0
    hidden = property(_hidden)


class KbdPlugWindow(Gtk.Plug, KbdWindowBase):
    def __init__(self):
        Gtk.Plug.__init__(self)
        KbdWindowBase.__init__(self)

class KbdWindow(Gtk.Window, KbdWindowBase):
    def __init__(self):
        Gtk.Window.__init__(self)
        KbdWindowBase.__init__(self)
        GObject.signal_new("quit-onboard", KbdWindow,
                           GObject.SIGNAL_RUN_LAST,
                           GObject.TYPE_BOOLEAN, ())
        self.connect("delete-event", self._emit_quit_onboard)

    def save_size_and_position(self):
        """
        Save size and position into the corresponding gsettings keys.
        """
        _logger.debug("Entered in save_size_and_position")
        x_pos, y_pos = self.get_position()
        width, height = self.get_size()

        # store new value only if it is different to avoid infinite loop
        config.x = x_pos
        config.y = y_pos
        config.width = width
        config.height = height

    def _emit_quit_onboard(self, event, data=None):
        self.emit("quit-onboard")
