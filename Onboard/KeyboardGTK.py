import gtk
import gobject

### Config Singleton ###
from Onboard.Config import Config
config = Config()
########################

class KeyboardGTK(gtk.DrawingArea):
    def __init__(self):
        gtk.DrawingArea.__init__(self)
        self.add_events(gtk.gdk.BUTTON_PRESS_MASK 
                      | gtk.gdk.BUTTON_RELEASE_MASK 
                      | gtk.gdk.LEAVE_NOTIFY_MASK)

        self.connect("expose_event",         self.expose)
        self.connect("button_press_event",   self.mouse_button_press)
        self.connect("button_release_event", self.mouse_button_release)
        self.connect("leave-notify-event",   self.cb_leave_notify)

    def cb_leave_notify(self, widget, grabbed):
        """ 
        horrible.  Grabs pointer when key is pressed, released when cursor 
        leaves keyboard
        """

        gtk.gdk.pointer_ungrab() 
        if self.active:
                    
            if self.scanningActive:
                self.active = None      
                self.scanningActive = None
            else:       
                self.release_key(self.active)
            self.queue_draw()
        return True

    def mouse_button_release(self,widget,event):
        if self.active:
            #self.active.on = False
            self.release_key(self.active)
            if len(self.stuck) > 0:
                for stick in self.stuck:
                    self.release_key(stick)
                self.stuck = []
            self.active = None

        self.queue_draw()
        return True

    def mouse_button_press(self,widget,event):
        gtk.gdk.pointer_grab(self.window, True)
        if event.type == gtk.gdk.BUTTON_PRESS:
            self.active = None#is this doing anything
            
            if config.scanning and self.basePane.columns:
                
                if self.scanningTimeId:
                    if not self.scanningNoY == None:
                        self.press_key(self.scanningActive)
                        gobject.source_remove(self.scanningTimeId)
                        self.reset_scan()
                    else:
                        self.scanningNoY = -1
                        gobject.source_remove(self.scanningTimeId)
                        self.scanningTimeId = gobject.timeout_add(
                                config.scanning_interval, self.scan_tick)
                else:   
                    self.scanningTimeId = gobject.timeout_add(
                        config.scanning_interval, self.scan_tick)
                    self.scanningNoX = -1
            else:
                if self.activePane:
                    for key in self.activePane.keys.values():
                        self.is_key_pressed(key, widget, event)
                else:   
                    for key in self.basePane.keys.values():
                        self.is_key_pressed(key, widget, event)

                for key in self.tabKeys:
                    self.is_key_pressed(key, widget, event)
        return True 

    def expose(self, widget, event):
        context = widget.window.cairo_create()
        context.set_line_width(1.1)

        size = self.get_allocation()

        self.kbwidth = size.width - config.SIDEBARWIDTH # to allow for sidebar
        self.height = size.height

        context.set_source_rgba(float(self.basePane.rgba[0]),
                    float(self.basePane.rgba[1]),
                    float(self.basePane.rgba[2]),
                    float(self.basePane.rgba[3]))#get from .sok
        context.paint()


        self.basePane.paint(context,self.kbwidth,self.height)

        if (self.activePane):

            context.rectangle(0, 0, self.kbwidth, self.height)
            context.set_source_rgba(float(self.activePane.rgba[0]),
                        float(self.activePane.rgba[1]),
                        float(self.activePane.rgba[2]),
                        float(self.activePane.rgba[3]))#get from .sok
            context.fill()
            self.activePane.paint(context,self.kbwidth,self.height)

        for key in self.tabKeys:
            key.paint(context)

        return True
