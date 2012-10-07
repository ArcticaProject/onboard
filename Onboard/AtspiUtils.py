# -*- coding: utf-8 -*-
""" GTK specific keyboard class """

from __future__ import division, print_function, unicode_literals

from Onboard.utils        import Rect, EventSource, Process

### Logging ###
import logging
_logger = logging.getLogger("KeyboardGTK")
###############

from gi.repository import GObject
try:
    from gi.repository import Atspi
except ImportError as e:
    _logger.info(_("Atspi unavailable, auto-hide won't be available"))


class AsyncEvent:
    """
    Decouple AT-SPI events from D-Bus callbacks to to reduce the risk for deadlocks.
    """
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class AtspiStateTracker(EventSource):
    """
    Keeps track of the currently active accessible by listening
    to AT-SPI focus events.
    """

    _focus_listeners_registered = False
    _keystroke_listeners_registered = False
    _text_listeners_registered = False
    _focused_accessible = None

    _focus_event_names      = ["text-entry-activated"]
    _text_event_names       = ["text-changed", "text-caret-moved"]
    _key_stroke_event_names = ["key-pressed"]
    _event_names = ["focus-changed"] + \
                   _focus_event_names + \
                   _text_event_names + \
                   _key_stroke_event_names

    def __init__(self):
        EventSource.__init__(self, self._event_names)

        self._last_accessible = None
        self._last_accessible_active = None
        self._state = {}
        self._frozen = False

    def cleanup(self):
        EventSource.cleanup(self)
        self._register_atspi_listeners(False)

    def connect(self, event_name, callback):
        EventSource.connect(self, event_name, callback)
        self._update_listeners()

    def disconnect(self, event_name, callback):
        EventSource.disconnect(self, event_name, callback)
        self._update_listeners()

    def _update_listeners(self):
        register = self.has_listeners(self._focus_event_names)
        self._register_atspi_focus_listeners(register)

        register = self.has_listeners(self._text_event_names)
        self._register_atspi_text_listeners(register)

        register = self.has_listeners(self._key_stroke_event_names)
        self._register_atspi_keystroke_listeners(register)

    def _register_atspi_listeners(self, register):
        self._register_atspi_focus_listeners(register)
        self._register_atspi_text_listeners(register)
        self._register_atspi_keystroke_listeners(register)

    def _register_atspi_focus_listeners(self, register):
        if not "Atspi" in globals():
            return

        if self._focus_listeners_registered != register:

            if register:
                Atspi.EventListener.register_no_data( \
                    self._on_atspi_global_focus, "focus")
                Atspi.EventListener.register_no_data( \
                    self._on_atspi_object_focus, "object:state-changed:focused")
                
                # private asynchronous event
                EventSource.connect(self, "focus-changed",
                                      self._on_focus_changed)
            else:
                Atspi.EventListener.deregister_no_data( \
                    self._on_atspi_global_focus, "focus")
                Atspi.EventListener.deregister_no_data( \
                    self._on_atspi_object_focus, "object:state-changed:focused")

                EventSource.disconnect(self, "focus-changed",
                                      self._on_focus_changed)

            self._focus_listeners_registered = register

    def _register_atspi_text_listeners(self, register):
        if self._text_listeners_registered != register:
            if register:
                Atspi.EventListener.register_no_data( \
                    self._on_atspi_text_changed, "object:text-changed")
                Atspi.EventListener.register_no_data( \
                    self._on_atspi_text_caret_moved, "object:text-caret-moved")

            else:
                Atspi.EventListener.deregister_no_data( \
                    self._on_atspi_text_changed, "object:text-changed")
                Atspi.EventListener.deregister_no_data( \
                    self._on_atspi_text_caret_moved, "object:text-caret-moved")

        self._text_listeners_registered = register

    def _register_atspi_keystroke_listeners(self, register):
        if self._keystroke_listeners_registered != register:
            modifier_masks = range(16)

            if register:
                self._keystroke_listener = \
                        Atspi.DeviceListener.new(self._on_atspi_keystroke, None)

                for modifier_mask in modifier_masks:
                    Atspi.register_keystroke_listener( \
                                        self._keystroke_listener,
                                        None,        # key set, None=all
                                        modifier_mask,
                                        Atspi.KeyEventType.PRESSED,
                                        Atspi.KeyListenerSyncType.SYNCHRONOUS)
            else:
                # Apparently any single deregister call will turn off 
                # all the other registered modifier_masks too. Since
                # deregistering takes extremely long (~2.5s for 16 calls)
                # seize the opportunity and just pick a single arbitrary
                # mask (Quantal).
                modifier_masks = [2]

                for modifier_mask in modifier_masks:
                    Atspi.deregister_keystroke_listener(
                                        self._keystroke_listener,
                                        None, # key set, None=all
                                        modifier_mask,
                                        Atspi.KeyEventType.PRESSED)

                self._keystroke_listener = None

        self._keystroke_listeners_registered = register

    def freeze(self):
        """
        Freeze AT-SPI message processing, e.g. while displaying
        a dialog or popoup menu.
        """
        self._register_atspi_listeners(False)
        self._frozen = True

    def thaw(self):
        """
        Resume AT-SPI message processing.
        """
        self._update_listeners()
        self._frozen = False

    def emit_async(self, event_name, *args, **kwargs):
        if not self._frozen:
            EventSource.emit_async(self, event_name, *args, **kwargs)

    ########## synchronous handlers ##########

    def _on_atspi_global_focus(self, event):
        self._on_atspi_focus(event, True)

    def _on_atspi_object_focus(self, event):
        self._on_atspi_focus(event)

    def _on_atspi_focus(self, event, focus_received = False):
        focused = bool(focus_received) or bool(event.detail1) # received focus?
        ae = AsyncEvent(accessible = event.source,
                        focused    = focused)
        self.emit_async("focus-changed", ae)

    def _on_atspi_text_changed(self, event):
        if event.source is self._focused_accessible:
            #print("_on_atspi_text_changed", event.detail1, event.detail2, event.source, event.type, event.type.endswith("delete"))
            insert = event.type.endswith("insert")
            delete = event.type.endswith("delete")
            if insert or delete:
                ae = AsyncEvent(pos    = event.detail1,
                                length = event.detail2,
                                insert = insert)
                self.emit_async("text-changed", ae)
            else:
                _logger.error("_on_atspi_text_changed: unknown event type '{}'" \
                              .format(event.type))
        return False

    def _on_atspi_text_caret_moved(self, event):
        if event.source is self._focused_accessible:
#            print("_on_atspi_text_caret_moved", event.detail1, event.detail2, event.source, event.type, event.source.get_name(), event.source.get_role())
            ae = AsyncEvent(caret = event.detail1)
            self.emit_async("text-caret-moved", ae)
        return False

    def _on_atspi_keystroke(self, event, data):
        #print("_on_atspi_keystroke",event, event.modifiers, event.hw_code, event.id, event.is_text, event.type, event.event_string)
        if event.type == Atspi.EventType.KEY_PRESSED_EVENT:
            ae = AsyncEvent(hw_code   = event.hw_code,
                            modifiers = event.modifiers)
            self.emit_async("key-pressed", ae)

        return False # don't consume event

    ########## asynchronous handlers ##########

    def _on_focus_changed(self, event):
        accessible = event.accessible
        focused = event.focused
        self._state = {}

        # Don't access the accessible while frozen. This leads to deadlocks
        # while displaying Onboard's own dialogs/popup menu's.
        if not self._frozen:
            self._log_accessible(accessible, focused)

            if accessible:
                try:
                    self._state = self._read_accessible_state(accessible)
                except: # private exception gi._glib.GError when gedit became unresponsive
                   _logger.warning("Invalid accessible, failed to read state")

                editable = self._is_accessible_editable(self._state)
                visible =  focused and editable

                active = visible
                if focused:
                    self._focused_accessible = accessible
                elif not focused and self._focused_accessible == accessible:
                    self._focused_accessible = None
                else:
                    active = False

                if not self._last_accessible is self._focused_accessible or \
                   self._last_accessible_active != active:
                    self._last_accessible = self._focused_accessible
                    self._last_accessible_active = active

                    self.emit("text-entry-activated", accessible, active)

    def get_state(self):
        """ All available state of the focused accessible """
        if self._focused_accessible:
            return self._state
        return {}
 
    def get_role(self):
        """ Role of the focused accessible """
        if self._focused_accessible:
            return self._state.get("role")
        return None
 
    def get_state_set(self):
        """ State set of the focused accessible """
        if self._focused_accessible:
            return self._state.get("state")
        return None
 
    def get_extents(self):
        """ Screen rect of the focused accessible """

        if self._focused_accessible:
            return self._state.get("extents", Rect())
        return Rect()

    def _is_accessible_editable(self, acc_state):
        """ Is this an accessible onboard should be shown for? """

        role  = acc_state.get("role")
        state = acc_state.get("state-set")
        if not state is None:

            if role in [Atspi.Role.TEXT,
                        Atspi.Role.TERMINAL,
                        Atspi.Role.DATE_EDITOR,
                        Atspi.Role.PASSWORD_TEXT,
                        Atspi.Role.EDITBAR,
                        Atspi.Role.ENTRY,
                        Atspi.Role.DOCUMENT_TEXT,
                        Atspi.Role.DOCUMENT_FRAME,
                        Atspi.Role.DOCUMENT_EMAIL,
                        Atspi.Role.SPIN_BUTTON,
                        Atspi.Role.COMBO_BOX,
                        Atspi.Role.DATE_EDITOR,
                        Atspi.Role.PARAGRAPH,      # LibreOffice Writer
                        Atspi.Role.HEADER,
                        Atspi.Role.FOOTER,
                       ]:
                if role in [Atspi.Role.TERMINAL] or \
                   (not state is None and state.contains(Atspi.StateType.EDITABLE)):
                    return True
        return False

    def _read_accessible_state(self, accessible):
        """
        Read attributes and find out as much as we
        can about the accessibles purpose.
        """
        state = {}

        interfaces = accessible.get_interfaces()
        state["id"] = accessible.get_id()
        state["role"] = accessible.get_role()
        state["state-set"] = accessible.get_state_set()
        state["name"] = accessible.get_name()
        state["attributes"] = accessible.get_attributes()
        state["interfaces"] = interfaces

        ext = accessible.get_extents(Atspi.CoordType.SCREEN)
        state["extents"] = Rect(ext.x, ext.y, ext.width, ext.height)

        pid = accessible.get_process_id()
        state["process-id"] = pid
        if pid != -1:
            state["process-name"] = Process.get_process_name(pid)

        app = accessible.get_application()
        if app:
            state["app-name"] = app.get_name()
            state["app-description"] = app.get_description()

        return state

    def _log_accessible(self, accessible, focused):
        if _logger.isEnabledFor(logging.DEBUG):
            msg = "AT-SPI focus event: focused={}, ".format(focused)
            if not accessible:
                msg += "accessible={}".format(accessible)
            else:
                try:
                    role = accessible.get_role()
                except: # private exception gi._glib.GError when gedit became unresponsive
                    role = None

                try:
                    role_name = accessible.get_role_name()
                except: # private exception gi._glib.GError when gedit became unresponsive
                    role_name = None

                try:
                    state_set = accessible.get_state_set()
                    states = state_set.states
                    editable = state_set.contains(Atspi.StateType.EDITABLE) \
                               if state_set else None
                except: # private exception gi._glib.GError when gedit became unresponsive
                    states = None
                    editable = None

                try:
                    ext = accessible.get_extents(Atspi.CoordType.SCREEN)
                    extents   = Rect(ext.x, ext.y, ext.width, ext.height)
                except: # private exception gi._glib.GError when gedit became unresponsive
                    extents = None

                msg += "name={name}, role={role}({role_name}), " \
                       "editable={editable}, states={states}, " \
                       "extents={extents}]" \
                        .format(name=accessible.get_name(),
                                role = role,
                                role_name = role_name,
                                editable = editable,
                                states = states,
                                extents = extents \
                               )
            _logger.debug(msg)



