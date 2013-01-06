# -*- coding: utf-8 -*-
""" Touch input """

from __future__ import division, print_function, unicode_literals

import time

from gi.repository         import Gdk

from Onboard.utils         import Timer
from Onboard.XInput        import XIDeviceManager, XIEventType, XIEventMask

### Logging ###
import logging
_logger = logging.getLogger("TouchInput")
###############

### Config Singleton ###
from Onboard.Config import Config
config = Config()
########################

BUTTON123_MASK = Gdk.ModifierType.BUTTON1_MASK | \
                 Gdk.ModifierType.BUTTON2_MASK | \
                 Gdk.ModifierType.BUTTON3_MASK

DRAG_GESTURE_THRESHOLD2 = 40**2

(
    NO_GESTURE,
    TAP_GESTURE,
    DRAG_GESTURE,
    FLICK_GESTURE,
) = range(4)

# sequence id of core pointer events
POINTER_SEQUENCE = 0

class InputEventSourceEnum:
    (
        GTK,
        XINPUT,
    ) = range(2)


class TouchInputEnum:
    (
        NONE,
        SINGLE,
        MULTI,
    ) = range(3)


class InputSequence:
    """
    State of a single click- or touch sequence.
    On a multi-touch capable touch screen, any number of
    InputSequences may be in flight simultaneously.
    """
    id         = None
    point      = None
    root_point = None
    time       = None
    button     = None
    event_type = None
    state      = None
    active_key = None
    cancel     = False
    updated    = None
    primary    = False   # primary sequence for drag operations
    delivered  = False

    def init_from_button_event(self, event):
        self.id         = POINTER_SEQUENCE
        self.point      = (event.x, event.y)
        self.root_point = (event.x_root, event.y_root)
        self.time       = event.get_time()
        self.button     = event.button
        self.updated    = time.time()

    def init_from_motion_event(self, event):
        self.id         = POINTER_SEQUENCE
        self.point      = (event.x, event.y)
        self.root_point = (event.x_root, event.y_root)
        self.time       = event.get_time()
        self.state      = event.state
        self.updated    = time.time()

    def init_from_touch_event(self, event, id):
        self.id         = id
        self.point      = (event.x, event.y)
        self.root_point = (event.x_root, event.y_root)
        self.time       = event.time  # has no get_time() method, update has no time too
        self.button     = 1
        self.state      = Gdk.ModifierType.BUTTON1_MASK
        self.updated    = time.time()

    def is_touch(self):
        return self.id != POINTER_SEQUENCE

    def __repr__(self):
        return "{}({})".format(type(self).__name__,
                               repr(self.id))


class InputEventSource:
    """
    Setup and handle GTK or XInput device events.
    """

    def __init__(self):
        self._gtk_handler_ids = None
        self._device_manager = None

        self._master_device = None      # receives enter/leave events
        self._master_device_id = None   # for convenience/speed only
        self._slave_devices = None      # receive pointer and touch events
        self._slave_device_ids = None   # for convenience/speed only

        self.connect("realize",              self._on_realize_event)
        self.connect("unrealize",            self._on_unrealize_event)

    def cleanup(self):
        self._register_gtk_events(False)
        self._register_xinput_events(False)

    def _on_realize_event(self, user_data):
        self.handle_realize_event()

    def _on_unrealize_event(self, user_data):
        self.handle_unrealize_event()

    def handle_realize_event(self):
        # register events in derived class
        pass

    def handle_unrealize_event(self):
        self.register_input_events(False)

    def register_input_events(self, register, use_gtk = False):
        self._register_gtk_events(False)
        self._register_xinput_events(False)

        if register:
            if use_gtk:
                self._register_gtk_events(True)
            else:
                if not self._register_xinput_events(True):
                    _logger.warning("XInput event source failed to initialize, "
                                    "falling back to GTK.")
                    self._register_gtk_events(True)

    def _register_gtk_events(self, register):
        """ Setup GTK event handling """
        if register:
            event_mask = Gdk.EventMask.BUTTON_PRESS_MASK | \
                              Gdk.EventMask.BUTTON_RELEASE_MASK | \
                              Gdk.EventMask.POINTER_MOTION_MASK | \
                              Gdk.EventMask.LEAVE_NOTIFY_MASK | \
                              Gdk.EventMask.ENTER_NOTIFY_MASK
            if self._touch_events_enabled:
                event_mask |= Gdk.EventMask.TOUCH_MASK

            self.add_events(event_mask)

            self._gtk_handler_ids = [
                self.connect("button-press-event",
                             self._on_button_press_event),
                self.connect("button_release_event",
                             self._on_button_release_event),
                self.connect("motion-notify-event",
                             self._on_motion_event),
                self.connect("enter-notify-event",   
                             self._on_enter_notify),
                self.connect("leave-notify-event",   
                             self._on_leave_notify),
                self.connect("touch-event",
                             self._on_touch_event),
            ]

        else:

            if self._gtk_handler_ids:
                for id in self._gtk_handler_ids:
                    self.disconnect(id)
                self._gtk_handler_ids = None

    def _register_xinput_events(self, register):
        """ Setup XInput event handling """
        success = True

        if register:
            self._device_manager = XIDeviceManager()
            if self._device_manager.is_valid():
                self._device_manager.connect("device-event",
                                             self._device_event_handler)
                self.select_xinput_devices()
            else:
                success = False
                self._device_manager = None
        else:

            if self._device_manager:
                self._device_manager.disconnect("device-event",
                                                self._device_event_handler)

            if self._master_device:
                device = self._master_device
                try:
                    self._device_manager.unselect_events(self, device)
                except Exception as ex:
                    _logger.warning("Failed to unselect events for device "
                                   "{id}: {ex}"
                                   .format(id = device.id, ex = ex))
                self._master_device = None
                self._master_device_id = None

            if self._slave_devices:
                for device in self._slave_devices:
                    try:
                        self._device_manager.unselect_events(self, device)
                    except Exception as ex:
                        _logger.warning("Failed to unselect events for device "
                                       "{id}: {ex}"
                                       .format(id = device.id, ex = ex))
                self._slave_devices = None
                self._slave_device_ids = None

        return success

    def select_xinput_devices(self):
        """ Select events of all slave pointer devices. """

        # select events for the master pointer
        event_mask = XIEventMask.EnterMask | \
                     XIEventMask.LeaveMask
        device = self._device_manager.get_client_pointer()
        _logger.info("listening to XInput master: {}" \
                     .format((device.name, device.id, 
                             device.get_config_string())))
        try:
            self._device_manager.select_events(self, device, event_mask)
        except Exception as ex:
            _logger.warning("Failed to select events for device "
                            "{id}: {ex}"
                            .format(id = device.id, ex = ex))

        self._master_device = device
        self._master_device_id = device.id

        # select events for all attached (non-floating) slave pointers
        event_mask = XIEventMask.ButtonPressMask | \
                     XIEventMask.ButtonReleaseMask | \
                     XIEventMask.EnterMask | \
                     XIEventMask.LeaveMask | \
                     XIEventMask.MotionMask
        if self._touch_events_enabled:
            event_mask |= XIEventMask.TouchMask

        devices = self._device_manager.get_client_slave_pointer_devices()
        devices = [d for d in devices if not d.is_floating()]
        _logger.info("listening to XInput devices: {}" \
                     .format([(d.name, d.id, d.get_config_string()) \
                              for d in devices]))
        for device in devices:
            try:
                self._device_manager.select_events(self, device, event_mask)
            except Exception as ex:
                _logger.warning("Failed to select events for device "
                                "{id}: {ex}"
                                .format(id = device.id, ex = ex))

        self._slave_devices = devices
        self._slave_device_ids = [d.id for d in devices]

    def _device_event_handler(self, event):
        """
        Handler for XI2 events.
        """
        event_type = event.xi_type
        device_id  = event.device_id

        if _logger.isEnabledFor(logging.DEBUG):
            win = self.get_window()
            if not event_type in [XIEventType.Motion,
                                  XIEventType.TouchUpdate,]:
                _logger.debug("Device event: dev_id={} src_id={} xi_type={} "
                              "xid_event={}({}) x={} y={} x_root={} y_root={} "
                              "button={} state={} sequence={}"
                              "".format(event.device_id,
                                        event.source_id,
                                        event.xi_type,
                                        event.xid_event, 
                                        win.get_xid() if win else 0,
                                        event.x, event.y,
                                        event.x_root, event.y_root,
                                        event.button, event.state,
                                        yevent.sequence,
                                       )
                             )

        # re-select devices on changes to the device hierarchy
        if event_type == XIEventType.DeviceAdded or \
           event_type == XIEventType.DeviceRemoved or \
           event_type == XIEventType.DeviceChanged:
            self.select_xinput_devices()
            return

        # check device_id, stop duplicate and unknown events
        if (event_type == XIEventType.Enter or \
            event_type == XIEventType.Leave):

            # enter/leave are only expected from the master device
            if not device_id == self._master_device_id:
                return
        else:
            # all other pointer/touch events have to come from slaves
            if not event.device_id in self._slave_device_ids:
                return

        # Is self the hit window?
        # We need this only for the multi touch case with open long press popup,
        # e.g. while shift is held down touching anything in a long press popup
        # must not also affect the keyboard below.
        win = self.get_window()
        if not win:
            return
        xid_event = event.xid_event
        if xid_event != 0 and \
            xid_event != win.get_xid():
            return

        if event_type == XIEventType.Motion:
            self._on_motion_event(self, event)

        elif event_type == XIEventType.TouchUpdate:
            self._on_touch_event(self, event)

        else:

            if event_type == XIEventType.TouchBegin or \
               event_type == XIEventType.TouchEnd:
                self._on_touch_event(self, event)

            elif event_type == XIEventType.ButtonPress:
                self._on_button_press_event(self, event)

            elif event_type == XIEventType.ButtonRelease:
                self._on_button_release_event(self, event)

            elif event_type == XIEventType.Enter:
                self._on_enter_notify(self, event)

            elif event_type == XIEventType.Leave:
                self._on_leave_notify(self, event)


class TouchInput(InputEventSource):
    """
    Unified handling of multi-touch sequences and conventional pointer input.
    """
    GESTURE_DETECTION_SPAN = 100 # [ms] until two finger tap&drag is detected
    GESTURE_DELAY_PAUSE = 3000   # [ms] Suspend delayed sequence begin for this
                                 # amount of time after the last key press.
    delay_sequence_begin = True  # No delivery, i.e. no key-presses after
                                 # gesture detection, but delays press-down.

    def __init__(self):
        InputEventSource.__init__(self)

        self._input_sequences = {}
        self._touch_events_enabled = self.is_touch_enabled()
        self._multi_touch_enabled  = config.keyboard.touch_input == \
                                     TouchInputEnum.MULTI
        self._gestures_enabled     = self._touch_events_enabled
        self._last_event_was_touch = False
        self._last_sequence_time = 0

        self._gesture = NO_GESTURE
        self._gesture_begin_point = (0, 0)
        self._gesture_begin_time = 0
        self._gesture_detected = False
        self._gesture_cancelled = False
        self._num_tap_sequences = 0
        self._gesture_timer = Timer()

    def is_touch_enabled(self):
        return config.keyboard.touch_input != TouchInputEnum.NONE

    def has_input_sequences(self):
        """ Are any clicks/touches still ongoing? """
        return bool(self._input_sequences)

    def last_event_was_touch(self):
        """ Was there just a touch event? """
        return self._last_event_was_touch

    def has_touch_source(self, event):
        source_device = event.get_source_device()
        source = source_device.get_source()
        return source == Gdk.InputSource.TOUCHSCREEN

    def _on_button_press_event(self, widget, event):
        if self._touch_events_enabled and \
           self.has_touch_source(event):
                return

        # Ignore double clicks (GDK_2BUTTON_PRESS),
        # we're handling them ourselves.
        if event.type == Gdk.EventType.BUTTON_PRESS and \
           1 <= event.button <= 3:
            sequence = InputSequence()
            sequence.init_from_button_event(event)
            sequence.primary = True
            self._last_event_was_touch = False

            self._input_sequence_begin(sequence)

    def _on_button_release_event(self, widget, event):
        sequence = self._input_sequences.get(POINTER_SEQUENCE)
        if not sequence is None:
            sequence.point      = (event.x, event.y)
            sequence.root_point = (event.x_root, event.y_root)
            sequence.time       = event.get_time()

            self._input_sequence_end(sequence)

    def _on_motion_event(self, widget, event):
        if self._touch_events_enabled and \
           self.has_touch_source(event):
                return

        sequence = self._input_sequences.get(POINTER_SEQUENCE)
        if sequence is None:
            sequence = InputSequence()
            sequence.primary = True
        sequence.init_from_motion_event(event)

        self._last_event_was_touch = False
        self._input_sequence_update(sequence)

    def _on_enter_notify(self, widget, event):
        self.on_enter_notify(widget, event)

    def _on_leave_notify(self, widget, event):
        self.on_leave_notify(widget, event)

    def _on_touch_event(self, widget, event):
        if not self.has_touch_source(event):
            return

        touch = event.touch
        id = str(touch.sequence)
        self._last_event_was_touch = True

        event_type = event.type
        if event_type == Gdk.EventType.TOUCH_BEGIN:
            sequence = InputSequence()
            sequence.init_from_touch_event(touch, id)
            if len(self._input_sequences) == 0:
                sequence.primary = True

            self._input_sequence_begin(sequence)

        elif event_type == Gdk.EventType.TOUCH_UPDATE:
            sequence = self._input_sequences.get(id)
            if not sequence is None:
                sequence.point      = (touch.x, touch.y)
                sequence.root_point = (touch.x_root, touch.y_root)
                sequence.time       = event.get_time()
                sequence.updated    = time.time()

                self._input_sequence_update(sequence)

        else:
            if event_type == Gdk.EventType.TOUCH_END:
                pass

            elif event_type == Gdk.EventType.TOUCH_CANCEL:
                pass

            sequence = self._input_sequences.get(id)
            if not sequence is None:
                sequence.time       = event.get_time()
                self._input_sequence_end(sequence)

    def _input_sequence_begin(self, sequence):
        """ Button press/touch begin """
        self._gesture_sequence_begin(sequence)
        first_sequence = len(self._input_sequences) == 0

        if first_sequence or \
           self._multi_touch_enabled:
            self._input_sequences[sequence.id] = sequence

            if not self._gesture_detected:
                if first_sequence and \
                   self._multi_touch_enabled and \
                   self.delay_sequence_begin and \
                   sequence.time - self._last_sequence_time > \
                                   self.GESTURE_DELAY_PAUSE:
                    # Delay the first tap; we may have to stop it
                    # from reaching the keyboard.
                    self._gesture_timer.start(self.GESTURE_DETECTION_SPAN / 1000.0,
                                              self.on_delayed_sequence_begin,
                                              sequence, sequence.point)

                else:
                    # Tell the keyboard right away.
                    self.deliver_input_sequence_begin(sequence)

        self._last_sequence_time = sequence.time

    def on_delayed_sequence_begin(self, sequence, point):
        if not self._gesture_detected: # work around race condition
            sequence.point = point # return to the original begin point
            self.deliver_input_sequence_begin(sequence)
            self._gesture_cancelled = True
        return False

    def deliver_input_sequence_begin(self, sequence):
        self.on_input_sequence_begin(sequence)
        sequence.delivered = True

    def _input_sequence_update(self, sequence):
        """ Pointer motion/touch update """
        self._gesture_sequence_update(sequence)
        if not sequence.state & BUTTON123_MASK or \
           not self.in_gesture_detection_delay(sequence):
            self._gesture_timer.finish()  # don't run begin out of order
            self.on_input_sequence_update(sequence)

    def _input_sequence_end(self, sequence):
        """ Button release/touch end """
        self._gesture_sequence_end(sequence)
        self._gesture_timer.finish()  # run delayed sequence before end
        if sequence.id in self._input_sequences:
            del self._input_sequences[sequence.id]

            if sequence.delivered:
                self._gesture_timer.finish()  # run delayed sequence before end
                self.on_input_sequence_end(sequence)

        if self._input_sequences:
            self._discard_stuck_input_sequences()

        self._last_sequence_time = sequence.time

    def _discard_stuck_input_sequences(self):
        """
        Input sequence handling requires guaranteed balancing of
        begin, update and end events. There is no indication yet this
        isn't always the case, but still, at this time it seems like a
        good idea to prepare for the worst.
        -> Clear out aged input sequences, so Onboard can start from a
        fresh slate and not become terminally unresponsive.
        """
        expired_time = time.time() - 30
        for id, sequence in list(self._input_sequences.items()):
            if sequence.updated < expired_time:
                _logger.warning("discarding expired input sequence " + str(id))
                del self._input_sequences[id]

    def in_gesture_detection_delay(self, sequence):
        span = sequence.time - self._gesture_begin_time
        return span < self.GESTURE_DETECTION_SPAN

    def _gesture_sequence_begin(self, sequence):
        if self._num_tap_sequences == 0:
            self._gesture = NO_GESTURE
            self._gesture_detected = False
            self._gesture_cancelled = False
            self._gesture_begin_point = sequence.point
            self._gesture_begin_time = sequence.time # event time
        else:
            if self.in_gesture_detection_delay(sequence) and \
               not self._gesture_cancelled:
                self._gesture_timer.stop()  # cancel delayed sequence begin
                self._gesture_detected = True
        self._num_tap_sequences += 1

    def _gesture_sequence_update(self, sequence):
        if self._gesture_detected and \
           sequence.state & BUTTON123_MASK and \
           self._gesture == NO_GESTURE:
            point = sequence.point
            dx = self._gesture_begin_point[0] - point[0]
            dy = self._gesture_begin_point[1] - point[1]
            d2 = dx * dx + dy * dy

            # drag gesture?
            if d2 >= DRAG_GESTURE_THRESHOLD2:
                num_touches = len(self._input_sequences)
                self._gesture = DRAG_GESTURE
                self.on_drag_gesture_begin(num_touches)
        return True

    def _gesture_sequence_end(self, sequence):
        if len(self._input_sequences) == 1: # last sequence of the gesture?
            if self._gesture_detected:
                gesture = self._gesture

                if gesture == NO_GESTURE:
                    # tap gesture?
                    elapsed = sequence.time - self._gesture_begin_time
                    if elapsed <= 300:
                        self.on_tap_gesture(self._num_tap_sequences)

                elif gesture == DRAG_GESTURE:
                    self.on_drag_gesture_end(0)

            self._num_tap_sequences = 0

    def on_tap_gesture(self, num_touches):
        return False

    def on_drag_gesture_begin(self, num_touches):
        return False

    def on_drag_gesture_end(self, num_touches):
        return False

