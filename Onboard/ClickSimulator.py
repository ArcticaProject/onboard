# -*- coding: utf-8 -*-
"""
Dwelling control via mousetweaks and general mouse support functions.
"""

from __future__ import division, print_function, unicode_literals

try:
    import dbus
except ImportError:
    pass

from gi.repository.Gio   import Settings, SettingsBindFlags
from gi.repository       import GLib, GObject, Gtk

from Onboard.utils       import DelayedLauncher, EventSource
from Onboard.ConfigUtils import ConfigObject
from Onboard.XInput      import XIDeviceManager, XIEventType, XIEventMask

import Onboard.osk as osk

### Logging ###
import logging
_logger = logging.getLogger("ClickSimulator")
###############


class ClickSimulator(GObject.GObject):
    """ Abstract base class for mouse click simulators """

    PRIMARY_BUTTON   = 1
    MIDDLE_BUTTON    = 2
    SECONDARY_BUTTON = 3

    CLICK_TYPE_SINGLE = 3
    CLICK_TYPE_DOUBLE = 2
    CLICK_TYPE_DRAG   = 1

    # Public interface
    def supports_click_params(self, button, click_type):
        raise NotImplementedError()

    def map_primary_click(self, event_source, button, click_type):
        raise NotImplementedError()

    def get_click_button(self):
        raise NotImplementedError()

    def get_click_type(self):
        raise NotImplementedError()


class CSButtonMapper(ClickSimulator):
    """
    Onboards built-in mouse click mapper.
    Maps secondary or middle button to the primary button.
    """
    def __init__(self):
        ClickSimulator.__init__(self)

        self._osk_cm = osk.ClickMapper()
        self._click_done_notify_callbacks = []
        self._exclusion_rects = []
        self._grab_event_source = None

    def cleanup(self):
        self.end_mapping()
        self._click_done_notify_callbacks = []

    def supports_click_params(self, button, click_type):
        return True

    def map_primary_click(self, event_source, button, click_type):
        if event_source and (button != self.PRIMARY_BUTTON or \
                             click_type != self.CLICK_TYPE_SINGLE):
            self._begin_mapping(event_source, button, click_type)
        else:
            self.end_mapping()

    def _begin_mapping(self, event_source, button, click_type):
        # remap button
        if button != self.PRIMARY_BUTTON and \
           click_type == self.CLICK_TYPE_SINGLE:
            # "grab" the pointer so we can detect button-release
            # anywhere on screen. Works only with XInput as InputEventSource.
            self._grab_event_source = event_source
            event_source.grab_xi_pointer(True)
            EventSource.connect(event_source, "button-release",
                            self._on_xi_button_release)
            self._osk_cm.map_pointer_button(button)
            self._osk_cm.button = button
            self._osk_cm.click_type = click_type
        else:
            self._set_next_mouse_click(button, click_type)

    def end_mapping(self):
        if self._grab_event_source:
            EventSource.disconnect(self._grab_event_source,
                                   "button-release",
                                   self._on_xi_button_release)
            self._grab_event_source.grab_xi_pointer(False)
            self._grab_event_source = None

        if self._osk_cm:
            if self._osk_cm.click_type == self.CLICK_TYPE_SINGLE:
                self._osk_cm.restore_pointer_buttons()
                self._osk_cm.button = self.PRIMARY_BUTTON
                self._osk_cm.click_type = self.CLICK_TYPE_SINGLE
            else:
                self._set_next_mouse_click(self.PRIMARY_BUTTON, self.CLICK_TYPE_SINGLE)

    def is_mapping_active(self):
        return self._grab_event_source or \
           self._osk_cm and \
           (self._osk_cm.click_type != self.CLICK_TYPE_SINGLE or \
            self._osk_cm.button == self.PRIMARY_BUTTON)

    def _on_xi_button_release(self, event):
        """ end of CLICK_TYPE_SINGLE in XInput mode """
        _logger.debug("_on_xi_button_release")
        self.end_mapped_click()

    def get_click_button(self):
        return self._osk_cm.button

    def get_click_type(self):
        return self._osk_cm.click_type

    def _set_next_mouse_click(self, button, click_type):
        """
        Converts the next mouse left-click to the click
        specified in @button. Possible values are 2 and 3.
        """
        try:
            self._osk_cm.convert_primary_click(button, click_type,
                                               self._exclusion_rects,
                                               self.end_mapped_click)
        except osk.error as error:
            _logger.warning(error)

    def state_notify_add(self, callback):
        self._click_done_notify_callbacks.append(callback)

    def end_mapped_click(self):
        """ osk callback, outside click, xi button release """
        if self.is_mapping_active():
            self.end_mapping()

            # update click type buttons
            for callback in self._click_done_notify_callbacks:
                callback(None)

    def set_exclusion_rects(self, rects):
        self._exclusion_rects = rects


class CSFloatingSlave(ClickSimulator):
    """
    Onboards built-in mouse click mapper.
    Maps secondary or middle button to the primary button.
    """
    def __init__(self):
        ClickSimulator.__init__(self)

        self._click_done_notify_callbacks = []
        self._exclusion_rects = []

        self._device_manager = XIDeviceManager()
        self._grabbed_device_id = None
        self._osk_cm = osk.ClickMapper()
        self._num_clicks_detected = 0

        self._button = self.PRIMARY_BUTTON
        self._click_type = self.CLICK_TYPE_SINGLE

    def cleanup(self):
        self.end_mapping()
        self._click_done_notify_callbacks = []

    def is_valid(self):
        return self._device_manager.is_valid()

    def supports_click_params(self, button, click_type):
        return True

    def map_primary_click(self, event_source, button, click_type):
        if event_source and (button != self.PRIMARY_BUTTON or \
                             click_type != self.CLICK_TYPE_SINGLE):
            self._begin_mapping(event_source, button, click_type)
        else:
            self.end_mapping()

    def _begin_mapping(self, event_source, button, click_type):
        try:
            event = self._device_manager._current_event
            device = event.get_source_device()
            self._grabbed_device_id = device.id

            _logger.info("grab " + str(device))

            try:
                self._device_manager.grab_device(device)
            except osk.error as ex:
                _logger.error("grab device {id} '{name}': {ex}"
                              .format(id = device.id,
                                      name=device.name,
                                      ex = ex))
                raise ex

            # connect to root window events to get them for the whole screen
            self._device_manager.connect("device-event",
                                          self._device_event_handler)
            event_mask = XIEventMask.ButtonPressMask | \
                         XIEventMask.ButtonReleaseMask | \
                         XIEventMask.MotionMask
            try:
                self._device_manager.select_events(None, device, event_mask)
            except osk.error as ex:
                _logger.error("select root events for device "
                              "{id} '{name}': {ex}"
                              .format(id = device.id,
                                      name=device.name,
                                      ex = ex))
                raise ex

            self._button = button
            self._click_type = click_type
            self._num_clicks_detected = 0

        except osk.error:
            self.end_mapping()

    def end_mapping(self):
        if not self._grabbed_device_id is None:
            self._device_manager.disconnect("device-event",
                                            self._device_event_handler)
            device = self._device_manager \
                         .lookup_device_id(self._grabbed_device_id)

            _logger.info("ungrab " + str(device))

            try:
                self._device_manager.unselect_events(None, device)
            except osk.error as ex:
                _logger.error("unselect root events for device "
                              "{id} '{name}': {ex}"
                              .format(id = device.id,
                                      name=device.name,
                                      ex = ex))

            try:
                self._device_manager.ungrab_device(device)
            except osk.error as ex:
                _logger.error("ungrab device {id} '{name}': {ex}"
                              .format(id = device.id,
                                      name=device.name,
                                      ex = ex))

            self._grabbed_device_id = None

        self._button = self.PRIMARY_BUTTON
        self._click_type = self.CLICK_TYPE_SINGLE

    def _device_event_handler(self, event):
        if event.device_id != self._grabbed_device_id:
            return

        device = event.get_source_device()
        event_type = event.xi_type
        root_point = (event.x_root, event.y_root)
        button = self._button
        click_type = self._click_type
        generate_button_event = self._osk_cm.generate_button_event

        #print("device event:", event.device_id, event.xi_type,
        #      (event.x, event.y), root_point, event.xid_event)

        if event_type == XIEventType.Motion:
            self._osk_cm.generate_motion_event(int(event.x_root),
                                               int(event.y_root))

        # single click
        if click_type == self.CLICK_TYPE_SINGLE:
            if event_type == XIEventType.ButtonPress:
                generate_button_event(button, True)

            elif event_type == XIEventType.ButtonRelease:
                generate_button_event(button, False)
                if self._num_clicks_detected and \
                   not self._is_point_in_exclusion_rects(root_point):
                    self.end_mapped_click()

        # double click
        elif click_type == self.CLICK_TYPE_DOUBLE:
            if event_type == XIEventType.ButtonRelease:
                if self._num_clicks_detected:
                   if not self._is_point_in_exclusion_rects(root_point):
                       delay = 40
                       generate_button_event(button, True)
                       generate_button_event(button, False, delay)
                       generate_button_event(button, True, delay)
                       generate_button_event(button, False, delay)
                   self.end_mapped_click()

        # drag click
        elif click_type == self.CLICK_TYPE_DRAG:
            if event_type == XIEventType.ButtonRelease:
                if self._num_clicks_detected == 1:
                    if self._is_point_in_exclusion_rects(root_point):
                        self.end_mapped_click()
                    else:
                        generate_button_event(button, True)

                elif self._num_clicks_detected >= 2:
                   generate_button_event(button, False)
                   self.end_mapped_click()

        # count button presses
        if event_type == XIEventType.ButtonPress:
            self._num_clicks_detected += 1

    def _is_point_in_exclusion_rects(self, point):
        for rect in self._exclusion_rects:
            if rect.is_point_within(point):
                return True
        return False

    def is_mapping_active(self):
        return self._grabbed_device_id

    def get_click_button(self):
        return self._button

    def get_click_type(self):
        return self._click_type

    def state_notify_add(self, callback):
        self._click_done_notify_callbacks.append(callback)

    def end_mapped_click(self):
        """ osk callback, outside click, xi button release """
        if self.is_mapping_active():
            self.end_mapping()

            # update click type buttons
            for callback in self._click_done_notify_callbacks:
                callback(None)

    def set_exclusion_rects(self, rects):
        self._exclusion_rects = rects


class CSMousetweaks(ConfigObject, ClickSimulator):
    """ Mousetweaks settings, D-bus control and signal handling """

    CLICK_TYPE_RIGHT  = 0
    CLICK_TYPE_MIDDLE = 4

    MOUSE_A11Y_SCHEMA_ID = "org.gnome.desktop.a11y.mouse"
    MOUSETWEAKS_SCHEMA_ID = "org.gnome.mousetweaks"

    MT_DBUS_NAME  = "org.gnome.Mousetweaks"
    MT_DBUS_PATH  = "/org/gnome/Mousetweaks"
    MT_DBUS_IFACE = "org.gnome.Mousetweaks"
    MT_DBUS_PROP  = "ClickType"

    def __init__(self):
        self._click_type_callbacks = []

        if not "dbus" in globals():
            raise ImportError("python-dbus unavailable")

        ConfigObject.__init__(self)
        ClickSimulator.__init__(self)

        self.launcher = DelayedLauncher()
        self._daemon_running_notify_callbacks = []

        # Check if mousetweaks' schema is installed.
        # Raises SchemaError if it isn't.
        self.mousetweaks = ConfigObject(None, self.MOUSETWEAKS_SCHEMA_ID)

        # connect to session bus
        self._bus = dbus.SessionBus()
        self._bus.add_signal_receiver(self._on_name_owner_changed,
                                      "NameOwnerChanged",
                                      dbus.BUS_DAEMON_IFACE,
                                      arg0=self.MT_DBUS_NAME)
        # Initial state
        proxy = self._bus.get_object(dbus.BUS_DAEMON_NAME, dbus.BUS_DAEMON_PATH)
        result = proxy.NameHasOwner(self.MT_DBUS_NAME, dbus_interface=dbus.BUS_DAEMON_IFACE)
        self._set_connection(bool(result))

    def _init_keys(self):
        """ Create gsettings key descriptions """

        self.schema = self.MOUSE_A11Y_SCHEMA_ID
        self.sysdef_section = None

        self.add_key("dwell-click-enabled", False)
        self.add_key("dwell-time", 1.2)
        self.add_key("dwell-threshold", 10)
        self.add_key("click-type-window-visible", False)

    def on_properties_initialized(self):
        ConfigObject.on_properties_initialized(self)

        # launch mousetweaks on startup if necessary
        if not self._iface and \
           self.dwell_click_enabled:
            self._launch_daemon(0.5)

    def cleanup(self):
        self._daemon_running_notify_callbacks = []

    def _launch_daemon(self, delay):
        self.launcher.launch_delayed(["mousetweaks"], delay)

    def _set_connection(self, active):
        ''' Update interface object, state and notify listeners '''
        if active:
            proxy = self._bus.get_object(self.MT_DBUS_NAME, self.MT_DBUS_PATH)
            self._iface = dbus.Interface(proxy, dbus.PROPERTIES_IFACE)
            self._iface.connect_to_signal("PropertiesChanged",
                                          self._on_click_type_prop_changed)
            self._click_type = self._iface.Get(self.MT_DBUS_IFACE, self.MT_DBUS_PROP)
        else:
            self._iface = None
            self._click_type = self.CLICK_TYPE_SINGLE

    def _on_name_owner_changed(self, name, old, new):
        '''
        The daemon has de/registered the name.
        Called when dwell-click-enabled changes in gsettings.
        '''
        active = old == ""
        if active:
            self.launcher.stop()
        self._set_connection(active)

        # update hover click button
        for callback in self._daemon_running_notify_callbacks:
            callback(active)

    def daemon_running_notify_add(self, callback):
        self._daemon_running_notify_callbacks.append(callback)

    def _on_click_type_prop_changed(self, iface, changed_props, invalidated_props):
        ''' Either we or someone else has change the click-type. '''
        if self.MT_DBUS_PROP in changed_props:
            self._click_type = changed_props.get(self.MT_DBUS_PROP)

            # notify listeners
            for callback in self._click_type_callbacks:
                callback(self._click_type)

    def _get_mt_click_type(self):
        return self._click_type;

    def _set_mt_click_type(self, click_type):
        if click_type != self._click_type:# and self.is_active():
            self._click_type = click_type
            self._iface.Set(self.MT_DBUS_IFACE, self.MT_DBUS_PROP, click_type)

    ##########
    # Public
    ##########

    def state_notify_add(self, callback):
        """ Convenience function to subscribes to all notifications """
        self.dwell_click_enabled_notify_add(callback)
        self.click_type_notify_add(callback)
        self.daemon_running_notify_add(callback)

    def click_type_notify_add(self, callback):
        self._click_type_callbacks.append(callback)

    def is_active(self):
        return self.dwell_click_enabled and bool(self._iface)

    def set_active(self, active):
        self.dwell_click_enabled = active

        # try to launch mousetweaks if it isn't running yet
        if active and not self._iface:
            self._launch_daemon(1.0)
        else:
            self.launcher.stop()

    def supports_click_params(self, button, click_type):
        # mousetweaks since 3.3.90 supports middle click button too.
        return True

    def map_primary_click(self, event_source, button, click_type):
        mt_click_type = click_type
        if button == self.SECONDARY_BUTTON:
            mt_click_type = self.CLICK_TYPE_RIGHT
        if button == self.MIDDLE_BUTTON:
            mt_click_type = self.CLICK_TYPE_MIDDLE
        self._set_mt_click_type(mt_click_type)

    def get_click_button(self):
        mt_click_type = self._get_mt_click_type()
        if mt_click_type == self.CLICK_TYPE_RIGHT:
            return self.SECONDARY_BUTTON
        if mt_click_type == self.CLICK_TYPE_MIDDLE:
            return self.MIDDLE_BUTTON
        return self.PRIMARY_BUTTON

    def get_click_type(self):
        mt_click_type = self._get_mt_click_type()
        if mt_click_type in [self.CLICK_TYPE_RIGHT, self.CLICK_TYPE_MIDDLE]:
            return self.CLICK_TYPE_SINGLE
        return mt_click_type


