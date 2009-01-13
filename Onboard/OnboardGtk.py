# -*- coding: UTF-8 -*-

### Logging ###
import logging
logging.basicConfig()
logger = logging.getLogger("OnboardGtk")
#logger.setLevel(logging.DEBUG)
###############

import sys
import gobject
gobject.threads_init()

import gtk
import virtkey
import gconf
import gettext
import os.path

from gettext import gettext as _

from Onboard.Keyboard import Keyboard
from KeyGtk import *
from Onboard.Pane import Pane
from Onboard.KbdWindow import KbdWindow
from Onboard.utils import get_install_dir
from Onboard.KeyboardSVG import KeyboardSVG


### Config Singleton ###
from Onboard.Config import Config
config = Config()
########################

import KeyCommon

# can't we just import Onboard.utils and then use Onboard.utils.run_script ?
from Onboard.utils import run_script

import Onboard.utils as utils


#setup gettext
app="onboard"
gettext.textdomain(app)
gettext.bindtextdomain(app)

DEFAULT_FONTSIZE = 10

class OnboardGtk(object):
    """
    This class is a mishmash of things that I didn't have time to refactor in to seperate classes.
    It needs a lot of work.
    The name comes from onboards original working name of simple onscreen keyboard.
    """

    def __init__(self, main=True):
        sys.path.append(os.path.join(get_install_dir(), 'scripts'))

        # this object is the source of all layout info and where we send key presses to be emulated.
        logger.info("Initialising virtkey")
        self.vk = virtkey.virtkey()

        logger.info("Getting user settings")
        self.gconfClient = gconf.client_get_default()

        self.load_layout(config.layout_filename)
        self.macros = self.gconfClient.get_list("/apps/onboard/snippets",gconf.VALUE_STRING)

        self.window = KbdWindow(self)
        self.window.set_keyboard(self.keyboard)

        logger.info("Creating trayicon")
        #Create menu for trayicon
        uiManager = gtk.UIManager()

        actionGroup = gtk.ActionGroup('UIManagerExample')
        actionGroup.add_actions([('Quit', gtk.STOCK_QUIT, _('_Quit'), None,
                                  _('Quit onBoard'), self.quit),
                                 ('Settings', gtk.STOCK_PREFERENCES, _('_Settings'), None, _('Show settings'), self.cb_settings_item_clicked)])

        uiManager.insert_action_group(actionGroup, 0)

        uiManager.add_ui_from_string("""<ui>
                        <popup>
                            <menuitem action="Settings"/>
                            <menuitem action="Quit"/>
                        </popup>
                    </ui>""")
        trayMenu = uiManager.get_widget("/ui/popup")

        # Create the trayicon
        self.statusIcon = gtk.status_icon_new_from_file(
                os.path.join(get_install_dir(), "data", "onboard.svg"))
        self.statusIcon.connect("activate", self.cb_status_icon_clicked)
        self.statusIcon.connect("popup-menu", self.cb_status_icon_menu,
                trayMenu)

        logger.info("Showing window")
        self.window.do_show()

        if self.gconfClient.get_bool("/apps/onboard/start_minimized"):
            self.window.do_hide()

        self.gconfClient.notify_add("/apps/onboard/layout_filename",self.do_set_layout)
        self.gconfClient.notify_add("/apps/onboard/snippets",self.do_change_macros)
        self.gconfClient.notify_add("/apps/onboard/use_trayicon", self.do_set_trayicon)


        if self.gconfClient.get_bool("/apps/onboard/use_trayicon"):
            self.hide_status_icon()
            self.show_status_icon()
        else:
            self.hide_status_icon()

        if main:
            logger.info("Entering mainloop")
            gtk.main()
            self.clean()

    def cb_settings_item_clicked(self,widget):
        """
        Callback called when setting button clicked in the trayicon menu.
        """
        run_script("sokSettings",self)

    def cb_status_icon_menu(self,status_icon, button, activate_time,trayMenu):
        """
        Callback called when trayicon right clicked.  Produces menu.
        """
        trayMenu.popup(None, None, gtk.status_icon_position_menu,
             button, activate_time, status_icon)

    def do_set_trayicon(self, cxion_id=None, entry=None, user_data=None,thing=None):
        """
        Callback called when gconf detects that the gconf key specifying
        whether the trayicon should be shown or not is changed.
        """
        if self.gconfClient.get_bool("/apps/onboard/use_trayicon"):
            self.show_status_icon()
        else:
            self.hide_status_icon()

    def show_status_icon(self):
        """
        Shows the status icon.  When it is shown we set a wm hint so that
        onboard does not appear in the taskbar.
        """
        self.statusIcon.set_visible(True)
        self.window.set_property('skip-taskbar-hint', True)

    def hide_status_icon(self):
        """
        The opposite of the above.
        """
        self.statusIcon.set_visible(False)
        self.window.set_property('skip-taskbar-hint', False)

    def cb_status_icon_clicked(self,widget):
        """
        Callback called when trayicon clicked.
        Toggles whether onboard window visibile or not.

        TODO would be nice if appeared to iconify to taskbar
        """
        if self.window.hidden: self.window.do_show()
        else: self.window.do_hide()

    def unstick(self):
        for key in self.keyboard.basePane.keys.values():
            if key.on :
                self.keyboard.release_key(key)


    def clean(self): #Called when sok is gotten rid off.
        self.unstick()
        self.window.hide()

    def quit(self, widget=None):
        self.clean()
        gtk.main_quit()

    def do_change_macros(self,client, cxion_id,entry,user_data):
        self.macros = self.gconfClient.get_list("/apps/onboard/snippets",gconf.VALUE_STRING)

    def do_set_layout(self,client, cxion_id, entry, user_data):
        self.unstick()
        filename = self.gconfClient.get_string("/apps/onboard/layout_filename")
        if os.path.exists(filename):
            self.load_layout(filename)
            self.window.set_keyboard(self.keyboard)
        else:
            self.load_default_layout()

        self.window.set_keyboard(self.keyboard)

    def load_layout(self, filename):
        self.keyboard = KeyboardSVG(self, filename)



