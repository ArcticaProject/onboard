
import cairo
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
        _logger.debug("Entered in __init__")

        self.application = None
        self.keyboard = None
        self.supports_alpha = False
        self._default_resize_grip = self.get_has_resize_grip()
        self._visibility_state = 0
        self._iconified = False

        self.set_accept_focus(False)
        self.set_app_paintable(True)
        self.set_keep_above(True)
        self.grab_remove()
        self.set_decorated(config.window_decoration)
        self.update_window_options()

        Gtk.Window.set_default_icon_name("onboard")
        self.set_title(_("Onboard"))

        config.geometry_notify_add(lambda x: self.resize(config.width, config.height))
        self.set_default_size(config.width, config.height)
        config.position_notify_add(lambda x: self.move(config.x, config.y))
        self.move(config.x, config.y)

        self.connect("window-state-event", self.cb_state_change)
        self.connect("visibility-notify-event", self.cb_visibility_notify)

        self.icp = IconPalette()
        self.icp.connect("activated", self.cb_icon_palette_acticated)

        self.connect('screen-changed', self._cb_screen_changed)
        self.connect('composited-changed', self._cb_composited_changed)
        self.check_alpha_support()

        self.show_all()
        #self.get_window().set_override_redirect(True)
        self.set_visible(not config.start_minimized)

        _logger.debug("Leaving __init__")

    def _cb_screen_changed(self, widget, old_screen=None):
        self.check_alpha_support()
        self.queue_draw()

    def _cb_composited_changed(self, widget):
        self.check_alpha_support()
        self.queue_draw()

    def check_alpha_support(self):
        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        self.supports_alpha = visual and screen.is_composited()

        _logger.debug(_("screen changed, supports_alpha={}") \
                       .format(self.supports_alpha))

        if self.supports_alpha:
            self.set_visual(visual)
            if self.keyboard:
                self.keyboard.set_visual(visual)
        else:
            _logger.info(_("no window transparency available;"
                           " screen doesn't support alpha channels"))
        return False

    def update_window_options(self):
        if not config.xid_mode:   # not when embedding
            decorated = config.window_decoration
            if decorated != self.get_decorated():
                self.set_decorated(decorated),

            if not self.get_mapped():
                if config.force_to_top:
                    self.set_type_hint(Gdk.WindowTypeHint.DOCK)
                else:
                    self.set_type_hint(Gdk.WindowTypeHint.NORMAL)

            if config.has_window_decoration():
                self.set_has_resize_grip(self._default_resize_grip)
            else:
                self.set_has_resize_grip(False)

        if False:
            geometry = Gdk.Geometry()
            geometry.min_aspect = geometry.max_aspect = 3.5
            self.set_geometry_hints(self, geometry, Gdk.WindowHints.ASPECT)

    def is_visible(self):
        # via window decoration.
        return Gtk.Window.get_visible(self) and \
               not self._visibility_state & \
                                Gdk.VisibilityState.FULLY_OBSCURED and \
               not self._iconified

    def toggle_visible(self):
        self.set_visible(not self.is_visible())

    def set_visible(self, visible):
        # Gnome-shell in Oneiric doesn't send window-state-event when
        # iconifying. Hide and show the window instead.
        Gtk.Window.set_visible(self, visible)
        if visible:
            if not config.xid_mode:
                # Deiconify in unity, no use in gnome-shell
                # Not in xembed mode, it kills typing in lightdm.
                self.present()  
        self.on_visibility_changed(visible)

    def on_visibility_changed(self, visible):
        if visible:
            self.icp.hide()
            #self.move(config.x, config.y) # to be sure that the window manager places it correctly
        else:
            if config.icp.in_use: 
                self.icp.show()

        # update indicator menu for unity and unity2d
        # not necessary but doesn't hurt in gnome-shell, gnome classic
        if self.application:
            status_icon = self.application.status_icon
            if status_icon:
                status_icon.update_menu_items()

    def cb_visibility_notify(self, widget, event):
        """
        This is the callback that gets executed when the user hides the
        onscreen keyboard by using the minimize button in the decoration
        of the window.
        """
        _logger.debug("Entered in cb_visibility_notify")
        self._visibility_state = event.state
        self.on_visibility_changed(self.is_visible())

    def cb_state_change(self, widget, event):
        """
        This is the callback that gets executed when the user hides the
        onscreen keyboard by using the minimize button in the decoration
        of the window.
        """
        _logger.debug("Entered in cb_state_change")
        if event.changed_mask & Gdk.WindowState.ICONIFIED:
            if event.new_window_state & Gdk.WindowState.ICONIFIED:
                self._iconified = True
            else:
                self._iconified = False
            self.on_visibility_changed(self.is_visible())

    def cb_icon_palette_acticated(self, widget):
        self.toggle_visible()

    def set_keyboard(self, keyboard):
        _logger.debug("Entered in set_keyboard")
        if self.keyboard:
            self.remove(self.keyboard)
        self.keyboard = keyboard
        self.add(self.keyboard)
        self.check_alpha_support()
        self.keyboard.show()
        self.queue_draw()

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


class KbdWindow(KbdWindowBase, Gtk.Window):
    def __init__(self):
        Gtk.Window.__init__(self)
        KbdWindowBase.__init__(self)
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


class KbdPlugWindow(KbdWindowBase, Gtk.Plug):
    def __init__(self):
        Gtk.Plug.__init__(self)
        KbdWindowBase.__init__(self)

    def toggle_visible(self):
        pass

# Do this only once, not in KbdWindows constructor. 
# The main window may be recreated when changing
# the "force_to_top" setting.
GObject.signal_new("quit-onboard", KbdWindow,
                   GObject.SIGNAL_RUN_LAST,
                   GObject.TYPE_BOOLEAN, ())


