# -*- coding: utf-8 -*-
"""
Module for theme related classes.
"""

from __future__ import with_statement

### Logging ###
import logging
_logger = logging.getLogger("Theme")
###############

from gettext import gettext as _
from xml.dom import minidom
import os
import re
import colorsys
from math import log

from Onboard             import Exceptions
from Onboard.utils       import hexstring_to_float, brighten, toprettyxml, \
                                TreeItem

import Onboard.utils as utils

### Config Singleton ###
from Onboard.Config import Config
config = Config()
########################

class Theme:
    """
    Theme controls the visual appearance of Onboards keyboard window.
    """

    format = 1.1

    # core theme members
    # name, type, default
    attributes = [
            ["color_scheme_basename", "s", ""],
            ["key_style", "s", "flat"],
            ["roundrect_radius", "f", 0],
            ["key_size", "f", 100],
            ["key_fill_gradient", "f", 0],
            ["key_stroke_gradient", "f", 0],
            ["key_gradient_direction", "f", 0],
            ["key_label_font", "s", ""],
            ["key_label_overrides", "d", {}]   # dict {name:(key:group)}
            ]

    def __init__(self):
        self.modified = False

        self.filename = ""
        self.is_system = False       # True if this a system theme
        self.system_exists = False   # True if there exists a system
                                     #  theme with the same basename
        self.name = ""

        # create attributes
        for name, _type, default in self.attributes:
            setattr(self, name, default)

    @property
    def basename(self):
        """ Returns the file base name of the theme. """
        return os.path.splitext(os.path.basename(self.filename))[0]

    def __eq__(self, other):
        if not other:
            return False
        for name, _type, _default in self.attributes:
            if getattr(self, name) != getattr(other, name):
                return False
        return True

    def __str__(self):
        return "name=%s, colors=%s, font=%s, radius=%d" % (self.name,
                                                self.color_scheme_basename,
                                                self.key_label_font,
                                                self.roundrect_radius)

    def apply(self, save=True):
        """ Applies the theme to config properties/gsettings. """
        filename = self.get_color_scheme_filename()
        if not filename:
            _logger.error(_("Color scheme for theme '%s' not found")
                            % self.filename)
            return False

        config.theme_settings.set_color_scheme_filename(filename, save)
        for name, _type, _default in self.attributes:
            if name != "color_scheme_basename":
                getattr(config.theme_settings, "set_" + name) \
                                 (getattr(self, name), save)

        return True

    def get_color_scheme_filename(self):
        """ Returns the filename of the themes color scheme."""
        filename = os.path.join(Theme.user_path(),
                                self.color_scheme_basename) + \
                                "." + ColorScheme.extension()
        if not os.path.isfile(filename):
            filename = os.path.join(Theme.system_path(),
                                    self.color_scheme_basename) + \
                                    "." + ColorScheme.extension()
        if not os.path.isfile(filename):
            return None
        return filename

    def set_color_scheme_filename(self, filename):
        """ Set the filename of the color_scheme. """
        self.color_scheme_basename = \
                             os.path.splitext(os.path.basename(filename ))[0]

    def get_superkey_label(self):
        """ Returns the (potentially overridden) label of the super keys. """
        override = self.key_label_overrides.get("LWIN")
        if override:
            return override[0] # assumes RWIN=LWIN
        return None

    def get_superkey_size_group(self):
        """
        Returns the (potentially overridden) size group of the super keys.
        """
        override = self.key_label_overrides.get("LWIN")
        if override:
            return override[1] # assumes RWIN=LWIN
        return None

    def set_superkey_label(self, label, size_group):
        """ Sets or clears the override for left and right super key labels. """
        tuples = self.key_label_overrides
        if label is None:
            if "LWIN" in tuples:
                del tuples["LWIN"]
            if "RWIN" in tuples:
                del tuples["RWIN"]
        else:
            tuples["LWIN"] = (label, size_group)
            tuples["RWIN"] = (label, size_group)
        self.key_label_overrides = tuples

    @staticmethod
    def system_to_user_filename(filename):
        """ Returns the user filename for the given system filename. """
        basename = os.path.splitext(os.path.basename(filename ))[0]
        return os.path.join(Theme.user_path(),
                                basename) + "." + Theme.extension()

    @staticmethod
    def build_user_filename(basename):
        """
        Returns a fully qualified filename pointing into the user directory
        """
        return os.path.join(Theme.user_path(),
                                basename) + "." + Theme.extension()

    @staticmethod
    def build_system_filename(basename):
        """
        Returns a fully qualified filename pointing into the system directory
        """
        return os.path.join(Theme.system_path(),
                                basename) + "." + Theme.extension()

    @staticmethod
    def user_path():
        """ Returns the path of the user directory for themes. """
        return os.path.join(config.user_dir, "themes")

    @staticmethod
    def system_path():
        """ Returns the path of the system directory for themes. """
        return os.path.join(config.install_dir, "themes")

    @staticmethod
    def extension():
        """ Returns the file extension of theme files """
        return "theme"

    @staticmethod
    def load_merged_themes():
        """
        Merge system and user themes.
        User themes take precedence and hide system themes.
        """
        system_themes = Theme.load_themes(True)
        user_themes = Theme.load_themes(False)
        themes = dict((t.basename, (t, None)) for t in system_themes)
        for theme in user_themes:
            # system theme hidden behind user theme?
            if theme.basename in themes:
                # keep the system theme behind the user theme
                themes[theme.basename] = (theme, themes[theme.basename][0])
            else:
                themes[theme.basename] = (theme, None)
        return themes

    @staticmethod
    def load_themes(is_system=False):
        """ Load all themes from either the user or the system directory. """
        themes = []

        if is_system:
            path = Theme.system_path()
        else:
            path = Theme.user_path()

        filenames = Theme.find_themes(path)
        for filename in filenames:
            theme = Theme.load(filename, is_system)
            themes.append(theme)
        return themes

    @staticmethod
    def find_themes(path):
        """
        Returns the full path names of all themes found in the given path.
        """
        files = os.listdir(path)
        themes = []
        for filename in files:
            if filename.endswith(Theme.extension()):
                themes.append(os.path.join(path, filename))
        return themes

    @staticmethod
    def load(filename, is_system=False):
        """ Load a theme and return a new theme object. """

        result = None

        _file = open(filename)
        try:
            domdoc = minidom.parse(_file).documentElement
            try:
                theme = Theme()

                node = domdoc.attributes.get("format")
                format = float(node.value) if node else 1.0

                theme.name = domdoc.attributes["name"].value

                # "color_scheme" is the base file name of the color scheme
                text = utils.xml_get_text(domdoc, "color_scheme")
                if not text is None:
                    theme.color_scheme_basename = text

                # get key label overrides
                nodes = domdoc.getElementsByTagName("key_label_overrides")
                if nodes:
                    overrides = nodes[0]
                    tuples = {}
                    for override in overrides.getElementsByTagName("key"):
                        key_id = override.attributes["id"].value
                        node = override.attributes.get("label")
                        label = node.value if node else ""
                        node = override.attributes.get("group")
                        group = node.value if node else ""
                        tuples[key_id] = (label, group)
                    theme.key_label_overrides = tuples

                # read all other members
                for name, _type, _default in Theme.attributes:
                    if not name in ["color_scheme_basename",
                                    "key_label_overrides"]:
                        value = utils.xml_get_text(domdoc, name)
                        if not value is None:

                            if _type == "i":
                                value = int(value)
                            if _type == "f":
                                value = float(value)

                            # upgrade to current file format
                            if format < 1.1:
                                # direction was    0..360, ccw
                                #        is now -180..180, cw
                                if name == "key_gradient_direction":
                                    value = -(value % 360)
                                    if value <= -180:
                                        value += 360

                            setattr(theme, name, value)

                theme.filename = filename
                theme.is_system = is_system
                theme.system_exists = is_system
                result = theme
            except Exceptions.ThemeFileError, (ex):
                raise Exceptions.ThemeFileError(_("Error loading ")
                    + filename, chained_exception = ex)
            finally:
                domdoc.unlink()

        finally:
            _file.close()

        return result

    def save_as(self, basename, name):
        """ Save this theme under a new name. """
        self.filename = self.build_user_filename(basename)
        self.name = name
        self.save()

    def save(self):
        """ Save this theme. """

        domdoc = minidom.Document()
        try:
            theme_element = domdoc.createElement("theme")
            theme_element.setAttribute("name", self.name)
            theme_element.setAttribute("format", str(self.format))
            domdoc.appendChild(theme_element)

            for name, _type, _default in self.attributes:
                if name == "color_scheme_basename":
                    element = domdoc.createElement("color_scheme")
                    text = domdoc.createTextNode(self.color_scheme_basename)
                    element.appendChild(text)
                    theme_element.appendChild(element)
                elif name == "key_label_overrides":
                    overrides_element = \
                            domdoc.createElement("key_label_overrides")
                    theme_element.appendChild(overrides_element)
                    tuples = self.key_label_overrides
                    for key_id, values in tuples.items():
                        element = domdoc.createElement("key")
                        element.setAttribute("id", key_id)
                        element.setAttribute("label", values[0])
                        element.setAttribute("group", values[1])
                        overrides_element.appendChild(element)
                else:
                    value = getattr(self, name)
                    if _type == "s":
                        pass
                    elif _type == "i":
                        value = str(value)
                    elif _type == "f":
                        value = str(round(value, 2))
                    else:
                        assert(False) # attribute of unknown type

                    element = domdoc.createElement(name)
                    text = domdoc.createTextNode(value)
                    element.appendChild(text)
                    theme_element.appendChild(element)

            pretty_xml = toprettyxml(domdoc)

            with open(self.filename, "w") as _file:
                _file.write(pretty_xml.encode("UTF-8"))

        except Exception, (ex):
            raise Exceptions.ThemeFileError(_("Error saving ")
                + self.filename, chained_exception = ex)
        finally:
            domdoc.unlink()


class ColorScheme(object):
    """
    ColorScheme defines the colors of onboards keyboard.
    Each key or groups of keys may have their own individual colors.
    Any color definition may be omitted. Undefined colors fall back
    to color scheme defaults first, then to hard coded default colors.
    """

    format = 2.0

    name = ""
    filename = ""
    is_system = False
    root = None       # tree root

    def __init__(self):
        pass

    @property
    def basename(self):
        """ Returns the file base name of the color scheme. """
        return os.path.splitext(os.path.basename(self.filename))[0]

    def get_key_rgba(self, key, element, state = None):
        # build a dict of supported key states
        if state is None:
            state = {}
            state["prelight"]    =  key.prelight
            state["pressed"]     =  key.pressed
            state["active"]      =  key.active
            state["locked"]      =  key.locked
            state["scanned"]     =  key.scanned
            state["insensitive"] =  not key.sensitive

        rgb = None
        opacity = None

        # first try the theme_id then fall back to the regular id
        for id in [key.theme_id, key.id]:
            key_group = self.root.find_key_id(id)
            if key_group:
                rgb, opacity = key_group.find_element_color(element, state)
                break

        if not key_group:
            # Special case for layer buttons
            # default color is layer fill color
            if element == "fill" and key.is_layer_button():
                layer_index = key.get_layer_index()
                rgba = self.get_layer_fill_rgba(layer_index)
                rgb, opacity = rgba[:3], rgba[3]
            else:
                # for all other keys use the default key group
                key_group = self.root.get_default_key_group()
                if key_group:
                    rgb, opacity = key_group.find_element_color(element, state)

        if rgb is None:
            rgb = self.get_key_default_rgba(key, element, state)[:3]

        if opacity is None:
            opacity = self.get_key_default_rgba(key, element, state)[3]

        rgba = rgb + [opacity]
        return rgba

    def get_key_default_rgba(self, key, element, state):
        colors = {
                    "fill":                   [0.9,  0.85, 0.7, 1.0],
                    "prelight":               [0.0,  0.0,  0.0, 1.0],
                    "pressed":                [0.6,  0.6,  0.6, 1.0],
                    "active":                 [0.5,  0.5,  0.5, 1.0],
                    "locked":                 [1.0,  0.0,  0.0, 1.0],
                    "scanned":                [0.45, 0.45, 0.7, 1.0],
                    "stroke":                 [0.0,  0.0,  0.0, 1.0],
                    "label":                  [0.0,  0.0,  0.0, 1.0],
                    "dwell-progress":         [0.82, 0.19, 0.25, 1.0],
                    }

        rgba = [0.0, 0.0, 0.0, 1.0]

        if element == "fill":
            if state.get("pressed"):
                new_state = dict(state.items())
                new_state["pressed"] = False
                rgba = self.get_key_rgba(key, element, new_state)

                # Make the default pressed color a slightly darker 
                # or brighter variation of the unpressed color.
                h, l, s = colorsys.rgb_to_hls(*rgba[:3])

                # boost lightness changes for very dark and very bright colors
                # Ad-hoc formula, purly for aesthetics
                amount = -(log((l+.001)*(1-(l-.001))))*0.05 + 0.05

                if l < .5:  # dark color?
                    rgba = brighten(+amount, *rgba) # brigther
                else:
                    rgba = brighten(-amount, *rgba) # darker

            elif state.get("locked"):
                rgba = colors["locked"]
            elif state.get("active"):
                rgba = colors["active"]
            else:
                rgba = colors["fill"]

        elif element == "stroke":
            rgba == colors["stroke"]

        elif element == "label":
            rgba = colors["label"]

            # dim label color for insensitive keys
            if state.get("insensitive"):
                new_state = dict(state.items())
                new_state["insensitive"] = False
                fill = self.get_key_rgba(key, "fill", new_state)
                rgba = self.get_key_rgba(key, "label", new_state)

                h, lf, s = colorsys.rgb_to_hls(*fill[:3])
                h, ll, s = colorsys.rgb_to_hls(*rgba[:3])

                # Leave only one third of the lightness difference
                # between label and fill color.
                amount = (ll - lf) * 2.0 / 3.0
                rgba = brighten(-amount, *rgba)

        elif element == "dwell-progress":
            rgba = colors["dwell-progress"]

        else:
            assert(False)   # unknown element

        return rgba

    def get_layer_fill_rgba(self, layer_index):
        """
        Returns the background fill color of the layer with the given index.
        """

        rgb = None
        opacity = None
        layers = self.root.get_layers()

        if layer_index >= 0 and layer_index < len(layers):
            for item in layers[layer_index].items:
                if item.is_color() and \
                   item.element == "background":
                    rgb = item.rgb
                    opacity = item.opacity
                    break

        if rgb == None:
            rgb = [0.5, 0.5, 0.5]
        if opacity == None:
            opacity = 1.0
        rgba = rgb + [opacity]

        return rgba

    @staticmethod
    def user_path():
        """ Returns the path of the user directory for color schemes. """
        return os.path.join(config.user_dir, "themes/")

    @staticmethod
    def system_path():
        """ Returns the path of the system directory for color schemes. """
        return os.path.join(config.install_dir, "themes")

    @staticmethod
    def extension():
        """ Returns the file extension of color scheme files """
        return "colors"

    @staticmethod
    def get_merged_color_schemes():
        """
        Merge system and user color schemes.
        User color schemes take precedence and hide system color schemes.
        """
        system_color_schemes = ColorScheme.load_color_schemes(True)
        user_color_schemes = ColorScheme.load_color_schemes(False)
        color_schemes = dict((t.basename, t) for t in system_color_schemes)
        for scheme in user_color_schemes:
            color_schemes[scheme.basename] = scheme
        return color_schemes

    @staticmethod
    def load_color_schemes(is_system=False):
        """
        Load all color schemes from either the user or the system directory.
        """
        color_schemes = []

        if is_system:
            path = ColorScheme.system_path()
        else:
            path = ColorScheme.user_path()

        filenames = ColorScheme.find_color_schemes(path)
        for filename in filenames:
            color_scheme = ColorScheme.load(filename, is_system)
            color_schemes.append(color_scheme)
        return color_schemes

    @staticmethod
    def find_color_schemes(path):
        """
        Returns the full path names of all color schemes found in the given path.
        """
        files = os.listdir(path)
        color_schemes = []
        for filename in files:
            if filename.endswith(ColorScheme.extension()):
                color_schemes.append(os.path.join(path, filename))
        return color_schemes

    @staticmethod
    def load(filename, is_system=False):
        """ Load a color scheme and return it as a new object. """

        color_scheme = None

        f = open(filename)
        try:
            dom = minidom.parse(f).documentElement
            name = dom.attributes["name"].value

            # check layout format
            format = 1.0
            if dom.hasAttribute("format"):
               format = float(dom.attributes["format"].value)

            if format >= 2.0:   # tree format?
                items = ColorScheme._parse_dom_node(dom, None, {})
            else:
                _logger.warning(_("Loading legacy color scheme format '{}'. "
                            "Please consider upgrading to current format '{}'"
                            ).format(format, ColorScheme.format))
                items = ColorScheme._parse_legacy_color_scheme(dom)

            if items:
                root = Root()
                root.set_items(items)

                color_scheme = ColorScheme()
                color_scheme.name = name
                color_scheme.filename = filename
                color_scheme.is_system = is_system
                color_scheme.root = root
                #print root.dumps()
        finally:
            f.close()

        return color_scheme

    @staticmethod
    def _parse_dom_node(dom_node, parent_item, used_keys):
        """ Recursive function to parse all dom nodes of the layout tree """
        items = []
        for child in dom_node.childNodes:
            if child.nodeType == minidom.Node.ELEMENT_NODE:
                if child.tagName == u"layer":
                    item = ColorScheme._parse_layer(child)
                elif child.tagName == u"key_group":
                    item = ColorScheme._parse_key_group(child, used_keys)
                elif child.tagName == u"color":
                    item = ColorScheme._parse_color(child)
                else:
                    item = None

                if item:
                    item.parent = parent_item
                    item.items = ColorScheme._parse_dom_node(child, item, used_keys)
                    items.append(item)

        return items

    @staticmethod
    def _parse_dom_node_item(node, item):
        """ Parses common properties of all items """
        if node.hasAttribute("id"):
            item.id = node.attributes["id"].value

    @staticmethod
    def _parse_layer(node):
        item = Layer()
        ColorScheme._parse_dom_node_item(node, item)
        return item

    @staticmethod
    def _parse_key_group(node, used_keys):
        item = KeyGroup()
        ColorScheme._parse_dom_node_item(node, item)

        # read key ids
        text = "".join([n.data for n in node.childNodes \
                        if n.nodeType == n.TEXT_NODE])
        ids = [x for x in re.findall('\w+(?:[.][\w-]+)?', text) if x]

        # check for duplicate key definitions
        for key_id in ids:
            if key_id in used_keys:
                raise ValueError(_("Duplicate key_id '{}' found "
                  "in color scheme file. "
                  "Key_ids must occur only once."
                 .format(key_id)))
        used_keys.update(zip(ids, ids))

        item.key_ids = ids

        return item

    @staticmethod
    def _parse_color(node):
        item = KeyColor()
        ColorScheme._parse_dom_node_item(node, item)

        if node.hasAttribute("element"):
            item.element = node.attributes["element"].value
        if node.hasAttribute("rgb"):
            value = node.attributes["rgb"].value
            item.rgb = [hexstring_to_float(value[1:3])/255,
                        hexstring_to_float(value[3:5])/255,
                        hexstring_to_float(value[5:7])/255]
        if node.hasAttribute("opacity"):
            item.opacity = float(node.attributes["opacity"].value)

        state = {}
        ColorScheme._parse_state_attibute(node, "prelight", state)
        ColorScheme._parse_state_attibute(node, "pressed", state)
        ColorScheme._parse_state_attibute(node, "active", state)
        ColorScheme._parse_state_attibute(node, "locked", state)
        ColorScheme._parse_state_attibute(node, "insensitive", state)
        ColorScheme._parse_state_attibute(node, "scanned", state)
        item.state = state

        return item

    @staticmethod
    def _parse_state_attibute(node, name, state):
        if node.hasAttribute(name):
            value = node.attributes[name].value == "true"
            state[name] = value

            if name == "locked" and value:
                state["active"] = True  # locked implies active


    ###########################################################################
    @staticmethod
    def _parse_legacy_color_scheme(dom_node):
        """ Load a color scheme and return it as a new object. """
        return None

        color_names = {
                    "fill":                   [0.0,  0.0,  0.0, 1.0],
                    "hovered":                [0.0,  0.0,  0.0, 1.0],
                    "pressed":                [0.6,  0.6,  0.6, 1.0],
                    "pressed-latched":        [0.6,  0.6,  0.6, 1.0],
                    "pressed-locked":         [0.6,  0.6,  0.6, 1.0],
                    "latched":                [0.5,  0.5,  0.5, 1.0],
                    "locked":                 [1.0,  0.0,  0.0, 1.0],
                    "scanned":                [0.45, 0.45, 0.7, 1.0],

                    "stroke":                 [0.0,  0.0,  0.0, 1.0],
                    "stroke-hovered":         [0.0,  0.0,  0.0, 1.0],
                    "stroke-pressed":         [0.0,  0.0,  0.0, 1.0],
                    "stroke-pressed-latched": [0.0,  0.0,  0.0, 1.0],
                    "stroke-pressed-locked":  [0.0,  0.0,  0.0, 1.0],
                    "stroke-latched":         [0.0,  0.0,  0.0, 1.0],
                    "stroke-locked":          [0.0,  0.0,  0.0, 1.0],
                    "stroke-scanned":         [0.0,  0.0,  0.0, 1.0],

                    "label":                  [0.0,  0.0,  0.0, 1.0],
                    "label-hovered":          [0.0,  0.0,  0.0, 1.0],
                    "label-pressed":          [0.0,  0.0,  0.0, 1.0],
                    "label-pressed-latched":  [0.0,  0.0,  0.0, 1.0],
                    "label-pressed-locked":   [0.0,  0.0,  0.0, 1.0],
                    "label-latched":          [0.0,  0.0,  0.0, 1.0],
                    "label-locked":           [0.0,  0.0,  0.0, 1.0],
                    "label-scanned":          [0.0,  0.0,  0.0, 1.0],

                    "dwell-progress":         [0.82, 0.19, 0.25, 1.0],
                    }


        def __init__(self):
            self.filename = ""
            self.is_system = False
            self.name = ""

            # all colors are 4 component arrays, rgba
            # convert colors with:
            # ["%x" % int(round(255*x)) for x in [0.82, 0.19, 0.25, 1.0]]
            self.default_layer_fill_color = [0.0, 0.0, 0.0, 1.0]
            self.default_layer_fill_opacity = 1.0
            self.layer_fill_color = {}
            self.layer_fill_opacity = {}

            self.key_default_main_opacity = None
            self.key_main_opacities = {}
            self.key_default_colors = {}    # loaded default color names and colors
            self.key_default_opacities = {}
            self.key_colors = {}
            self.key_opacities = {}

        color_scheme = None

        _file = open(filename)
        try:
            domdoc = minidom.parse(_file).documentElement
            try:
                color_scheme = ColorScheme()
                color_scheme.name = domdoc.attributes["name"].value

                # layer colors
                layers = domdoc.getElementsByTagName("layer")
                if not layers:
                    # Still accept "pane" for backwards compatibility
                    layers = domdoc.getElementsByTagName("pane")
                for i, layer in enumerate(layers):
                    attrib = "fill"
                    if layer.hasAttribute(attrib):
                        value = layer.attributes[attrib].value
                        rgba = [hexstring_to_float(value[1:3])/255,
                        hexstring_to_float(value[3:5])/255,
                        hexstring_to_float(value[5:7])/255,
                        1]
                        color_scheme.layer_fill_color[i] = rgba

                    oattrib = attrib + "-opacity"
                    if layer.hasAttribute(oattrib):
                        opacity = float(layer.attributes[oattrib].value)
                        color_scheme.layer_fill_opacity[i] = opacity

                # key colors
                used_keys = {}
                for group in domdoc.getElementsByTagName("key_group"):

                    # Check for default flag.
                    # Default colors are applied to all keys
                    # not found in the color scheme.
                    default_group = False
                    if group.hasAttribute("default"):
                        default_group = bool(group.attributes["default"].value)

                    # read key ids
                    text = "".join([n.data for n in group.childNodes])
                    ids = [x for x in re.findall('\w+(?:[.][\w-]+)?', text) if x]

                    # check for duplicate key definitions
                    for key_id in ids:
                        if key_id in used_keys:
                            raise ValueError(_("Duplicate key_id '{}' found "
                              "in color scheme file. "
                              "Key_ids must occur only once."
                             .format(key_id)))
                    used_keys.update(zip(ids, ids))

                    key_default_colors    = color_scheme.key_default_colors
                    key_default_opacities = color_scheme.key_default_opacities
                    key_colors            = color_scheme.key_colors
                    key_opacities         = color_scheme.key_opacities

                    for attrib in ColorScheme.color_names.keys():

                        # read color attribute
                        if group.hasAttribute(attrib):
                            value = group.attributes[attrib].value
                            rgb = [hexstring_to_float(value[1:3])/255,
                                   hexstring_to_float(value[3:5])/255,
                                   hexstring_to_float(value[5:7])/255]

                            if default_group:
                                key_default_colors[attrib] = rgb

                            for key_id in ids:
                                colors = key_colors.get(key_id, {})
                                colors[attrib] = rgb
                                key_colors[key_id] = colors

                        # read opacity attribute
                        oattrib = attrib + "-opacity"
                        if group.hasAttribute(oattrib):
                            opacity = float(group.attributes[oattrib].value)
                            if default_group:
                                key_default_opacities[attrib] = opacity

                            for key_id in ids:
                                opacities = key_opacities.get(key_id, {})
                                opacities[attrib] = opacity
                                key_opacities[key_id] = opacities

                    # read main opacity setting
                    # applies to all colors that don't have their own opacity set
                    if group.hasAttribute("opacity"):
                        value = float(group.attributes["opacity"].value)
                        if default_group:
                            color_scheme.key_default_main_opacity = value
                        for key_id in ids:
                            color_scheme.key_main_opacities[key_id] = value

                color_scheme.filename = filename
                color_scheme.is_system = is_system

            except Exception, (ex):
                raise Exceptions.ColorSchemeFileError(_("Error loading ")
                    + filename, chained_exception = ex)
            finally:
                domdoc.unlink()
        finally:
            _file.close()

        return color_scheme


class ColorSchemeItem(TreeItem):
    """ Base class of color scheme items """

    def dumps(self):
        """
        Recursively dumps the (sub-) tree starting from self.
        Returns a multi-line string.
        """
        global _level
        if not "_level" in globals():
            _level = -1
        _level += 1
        s = "   "*_level + repr(self) + "\n" + \
               "".join(item.dumps() for item in self.items)
        _level -= 1
        return s

    def is_layer(self):
        return False
    def is_key_group(self):
        return False
    def is_color(self):
        return False

    def find_key_id(self, key_id):
        """ Find the key group that has key_id """
        if self.is_key_group():
           if key_id in self.key_ids:
               return self

        for child in self.items:
            item = child.find_key_id(key_id)
            if item:
                return item

        return None


class Root(ColorSchemeItem):
    """ Container for a layers colors """

    def get_layers(self):
        """ list of layers in order of appearance in the color scheme file """
        layers = []
        for item in self.items:
            if item.is_layer():
                layers.append(item)
        return layers

    def get_default_key_group(self):
        """ Default key group for keys that aren't part of any key group """
        for child in self.items:
            if child.is_key_group():
                return child
        return None


class Layer(ColorSchemeItem):
    """ Container for a layers colors """

    def is_layer(self):
        return True


class Color(ColorSchemeItem):
    """ A single color, rgb + opacity """
    element = None
    rgb = None
    opacity = None

    def __repr__(self):
        return "{} element={} rgb={} opacity={}".format( \
                                    ColorSchemeItem.__repr__(self),
                                    repr(self.element),
                                    repr(self.rgb),
                                    repr(self.opacity))
    def is_color(self):
        return True

    def matches(self, element, *args):
        """
        Returns true if self matches the given parameters.
        """
        return self.element == element

class KeyColor(Color):
    """ A single key color"""
    state = None   # dict whith "pressed"=True, "active"=False, etc.

    def __repr__(self):
        return "{} element={} rgb={} opacity={} state={}".format( \
                                    ColorSchemeItem.__repr__(self),
                                    repr(self.element),
                                    repr(self.rgb),
                                    repr(self.opacity),
                                    repr(self.state))
    def matches(self, element, state):
        """
        Returns true if self matches the given parameters.
        state attributes match if they are equal or None, i.e. an
        empty state dict always matches.
        """
        if not self.element == element:
            return False

        for attr, value in state.items():
            # Special case for fill color
            # By default the fill color is only applied to the single
            # state where nothing is pressed, active, locked, etc.
            # All other elements apply to all state permutations if
            # not asked to do otherwise.
            # Allows for hard coded default fill colors to take over without
            # doing anything special in the color scheme files.
            default = value  # "don't care", always match unspecified states

            if element == "fill" and \
               attr in ["active", "locked", "pressed"] and \
               not attr in self.state:
                default = False   # consider unspecified states to be False

            if element == "label" and \
               attr in ["insensitive"] and \
               not attr in self.state:
                default = False   # consider unspecified states to be False

            if  self.state.get(attr, default) != value:
                return False

        return True


class KeyGroup(ColorSchemeItem):
    """ A group of key ids and their colors """
    key_ids = ()

    def __repr__(self):
        return "{} key_ids={}".format(ColorSchemeItem.__repr__(self),
                                    repr(self.key_ids))

    def is_key_group(self):
        return True

    def find_element_color(self, element, state):
        rgb = None
        opacity = None

        # walk key groups from self down to the root
        for key_group in self.iter_to_root():
            if key_group.is_key_group():

                # run through all colors of the key group, top to bottom
                for child in key_group.items:
                    if child.is_color():
                        for color in child.iter_depth_first():

                            # matching color found?
                            if color.matches(element, state):
                                if rgb is None:
                                    rgb = color.rgb
                                if opacity is None:
                                    opacity = color.opacity
                                if not rgb is None and not opacity is None:
                                    return rgb, opacity # break early

        return rgb, opacity

