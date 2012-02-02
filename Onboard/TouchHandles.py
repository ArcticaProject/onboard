# -*- coding: utf-8 -*-
""" Enlarged drag handles for resizing or moving """

from __future__ import division, print_function, unicode_literals

from math import pi, sqrt, sin, log
import cairo

from Onboard.utils    import Rect, Handle

class TouchHandle(object):
    """ Enlarged drag handle for resizing or moving """

    id = None
    prelight = False
    pressed = False
    corner_radius = 0     # radius of the outer corners (window edges)

    _size = (40, 40)
    _rect = None
    _scale = 1.0   # scale of handle relative to resize handles
    _shadow_size = 4
    _shadow_offset = (0.0, 3.0)

    _handle_angles = {}  # dictionary at class scope!

    def __init__(self, id):
        self.id = id

        # initialize angles
        if not self._handle_angles:
            for i, h in enumerate(Handle.EDGES):
                self._handle_angles[h] = i * pi / 2.0
            for i, h in enumerate(Handle.CORNERS):
                self._handle_angles[h] = i * pi / 2.0 + pi /  4.0
            self._handle_angles[Handle.MOVE] = 0.0

    def get_rect(self):
        rect = self._rect
        if not rect is None and \
           self.pressed:
            rect = rect.offset(1.0, 1.0)
        return rect

    def get_radius(self):
        w, h = self.get_rect().get_size()
        return min(w, h) / 2.0

    def get_shadow_rect(self):
        rect = self.get_rect().inflate(self._shadow_size+1)
        rect.w += self._shadow_offset[0]
        rect.h += self._shadow_offset[1]
        return rect

    def get_arrow_angle(self):
        return self._handle_angles[self.id]

    def is_edge_handle(self):
        return self.id in Handle.EDGES

    def is_corner_handle(self):
        return self.id in Handle.CORNERS

    def update_position(self, canvas_rect):
        w, h = self._size
        w = min(w, canvas_rect.w / 3.0)
        w = min(w, canvas_rect.h / 3.0)
        h = w
        self._scale = 1.0

        xc, yc = canvas_rect.get_center()
        if self.id is Handle.MOVE:  # move handle?
            d = min(canvas_rect.w - 2.0 * w, canvas_rect.h - 2.0 * h)
            self._scale = 1.4
            w = min(w * self._scale, d)
            h = min(h * self._scale, d)

        if self.id in [Handle.WEST,
                           Handle.NORTH_WEST,
                           Handle.SOUTH_WEST]:
            x = canvas_rect.left()
        if self.id in [Handle.NORTH,
                           Handle.NORTH_WEST,
                           Handle.NORTH_EAST]:
            y = canvas_rect.top()
        if self.id in [Handle.EAST,
                           Handle.NORTH_EAST,
                           Handle.SOUTH_EAST]:
            x = canvas_rect.right() - w
        if self.id in [Handle.SOUTH,
                           Handle.SOUTH_WEST,
                           Handle.SOUTH_EAST]:
            y = canvas_rect.bottom() - h

        if self.id in [Handle.MOVE, Handle.EAST, Handle.WEST]:
            y = yc - h / 2.0
        if self.id in [Handle.MOVE, Handle.NORTH, Handle.SOUTH]:
            x = xc - w / 2.0

        self._rect = Rect(x, y, w, h)

    def hit_test(self, point):
        rect = self.get_rect()
        if rect and rect.is_point_within(point):
            _win = self._window.get_window()
            if _win:
                context = _win.cairo_create()
                self.build_handle_path(context)
                return context.in_fill(*point)
        return False

        radius = self.get_radius()
        xc, yc = rect.get_center()
        dx = xc - point[0]
        dy = yc - point[1]
        d = sqrt(dx*dx + dy*dy)
        return d <= radius

    def draw(self, context):
        if self.pressed:
            alpha_factor = 1.5
        else:
            alpha_factor = 1.0

        context.new_path()

        self.draw_handle_shadow(context, alpha_factor)
        self.draw_handle(context, alpha_factor)
        self.draw_arrows(context)

    def draw_handle(self, context, alpha_factor):
        radius = self.get_radius()
        line_width = radius / 15.0

        alpha = 0.4  * alpha_factor
        if self.pressed:
            context.set_source_rgba(0.78, 0.33, 0.17, alpha)
        elif self.prelight:
            context.set_source_rgba(0.98, 0.53, 0.37, alpha)
        else:
            context.set_source_rgba(0.78, 0.33, 0.17, alpha)

        self.build_handle_path(context)
        context.fill_preserve()
        context.set_line_width(line_width)
        context.stroke()

    def draw_handle_shadow(self, context, alpha_factor):
        rect = self.get_rect()
        radius = self.get_radius()
        xc, yc = rect.get_center()
        alpha = 0.15 * alpha_factor

        context.save()

        # There is a massive performance boost for groups when clipping is used.
        # Integer limits are again dramatically faster (x4) then using floats.
        # for 1000x draw_drop_shadow:
        #     with clipping: ~300ms, without: ~11000ms
        context.rectangle(*self.get_shadow_rect().int())
        context.clip()

        context.push_group()

        # draw the shadow
        context.push_group_with_content(cairo.CONTENT_ALPHA)
        self.build_handle_path(context)
        context.set_source_rgba(0.0, 0.0, alpha)
        context.fill()
        group = context.pop_group()
        self.draw_drop_shadow(context, group,
                              (xc, yc), radius,
                              self._shadow_size,
                              self._shadow_offset)

        # cut out the handle area, because the handle is transparent
        context.save()
        context.set_operator(cairo.OPERATOR_CLEAR)
        context.set_source_rgba(0.0, 0.0, 0.0, 1.0)
        self.build_handle_path(context)
        context.fill()
        context.restore()

        context.pop_group_to_source()
        context.paint()

        context.restore()

    def draw_drop_shadow(self, cr, pattern, origin, radius, shadow_size, offset):
        n = shadow_size
        for i in range(n):
            #k = i
            #k = -log(max(i, 0.1)) / log(10) * n / 2.0 + n / 2.0
            k = (1.0-sin(i*pi/2.0/n)) * n
            _scale = (radius + k) / radius
            cr.save()
            cr.translate(*origin)
            cr.scale(_scale, _scale)
            cr.translate(-origin[0], -origin[1])
            cr.translate(*offset)
            cr.set_source_rgba(0.0, 0.0, 0.0, 0.04)
            cr.mask(pattern)
            cr.restore()

    def draw_arrows(self, context):
        radius = self.get_radius()
        xc, yc = self.get_rect().get_center()
        scale = radius / 2.0 / self._scale * 1.2
        num_arrows = 4 if self.id == Handle.MOVE else 2
        angle = self.get_arrow_angle()
        angle_step = 2.0 * pi / num_arrows

        context.save()

        for i in range(num_arrows):
            m = cairo.Matrix()
            m.translate(xc, yc)
            m.rotate(angle + i * angle_step)
            m.scale(scale, scale)

            # arrow distance from center
            if self.id is Handle.MOVE:
                m.translate(0.9, 0)
            else:
                m.translate(0.30, 0)

            context.set_matrix(m)
            self.draw_arrow(context)

        context.restore()

    def draw_arrow(self, context):
        context.move_to( 0.0, -0.5)
        context.line_to( 0.5,  0.0)
        context.line_to( 0.0,  0.5)
        context.close_path()

        context.set_source_rgba(1.0, 1.0, 1.0, 0.8)
        context.fill_preserve()

        context.set_source_rgba(0.0, 0.0, 0.0, 0.8)
        context.set_line_width(0)
        context.stroke()

    def build_handle_path(self, context):
        rect = self.get_rect()
        xc, yc = rect.get_center()
        radius = self.get_radius()
        corner_radius = self.corner_radius

        angle = self.get_arrow_angle()
        m = cairo.Matrix()
        m.translate(xc, yc)
        m.rotate(angle)

        if self.is_edge_handle():
            p0 = m.transform_point(radius, -radius)
            p1 = m.transform_point(radius, radius)
            context.arc(xc, yc, radius, angle + pi / 2.0, angle + pi / 2.0 + pi)
            context.line_to(*p0)
            context.line_to(*p1)
            context.close_path()
        elif self.is_corner_handle():
            m.rotate(-pi / 4.0)  # rotate to SOUTH_EAST

            context.arc(xc, yc, radius, angle + 3 * pi / 4.0,
                                        angle + 5 * pi / 4.0)
            pt = m.transform_point(radius, -radius)
            context.line_to(*pt)

            if corner_radius:
                # outer corner, following the rounded window corner
                pt  = m.transform_point(radius,  radius - corner_radius)
                ptc = m.transform_point(radius - corner_radius,
                                        radius - corner_radius)
                context.line_to(*pt)
                context.arc(ptc[0], ptc[1], corner_radius,
                            angle - pi / 4.0,  angle + pi / 4.0)
            else:
                pt = m.transform_point(radius,  radius)
                context.line_to(*pt)

            pt = m.transform_point(-radius,  radius)
            context.line_to(*pt)
            context.close_path()
        else:
            context.arc(xc, yc, radius, 0, 2.0 * pi)

    def redraw(self, window):
        self._window = window
        rect = self.get_shadow_rect()
        if rect:
            window.queue_draw_area(*rect)


class TouchHandles(object):
    """ Full set of resize and move handles """
    active = False
    opacity = 1.0
    rect = None

    def __init__(self):
        handles = []
        handles.append(TouchHandle(Handle.MOVE))
        handles.append(TouchHandle(Handle.NORTH_WEST))
        handles.append(TouchHandle(Handle.NORTH))
        handles.append(TouchHandle(Handle.NORTH_EAST))
        handles.append(TouchHandle(Handle.EAST))
        handles.append(TouchHandle(Handle.SOUTH_EAST))
        handles.append(TouchHandle(Handle.SOUTH))
        handles.append(TouchHandle(Handle.SOUTH_WEST))
        handles.append(TouchHandle(Handle.WEST))
        self.handles = handles

    def update_positions(self, canvas_rect):
        self.rect = canvas_rect
        for handle in self.handles:
            handle.update_position(canvas_rect)

    def draw(self, context):
        context.push_group()

        for handle in self.handles:
            handle.draw(context)

        context.pop_group_to_source()
        context.paint_with_alpha(self.opacity);

    def redraw(self, window):
        if self.rect:
            for handle in self.handles:
                handle.redraw(window)

    def hit_test(self, point):
        if self.active:
            for handle in self.handles:
                if handle.hit_test(point):
                    return handle.id

    def set_prelight(self, handle_id, window = None):
        for handle in self.handles:
            prelight = handle.id == handle_id and not handle.pressed
            if handle.prelight != prelight:
                handle.prelight = prelight
                if window:
                    window.queue_draw_area(*handle.get_rect())

    def set_pressed(self, handle_id, window = None):
        for handle in self.handles:
            pressed = handle.id == handle_id
            if handle.pressed != pressed:
                handle.pressed = pressed
                handle.redraw(window)

    def set_corner_radius(self, corner_radius):
        for handle in self.handles:
            handle.corner_radius = corner_radius

