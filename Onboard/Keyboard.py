### Logging ###
import logging
_logger = logging.getLogger("Keyboard")
###############

import string

from gi.repository import GObject, Gtk, Gdk

from gettext import gettext as _

from Onboard.KeyGtk import *
from Onboard import KeyCommon
from Onboard.MouseControl import MouseController
from Onboard.utils import Timer

try:
    from Onboard.utils import run_script, get_keysym_from_name, dictproperty
except DeprecationWarning:
    pass

### Config Singleton ###
from Onboard.Config import Config
config = Config()
########################

### Logging ###
import logging
_logger = logging.getLogger("Keyboard")
###############

class UnpressTimer(Timer):
    """ Redraw key unpressed after a short while """

    def __init__(self, keyboard):
        self._keyboard = keyboard
        self._key = None

    def start(self, key):
        self._key = key
        Timer.start(self, 0.08)

    def reset(self):
        Timer.stop(self)
        self.draw_unpressed()

    def on_timer(self):
        self.draw_unpressed()
        return False

    def draw_unpressed(self):
        if self._key:
            self._key.pressed = False
            self._keyboard.redraw(self._key)
            self._key = None


class Keyboard:
    "Cairo based keyboard widget"

    active_scan_key = None # Key currently being scanned.
    scanning_x = None
    scanning_y = None

    color_scheme = None
    alt_locked = False
    layer_locked = False

### Properties ###

    # The number of pressed keys per modifier
    _mods = {1:0,2:0, 4:0,8:0, 16:0,32:0,64:0,128:0}
    def _get_mod(self, key):
        return self._mods[key]
    def _set_mod(self, key, value):
        self._mods[key] = value
        self._on_mods_changed()
    mods = dictproperty(_get_mod, _set_mod)

    # currently active layer
    def _get_active_layer_index(self):
        return config.active_layer_index
    def _set_active_layer_index(self, index):
        config.active_layer_index = index
    active_layer_index = property(_get_active_layer_index,
                                  _set_active_layer_index)

    def _get_active_layer(self):
        layers = self.get_layers()
        if not layers:
            return None
        index = self.active_layer_index
        if index < 0 or index >= len(layers):
            index = 0
        return layers[index]
    def _set_active_layer(self, layer):
        index = 0
        for i, layer in enumerate(self.get_layers()):
            if layer is layer:
                index = i
                break
        self.active_layer_index = index
    active_layer = property(_get_active_layer, _set_active_layer)

    def assure_valid_active_layer(self):
        """
        Reset layer index if it is out of range. e.g. due to
        loading a layout with fewer panes.
        """
        index = self.active_layer_index
        if index < 0 or index >= len(self.get_layers()):
            self.active_layer_index = 0

##################

    def __init__(self, vk):
        self.vk = vk
        self.unpress_timer = UnpressTimer(self)

    def destruct(self):
        self.cleanup()

    def initial_update(self):
        """ called when the layout has been loaded """

        #List of keys which have been latched.
        #ie. pressed until next non sticky button is pressed.
        self._latched_sticky_keys = []
        self._locked_sticky_keys = []

        self.canvas_rect = Rect()
        self.button_controllers = {}
        self.editing_snippet = False

        self._last_canvas_extents = None

        # connect button controllers to button keys
        types = [BCMiddleClick, BCSingleClick, BCSecondaryClick, BCDoubleClick, BCDragClick,
                 BCHoverClick,
                 BCHide, BCShowClick, BCMove, BCPreferences, BCQuit,
                ]
        for key in self.layout.iter_keys():
            if key.is_layer_button():
                bc = BCLayer(self, key)
                bc.layer_index = key.get_layer_index()
                self.button_controllers[key] = bc
            else:
                for type in types:
                    if type.id == key.id:
                        self.button_controllers[key] = type(self, key)

        self.assure_valid_active_layer()
        self.update_ui()

    def get_layers(self):
        if self.layout:
            return self.layout.get_layer_ids()
        return []

    def iter_keys(self, group_name=None):
        """ iterate through all keys or all keys of a group """
        if self.layout:
            return self.layout.iter_keys(group_name)
        else:
            return []

    def utf8_to_unicode(self,utf8Char):
        return ord(utf8Char.decode('utf-8'))

    def get_scan_columns(self):
        for item in self.layout.iter_layer_items(self.active_layer):
            if item.scan_columns:
                return item.scan_columns
        return None

    def scan_tick(self): #at intervals scans across keys in the row and then down columns.
        if self.active_scan_key:
            self.active_scan_key.scanned = False

        columns = self.get_scan_columns()
        if columns:
            if not self.scanning_y == None:
                self.scanning_y = (self.scanning_y + 1) % len(columns[self.scanning_x])
            else:
                self.scanning_x = (self.scanning_x + 1) % len(columns)

            if self.scanning_y == None:
                y = 0
            else:
                y = self.scanning_y

            key_id = columns[self.scanning_x][y]
            keys = self.find_keys_from_ids([key_id])
            if keys:
                self.active_scan_key = keys[0]
                self.active_scan_key.scanned = True

            self.queue_draw()

        return True

    def get_key_at_location(self, location):
        if not self.layout:   # don't fail on exit
            return None

        # First try all keys of the active layer
        for item in reversed(list(self.layout.iter_layer_keys(self.active_layer))):
            if item.visible and item.is_point_within(location):
                return item

        # Then check all non-layer keys (layer switcher, hide, etc.)
        for item in reversed(list(self.layout.iter_layer_keys(None))):
            if item.visible and item.is_point_within(location):
                return item

    def cb_dialog_response(self, dialog, response, snippet_id, \
                           label_entry, text_entry):
        if response == Gtk.ResponseType.OK:
            label = label_entry.get_text().decode("utf-8")
            text = text_entry.get_text().decode("utf-8")
            config.set_snippet(snippet_id, (label, text))
        dialog.destroy()
        self.editing_snippet = False

    def cb_macroEntry_activate(self,widget,macroNo,dialog):
        self.set_new_macro(macroNo, gtk.RESPONSE_OK, widget, dialog)

    def set_new_macro(self,macroNo,response,macroEntry,dialog):
        if response == gtk.RESPONSE_OK:
            config.set_snippet(macroNo, macroEntry.get_text())

        dialog.destroy()

    def _on_mods_changed(self):
        raise NotImplementedException()

    def press_key(self, key, button = 1):
        if not key.sensitive:
            return

        # unpress the previous key
        self.unpress_timer.reset() 

        key.pressed = True

        if not key.active:
            if self.mods[8]:
                self.alt_locked = True
                self.vk.lock_mod(8)

        if not key.sticky or not key.active:
            # press key
            self.send_press_key(key, button)

            # Modifier keys may change multiple keys -> redraw everything
            if key.action_type == KeyCommon.MODIFIER_ACTION:
                self.redraw()

        self.redraw(key)

    def release_key(self, key, button = 1):
        if not key.sensitive:
            return

        if key.sticky:
            disable_locked_state = config.lockdown.disable_locked_state

            # special case caps-lock key:
            # CAPS skips latched state and goes directly
            # into the locked position.
            if not key.active and \
               (not key.id in ["CAPS"] or \
                disable_locked_state):
                key.active = True
                self._latched_sticky_keys.append(key)

            elif not key.locked and \
                 not disable_locked_state:
                if key in self._latched_sticky_keys: # not CAPS
                    self._latched_sticky_keys.remove(key)
                self._locked_sticky_keys.append(key)
                key.active = True
                key.locked = True

            else:
                if key in self._latched_sticky_keys: # with disable_locked_state
                    self._latched_sticky_keys.remove(key)
                if key in self._locked_sticky_keys:
                    self._locked_sticky_keys.remove(key)
                self.send_release_key(key)
                key.active = False
                key.locked = False
                if key.action_type == KeyCommon.MODIFIER_ACTION:
                    self.redraw()   # redraw the whole keyboard
        else:
            self.send_release_key(key, button)

            # Don't release latched modifiers for click buttons right now.
            # Keep modifier keys unchanged until the actual click happens
            # -> allow clicks with modifiers
            if not key.is_layer_button() and \
               not (key.action_type == KeyCommon.BUTTON_ACTION and \
                key.id in ["middleclick", "secondaryclick"]):
                # release latched modifiers
                self.release_latched_sticky_keys()

            # switch to layer 0
            if not key.is_layer_button() and \
               not key.id in ["move", "showclick"] and \
               not self.editing_snippet:
                if self.active_layer_index != 0 and not self.layer_locked:
                    self.active_layer_index = 0
                    self.redraw()

        self.update_controllers()
        self.update_layout()

        # Draw key unpressed after a short while to give visual
        # feedback of the key press.
        self.unpress_timer.start(key)

    def send_press_key(self, key, button=1):

        if key.action_type == KeyCommon.CHAR_ACTION:
            self.vk.press_unicode(self.utf8_to_unicode(key.action))

        elif key.action_type == KeyCommon.KEYSYM_ACTION:
            self.vk.press_keysym(key.action)
        elif key.action_type == KeyCommon.KEYPRESS_NAME_ACTION:
            self.vk.press_keysym(get_keysym_from_name(key.action))
        elif key.action_type == KeyCommon.MODIFIER_ACTION:
            mod = key.action

            if not mod == 8: #Hack since alt puts metacity into move mode and prevents clicks reaching widget.
                self.vk.lock_mod(mod)
            self.mods[mod] += 1
        elif key.action_type == KeyCommon.MACRO_ACTION:
            snippet_id = string.atoi(key.action)
            mlabel, mString = config.snippets.get(snippet_id, (None, None))
            if mString:
                self.press_key_string(mString)

            elif not config.xid_mode:  # block dialog in xembed mode
                dialog = Gtk.Dialog(_("New snippet"),
                                    self.get_toplevel(), 0,
                                    (Gtk.STOCK_CANCEL,
                                     Gtk.ResponseType.CANCEL,
                                     _("_Save snippet"),
                                     Gtk.ResponseType.OK))

                dialog.set_default_response(Gtk.ResponseType.OK)

                box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                              spacing=12, border_width=5)
                dialog.get_content_area().add(box)

                msg = Gtk.Label(_("Enter a new snippet for this button:"),
                                xalign=0.0)
                box.add(msg)

                label_entry = Gtk.Entry(hexpand=True)
                text_entry  = Gtk.Entry(hexpand=True)
                label_label = Gtk.Label(_("_Button label:"),
                                        xalign=0.0,
                                        use_underline=True,
                                        mnemonic_widget=label_entry)
                text_label  = Gtk.Label(_("S_nippet:"),
                                        xalign=0.0,
                                        use_underline=True,
                                        mnemonic_widget=text_entry)

                grid = Gtk.Grid(row_spacing=6, column_spacing=3)
                grid.attach(label_label, 0, 0, 1, 1)
                grid.attach(text_label, 0, 1, 1, 1)
                grid.attach(label_entry, 1, 0, 1, 1)
                grid.attach(text_entry, 1, 1, 1, 1)
                box.add(grid)

                dialog.connect("response", self.cb_dialog_response, \
                               snippet_id, label_entry, text_entry)
                label_entry.grab_focus()
                dialog.show_all()
                self.editing_snippet = True

        elif key.action_type == KeyCommon.KEYCODE_ACTION:
            self.vk.press_keycode(key.action)

        elif key.action_type == KeyCommon.SCRIPT_ACTION:
            if not config.xid_mode:  # block settings dialog in xembed mode
                if key.action:
                    run_script(key.action)

        elif key.action_type == KeyCommon.BUTTON_ACTION:
            controller = self.button_controllers.get(key)
            if controller:
                controller.press(button)

    def release_latched_sticky_keys(self, except_keys = None):
        """ release latched sticky (modifier) keys """
        if len(self._latched_sticky_keys) > 0:
            for key in self._latched_sticky_keys[:]:
                if not except_keys or not key in except_keys:
                    self.send_release_key(key)
                    self._latched_sticky_keys.remove(key)
                    key.active = False

            # modifiers may change many key labels -> redraw everything
            self.redraw()

    def release_locked_sticky_keys(self):
        """ release locked sticky (modifier) keys """
        if len(self._locked_sticky_keys) > 0:
            for key in self._locked_sticky_keys[:]:
                self.send_release_key(key)
                self._locked_sticky_keys.remove(key)
                key.active = False
                key.locked = False
                key.pressed = False

            # modifiers may change many key labels -> redraw everything
            self.redraw()

    def send_release_key(self,key, button = 1):
        if key.action_type == KeyCommon.CHAR_ACTION:
            self.vk.release_unicode(self.utf8_to_unicode(key.action))
        elif key.action_type == KeyCommon.KEYSYM_ACTION:
            self.vk.release_keysym(key.action)
        elif key.action_type == KeyCommon.KEYPRESS_NAME_ACTION:
            self.vk.release_keysym(get_keysym_from_name(key.action))
        elif key.action_type == KeyCommon.KEYCODE_ACTION:
            self.vk.release_keycode(key.action);
        elif key.action_type == KeyCommon.MACRO_ACTION:
            pass
        elif key.action_type == KeyCommon.SCRIPT_ACTION:
            pass
        elif key.action_type == KeyCommon.BUTTON_ACTION:
            controller = self.button_controllers.get(key)
            if controller:
                controller.release(button)
        elif key.action_type == KeyCommon.MODIFIER_ACTION:
            mod = key.action

            if not mod == 8:
                self.vk.unlock_mod(mod)

            self.mods[mod] -= 1

        if self.alt_locked:
            self.alt_locked = False
            self.vk.unlock_mod(8)

    def press_key_string(self, keystr):
        """
        Send key presses for all characters in a unicode string
        and keep track of the changes in input_line.
        """
        capitalize = False

        keystr = keystr.replace(u"\\n", u"\n")

        if self.vk:   # may be None in the last call before exiting
            for ch in keystr:
                if ch == u"\b":   # backspace?
                    keysym = get_keysym_from_name("backspace")
                    self.vk.press_keysym  (keysym)
                    self.vk.release_keysym(keysym)

                elif ch == u"\x0e":  # set to upper case at sentence begin?
                    capitalize = True

                elif ch == u"\n":
                    # press_unicode("\n") fails in gedit.
                    # -> explicitely send the key symbol instead
                    keysym = get_keysym_from_name("return")
                    self.vk.press_keysym  (keysym)
                    self.vk.release_keysym(keysym)
                else:             # any other printable keys
                    self.vk.press_unicode(ord(ch))
                    self.vk.release_unicode(ord(ch))

        return capitalize

    def update_ui(self):
        """ Force update of everything """
        self.update_controllers()
        self.update_layout()
        self.update_font_sizes()

    def update_controllers(self):
        # update buttons
        for controller in self.button_controllers.values():
            controller.update()

    def update_layout(self):
        layout = self.layout
        if not layout:
            return

        # show/hide layers
        layers = layout.get_layer_ids()
        if layers:
            layout.set_visible_layers([layers[0], self.active_layer])

        # recalculate items rectangles
        rect = self.canvas_rect.deflate(config.get_frame_width())
        #keep_aspect = config.xid_mode and self.supports_alpha()
        keep_aspect = False
        layout.fit_inside_canvas(rect, keep_aspect)

        # Give toolkit dependent keyboardGTK a chance to
        # update the aspect ratio of the main window
        self.on_layout_updated()

    def on_outside_click(self):
        # release latched modifier keys
        mc = config.clickmapper
        if mc.get_click_button() != mc.PRIMARY_BUTTON:
            self.release_latched_sticky_keys()

        self.update_controllers()

    def get_mouse_controller(self):
        if config.mousetweaks and \
           config.mousetweaks.is_active():
            return config.mousetweaks
        return config.clickmapper

    def cleanup(self):
        # resets still latched and locked modifier keys on exit
        self.release_latched_sticky_keys()
        self.release_locked_sticky_keys()
        self.unpress_timer.stop()

        for key in self.iter_keys():
            if key.pressed and key.action_type in \
                [KeyCommon.CHAR_ACTION,
                 KeyCommon.KEYSYM_ACTION,
                 KeyCommon.KEYPRESS_NAME_ACTION,
                 KeyCommon.KEYCODE_ACTION]:

                # Release still pressed enter key when onboard gets killed
                # on enter key press.
                _logger.debug(_("Releasing still pressed key '{}'") \
                             .format(key.id))
                self.send_release_key(key)

        # Somehow keyboard objects don't get released
        # when switching layouts, there are still
        # excess references/memory leaks somewhere.
        # We need to manually release virtkey references or
        # Xlib runs out of client connections after a couple
        # dozen layout switches.
        self.vk = None
        self.layout = None  # free the memory

    def find_keys_from_ids(self, key_ids):
        if self.layout is None:
            return []
        return self.layout.find_ids(key_ids)



class ButtonController(object):
    """
    MVC inspired controller that handles events and the resulting
    state changes of buttons.
    """
    def __init__(self, keyboard, key):
        self.keyboard = keyboard
        self.key = key

    def press(self, button):
        """ button pressed """
        pass

    def long_press(self, button):
        """ button pressed long """
        pass

    def release(self, button):
        """ button released """
        pass

    def update(self):
        """ asynchronous ui update """
        pass

    def can_dwell(self):
        """ can start dwelling? """
        return False

    def can_long_press(self):
        """ can start long press? """
        return False

    def set_visible(self, visible):
        if self.key.visible != visible:
            self.key.visible = visible
            self.keyboard.redraw(self.key)

    def set_sensitive(self, sensitive):
        if self.key.sensitive != sensitive:
            self.key.sensitive = sensitive
            self.keyboard.redraw(self.key)

    def set_active(self, active = None):
        if not active is None and self.key.active != active:
            self.key.active = active
            self.keyboard.redraw(self.key)

    def set_locked(self, locked = None):
        if not locked is None and self.key.locked != locked:
            self.key.active = locked
            self.key.locked = locked
            self.keyboard.redraw(self.key)


class BCClick(ButtonController):
    """ Controller for click buttons """
    def release(self, button):
        mc = self.keyboard.get_mouse_controller()
        if self.is_active():
            # stop click mapping, resets to primary button and single click
            mc.set_click_params(MouseController.PRIMARY_BUTTON,
                                MouseController.CLICK_TYPE_SINGLE)
        else:
            # Exclude click type buttons from the click mapping.
            # to be able to reliably cancel the click.
            # -> They will receive only single left clicks.
            rects = self.keyboard.get_click_type_button_rects()
            config.clickmapper.set_exclusion_rects(rects)

            # start the click mapping
            mc.set_click_params(self.button, self.click_type)

    def update(self):
        mc = self.keyboard.get_mouse_controller()
        self.set_active(self.is_active())
        self.set_sensitive(
            mc.supports_click_params(self.button, self.click_type))

    def is_active(self):
        mc = self.keyboard.get_mouse_controller()
        return mc.get_click_button() == self.button and \
               mc.get_click_type() == self.click_type

class BCSingleClick(BCClick):
    id = "singleclick"
    button = MouseController.PRIMARY_BUTTON
    click_type = MouseController.CLICK_TYPE_SINGLE

class BCMiddleClick(BCClick):
    id = "middleclick"
    button = MouseController.MIDDLE_BUTTON
    click_type = MouseController.CLICK_TYPE_SINGLE

class BCSecondaryClick(BCClick):
    id = "secondaryclick"
    button = MouseController.SECONDARY_BUTTON
    click_type = MouseController.CLICK_TYPE_SINGLE

class BCDoubleClick(BCClick):
    id = "doubleclick"
    button = MouseController.PRIMARY_BUTTON
    click_type = MouseController.CLICK_TYPE_DOUBLE

class BCDragClick(BCClick):
    id = "dragclick"
    button = MouseController.PRIMARY_BUTTON
    click_type = MouseController.CLICK_TYPE_DRAG

    def release(self, button):
        BCClick. release(self, button)
        self.keyboard.show_touch_handles(self.can_show_handles())

    def update(self):
        active = self.key.active
        BCClick.update(self)

        if active and not self.key.active:
            # hide the touch handles
            self.keyboard.show_touch_handles(self.can_show_handles())

    def can_show_handles(self):
        return self.is_active() and \
               config.mousetweaks and config.mousetweaks.is_active() and \
               not config.xid_mode

class BCHoverClick(ButtonController):

    id = "hoverclick"

    def release(self, button):
        config.enable_hover_click(not config.mousetweaks.is_active())

    def update(self):
        available = bool(config.mousetweaks)
        active    = config.mousetweaks.is_active() \
                    if available else False

        self.set_sensitive(available and \
                           not config.lockdown.disable_hover_click)
        # force locked color for better visibility
        self.set_locked(active)
        #self.set_active(config.mousetweaks.is_active())

    def can_dwell(self):
        return not (config.mousetweaks and config.mousetweaks.is_active())

class BCHide(ButtonController):

    id = "hide"

    def release(self, button):
        self.keyboard.toggle_visible()

    def update(self):
        self.set_sensitive(not config.xid_mode) # insensitive in XEmbed mode

class BCShowClick(ButtonController):

    id = "showclick"

    def release(self, button):
        config.show_click_buttons = not config.show_click_buttons

        # enable hover click when the key was dwell-activated
        # disabled for now, seems too confusing
        if False:
            if button == self.keyboard.DWELL_ACTIVATED and \
               config.show_click_buttons and \
               not config.mousetweaks.is_active():
                config.enable_hover_click(True)

    def update(self):
        allowed = not config.lockdown.disable_click_buttons

        self.set_visible(allowed)

        # Don't show active state. Toggling the click column
        # should be enough feedback.
        #self.set_active(config.show_click_buttons)

        # show/hide click buttons
        show_click = config.show_click_buttons and allowed
        layout = self.keyboard.layout
        if layout:
            for item in layout.iter_items():
                if item.group == 'click':
                    item.visible = show_click
                if item.group == 'noclick':
                    item.visible = not show_click


    def can_dwell(self):
        return not config.mousetweaks or not config.mousetweaks.is_active()

class BCMove(ButtonController):

    id = "move"

    def press(self, button):
        self.keyboard.start_move_window()

    def long_press(self, button):
        self.keyboard.show_touch_handles(True)

    def release(self, button):
        self.keyboard.stop_move_window()

    def update(self):
        self.set_visible(not config.has_window_decoration())
        self.set_sensitive(not config.xid_mode)

    def can_long_press(self):
        return not config.xid_mode

class BCLayer(ButtonController):
    """ layer switch button, switches to layer <layer_index> when released """

    layer_index = None

    def _get_id(self):
        return "layer" + str(self.layer_index)
    id = property(_get_id)

    def release(self, button):
        layer_index = self.key.get_layer_index()
        if self.keyboard.active_layer_index != layer_index:
            self.keyboard.active_layer_index = layer_index
            self.keyboard.layer_locked = False
            self.keyboard.redraw()
        elif self.layer_index != 0:
            if not self.keyboard.layer_locked and \
               not config.lockdown.disable_locked_state:
                self.keyboard.layer_locked = True
            else:
                self.keyboard.active_layer_index = 0
                self.keyboard.layer_locked = False
                self.keyboard.redraw()

    def update(self):
        # don't show active state for layer 0, it'd be visible all the time
        active = self.key.get_layer_index() != 0 and \
                  self.key.get_layer_index() == self.keyboard.active_layer_index
        self.set_active(active)
        self.set_locked(active and self.keyboard.layer_locked)


class BCPreferences(ButtonController):

    id = "settings"

    def release(self, button):
        run_script("sokSettings")

    def update(self):
        self.set_sensitive(not config.xid_mode and \
                           not config.running_under_gdm and \
                           not config.lockdown.disable_preferences)

class BCQuit(ButtonController):

    id = "quit"

    def release(self, button):
        self.keyboard.emit_quit_onboard()

    def update(self):
        self.set_sensitive(not config.xid_mode and not config.lockdown.disable_quit)

