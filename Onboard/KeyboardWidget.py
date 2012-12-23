# -*- coding: utf-8 -*-
""" GTK keyboard widget """

from __future__ import division, print_function, unicode_literals

import sys
import time
from math import sin, pi

from gi.repository         import GLib, Gdk, Gtk

from Onboard.utils         import Rect, Timer, FadeTimer, roundrect_arc
from Onboard.WindowUtils   import WindowManipulator, Handle, DockingEdge, \
                                  limit_window_position, \
                                  get_monitor_rects
from Onboard.TouchInput    import TouchInput, InputSequence
from Onboard.Keyboard      import EventType
from Onboard.KeyGtk        import Key, RectKey
from Onboard.KeyCommon     import LOD
from Onboard               import KeyCommon
from Onboard.TouchHandles  import TouchHandles
from Onboard.Layout        import LayoutRoot, LayoutPanel, KeyContext
from Onboard.LayoutView    import LayoutView
from Onboard.AtspiAutoShow import AtspiAutoShow

### Logging ###
import logging
_logger = logging.getLogger("KeyboardWidget")
###############

### Config Singleton ###
from Onboard.Config import Config
config = Config()
########################

try:
    from gi.repository import Atspi
except ImportError as e:
    _logger.info(_("Atspi unavailable, auto-hide won't be available"))

# Gnome introspection calls are surprisingly expensive
# -> prepare stuff for faster access
BUTTON123_MASK = Gdk.ModifierType.BUTTON1_MASK | \
                 Gdk.ModifierType.BUTTON2_MASK | \
                 Gdk.ModifierType.BUTTON3_MASK

class AutoReleaseTimer(Timer):
    """
    Releases latched and locked modifiers after a period of inactivity.
    Inactivity here means no keys are pressed.
    """
    _keyboard = None

    def __init__(self, keyboard):
        self._keyboard = keyboard

    def start(self):
        self.stop()
        delay = config.keyboard.sticky_key_release_delay
        if delay:
            Timer.start(self, delay)

    def on_timer(self):
        self._keyboard.release_latched_sticky_keys()
        self._keyboard.release_locked_sticky_keys()
        self._keyboard.active_layer_index = 0
        self._keyboard.update_ui_no_resize()
        self._keyboard.redraw()
        return False

class InactivityTimer(Timer):
    """
    Waits for the inactivity delay and transitions between
    active and inactive state.
    Inactivity here means, the pointer has left the keyboard window
    """
    _keyboard = None
    _active = False

    def __init__(self, keyboard):
        self._keyboard = keyboard

    def is_enabled(self):
        window = self._keyboard.get_kbd_window()
        if not window:
            return False
        screen = window.get_screen()
        return screen and  screen.is_composited() and \
               config.is_inactive_transparency_enabled() and \
               config.window.enable_inactive_transparency and \
               not config.xid_mode

    def is_active(self):
        return self._active

    def begin_transition(self, active):
        self._active = active
        if active:
            Timer.stop(self)
            if self._keyboard.transition_active_to(True):
                self._keyboard.commit_transition()
        else:
            if not config.xid_mode:
                Timer.start(self, config.window.inactive_transparency_delay)

    def on_timer(self):
        self._keyboard.transition_active_to(False)
        self._keyboard.commit_transition()
        return False

class TransitionVariable:
    """ A variable taking part in opacity transitions """
    value        = 0.0
    start_value  = 0.0
    target_value = 0.0
    start_time   = 0.0
    duration     = 0.0
    done         = False

    def start_transition(self, target, duration):
        """ Begin transition """
        self.start_value = self.value
        self.target_value = target
        self.start_time = time.time()
        self.duration = duration
        self.done = False

    def update(self):
        """
        Update self.value based on the elapsed time since start_transition.
        """
        range = self.target_value - self.start_value
        if range and self.duration:
            elapsed  = time.time() - self.start_time
            lin_progress = min(1.0, elapsed / self.duration)
        else:
            lin_progress = 1.0
        sin_progress = (sin(lin_progress * pi - pi / 2.0) + 1.0) / 2.0
        self.value = self.start_value + sin_progress * range
        self.done = lin_progress >= 1.0


class TransitionState:
    """ Set of all state variables involved in opacity transitions. """

    def __init__(self):
        self.visible = TransitionVariable()
        self.active  = TransitionVariable()
        self.x       = TransitionVariable()
        self.y       = TransitionVariable()
        self._vars = [self.visible, self.active, self.x, self.y]

        self.target_visibility = False

    def update(self):
        for var in self._vars:
            var.update()

    def is_done(self):
        return all(var.done for var in self._vars)

    def get_max_duration(self):
        return max(x.duration for x in self._vars)


class KeyboardWidget(Gtk.DrawingArea, WindowManipulator, LayoutView, TouchInput):

    TRANSITION_DURATION_MOVE = 0.25
    TRANSITION_DURATION_SLIDE = 0.25
    TRANSITION_DURATION_OPACITY_HIDE = 0.3

    def __init__(self, keyboard):
        Gtk.DrawingArea.__init__(self)
        WindowManipulator.__init__(self)
        LayoutView.__init__(self, keyboard)
        TouchInput.__init__(self)

        self.canvas_rect = Rect()

        self._last_click_time = 0
        self._last_click_key = None

        self._outside_click_timer = Timer()
        self._outside_click_detected = False
        self._outside_click_start_time = None

        self._long_press_timer = Timer()
        self._auto_release_timer = AutoReleaseTimer(keyboard)
        self._alternative_keys_popup = None

        self.dwell_timer = None
        self.dwell_key = None
        self.last_dwelled_key = None

        self.inactivity_timer = InactivityTimer(self)
        self.auto_show = AtspiAutoShow(self)
        self.auto_show.enable(config.is_auto_show_enabled())

        self.touch_handles = TouchHandles()
        self.touch_handles_hide_timer = Timer()
        self.touch_handles_fade = FadeTimer()
        self.touch_handles_auto_hide = True

        self._aspect_ratio = None

        self._transition_timer = Timer()
        self._transition_state = TransitionState()
        self._transition_state.visible.value = 0.0
        self._transition_state.active.value = 1.0
        self._transition_state.x.value = 0.0
        self._transition_state.y.value = 0.0

        self._configure_timer = Timer()

        #self.set_double_buffered(False)
        self.set_app_paintable(True)

        # no tooltips when embedding, gnome-screen-saver flickers (Oneiric)
        if not config.xid_mode:
            self.set_has_tooltip(True) # works only at window creation -> always on

        self.connect("parent-set",           self._on_parent_set)
        self.connect("draw",                 self._on_draw)
        self.connect("query-tooltip",        self._on_query_tooltip)
        self.connect("enter-notify-event",   self._on_enter_notify)
        self.connect("leave-notify-event",   self._on_leave_notify)
        self.connect("configure-event",      self._on_configure_event)

        self._update_double_click_time()

        self.show()

    def on_layout_loaded(self):
        """ called when the layout has been loaded """
        LayoutView.on_layout_loaded(self)

    def _on_parent_set(self, widget, old_parent):
        win = self.get_kbd_window()
        if win:
            self.touch_handles.set_window(win)
            self.update_resize_handles()

    def cleanup(self):

        # Enter-notify isn't called when resizing without crossing into
        # the window again. Do it here on exit, at the latest, to make sure
        # the home_rect is updated before is is saved later.
        self.stop_system_drag()

        # stop timer callbacks for unused, but not yet destructed keyboards
        self.touch_handles_fade.stop()
        self.touch_handles_hide_timer.stop()
        self._transition_timer.stop()
        self.inactivity_timer.stop()
        self._long_press_timer.stop()
        self._auto_release_timer.stop()
        self.auto_show.cleanup()
        self.stop_click_polling()
        self._configure_timer.stop()
        self.close_alternative_keys_popup()

        # free xserver memory
        self.invalidate_keys()
        self.invalidate_shadows()

        LayoutView.cleanup(self)
        TouchInput.cleanup(self)

    def set_startup_visibility(self):
        win = self.get_kbd_window()
        assert(win)

        # Show the keyboard when turning off auto-show.
        # Hide the keyboard when turning on auto-show.
        #   (Fix this when we know how to get the active accessible)
        # Hide the keyboard on start when start-minimized is set.
        # Start with active transparency if the inactivity_timer is enabled.
        #
        # start_minimized            False True  False True
        # auto_show                  False False True  True
        # --------------------------------------------------
        # window visible on start    True  False False False

        visible = config.is_visible_on_start()

        # Start with low opacity to stop opacity flashing
        # when inactive transparency is enabled.
        screen = self.get_screen()
        if screen and screen.is_composited() and \
            self.inactivity_timer.is_enabled():
            win.set_opacity(0.05, True) # keep it slightly visible just in case

        # transition to initial opacity
        self.transition_visible_to(visible, 0.0, 0.4)
        self.transition_active_to(True, 0.0)
        self.commit_transition()

        # kick off inactivity timer, i.e. inactivate on timeout
        if self.inactivity_timer.is_enabled():
            self.inactivity_timer.begin_transition(False)

        # Be sure to initially show/hide window and icon palette
        win.set_visible(visible)

    def update_ui(self):
        """
        Force update of everything.
        Relatively expensive, don't call this while typing.
        """
        self.update_layout()
        self.invalidate_font_sizes()
        self.invalidate_keys()
        self.invalidate_shadows()
        #self.invalidate_label_extents()

    def update_ui_no_resize(self):
        """
        Update everything assuming key sizes don't change.
        Doesn't invalidate cached surfaces.
        """
        self.update_layout()

    def update_layout(self):
        layout = self.get_layout()
        if not layout:
            return

        # recalculate items rectangles
        self.canvas_rect = Rect(0, 0,
                                self.get_allocated_width(),
                                self.get_allocated_height())
        rect = self.canvas_rect.deflate(self.get_frame_width())
        #keep_aspect = config.xid_mode and self.supports_alpha()
        keep_aspect = False
        layout.fit_inside_canvas(rect, keep_aspect)

        # update the aspect ratio of the main window
        self.on_layout_updated()

    def update_resize_handles(self):
        """ Tell WindowManipulator about the active resize handles """
        docking = config.is_docking_enabled()

        # frame handles
        WindowManipulator.set_drag_handles(self, self._get_active_drag_handles())
        WindowManipulator.lock_x_axis(self, docking)

        # touch handles
        self.touch_handles.set_active_handles(self._get_active_drag_handles(True))
        self.touch_handles.lock_x_axis(docking)

    def update_auto_show(self):
        """
        Turn on/off auto-show in response to user action (preferences)
        and show/hide the window accordingly.
        """
        enable = config.is_auto_show_enabled()
        self.auto_show.enable(enable)
        self.auto_show.show_keyboard(not enable)

    def update_transparency(self):
        """
        Updates transparencies in response to user action.
        Temporarily presents the window with active transparency when
        inactive transparency is enabled.
        """
        self.transition_active_to(True)
        self.commit_transition()
        if self.inactivity_timer.is_enabled():
            self.inactivity_timer.begin_transition(False)
        else:
            self.inactivity_timer.stop()
        self.redraw() # for background transparency

    def touch_inactivity_timer(self):
        """ extend active transparency, kick of inactivity_timer """
        if self.inactivity_timer.is_enabled():
            self.inactivity_timer.begin_transition(True)
            self.inactivity_timer.begin_transition(False)

    def update_inactive_transparency(self):
        if self.inactivity_timer.is_enabled():
            self.transition_active_to(False)
            self.commit_transition()

    def _update_double_click_time(self):
        """ Scraping the bottom of the barrel to speed up key presses """
        self._double_click_time = Gtk.Settings.get_default() \
                        .get_property("gtk-double-click-time")

    def transition_visible_to(self, visible, opacity_duration = None,
                                             slide_duration = None):
        result = False
        state = self._transition_state
        win = self.get_kbd_window()

        # hide popup
        if not visible:
            self.close_alternative_keys_popup()

        # bail in xembed mode
        if config.xid_mode:
            return False

        # stop reposition updates when we're hiding anyway
        if win and not visible:
            win.stop_auto_position()

        if config.is_docking_enabled():
            if slide_duration is None:
                slide_duration = self.TRANSITION_DURATION_SLIDE
            opacity_duration = 0.0
            opacity_visible = True

            if win:
                if visible:
                    begin_rect = win.get_hidden_rect()
                    end_rect = win.get_visible_rect()
                else:
                    begin_rect = win.get_rect()
                    end_rect = win.get_docking_hideout_rect()
                state.y.value = begin_rect.y
                y             = end_rect.y
                state.x.value = begin_rect.x
                x             = end_rect.x

                result |= self._init_transition(state.x, x, slide_duration)
                result |= self._init_transition(state.y, y, slide_duration)
        else:
            opacity_visible  = visible

        if opacity_duration is None:
            if opacity_visible:
                # No duration when showing. Don't fight with compiz in unity.
                opacity_duration = 0.0
            else:
                opacity_duration = self.TRANSITION_DURATION_OPACITY_HIDE

        result |= self._init_opacity_transition(state.visible, opacity_visible,
                                                opacity_duration)
        state.target_visibility = visible

        return result

    def transition_active_to(self, active, duration = None):
        # not in xembed mode
        if config.xid_mode:
            return False

        if duration is None:
            if active:
                duration = 0.15
            else:
                duration = 0.3
        return self._init_opacity_transition(self._transition_state.active,
                                             active, duration)

    def transition_position_to(self, x, y):
        result = False
        state = self._transition_state
        duration = self.TRANSITION_DURATION_MOVE

        # not in xembed mode
        if config.xid_mode:
            return False

        win = self.get_kbd_window()
        if win:
            begin_rect = win.get_rect()
            state.y.value = begin_rect.y
            state.x.value = begin_rect.x

        result |= self._init_transition(state.x, x, duration)
        result |= self._init_transition(state.y, y, duration)

        return result

    def sync_transition_position(self, rect):
        """
        Update transition variables with the actual window position.
        Necessary on user positioning.
        """
        state = self._transition_state
        state.y.value        = rect.y
        state.x.value        = rect.x
        state.y.target_value = rect.y
        state.x.target_value = rect.x

    def _init_opacity_transition(self, var, target_value, duration):

        # No fade delay for screens that can't fade (unity-2d)
        screen = self.get_screen()
        if screen and not screen.is_composited():
            duration = 0.0

        target_value = 1.0 if target_value else 0.0

        return self._init_transition(var, target_value, duration)

    def _init_transition(self, var, target_value, duration):
        # Transition not yet in progress?
        if var.target_value != target_value:
            var.start_transition(target_value, duration)
            return True
        return False

    def commit_transition(self):
        # not in xembed mode
        if config.xid_mode:
            return

        duration = self._transition_state.get_max_duration()
        if duration == 0.0:
            self._on_transition_step()
        else:
            self._transition_timer.start(0.02, self._on_transition_step)

    def _on_transition_step(self):
        state = self._transition_state
        state.update()

        done              = state.is_done()

        active_opacity    = config.window.get_active_opacity()
        inactive_opacity  = config.window.get_inactive_opacity()
        invisible_opacity = 0.0

        opacity  = inactive_opacity + state.active.value * \
                   (active_opacity - inactive_opacity)
        opacity *= state.visible.value

        window = self.get_kbd_window()
        if window:
            if window.get_opacity() != opacity:
                window.set_opacity(opacity)

            visible_before = window.is_visible()
            visible_later  = state.target_visibility

            # move
            x = int(state.x.value)
            y = int(state.y.value)
            wx, wy = window.get_position()
            if x != wx or y != wy:
                window.reposition(x, y)

            # show/hide
            visible = (visible_before or visible_later) and not done or \
                      visible_later and done
            if window.is_visible() != visible:
                window.set_visible(visible)

                # _on_leave_notify does not start the inactivity timer
                # while the pointer remains inside of the window. Do it
                # here when hiding the window.
                if not visible and \
                   self.inactivity_timer.is_enabled():
                    self.inactivity_timer.begin_transition(False)

            if done:
                window.on_transition_done(visible_before, visible_later)

        return not done

    def toggle_visible(self):
        """ main method to show/hide onboard manually """
        self.set_visible(not self.is_visible())

    def is_visible(self):
        """ is the keyboard window currently visible? """
        window = self.get_kbd_window()
        return window.is_visible() if window else False

    def set_visible(self, visible):
        """ main method to show/hide onboard manually """
        self.lock_auto_show_visible(visible)  # pause auto show
        self.transition_visible_to(visible, 0.0)

        # briefly present the window
        if visible and self.inactivity_timer.is_enabled():
            self.transition_active_to(True, 0.0)
            self.inactivity_timer.begin_transition(False)

        self.commit_transition()

    def lock_auto_show_visible(self, visible):
        """
        If the user unhides onboard, don't auto-hide it until
        he manually hides it again.
        """
        if config.is_auto_show_enabled():
            self.auto_show.lock_visible(visible)

    def freeze_auto_show(self, thaw_time = None):
        """
        Stop both, hiding and showing.
        """
        if config.is_auto_show_enabled():
            self.auto_show.freeze(thaw_time)

    def thaw_auto_show(self, thaw_time = None):
        """
        Reenable both, hiding and showing.
        """
        if config.is_auto_show_enabled():
            self.auto_show.thaw(thaw_time)

    def start_click_polling(self):
        if self.keyboard.has_latched_sticky_keys() or \
           self._alternative_keys_popup:
            self._outside_click_timer.start(0.01, self._on_click_timer)
            self._outside_click_detected = False
            self._outside_click_start_time = time.time()

    def stop_click_polling(self):
        self._outside_click_timer.stop()

    def _on_click_timer(self):
        """ poll for mouse click outside of onboards window """
        rootwin = Gdk.get_default_root_window()
        dunno, x, y, mask = rootwin.get_pointer()
        if mask & BUTTON123_MASK:
            self._outside_click_detected = True
        elif self._outside_click_detected:
            # button released anywhere outside of onboard's control
            self.stop_click_polling()
            self.close_alternative_keys_popup()
            self.keyboard.on_outside_click()
            return False

        # stop after 30 seconds
        if time.time() - self._outside_click_start_time > 30.0:
            self.stop_click_polling()
            self.keyboard.on_cancel_outside_click()
            return False

        return True

    def get_drag_window(self):
        """ Overload for WindowManipulator """
        return self.get_kbd_window()

    def get_drag_threshold(self):
        """ Overload for WindowManipulator """
        return config.get_drag_threshold()

    def on_drag_initiated(self):
        """ Overload for WindowManipulator """
        window = self.get_drag_window()
        if window:
            window.on_user_positioning_begin()

    def on_drag_activated(self):
        if self.is_resizing():
            self._lod = LOD.MINIMAL

    def on_drag_done(self):
        """ Overload for WindowManipulator """
        window = self.get_drag_window()
        if window:
            window.on_user_positioning_done()

        self.reset_lod()

    def get_always_visible_rect(self):
        """
        Returns the bounding rectangle of all move buttons
        in canvas coordinates.
        Overload for WindowManipulator
        """
        if config.is_docking_enabled():
            bounds = self.canvas_rect
        else:
            keys = self.keyboard.find_keys_from_ids(["move"])
            bounds = None
            for key in keys:
                r = key.get_canvas_border_rect()
                if not bounds:
                    bounds = r
                else:
                    bounds = bounds.union(r)

        return bounds

    def get_move_button_rect(self):
        """
        Returns the bounding rectangle of all move buttons
        in canvas coordinates.
        Overload for WindowManipulator
        """
        keys = self.keyboard.find_keys_from_ids(["move"])
        bounds = None
        for key in keys:
            r = key.get_canvas_border_rect()
            if not bounds:
                bounds = r
            else:
                bounds = bounds.union(r)

        return bounds

    def hit_test_move_resize(self, point):
        """ Overload for WindowManipulator """
        hit = self.touch_handles.hit_test(point)
        if hit is None:
            hit = WindowManipulator.hit_test_move_resize(self, point)
        return hit

    def _on_configure_event(self, widget, user_data):
        if self.canvas_rect.w != self.get_allocated_width() or \
           self.canvas_rect.h != self.get_allocated_height():
            self.update_layout()
            self.touch_handles.update_positions(self.canvas_rect)
            self.invalidate_keys()
            if self._lod == LOD.FULL:
                self.invalidate_shadows()
            self.invalidate_font_sizes()

    def _on_enter_notify(self, widget, event):
        self._update_double_click_time()

        # ignore event if a mouse button is held down
        # we get the event once the button is released
        if event.state & BUTTON123_MASK:
            return

        # ignore unreliable touch enter event for inactivity timer
        # -> smooths startup, only one transition in set_startup_visibility()
        source_device = event.get_source_device()
        source = source_device.get_source()
        if source != Gdk.InputSource.TOUCHSCREEN:

            # stop inactivity timer
            if self.inactivity_timer.is_enabled():
                self.inactivity_timer.begin_transition(True)

        # stop click polling
        self.stop_click_polling()

        # Force into view for WindowManipulator's system drag mode.
        #if not config.xid_mode and \
        #   not config.window.window_decoration and \
        #   not config.is_force_to_top():
        #    GLib.idle_add(self.force_into_view)

    def _on_leave_notify(self, widget, event):
        # ignore event if a mouse button is held down
        # we get the event once the button is released
        if event.state & BUTTON123_MASK:
            return

        # Ignore leave events when the cursor hasn't acually left
        # our window. Fixes window becoming idle-transparent while
        # typing into firefox awesomebar.
        # Can't use event.mode as that appears to be broken and
        # never seems to become GDK_CROSSING_GRAB (Precise).
        if self.canvas_rect.is_point_within((event.x, event.y)):
            return

        self.stop_dwelling()
        self.reset_touch_handles()

        # start a timer to detect clicks outside of onboard
        self.start_click_polling()

        # ignore unreliable touch leave event for inactivity timer
        source_device = event.get_source_device()
        source = source_device.get_source()
        if source != Gdk.InputSource.TOUCHSCREEN:

            # start inactivity timer
            if self.inactivity_timer.is_enabled():
                self.inactivity_timer.begin_transition(False)

    def do_set_cursor_at(self, point, hit_key = None):
        """ Set/reset the cursor for frame resize handles """
        if not config.xid_mode:
            allow_drag_cursors = not config.has_window_decoration() and \
                                 not hit_key
            self.set_drag_cursor_at(point, allow_drag_cursors)

    def on_input_sequence_begin(self, sequence):
        """ Button press/touch begin """
        self.stop_click_polling()
        self.stop_dwelling()
        self.close_alternative_keys_popup()

        # There's no reliable enter/leave for touch input
        # -> turn up transparency on touch begin
        if sequence.is_touch() and \
           self.inactivity_timer.is_enabled():
            self.inactivity_timer.begin_transition(True)

        point = sequence.point
        key = None

        # hit-test touch handles first
        hit_handle = None
        if self.touch_handles.active:
            hit_handle = self.touch_handles.hit_test(point)
            self.touch_handles.set_pressed(hit_handle)
            if not hit_handle is None:
                # handle clicked -> stop auto-show until button release
                self.stop_touch_handles_auto_hide()
            else:
                # no handle clicked -> hide them now
                self.show_touch_handles(False)

        # hit-test keys
        if hit_handle is None:
            key = self.get_key_at_location(point)

        # enable/disable the drag threshold
        if not hit_handle is None:
            self.enable_drag_protection(False)
        elif key and key.id == "move":
            # Move key needs to support long press;
            # always use the drag threshold.
            self.enable_drag_protection(True)
            self.reset_drag_protection()
        else:
            self.enable_drag_protection(config.drag_protection)

        # handle resizing
        if key is None and \
           not config.has_window_decoration() and \
           not config.xid_mode:
            if WindowManipulator.handle_press(self, sequence):
                return True

        # bail if we are in scanning mode
        if config.scanner.enabled:
            return True

        # press the key
        sequence.active_key = key
        if key:
            # single click?
            if self._last_click_key != key or \
               sequence.time - self._last_click_time > self._double_click_time:
                sequence.event_type = EventType.CLICK
                self.key_down(sequence)

                # start long press detection
                delay = config.keyboard.long_press_delay
                if key.id == "move":  # don't show touch handels too easily
                    delay += 0.3
                self._long_press_timer.start(delay,
                                             self._on_long_press, sequence)

            # double click?
            else:
                sequence.event_type = EventType.DOUBLE_CLICK
                self.key_down(sequence)

            self._last_click_key = key
            self._last_click_time = sequence.time

        return True

    def on_input_sequence_update(self, sequence):
        """ Pointer motion/touch update """
        if not sequence.primary:  # only drag with the very first sequence
            return

        point = sequence.point
        hit_key = None

        # hit-test touch handles first
        hit_handle = None
        if self.touch_handles.active:
            hit_handle = self.touch_handles.hit_test(point)
            self.touch_handles.set_prelight(hit_handle)

        # hit-test keys
        if hit_handle is None:
            hit_key = self.get_key_at_location(point)

        if sequence.state & BUTTON123_MASK:

            # move/resize
            # fallback=False for faster system resizing (LP: #959035)
            fallback = True #self.is_moving() or config.is_force_to_top()

            # move/resize
            WindowManipulator.handle_motion(self, sequence, fallback = fallback)

            # stop long press when drag threshold has been overcome
            if self.is_drag_active():
                self.stop_long_press()

        else:
            if not hit_handle is None:
                # handle hovered over -> extend their visible time
                self.start_touch_handles_auto_hide()

            # start dwelling if we have entered a dwell-enabled key
            if hit_key and \
               hit_key.sensitive:
                controller = self.keyboard.button_controllers.get(hit_key)
                if controller and controller.can_dwell() and \
                   not self.is_dwelling() and \
                   not self.already_dwelled(hit_key) and \
                   not config.scanner.enabled and \
                   not config.lockdown.disable_dwell_activation:
                    self.start_dwelling(hit_key)

            self.do_set_cursor_at(point, hit_key)

        # cancel dwelling when the hit key changes
        if self.dwell_key and self.dwell_key != hit_key or \
           self.last_dwelled_key and self.last_dwelled_key != hit_key:
            self.cancel_dwelling()

    def on_input_sequence_end(self, sequence):
        """ Button release/touch end """
        if sequence.active_key and \
           not config.scanner.enabled:
            self.key_up(sequence)

        self.stop_drag()
        self.stop_long_press()

        # reset cursor when there was no cursor motion
        point = sequence.point
        hit_key = self.get_key_at_location(point)
        self.do_set_cursor_at(point, hit_key)

        # reset touch handles
        self.reset_touch_handles()
        self.start_touch_handles_auto_hide()

        # There's no reliable enter/leave for touch input
        # -> start inactivity timer on touch end
        if sequence.is_touch() and \
           self.inactivity_timer.is_enabled():
            self.inactivity_timer.begin_transition(False)

    def on_drag_gesture_begin(self, num_touches):
        self.stop_long_press()

        if num_touches and \
           not self.is_drag_initiated():
            self.show_touch_handles()
            self.start_move_window()
        return True

    def on_drag_gesture_end(self, num_touches):
        self.stop_move_window()
        return True

    def on_tap_gesture(self, num_touches):
        if num_touches == 3:
            self.show_touch_handles()
            return True
        return False

    def _on_long_press(self, sequence):
        long_pressed = self.keyboard.key_long_press(sequence.active_key,
                                                    self, sequence.button)
        sequence.cancel = long_pressed # cancel generating key presses now

    def stop_long_press(self):
        self._long_press_timer.stop()

    def key_down(self, sequence):
        self.keyboard.key_down(sequence.active_key, self,
                               sequence.button, sequence.event_type)
        self._auto_release_timer.start()

    def key_up(self, sequence):
        self.keyboard.key_up(sequence.active_key, self,
                             sequence.button, sequence.event_type,
                             sequence.cancel)

    def is_dwelling(self):
        return not self.dwell_key is None

    def already_dwelled(self, key):
        return self.last_dwelled_key is key

    def start_dwelling(self, key):
        self.cancel_dwelling()
        self.dwell_key = key
        self.last_dwelled_key = key
        key.start_dwelling()
        self.dwell_timer = GLib.timeout_add(50, self._on_dwell_timer)

    def cancel_dwelling(self):
        self.stop_dwelling()
        self.last_dwelled_key = None

    def stop_dwelling(self):
        if self.dwell_timer:
            GLib.source_remove(self.dwell_timer)
            self.dwell_timer = None
            self.redraw([self.dwell_key])
            self.dwell_key.stop_dwelling()
            self.dwell_key = None

    def _on_dwell_timer(self):
        if self.dwell_key:
            self.redraw([self.dwell_key])

            if self.dwell_key.is_done():
                key = self.dwell_key
                self.stop_dwelling()

                sequence = InputSequence()
                sequence.button = 0
                sequence.event_type = EventType.DWELL
                sequence.active_key = key

                self.key_down(sequence)
                self.key_up(sequence)

                return False
        return True

    def _on_query_tooltip(self, widget, x, y, keyboard_mode, tooltip):
        if config.show_tooltips and \
           not self.is_drag_initiated() and \
           not self.last_event_was_touch():
            key = self.get_key_at_location((x, y))
            if key and key.tooltip:
                r = Gdk.Rectangle()
                r.x, r.y, r.width, r.height = key.get_canvas_rect()
                tooltip.set_tip_area(r)   # no effect on Oneiric?
                tooltip.set_text(_(key.tooltip))
                return True
        return False

    def show_touch_handles(self, show = True, auto_hide = True):
        """
        Show/hide the enlarged resize/move handels.
        Initiates an opacity fade.
        """
        if show and config.lockdown.disable_touch_handles:
            return

        if show:
            self.touch_handles.set_prelight(None)
            self.touch_handles.set_pressed(None)
            self.touch_handles.active = True
            self.touch_handles_auto_hide = auto_hide

            size, size_mm = self.get_monitor_dimensions()
            self.touch_handles.set_monitor_dimensions(size, size_mm)
            self.touch_handles.update_positions(self.canvas_rect)

            if auto_hide:
                self.start_touch_handles_auto_hide()

            start, end = 0.0, 1.0
        else:
            self.stop_touch_handles_auto_hide()
            start, end = 1.0, 0.0

        if self.touch_handles_fade.target_value != end:
            self.touch_handles_fade.time_step = 0.025
            self.touch_handles_fade.fade_to(start, end, 0.2,
                                      self._on_touch_handles_opacity)

    def reset_touch_handles(self):
        if self.touch_handles.active:
            self.touch_handles.set_prelight(None)
            self.touch_handles.set_pressed(None)

    def start_touch_handles_auto_hide(self):
        """ (re-) starts the timer to hide touch handles """
        if self.touch_handles.active and self.touch_handles_auto_hide:
            self.touch_handles_hide_timer.start(5,
                                                self.show_touch_handles, False)

    def stop_touch_handles_auto_hide(self):
        """ stops the timer to hide touch handles """
        self.touch_handles_hide_timer.stop()

    def _on_touch_handles_opacity(self, opacity, done):
        if done and opacity < 0.1:
            self.touch_handles.active = False

        self.touch_handles.opacity = opacity

        # Convoluted workaround for a weird cairo glitch (Precise).
        # When queuing all handles for drawing, the background under
        # the move handle is clipped erroneously and remains transparent.
        # -> Divide handles up into two groups, draw only one
        #    group at a time and fade with twice the frequency.
        if 0:
            self.touch_handles.redraw()
        else:
            for handle in self.touch_handles.handles:
                if bool(self.touch_handles_fade.iteration & 1) != \
                   (handle.id in [Handle.MOVE, Handle.NORTH, Handle.SOUTH]):
                    handle.redraw()

            if done:
                # draw the missing final step
                GLib.idle_add(self._on_touch_handles_opacity, 1.0, False)

    def _on_draw(self, widget, context):
        decorated = LayoutView.draw(self, widget, context)

        # draw touch handles (enlarged move and resize handles)
        if self.touch_handles.active:
            corner_radius = config.CORNER_RADIUS if decorated else 0
            self.touch_handles.set_corner_radius(corner_radius)
            self.touch_handles.draw(context)

    def emit_quit_onboard(self, data=None):
        _logger.debug("Entered emit_quit_onboard")
        self.get_kbd_window().emit("quit-onboard")

    def get_kbd_window(self):
        return self.get_parent()

    def can_draw_frame(self):
        """ Overload for LayoutView """
        co = self.get_kbd_window().get_orientation_config_object()
        return not config.is_dock_expanded(co)

    def get_monitor_dimensions(self):
        window = self.get_window()
        screen = self.get_screen()
        if window and screen:
            monitor = screen.get_monitor_at_window(window)
            r = screen.get_monitor_geometry(monitor)
            size = (r.width, r.height)
            size_mm = (screen.get_monitor_width_mm(monitor),
                       screen.get_monitor_height_mm(monitor))

            # Nexus7 simulation
            device = None       # keep this at None
            #device = 1
            if device == 0:     # dimension unavailable
                size_mm = 0, 0
            if device == 1:     # Nexus 7, as it should report
                size = 1280, 800
                size_mm = 150, 94

            return size, size_mm
        else:
            return None, None

    def get_min_window_size(self):
        min_mm = (50, 20)  # just large enough to grab with a 3 finger gesture
        size, size_mm = self.get_monitor_dimensions()
        if size and size_mm:
            w = size[0] * min_mm[0] / size_mm[0] \
                if size_mm[0] else 150
            h = size[1] * min_mm[1] / size_mm[1] \
                if size_mm[0] else 100
        else:
            w = h = 0
        return w, h

    def get_frame_width(self):
        """ Width of the frame around the keyboard; canvas coordinates. """
        if config.xid_mode:
            return 1.0
        if config.has_window_decoration():
            return 0.0
        co = self.get_kbd_window().get_orientation_config_object()
        if config.is_dock_expanded(co):
            return 0.5
        if config.window.transparent_background:
            return 1.0
        return config.UNDECORATED_FRAME_WIDTH

    def get_hit_frame_width(self):
        return 10

    def _get_active_drag_handles(self, all_handles = False):
        if config.xid_mode:  # none when xembedding
            handles = ()
        else:
            if config.is_docking_enabled():
                expand = self.get_kbd_window().get_dock_expand()
                if expand:
                    handles = (Handle.NORTH, Handle.SOUTH, Handle.MOVE)
                else:
                    handles = Handle.ALL
            else:
                handles = Handle.ALL

            if not all_handles:
                # filter through handles enabled in config
                config_handles = config.window.resize_handles
                handles = tuple(set(handles).intersection(set(config_handles)))

        return handles

    def get_click_type_button_rects(self):
        """
        Returns bounding rectangles of all click type buttons
        in root window coordinates.
        """
        keys = self.keyboard.find_keys_from_ids(["singleclick",
                                                 "secondaryclick",
                                                 "middleclick",
                                                 "doubleclick",
                                                 "dragclick"])
        rects = []
        for key in keys:
            r = key.get_canvas_border_rect()
            rects.append(self.canvas_to_root_window_rect(r))

        return rects

    def canvas_to_root_window_rect(self, rect):
        """
        Convert rect in canvas coordinates to root window coordinates.
        """
        window = self.get_window()
        if window:
            x0, y0 = self.get_window().get_root_coords(rect.x, rect.y)
            x1, y1 = self.get_window().get_root_coords(rect.x + rect.w,
                                                       rect.y + rect.h)
            rect = Rect.from_extents(x0, y0, x1, y1)

        return rect

    def on_layout_updated(self):
        # experimental support for keeping window aspect ratio
        # Currently, in Oneiric, neither lightdm, nor gnome-screen-saver
        # appear to honor these hints.
        layout = self.get_layout()

        aspect_ratio = None
        if config.is_keep_aspect_ratio_enabled():
            log_rect = layout.get_border_rect()
            aspect_ratio = log_rect.w / float(log_rect.h)
            aspect_ratio = layout.get_log_aspect_ratio()

        if self._aspect_ratio != aspect_ratio:
            window = self.get_kbd_window()
            if window:
                geom = Gdk.Geometry()
                if aspect_ratio is None:
                    window.set_geometry_hints(self, geom, 0)
                else:
                    geom.min_aspect = geom.max_aspect = aspect_ratio
                    window.set_geometry_hints(self, geom, Gdk.WindowHints.ASPECT)

                self._aspect_ratio = aspect_ratio

    def refresh_pango_layouts(self):
        """
        When the systems font dpi setting changes, our pango layout object
        still caches the old setting, leading to wrong font scaling.
        Refresh the pango layout object.
        """
        _logger.info("Refreshing pango layout, new font dpi setting is '{}'" \
                .format(Gtk.Settings.get_default().get_property("gtk-xft-dpi")))

        Key.reset_pango_layout()
        self.invalidate_label_extents()
        self.keyboard.update_ui()

    def edit_snippet(self, snippet_id):
        dialog = Gtk.Dialog(_("New snippet"),
                            self.get_toplevel(), 0,
                            (Gtk.STOCK_CANCEL,
                             Gtk.ResponseType.CANCEL,
                             _("_Save snippet"),
                             Gtk.ResponseType.OK))

        # Don't hide dialog behind the keyboard in force-to-top mode.
        if config.is_force_to_top():
            dialog.set_position(Gtk.WindowPosition.NONE)

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

    def cb_dialog_response(self, dialog, response, snippet_id, \
                           label_entry, text_entry):
        if response == Gtk.ResponseType.OK:
            label = label_entry.get_text()
            text = text_entry.get_text()

            if sys.version_info.major == 2:
                label = label.decode("utf-8")
                text = text.decode("utf-8")

            config.set_snippet(snippet_id, (label, text))
        dialog.destroy()

        self.keyboard.editing_snippet = False

    def show_alternative_keys_popup(self, key, alternatives):
        r = key.get_canvas_border_rect()
        root_rect = self.canvas_to_root_window_rect(r)
        kbd_window = self.get_kbd_window()

        popup = AlternativeKeysPopup(self.keyboard,
                                     self.close_alternative_keys_popup)
        popup.create_layout(key, alternatives, self.get_color_scheme())
        popup.supports_alpha = self.supports_alpha
        popup.position_at(root_rect.x + root_rect.w * 0.5,
                         root_rect.y, 0.5, 1.0)
        popup.set_transient_for(kbd_window)
        popup.set_opacity(kbd_window.get_opacity())
        popup.show()

        self._alternative_keys_popup = popup

    def close_alternative_keys_popup(self):
        if self._alternative_keys_popup:
            self._alternative_keys_popup.destroy()
            self._alternative_keys_popup = None


class AlternativeKeysPopup(Gtk.Window, LayoutView, TouchInput):

    MAX_KEY_COLUMNS  = 8  # max number of keys in one row
    IDLE_CLOSE_DELAY = 0  # seconds of inactivity until window closes

    def __init__(self, keyboard, notify_done_callback):
        self._layout = None
        self._notify_done_callback = notify_done_callback

        Gtk.Window.__init__(self,
                            skip_taskbar_hint=True,
                            skip_pager_hint=True,
                            has_resize_grip=False,
                            urgency_hint=False,
                            decorated=False,
                            accept_focus=False,
                            opacity=1.0)

        self.set_keep_above(True)

        # use transparency if available
        screen = Gdk.Screen.get_default()
        visual = screen.get_rgba_visual()
        if visual:
            self.set_visual(visual)
            self.override_background_color(Gtk.StateFlags.NORMAL,
                                           Gdk.RGBA(0, 0, 0, 0))
            self.supports_alpha = True

        LayoutView.__init__(self, keyboard)
        TouchInput.__init__(self)

        self.connect("draw",                 self._on_draw)
        self.connect("realize",              self._on_realize_event)
        self.connect("destroy",              self._on_destroy_event)
        self.connect("enter-notify-event",   self._on_enter_notify)
        self.connect("leave-notify-event",   self._on_leave_notify)

        self._close_timer = Timer()
        self.start_close_timer()

    def cleanup(self):
        self.stop_close_timer()
        LayoutView.cleanup(self)  # deregister from keyboard
        TouchInput.cleanup(self)  # deregister device events

    def get_layout(self):
        return self._layout

    def get_frame_width(self):
        return self._frame_width

    def create_layout(self, source_key, alternatives, color_scheme):
        keys = []
        context = source_key.context

        # calculate border around the layout
        canvas_border = context.scale_log_to_canvas((1, 1))
        self._frame_width = 7 + min(canvas_border)
        frame_width = self.get_frame_width()
        frame_size  = frame_width, frame_width

        # parse alterantives into lines
        lines, ncolumns = self.parse_alternatives(alternatives)
        nrows = len(lines)
        spacing     = (1, 1)

        # calc canvas size
        rect = source_key.get_canvas_border_rect()
        layout_canvas_rect = Rect(frame_size[0], frame_size[1],
                              rect.w * ncolumns + spacing[0] * (ncolumns - 1),
                              rect.h * nrows + spacing[1] * (nrows - 1))

        canvas_rect = layout_canvas_rect.inflate(*frame_size)

        # subdive into logical rectangles for the keys
        layout_rect = context.canvas_to_log_rect(layout_canvas_rect)
        key_rects = layout_rect.subdivide(ncolumns, nrows, *spacing)

        # create the keys, slots for empty labels are skipped
        count = 0
        for i, line in enumerate(lines):
            for j, label in enumerate(line):
                slot = i * ncolumns + j
                if label:
                    key = RectKey("_alternative" + str(count), key_rects[slot])
                    key.group  = "alternatives"
                    key.color_scheme = color_scheme
                    if label == "-x-":
                        key.labels = {}
                        key.image_filename = "close.svg"
                        key.type = KeyCommon.BUTTON_TYPE
                    else:
                        key.labels = {0: label}
                        key.code  = label[0]
                        key.type = KeyCommon.CHAR_TYPE
                    keys.append(key)
                    count += 1

        item = LayoutPanel()
        item.border  = 0
        item.set_items(keys)
        layout = LayoutRoot(item)
        layout.fit_inside_canvas(layout_canvas_rect)
        self._layout = layout
        self.update_labels()

        self.color_scheme = color_scheme

        # set window size
        w, h = canvas_rect.get_size()
        self.set_default_size(w + 1, h + 1)

    def parse_alternatives(self, alternatives):
        """
        Split alternatives into lines, support newlines and
        append a close button.
        """
        if "\n" in alternatives:
            return self.parse_free_format(alternatives)
        else:
            return self.parse_fixed(alternatives)

    def parse_fixed(self, alternatives):
        max_columns = self.MAX_KEY_COLUMNS
        min_columns = max_columns // 2

        # find the number of columns with the best packing,
        # i.e. the least number of empty slots.
        n = len(alternatives) + 1    # +1 for close button
        max_mod = 0
        ncolumns = max_columns
        for i in range(max_columns, min_columns, -1):
            m = n % i
            if m == 0:
                max_mod = m
                ncolumns = i
                break
            if max_mod < m:
                max_mod = m
                ncolumns = i

        # limit to len for the single row case
        ncolumns = min(n, ncolumns)

        # cut the input into lines of the newly found optimal length
        lines = []
        line = []
        column = 0
        for value in alternatives:
            line.append(value)
            column += 1
            if column >= ncolumns:
                lines.append(line)
                line = []
                column = 0

        # append slot for close button
        n = len(line)
        line.extend([""]*(ncolumns - (n+1)))
        line.append("-x-")
        lines.append(line)

        return lines, ncolumns

    def parse_free_format(self, alternatives):
        max_columns = self.MAX_KEY_COLUMNS

        lines = []
        line = None
        ncolumns = 0

        for value in alternatives + ["-x-"]:
            if value == "\n" or \
               line and len(line) >= max_columns:
                if line:
                    lines.append(line)
                line = None

            if not value in ["\n"]:
                if value == "-x-":
                    if not line:
                        line = []
                    n = len(line)
                    line.extend([""]*(ncolumns - (n+1)))
                    line.append(value)
                    ncolumns = max(ncolumns, len(line))
                else:
                    if not line:
                        line = []
                    line.append(value)
                    ncolumns = max(ncolumns, len(line))

        if line:
            lines.append(line)

        return lines, ncolumns

    def position_at(self, x, y, x_align, y_align):
        """
        Align the window with the given point.
        x, y in root window coordinates.
        """
        rect = Rect.from_position_size(self.get_position(), self.get_size())
        rect = rect.align_at_point(x, y, x_align, y_align)
        rect = self.limit_to_workarea(rect)
        x, y = rect.get_position()

        self.move(x, y)

    def limit_to_workarea(self, rect, x_mon, y_mon):
        screen = self.get_screen()
        mon = screen.get_monitor_at_point(x_mon, y_mon)
        area = screen.get_monitor_workarea(mon)
        area = Rect(area.x, area.y, area.width, area.height)
        return rect.intersection(area)

    def limit_to_workarea(self, rect):
        visible_rect = Rect(0, 0, rect.w, rect.h)

        x, y = limit_window_position(rect.x, rect.y, visible_rect,
                                     get_monitor_rects(self.get_screen()))
        return Rect(x, y, rect.w, rect.h)

    def _on_realize_event(self, user_data):
        self.get_window().set_override_redirect(True)

    def _on_destroy_event(self, user_data):
        self.cleanup()

    def _on_enter_notify(self, widget, event):
        self.stop_close_timer()

    def _on_leave_notify(self, widget, event):
        self.start_close_timer()

    def on_input_sequence_begin(self, sequence):
        self.stop_close_timer()
        key = self.get_key_at_location(sequence.point)
        if key:
            sequence.active_key = key
            self.keyboard.key_down(key, self, sequence.button)

    def on_input_sequence_update(self, sequence):
        pass

    def on_input_sequence_end(self, sequence):
        key = sequence.active_key
        if key:
            keyboard = self.keyboard
            keyboard.key_up(key, self, sequence.button)

            Timer(config.UNPRESS_DELAY, self.close_window)
        else:
            self.close_window()

    def _on_draw(self, widget, context):
        decorated = LayoutView.draw(self, widget, context)

    def draw_window_frame(self, context, lod):
        corner_radius = config.CORNER_RADIUS
        border_rgba = self.get_popup_window_rgba("border")
        alpha = border_rgba[3]

        colors = [
                  [[0.5, 0.5, 0.5, alpha], 0, 1],
                  [           border_rgba, 1.5, 2.0],
                 ]

        rect = Rect(0, 0, self.get_allocated_width(),
                          self.get_allocated_height())

        for rgba, pos, width in colors:
            r = rect.deflate(width)
            roundrect_arc(context, r, corner_radius)
            context.set_line_width(width)
            context.set_source_rgba(*rgba)
            context.stroke()

    def close_window(self):
        self._notify_done_callback()

    def start_close_timer(self):
        if self.IDLE_CLOSE_DELAY:
            self._close_timer.start(self.IDLE_CLOSE_DELAY, self.close_window)

    def stop_close_timer(self):
        self._close_timer.stop()

