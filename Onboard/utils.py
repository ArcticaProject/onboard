# -*- coding: utf-8 -*-

from __future__ import division, print_function, unicode_literals

import sys
import os
import time
import re
import traceback
import colorsys
from subprocess import Popen
from math import pi, sqrt, sin
from contextlib import contextmanager

from gi.repository import GObject, Gtk

### Logging ###
import logging
from functools import reduce
_logger = logging.getLogger("utils")
###############

modifiers = {"shift":1,
             "caps":2,
             "control":4,
             "mod1":8,
             "mod2":16,
             "mod3":32,
             "mod4":64,
             "mod5":128}


modDic = {"LWIN" : ("Win",64),
          "RTSH" : ("⇧", 1),
          "LFSH" : ("⇧", 1),
          "RALT" : ("Alt Gr", 128),
          "LALT" : ("Alt", 8),
          "RCTL" : ("Ctrl", 4),
          "LCTL" : ("Ctrl", 4),
          "CAPS" : ("CAPS", 2),
          "NMLK" : ("Nm\nLk",16)}

otherDic = {"RWIN" : "Win",
            "MENU" : "Menu",
            "BKSP" : "⇦",
            "RTRN" : "Return",
            "TAB" : "Tab",
            "INS":"Ins",
            "HOME":"Hm",
            "PGUP": "Pg\nUp",
            "DELE":"Del",
            "END":"End",
            "PGDN":"Pg\nDn",
            "UP":  "↑",
            "DOWN":"↓",
            "LEFT" : "←",
            "RGHT" : "→",
            "KP0" : "0",
            "KP1" : "1",
            "KP2" : "2",
            "KP3" : "3",
            "KP4" : "4",
            "KP5" : "5",
            "KP6" : "6",
            "KP7" : "7",
            "KP8" : "8",
            "KP9" : "9",
            "KPDL":"Del",
            "KPEN": "Ent" }

funcKeys = (("ESC",65307),
            ("F1",65470),
            ("F2",65471),
            ("F3",65472),
            ("F4", 65473),
            ("F5", 65474),
            ("F6",65475),
            ("F7",65476),
            ("F8",65477),
            ("F9",65478),
            ("F10",65479),
            ("F11", 65480),
            ("F12", 65481),
            ("Prnt", 65377),
            ("Scroll", 65300),
            ("Pause", 65299))

keysyms = {"space" : 65408,
           "insert" : 0xff63,
           "home" : 0xff50,
           "page_up" : 0xff55,
           "page_down" : 0xff56,
           "end" :0xff57,
           "delete" : 0xffff,
           "return" : 65293,
           "backspace" : 65288,
           "left" : 0xff51,
           "up" : 0xff52,
           "right" : 0xff53,
           "down" : 0xff54,}

def get_keysym_from_name(name):
    return keysyms[name]

def run_script(script):
    a =__import__(script)
    a.run()

def toprettyxml(domdoc):
    ugly_xml = domdoc.toprettyxml(indent='  ')
    # Join lines with text elements with their tag lines
    pattern = re.compile('>\n\s+([^<>\s].*?)\n\s+</', re.DOTALL)
    pretty_xml = pattern.sub('>\g<1></', ugly_xml)

    # Work around http://bugs.python.org/issue5752
    pretty_xml = re.sub(
           '"[^"]*"',
           lambda m: m.group(0).replace("\n", "&#10;"),
           pretty_xml)

    # remove empty lines
    pretty_xml = os.linesep.join( \
                    [s for s in pretty_xml.splitlines() if s.strip()])
    return pretty_xml


def dec_to_hex_colour(dec):
    hexString = hex(int(255*dec))[2:]
    if len(hexString) == 1:
        hexString = "0" + hexString

    return hexString

def xml_get_text(dom_node, tag_name):
    """ extract text from a dom node """
    nodelist = dom_node.getElementsByTagName(tag_name)
    if not nodelist:
        return None
    rc = []
    for node in nodelist[0].childNodes:
        if node.nodeType == node.TEXT_NODE:
            rc.append(node.data)
    return ''.join(rc).strip()

def matmult(m, v):
    """ Matrix-vector multiplication """
    nrows = len(m)
    w = [None] * nrows
    for row in range(nrows):
        w[row] = reduce(lambda x,y: x+y, list(map(lambda x,y: x*y, m[row], v)))
    return w

def hexstring_to_float(hexString):
    return float(int(hexString, 16))

class dictproperty(object):
    """ Property implementation for dictionaries """

    class _proxy(object):

        def __init__(self, obj, fget, fset, fdel):
            self._obj = obj
            self._fget = fget
            self._fset = fset
            self._fdel = fdel

        def __getitem__(self, key):
            if self._fget is None:
                raise TypeError("can't read item")
            return self._fget(self._obj, key)

        def __setitem__(self, key, value):
            if self._fset is None:
                raise TypeError("can't set item")
            self._fset(self._obj, key, value)

        def __delitem__(self, key):
            if self._fdel is None:
                raise TypeError("can't delete item")
            self._fdel(self._obj, key)

    def __init__(self, fget=None, fset=None, fdel=None, doc=None):
        self._fget = fget
        self._fset = fset
        self._fdel = fdel
        self.__doc__ = doc

    def __get__(self, obj, objtype=None):
        if obj is None:
            return self
        return self._proxy(obj, self._fget, self._fset, self._fdel)

def show_error_dialog(error_string):
    """ Show an error dialog """

    error_dlg = Gtk.MessageDialog(type=Gtk.MessageType.ERROR,
                                  message_format=error_string,
                                  buttons=Gtk.ButtonsType.OK)
    error_dlg.run()
    error_dlg.destroy()

def show_ask_string_dialog(question, parent=None):
    question_dialog = Gtk.MessageDialog(type=Gtk.MessageType.QUESTION,
                                        buttons=Gtk.ButtonsType.OK_CANCEL)
    if parent:
        question_dialog.set_transient_for(parent)
    question_dialog.set_markup(question)
    entry = Gtk.Entry()
    entry.connect("activate", lambda event:
        question_dialog.response(Gtk.ResponseType.OK))
    question_dialog.get_message_area().add(entry)
    question_dialog.show_all()
    response = question_dialog.run()
    text = entry.get_text() if response == Gtk.ResponseType.OK else None
    question_dialog.destroy()
    return text

def show_confirmation_dialog(question, parent=None):
    """
    Show this dialog to ask confirmation before executing a task.
    """
    dlg = Gtk.MessageDialog(type=Gtk.MessageType.QUESTION,
                            message_format=question,
                            buttons=Gtk.ButtonsType.YES_NO)
    if parent:
        dlg.set_transient_for(parent)
    response = dlg.run()
    dlg.destroy()
    return response == Gtk.ResponseType.YES

def show_new_device_dialog(name, config_string, is_pointer, callback):
    """
    Show a "New Input Device" dialog.
    """
    dialog = Gtk.MessageDialog(type  = Gtk.MessageType.OTHER,
                               title = _("New Input Device"),
                               text  = _("Onboard has detected a new input device"))
    if is_pointer:
        dialog.set_image(Gtk.Image(icon_name = "input-mouse",
                                   icon_size = Gtk.IconSize.DIALOG))
    else:
        dialog.set_image(Gtk.Image(icon_name = "input-keyboard",
                                   icon_size = Gtk.IconSize.DIALOG))

    secondary  = "<i>{}</i>\n\n".format(name)
    secondary += _("Do you want to use this device for keyboard scanning?")

    dialog.format_secondary_markup(secondary)
    dialog.add_button(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL)
    dialog.add_button(_("Use device"), Gtk.ResponseType.ACCEPT).grab_default()
    dialog.connect("response", _show_new_device_dialog_response,
                   callback, config_string)
    dialog.show_all()

def _show_new_device_dialog_response(dialog, response, callback, config_string):
    """ Callback for the "New Input Device" dialog. """
    if response == Gtk.ResponseType.ACCEPT:
        callback(config_string)
    dialog.destroy()

def unpack_name_value_list(_list, num_values=2, key_type = str):
    """
    Converts a list of strings into a dict of tuples.
    Sample list: ['LWIN:label:super', ...]
    ":" in a value must be escaped as "\:"
    "\" in a value must be escaped as "\\"
    """
    result = {}

    # Awkward fixed regexes; todo: Allow arbirary number of values
    if num_values == 1:
        pattern = re.compile(r"""([^\s:]+)             # name
                                 : ((?:\\.|[^\\:])*)   # first value
                             """, re.VERBOSE)
    elif num_values == 2:
        pattern = re.compile(r"""([^\s:]+)             # name
                                 : ((?:\\.|[^\\:])*)   # first value
                                 : ((?:\\.|[^\\:])*)   # second value
                             """, re.VERBOSE)
    else:
        assert(False)  # unsupported number of values

    for text in _list:
        tuples = pattern.findall(text)
        if tuples:
            a = []
            for t in tuples[0]:
                t = t.replace("\\\\", "\\")   # unescape backslash
                t = t.replace("\\:", ":")     # unescape separator
                a.append(t)

            if key_type == str:
                item = {a[0] : (a[1:])}
            elif key_type == int:
                item = {int(a[0]) : (a[1:])}
            else:
                assert(False)
            result.update(item)

    return result

def pack_name_value_list(tuples, field_sep=":", name_sep=":"):
    """
    Converts a dict of tuples to a string array. It creates one string
    per dict key, with the key-string separated by <name_sep> and
    individual tuple elements separated by <field_sep>.
    """
    result = []
    for t in list(tuples.items()):
        text = str(t[0])
        sep = name_sep
        for value in t[1]:
            value = value.replace("\\", "\\\\")   # escape backslash
            value = value.replace(sep, "\\"+sep)  # escape separator
            text += sep + '%s' % value
            sep = field_sep
        result.append(text)
    return result

def merge_tuple_strings(text1, text2):
    """
    Existing entries in text1 will be kept or overwritten by text2.
    """
    tuples1 = unpack_name_value_tuples(text1)
    tuples2 = unpack_name_value_tuples(text2)
    for key,values in list(tuples2.items()):
        tuples1[key] = values
    return pack_name_value_tuples(tuples1)


class CallOnce(object):
    """
    call each <callback> during <delay> only once
    Useful to reduce a storm of config notifications
    to just a single (or a few) update(s) of onboards state.
    """

    def __init__(self, delay=20, delay_forever=False):
        self.callbacks = {}
        self.timer = None
        self.delay = delay
        self.delay_forever = delay_forever

    def enqueue(self, callback, *args):
        if not callback in self.callbacks:
            self.callbacks[callback] = args
        else:
            #print "CallOnce: ignored ", callback, args
            pass

        if self.delay_forever and self.timer:
            GObject.source_remove(self.timer)
            self.timer = None

        if not self.timer and self.callbacks:
            self.timer = GObject.timeout_add(self.delay, self.cb_timer)

    def cb_timer(self):
        for callback, args in list(self.callbacks.items()):
            try:
                callback(*args)
            except:
                traceback.print_exc()

        self.callbacks.clear()
        self.timer = None
        return False


class Rect:
    """
    Simple rectangle class.
    Left and top are included, right and bottom excluded.
    Attributes can be accessed by name or by index, e.g. rect.x or rect[0].
    """

    attributes = ("x", "y", "w", "h")

    def __init__(self, x = 0, y = 0, w = 0, h = 0):
        self.x = x
        self.y = y
        self.w = w
        self.h = h

    def __len__(self):
        return 4

    def __getitem__(self, index):
        """ Collection interface for rvalues, unpacking with '*' operator """
        return getattr(self, self.attributes[index])

    def __setitem__(self, index, value):
        """ Collection interface for lvalues """
        return setattr(self, self.attributes[index], value)

    def __str__(self):
        return "Rect(" + \
            " ".join(a+"="+str(getattr(self, a)) for a in self.attributes) + \
            ")"

    def __eq__(self, other):
        return self.x == other.x and \
               self.y == other.y and \
               self.w == other.w and \
               self.h == other.h

    def __ne__(self, other):
        return self.x != other.x or \
               self.y != other.y or \
               self.w != other.w or \
               self.h != other.h

    @staticmethod
    def from_extents(x0, y0, x1, y1):
        """
        New Rect from two points.
        x0 and y0 are considered inside, x1 and y1 are just outside the Rect.
        """
        return Rect(x0, y0, x1 - x0, y1 - y0)

    @staticmethod
    def from_position_size(position, size):
        """
        New Rect from two tuples.
        """
        return Rect(position[0], position[1], size[0], size[1])

    @staticmethod
    def from_points(p0, p1):
        """
        New Rect from two points, left-top and right-botton.
        The former lies inside, while the latter is considered to be
        just outside the rect.
        """
        return Rect(p0[0], p0[1], p1[0] - p0[0], p1[1] - p0[1])

    def to_extents(self):
        return self.x, self.y , self.x + self.w, self.y + self.h

    def to_position_size(self):
        return (self.x, self.y), (self.w, self.h)

    def copy(self):
        return Rect(self.x, self.y, self.w, self.h)

    def is_empty(self):
        return self.w <= 0 or self.h <= 0

    def get_position(self):
        return (self.x, self.y)

    def get_size(self):
        return (self.w, self.h)

    def get_center(self):
        return (self.x + self.w / 2.0, self.y + self.h / 2.0)

    def top(self):
        return self.y

    def left(self):
        return self.x

    def right(self):
        return self.x + self.w

    def bottom(self):
        return self.y + self.h

    def left_top(self):
        return self.x, self.y

    def is_point_within(self, point):
        """ True, if the given point lies inside the rectangle """
        if self.x <= point[0] and \
           self.x + self.w > point[0] and \
           self.y <= point[1] and \
           self.y + self.h > point[1]:
            return True
        return False

    def round(self):
        return Rect(round(self.x), round(self.y), round(self.w), round(self.h))

    def int(self):
        return Rect(int(self.x), int(self.y), int(self.w), int(self.h))

    def offset(self, dx, dy):
        """
        Returns a new Rect displaced by dx and dy.
        """
        return Rect(self.x + dx, self.y + dy, self.w, self.h)

    def inflate(self, dx, dy = None):
        """
        Returns a new Rect which is larger by dx and dy on all sides.
        """
        if dy is None:
            dy = dx
        return Rect(self.x-dx, self.y-dy, self.w+2*dx, self.h+2*dy)

    def apply_border(self, left, top, right, bottom):
        """
        Returns a new Rect which is larger by l, t, r, b on all sides.
        """
        return Rect(self.x-left, self.y-top,
                    self.w+left+right, self.h+top+bottom)

    def deflate(self, dx, dy = None):
        """
        Returns a new Rect which is smaller by dx and dy on all sides.
        """
        if dy is None:
            dy = dx
        return Rect(self.x+dx, self.y+dy, self.w-2*dx, self.h-2*dy)

    def grow(self, kx, ky = None):
        """
        Returns a new Rect with its size multiplied by kx, ky.
        """
        if ky is None:
            ky = kx
        w = self.w * kx
        h = self.h * ky
        return Rect(self.x + (self.w - w) / 2.0,
                    self.y + (self.h - h) / 2.0,
                    w, h)

    def intersects(self, rect):
        return not self.intersection(rect).is_empty()

    def intersection(self, rect):
       x0 = max(self.x, rect.x)
       y0 = max(self.y, rect.y)
       x1 = min(self.x + self.w,  rect.x + rect.w)
       y1 = min(self.y + self.h,  rect.y + rect.h)
       if x0 > x1 or y0 > y1:
           return Rect()
       else:
           return Rect(x0, y0, x1 - x0, y1 - y0)

    def union(self, rect):
       x0 = min(self.x, rect.x)
       y0 = min(self.y, rect.y)
       x1 = max(self.x + self.w,  rect.x + rect.w)
       y1 = max(self.y + self.h,  rect.y + rect.h)
       return Rect(x0, y0, x1 - x0, y1 - y0)

    def inscribe_with_aspect(self, rect, x_align = 0.5, y_align = 0.5):
        """ Returns a new Rect with the aspect ratio of self
            that fits inside the given rectangle.
        """
        if self.is_empty() or rect.is_empty():
            return Rect()

        src_aspect = self.w / float(self.h)
        dst_aspect = rect.w / float(rect.h)

        result = rect.copy()
        if dst_aspect > src_aspect:
            result.w = rect.h * src_aspect
            result.x = x_align * (rect.w - result.w)
        else:
            result.h = rect.w / src_aspect
            result.y = y_align * (rect.h - result.h)
        return result

    def align_rect(self, rect, x_align = 0.5, y_align = 0.5):
        """
        Alignes the given rect inside of self.
        x/y_align = 0.5 centers rect.
        """
        x = self.x + (self.w - rect.w) * x_align
        y = self.y + (self.h - rect.h) * y_align
        return Rect(x, y, rect.w, rect. h)

    def subdivide(self, rows, columns, x_spacing = None, y_spacing = None):
        """ Divide self into rows x columns sub-rectangles """
        if y_spacing is None:
            y_spacing = x_spacing
        if x_spacing is None:
            x_spacing = 0

        x, y, w, h = self
        ws = (self.w - (columns - 1) * x_spacing) / float(columns)
        hs = (self.h - (rows - 1)    * y_spacing) / float(rows)

        rects = []
        y = self.y
        for row in range(rows):
            x = self.x
            for column in range(columns):
                rects.append(Rect(x, y, ws, hs))
                x += ws + x_spacing
            y += hs + y_spacing

        return rects


def brighten(amount, r, g, b, a=0.0):
    """ Make the given color brighter by amount a [-1.0...1.0] """
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    l += amount
    if l > 1.0:
        l = 1.0
    if l < 0.0:
        l = 0.0
    return list(colorsys.hls_to_rgb(h, l, s)) + [a]


def roundrect_arc(context, rect, r = 15):
    x0,y0 = rect.x, rect.y
    x1,y1 = x0 + rect.w, y0 + rect.h

    # top left
    context.move_to(x0+r, y0)

    # top right
    context.line_to(x1-r,y0)
    context.arc(x1-r, y0+r, r, -pi/2, 0)

    # bottom right
    context.line_to(x1, y1-r)
    context.arc(x1-r, y1-r, r, 0, pi/2)

    # bottom left
    context.line_to(x0+r, y1)
    context.arc(x0+r, y1-r, r, pi/2, pi)

    # top left
    context.line_to(x0, y0+r)
    context.arc(x0+r, y0+r, r, pi, pi*1.5)

    context.close_path ()


def roundrect_curve(context, rect, r_pct = 100):
    """
    Uses B-splines for less even looks than with arcs, but
    still allows for approximate circles at r_pct = 100.
    """
    x0, y0 = rect.x, rect.y
    x1, y1 = rect.x + rect.w, rect.y + rect.h
    w, h   = rect.w, rect.h

    r = min(w, h) * min(r_pct/100.0, 0.5) # full range at 50%
    k = (r-1) * r_pct/200.0 # position of control points for circular curves

    # top left
    context.move_to(x0+r, y0)

    # top right
    context.line_to(x1-r,y0)
    context.curve_to(x1-k, y0, x1, y0+k, x1, y0+r)

    # bottom right
    context.line_to(x1, y1-r)
    context.curve_to(x1, y1-k, x1-k, y1, x1-r, y1)

    # bottom left
    context.line_to(x0+r, y1)
    context.curve_to(x0+k, y1, x0, y1-k, x0, y1-r)

    # top left
    context.line_to(x0, y0+r)
    context.curve_to(x0, y0+k, x0+k, y0, x0+r, y0)

    context.close_path ()


def round_corners(cr, r, x, y, w, h):
    """
    Paint 4 round corners.
    Currently x, y are ignored and assumed to be 0.
    """
    # top-left
    cr.curve_to (0, r, 0, 0, r, 0)
    cr.line_to (0, 0)
    cr.close_path()
    cr.fill()
    # top-right
    cr.curve_to (w, r, w, 0, w - r, 0)
    cr.line_to (w, 0)
    cr.close_path()
    cr.fill()
    # bottom-left
    cr.curve_to (r, h, 0, h, 0, h - r)
    cr.line_to (0, h)
    cr.close_path()
    cr.fill()
    # bottom-right
    cr.curve_to (w, h - r, w, h, w - r, h)
    cr.line_to (w, h)
    cr.close_path()
    cr.fill()


@contextmanager
def timeit(s, out=sys.stdout):
    import time, gc

    if out:
        gc.collect()
        gc.collect()
        gc.collect()

        t = time.time()
        text = s if s else "timeit"
        out.write("%-15s " % text)
        out.flush()
        yield None
        out.write("%10.3fms\n" % ((time.time() - t)*1000))
    else:
        yield None


class Timer(object):
    """
    Simple wrapper around gobject's timer API
    Overload on_timer in derived classes.
    For one-shot timers return False there.
    """
    _timer = None
    _callback = None
    _callback_args = None

    def __init__(self, delay = None, callback = None, *callback_args):
        self._callback = callback
        self._callback_args = callback_args

        if not delay is None:
            self.start(delay)

    def start(self, delay, callback = None, *callback_args):
        """
        Delay in seconds.
        Uses second granularity if delay is of type int.
        Uses medium resolution timer if delay is of type float.
        """
        if callback:
            self._callback = callback
            self._callback_args = callback_args

        self.stop()

        if type(delay) == int:
            self._timer = GObject.timeout_add_seconds(delay, self._cb_timer)
        else:
            ms = int(delay * 1000.0)
            self._timer = GObject.timeout_add(ms, self._cb_timer)

    def finish(self):
        """
        Run one last time and stop.
        """
        if self.is_running():
            self.stop()
            self.on_timer()

    def stop(self):
        if self.is_running():
            GObject.source_remove(self._timer)
            self._timer = None

    def is_running(self):
        return self._timer is not None

    def _cb_timer(self):
        if not self.on_timer():
            self.stop()
            return False
        return True

    def on_timer(self):
        """
        Overload this.
        For one-shot timers return False.
        """
        if self._callback:
            return self._callback(*self._callback_args)
        return True


class DelayedLauncher(Timer):
    """
    Launches a process after a certain delay.
    Used for launching mousetweaks.
    """
    args = None

    def launch_delayed(self, args, delay):
        self.args = args
        self.start(delay)

    def on_timer(self):
        _logger.debug(_("launching '{}'") \
                        .format(" ".join(self.args)))
        try:
            Popen(self.args)
        except OSError as e:
            _logger.warning(_("Failed to execute '{}', {}") \
                            .format(" ".join(self.args), e))
        return False


class FadeTimer(Timer):
    """
    Sine-interpolated fade between two values, e.g. opacities.
    """

    start_value = None
    target_value = None
    iteration = 0   # just a counter of on_timer calls since start
    time_step = 0.05

    def fade_to(self, start_value, target_value, duration,
                callback = None, *callback_args):
        """
        Start value fade.
        duration: fade time in seconds, 0 for immediate value change
        """
        self.start_value = start_value
        self._start_time = time.time()
        self._duration = duration
        self._callback = callback
        self._callback_args = callback_args

        self.start(self.time_step)

        self.target_value = target_value

    def start(self, delay):
        self.iteration = 0
        Timer.start(self, delay)

    def stop(self):
        self.target_value = None
        Timer.stop(self)

    def on_timer(self):
        elapsed = time.time() - self._start_time
        if self._duration:
            lin_progress = min(1.0, elapsed / self._duration)
        else:
            lin_progress = 1.0
        sin_progress = (sin(lin_progress * pi - pi / 2.0) + 1.0) / 2.0
        self.value = sin_progress * (self.target_value - self.start_value) + \
                  self.start_value

        done = lin_progress >= 1.0
        if self._callback:
            self._callback(self.value, done, *self._callback_args)

        self.iteration += 1
        return not done


class TreeItem(object):
    """
    Abstract base class of tree nodes.
    Base class of nodes in  layout- and color scheme tree.
    """

    # id string of the item
    id = None

    # parent item in the tree
    parent = None

    # child items
    items = ()

    def set_items(self, items):
        self.items = items
        for item in items:
            item.parent = self

    def append_items(self, items):
        if self.items:
            self.items += items
        else:
            self.items = items

        for item in items:
            item.parent = self

    def find_ids(self, ids):
        """ find all items with matching id """
        items = []
        for item in self.iter_items():
            if item.id in ids:
                items.append(item)
        return items

    def iter_items(self):
        """
        Iterates through all items of the tree.
        """
        yield self

        for item in self.items:
            for child in item.iter_depth_first():
                yield child

    def iter_depth_first(self):
        """
        Iterates depth first through the tree.
        """
        for item in self.items:
            for child in item.iter_depth_first():
                yield child

        yield self

    def iter_to_root(self):
        item = self
        while item:
            yield item
            item = item.parent


class Version(object):
    """ Simple class to encapsulate a version number """
    major = 0
    minor = 0

    def __init__(self, major, minor = 0):
        self.major = major
        self.minor = minor

    def __str__(self):
        return self.to_string()

    @staticmethod
    def from_string(version):
        components = version.split(".")

        major = 0
        minor = 0
        try:
            if components >= 1:
                major = int(components[0])
            if components >= 2:
                minor = int(components[1])
        except ValueError:
            pass

        return Version(major, minor)

    def to_string(self):
        return "{major}.{minor}".format(major=self.major, minor=self.minor)

    def __cmp__(self, other):
        if self.major < other.major:
            return -1
        if self.major > other.major:
            return 1
        if self.minor < other.minor:
            return -1
        if self.minor > other.minor:
            return 1
        return 0


class Process:
    """ Process utilities """

    @staticmethod
    def get_cmdline(pid):
        """ Returns the command line for process id pid """
        cmdline = ""
        with open("/proc/%s/cmdline" % pid) as f:
            cmdline = f.read()
        return cmdline

    @staticmethod
    def was_launched_by(process_name):
        """ Checks if this process was launched by <process_name> """
        ppid = os.getppid()
        if ppid:
            cmdline = Process.get_cmdline(ppid)
            return process_name in cmdline
        return False

def unicode_str(obj, encoding = "utf-8"):
    """ 
    Safe str() function that always returns an unicode string.
    Do nothing if the string was already unicode.
    """
    if sys.version_info.major >= 3:  # python 3?
        return str(obj)
    
    if type(obj) == unicode:         # unicode string?
        return obj

    if hasattr(obj, "__unicode__"):  # Exception object?
        return unicode(obj)

    return str(obj).decode("utf-8")  # strings, numbers, ...


