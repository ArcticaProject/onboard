### Logging ###
import logging
_logger = logging.getLogger("OnboardGtk")
###############

import os
import re
import string
import sys
from xml.dom import minidom

from Onboard.Keyboard    import Keyboard
from Onboard.KeyboardGTK import KeyboardGTK
from Onboard.KeyGtk      import LineKey, RectKey
from Onboard.Pane        import Pane
from Onboard.utils       import hexstring_to_float, modifiers, matmult
from Onboard             import KeyCommon

### Config Singleton ###
from Onboard.Config import Config
config = Config()
########################

class KeyboardSVG(config.kbd_render_mixin, Keyboard):
    """
    Keyboard loaded from an SVG file.
    """

    def __init__(self, filename):
        config.kbd_render_mixin.__init__(self)
        Keyboard.__init__(self)
        self.load_layout(filename)
        
    def load_layout(self, kblang):
        kbfolder = os.path.dirname(kblang)

        f = open(kblang)
        langdoc = minidom.parse(f).documentElement
        f.close()
            
        panes = []
        for paneXML in langdoc.getElementsByTagName("pane"):
            path= "%s/%s" % (kbfolder,paneXML.attributes["filename"].value)
            
            f = open(path)
            try:            
                svgdoc = minidom.parse(f).documentElement
                keys = {}

                try:
                    viewPortSizeX = float(svgdoc.attributes['width'].value)
                    viewPortSizeY = float(svgdoc.attributes['height'].value)
                except ValueError:
                    print "Units for canvas height and width must be px.  In the svg file this corresponds with having no units after the height and width"

                #find background of pane
                paneBackground = [0.0,0.0,0.0,0.0]
        
                if paneXML.hasAttribute("backgroundRed"):
                    paneBackground[0] = paneXML.attributes["backgroundRed"].value
                if paneXML.hasAttribute("backgroundGreen"):
                    paneBackground[1] = paneXML.attributes["backgroundGreen"].value
                if paneXML.hasAttribute("backgroundBlue"):
                    paneBackground[2] = paneXML.attributes["backgroundBlue"].value
                if paneXML.hasAttribute("backgroundAlpha"):
                    paneBackground[3] = paneXML.attributes["backgroundAlpha"].value

                #scanning
                columns = []
                
                
                if paneXML.hasAttribute("font"):
                    fontSize = string.atoi(paneXML.attributes["font"].value)
                else:
                    fontSize = DEFAULT_FONTSIZE
                
                self.load_keys_geometry(svgdoc, keys)
                svgdoc.unlink()
                key_groups = self.load_keys(langdoc, keys)
                
                try:
                    
                    for columnXML in paneXML.getElementsByTagName("column"):
                        column = []
                        columns.append(column)
                        for scanKey in columnXML.getElementsByTagName("scankey"):
                            column.append(keys[scanKey.attributes["id"].value])
                except KeyError, (strerror):
                    print "require %s key, appears in scanning only" % (strerror)
                
                pane = Pane(self,paneXML.attributes["id"].value, keys.values(),
                    columns, viewPortSizeX, viewPortSizeY, paneBackground,
                    fontSize)

                panes.append(pane)
            except KeyError, (strerror):
                print _("require %s") % (strerror)
                
            f.close()
        
        langdoc.unlink()
        
        
        basePane = panes[0]
        otherPanes = panes[1:]

        self.set_basePane(basePane)

        for pane in otherPanes:
            self.add_pane(pane)

    def load_keys_geometry(self, svgdoc, keys):
        for rect in svgdoc.getElementsByTagName("rect"): 
            id = rect.attributes["id"].value
            
            styleString = rect.attributes["style"].value
            result = re.search("(fill:#\d?\D?\d?\D?\d?\D?\d?\D?\d?\D?\d?\D?;)", 
                styleString).groups()[0]
    
            rgba = [hexstring_to_float(result[6:8])/255,
            hexstring_to_float(result[8:10])/255,
            hexstring_to_float(result[10:12])/255,
            1]#not bothered for now 

            keys[id] = RectKey(id,
                (float(rect.attributes['x'].value),
                 float(rect.attributes['y'].value)),
                (float(rect.attributes['width'].value),
                 float(rect.attributes['height'].value)),
                rgba)
        
            # TODO fix LineKeys
            """
            for path in svgdoc.getElementsByTagName("path"):
                id = path.attributes["id"].value
                keys[id] = self.parse_path(path, pane)
            """                     

    def load_keys(self, doc, keys):
        for key_xml in doc.getElementsByTagName("key"):  
            name = key_xml.attributes["id"].value
            try:
                if name in keys:
                    key = keys[name]
                    if key_xml.hasAttribute("char"):
                        key.action = key_xml.attributes["char"].value
                        key.action_type = KeyCommon.CHAR_ACTION
                    elif key_xml.hasAttribute("keysym"):
                        value = key_xml.attributes["keysym"].value
                        key.action_type = KeyCommon.KEYSYM_ACTION
                        if value[1] == "x":#Deals for when keysym is hex
                            key.action = string.atoi(value,16)
                        else:
                            key.action = string.atoi(value,10)
                    elif key_xml.hasAttribute("keypress_name"):
                        action = key_xml.attributes["keypress_name"].value
                        action_type = KeyCommon.KEYPRESS_NAME_ACTION
                    elif key_xml.hasAttribute("press"):
                        action = key_xml.attributes["char"].value
                        action_type = KeyCommon.CHAR_ACTION
                    elif key_xml.hasAttribute("modifier"):
                        try:
                            action = modifiers[
                                        key_xml.attributes["modifier"].value]
                            action_type = KeyCommon.MODIFIER_ACTION
                        except KeyError, (strerror):
                            print "Can't find modifier " + str(strerror)
                            
                    elif key_xml.hasAttribute("macro"):
                        action = key_xml.attributes["macro"].value
                        action_type = KeyCommon.MACRO_ACTION
                    elif key_xml.hasAttribute("script"):
                        action = key_xml.attributes["script"].value
                        action_type = KeyCommon.SCRIPT_ACTION
                    elif key_xml.hasAttribute("keycode"):
                        action = string.atoi(
                                            key_xml.attributes["keycode"].value)
                        action_type = KeyCommon.KEYCODE_ACTION

                    labels = ["","","","",""]
                    #if label specified search for modified labels.
                    if key_xml.hasAttribute("label"):
                        labels[0] = key_xml.attributes["label"].value
                        if key_xml.hasAttribute("cap_label"):
                            labels[1] = key_xml.attributes["cap_label"].value
                        if key_xml.hasAttribute("shift_label"):
                            labels[2] = key_xml.attributes["shift_label"].value
                        if key_xml.hasAttribute("altgr_label"):
                            labels[3] = key_xml.attributes["altgr_label"].value
                        if key_xml.hasAttribute("altgrNshift_label"):
                            labels[4] = \
                                key_xml.attributes["altgrNshift_label"].value   
                    #Get labels from keyboard.
                    else:
                        if action_type == KeyCommon.KEYCODE_ACTION:
                            labDic = self.vk.labels_from_keycode(action)
                            labels = (labDic[0],labDic[2],labDic[1],
                                                        labDic[3],labDic[4])
                    key.labels = labels

                    if key_xml.hasAttribute("font_offset_x"):
                        offset_x = \
                            float(key_xml.attributes["font_offset_x"].value)
                    else:
                        offset_y = config.DEFAULT_LABEL_OFFSET[0]
                    
                    if key_xml.hasAttribute("font_offset_y"):
                        offset_x = \
                            float(key_xml.attributes["font_offset_y"].value)
                    else:
                        offset_y = config.DEFAULT_LABEL_OFFSET[1]
                    key.label_offset = (offset_x, offset_y)
                    
                    sticky = key_xml.attributes["sticky"].value.lower()
                    if sticky == "true":
                        key.sticky = True
                    elif sticky == "false":
                        key.sticky = False
                    else:
                        raise KeyElementError(key, 
                            "'sticky' attribute had an invalid value: %s" 
                            % sticky)
                    

    def parse_path(self, path, pane):
        id = path.attributes["id"].value
        styleString = path.attributes["style"].value
        result = re.search("(fill:#\d?\D?\d?\D?\d?\D?\d?\D?\d?\D?\d?\D?;)", styleString).groups()[0]

        rgba = (hexstring_to_float(result[6:8])/255,
        hexstring_to_float(result[8:10])/255,
        hexstring_to_float(result[10:12])/255,
        1)#not bothered for now

        dList = path.attributes["d"].value.split(" ")
        dList = dList[1:-2] #trim unwanted M, Z
        coordList = []

        transformMatrix = None
        if path.hasAttribute("transform"):
            transform = path.attributes["transform"].value
            if transform.startswith("matrix"):
                #Convert strings to floats
                transformCoords = map(float,transform[7:-1].split(","))

                transformMatrix = (
                    (transformCoords[0],transformCoords[2],transformCoords[4]),
                    (transformCoords[1],transformCoords[3],transformCoords[5]),
                    (0, 0, 1))
            elif transform.startswith("translate"):
                transformCoords = map(float,transform[10:-1].split(","))

                transformMatrix = (
                    (1.0,0.0,transformCoords[0]),
                    (0.0,1.0,transformCoords[1]),
                    (0.0,0.0,1.0)
                )
            else:
                print "Warning: Unhandled transform " + transform

        xTotal = 0.0
        yTotal = 0.0
        numCoords = 0
        for d in dList:
            l = d.split(",")
            if len(l) == 1:
                #A letter
                coordList.append(l)
            else:
                #A coord
                numCoords = numCoords +1

                l = map(float,l)

                if transformMatrix:
                    l = matmult(transformMatrix, l+[1])[:-1]

                xTotal = xTotal + l[0]
                yTotal = yTotal + l[1]

                coordList.append(l[0])
                coordList.append(l[1])

        #Point at which we want the label drawn
        fontCoord = (xTotal/numCoords, yTotal/numCoords)

        return LineKey(pane, coordList, fontCoord, rgba)


