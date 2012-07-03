import sys, os
from PyQt4.QtCore import *
from PyQt4.QtGui import *

import matplotlib
from matplotlib.backends.backend_qt4agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt4agg import NavigationToolbar2QTAgg as NavigationToolbar
from matplotlib.figure import Figure
import numpy as np

import threading
import collections
import time
import serial
import struct
# Temporary for using Afproto from git repo.
sys.path.append("/home/clu/devel/Afproto/python")
import afproto


# Use the following command for virtual serial ports. (easy testing!).
# socat -d -d pty,raw,echo=0 pty,raw,echo=0


# Old class for plotting WFF analog data files...
# class SliceAnalogDataWad(object):
#     def __init__(self, file_name):
#         self.data_wad = None
#         self.fig = None
#         self.file_name = file_name
#         self.read_data()
            
#     def get_num_cols(self):
#         """ Returns number of columns (int) """
#         pass

#     def draw(self):
#         """Redraw the matplotlib plot"""
#         pass

#     def read_data(self):
#         """Read in slice data"""
#         # This will create a numpy matrix with column names
#         try:
#             self.data_wad = np.genfromtxt(self.file_name, delimiter = ',', names = True)
#         except:
#             raise Exception("Failed to read data file: %s" % self.file_name)

#         self.names = self.data_wad.dtype.names


class SerialReaderThread(threading.Thread):
    def __init__(self, data, ser):
        threading.Thread.__init__(self)
        self._data = data
        self._ser = ser
        self._stop_flag = threading.Event()
        self._kill_flag = threading.Event()
        self._buffer = b''

    def exit(self):
        self._kill_flag.set()
        
    def deactivate(self):
        self._stop_flag.clear()
        # Clear our local buffer...
        self._buffer = b''
        
    def activate(self):
        # Blow away stale data in serial buffer.
        self._ser.flushInput()
        self._start_time = time.time()
        self._stop_flag.set()
        
    def run(self):
        # This is where the fish lives.
        while (True):
            # Quit when user does.
            if self._kill_flag.is_set():
                print("HE'S DEAD JIM!")
                break
            
            if (not self._stop_flag.wait(1.0)):
                continue
            
            num_bytes = self._ser.inWaiting()
            if (num_bytes > 0):
                self._buffer += self._ser.read(num_bytes)
            else:
                continue
            
            if ((num_bytes + len(self._buffer)) >= 5):
                packet, self._buffer = afproto.extract_payload(self._buffer)
            else:
                continue
            
            if packet:
                payload = struct.unpack('H', packet)
            else:
                continue
                
            while (True):
                #if not self._data.put([payload[0]], [time.time() - start]):
                if not self._data.put([time.time() - self._start_time], [payload[0]]):
                    print("stuck in loop")
                    time.sleep(0.0001)
                else:
                    break
                    
            


class SliceAnalogData(object):
    """Serial packet queue for plotting"""
    def __init__(self, fifo_size):
        self._lock = threading.Lock()
        self._fifo_size = fifo_size
        # Most certainly private! Don't touch!
        self._fifo = collections.deque(self._fifo_size*[0], self._fifo_size)
        self._t_fifo = collections.deque(self._fifo_size*[0], self._fifo_size)

    def get(self):
        # Grab a data chunk from this "queue"
        self._lock.acquire(True)
        copy = self._fifo
        t_copy = self._t_fifo
        self._lock.release()
        return(t_copy, copy)

    def put(self, t_data, data):
        # Put a chunk of data in this "queue"
        if (self._lock.acquire(False)):
            #put data
            self._fifo.extend(data)
            self._t_fifo.extend(t_data)
            self._lock.release()
            return(True)
        else:
            # lock is held by plotter
            return(False)

    def clear(self):
        """Clear all data in the FIFOs"""
        self._lock.acquire(True)
        self._fifo.extend(self._fifo.maxlen*[0])
        self._t_fifo.extend(self._fifo.maxlen*[0])
        self._lock.release()


class SliceAnalogPlotter(QMainWindow):
    """The great and wise plotter"""
    def __init__(self, ser_thread, data, parent = None):
        QMainWindow.__init__(self, parent)
        self.setWindowTitle('SLICE Analog Plotter')

        self._data_thread = ser_thread
        self._plot_buffer = data
        
        self.create_menu()
        self.create_main_frame()

        self._timer = self.fig.canvas.new_timer(interval = 23)
        self._timer.interval = 23
        self._timer.add_callback(self.plot_data)
        self._data_thread.start()

    def closeEvent(self, event):
        # Kill thread!
        self._data_thread.exit()
        self._data_thread.join()
        print("DEATH!")
        
    def on_draw(self):
        for i in range(len(self.chk_boxes)):
            self.chk_box_status[i] = self.chk_boxes[i].isChecked()

        names = np.array(self.data.names)

    def plot_data(self):
        x, y = self._plot_buffer.get()
        self.plt[0].set_data(x, y)
        #self.ax.figure.canvas.draw()
        self.ax.axis([min(x), max(x), 270, 310])
        self.canvas.draw()
        
    def button_handler(self, checked):
        """Handle Start/Pause plotting button"""
        if checked:
            self.start_button.setText("&Stop")
            self.start_plotting()
        else:
            self.start_button.setText("&Start")
            self.stop_plotting()
        
    def start_plotting(self):
        print("START PLOTTING!")
        self._timer.start()
        self._data_thread.activate()

    def stop_plotting(self):
        print("STOP PLOTTING")
        self._timer.stop()
        self._data_thread.deactivate()
        self._plot_buffer.clear()
        
    def create_main_frame(self):
        self.main_frame = QWidget()

        self.fig = Figure()
        self.fig.subplots_adjust(hspace = 0, wspace = 0)
        self.ax = self.fig.add_subplot(1, 1, 1)
        x, y = self._plot_buffer.get()
        self.plt = self.ax.plot(x, y)
        self.canvas = FigureCanvas(self.fig)
        self.canvas.setParent(self.main_frame)
        
        self.mpl_toolbar = NavigationToolbar(self.canvas, self.main_frame)
        
        size = QSizePolicy()
        #size.setVerticalPolicy(QSizePolicy.Minimum)
        size.setHorizontalPolicy(QSizePolicy.Minimum)
        
        button_bar = QGroupBox()
        button_bar.setLayoutDirection(Qt.LeftToRight)
        button_bar.setSizePolicy(size)
        button_bar_hbox = QHBoxLayout()
        
        self.start_button = QToolButton()
        self.start_button.setCheckable(True)
        self.start_button.setText("&Start")
        self.start_button.connect(self.start_button, SIGNAL("toggled(bool)"), self.button_handler)

        button_bar_hbox.addWidget(self.start_button, 0, Qt.AlignLeft)
        button_bar.setLayout(button_bar_hbox)
        
        # The Box that holds matplotlib stuff
        mpvbox = QVBoxLayout()
        mpvbox.addWidget(button_bar)
        mpvbox.addWidget(self.canvas)
        mpvbox.addWidget(self.mpl_toolbar)

        main_box = QHBoxLayout()
        main_box.addLayout(mpvbox)
        
        self.main_frame.setLayout(main_box)
        self.setCentralWidget(self.main_frame)
        
    def create_menu(self):        
        self.file_menu = self.menuBar().addMenu("&File")

        load_action = self.create_action("&Open", slot = self.open_file,
                                         shortcut = "Ctrl+O", tip = "Open analog data file")
        
        quit_action = self.create_action("&Quit", slot=self.close, 
                                         shortcut="Ctrl+Q", tip="Close the application")
        
        self.add_actions(self.file_menu, 
            (load_action, None, quit_action))
        
    def add_actions(self, target, actions):
        for action in actions:
            if action is None:
                target.addSeparator()
            else:
                target.addAction(action)

    def create_action(self, text, slot=None, shortcut=None, 
                      icon=None, tip=None, checkable=False, 
                      signal="triggered()"):
        action = QAction(text, self)
        if icon is not None:
            action.setIcon(QIcon(":/%s.png" % icon))
        if shortcut is not None:
            action.setShortcut(shortcut)
        if tip is not None:
            action.setToolTip(tip)
            action.setStatusTip(tip)
        if slot is not None:
            self.connect(action, SIGNAL(signal), slot)
        if checkable:
            action.setCheckable(True)
        return action

    def open_file(self):
        path = unicode(QFileDialog.getOpenFileName(self,
                                                   'Open File',
                                                   '',
                                                   ''))
        if path:
            self.data = SliceAnalogDataWad(path)
            self.create_main_frame()

        
def main(ser_dev):
    ser = serial.Serial(ser_dev)
    plot_buffer = SliceAnalogData(500)
    data_thread = SerialReaderThread(plot_buffer, ser)
    
    
    app = QApplication(sys.argv)
    form = SliceAnalogPlotter(data_thread, plot_buffer)
    form.show()
    app.exec_()

    
if __name__ == '__main__':
    if (len(sys.argv) > 1):
        main(sys.argv[1])
    else:
        raise Exception("No serial device argument")

