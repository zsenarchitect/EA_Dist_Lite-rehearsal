import threading
import time

import REVIT_EVENT
"""
Also make a versionfor Rhino maybe...
"""

"""the idea is simple, this contain a abstract class that can use to make a thread that attach any funcs. 
The args of the func might need to be stored in runtime sticky
it auto run every 2 seconds under revit. It is not a idle hook!
Probaly need to use external command.

some potential usage might be:
    - there is no post command hook, so this is helpful to catch any post stage changes and make action
    - pop ask if want to place new crated view at sheet(The is no post command hook so use this to monitor the creation of new view)


Intentionally not using args to pass around, becasue 
#1, there might be more func to bind, it might have overlapping keys in small risk
#2, script.get_evno_variable should use tiny memory, it is better to not allow it to avoid accidental huge memory usage

"""

class RevitUpdater:
    tasks = []
    active_updaters = []  # Track all active updater instances
    """
    probally make more sense if register at startup.

    example:
    def my_func():
        from Autodesk.Revit import DB # You need to import it here to avoid external command error, or you can define it ina dedicated sciprt.
        doc = __revit__.ActiveUIDocument.Document # pyright: ignore
        if not doc:
            return
        all_sheets = DB.FilteredElementCollector(doc).OfClass(DB.ViewSheet).ToElements()
        print (len(all_sheets))
        
    updater = EnneadTab.REVIT.REVIT_AUTO.RevitUpdater(my_func)
    updater.start()
    """

    # check if passing func arg already exist in cls task, do not initate again if already exist


    
    def __init__(self, func, interval = 2, max_life = -1):
        if func.__name__ in RevitUpdater.tasks:
            print ("func {} already exist in RevitUpdater".format(func.__name__))
            return
        self.func = func #############!!!!!! this is not good, this means there are only one func allow to auto run. Need to upgrade to a dict toallow parrell run funcs. Need change to the runner logic as well.

        self.interval = interval
        self.max_life = max_life
        
        self.stop_flag = False
        self.starting_time = time.time()



        # register func
        self.registered_func_runner = REVIT_EVENT.ExternalEventRunner(self.func)


        RevitUpdater.tasks.append(func.__name__)
        RevitUpdater.active_updaters.append(self)  # Track this instance
        


    def main_player(self):
        if self.max_life > 0:
            if time.time() - self.starting_time > self.max_life:
                self.stop_flag = True
                return

        # do not pass any args. just let the func figure out internally.
        self.registered_func_runner.run(self.func.__name__, )

        if not self.stop_flag:
            self.timer = threading.Timer(self.interval, self.main_player)
            self.timer.start()
        else:
            self.timer.cancel()
        
            #NOTIFICATION.messenger (main_text = "Monitor terminated.")

           
    def start(self): 
        
        self.timer = threading.Timer(0.1, self.main_player) # immediately call first action
        self.timer.start()

    def stop(self):
        self.stop_flag = True


    def unregister(self):
        RevitUpdater.tasks.remove(self.func.__name__)
        self.registered_func_runner.unregister(self.func.__name__)
        # Remove from active updaters list
        if self in RevitUpdater.active_updaters:
            RevitUpdater.active_updaters.remove(self)

    @classmethod
    def cleanup_all_events(cls):
        """Clean up all registered external events - call this when Revit is shutting down"""
        print("Cleaning up all RevitUpdater events...")
        
        # Clean up tracked events
        for updater in cls.active_updaters[:]:  # Use slice copy to avoid modification during iteration
            try:
                updater.stop()
                updater.unregister()
                print("Cleaned up tracked event: {}".format(updater.func.__name__))
            except Exception as e:
                print("Error cleaning up tracked event {}: {}".format(updater.func.__name__, str(e)))
        
        # Clear the lists
        cls.tasks.clear()
        cls.active_updaters.clear()
        
        # Force cleanup of any orphaned events by checking common function names
        cls._cleanup_orphaned_events()
        
        print("All RevitUpdater events cleaned up.")

    @classmethod
    def _cleanup_orphaned_events(cls):
        """Attempt to cleanup orphaned events from previous sessions"""
        print("Attempting to cleanup orphaned events...")
        
        # Common function names that might have been registered
        potential_orphaned_funcs = [
            'export_area_data',
            'my_func',
            'monitor_area_func',
            'area_monitor_func'
        ]
        
        for func_name in potential_orphaned_funcs:
            try:
                # Try to create a dummy updater to unregister any existing event
                if func_name in cls.tasks:
                    print("Found orphaned event: {}, attempting cleanup...".format(func_name))
                    # Create a dummy function with the same name
                    dummy_func = type('DummyFunc', (), {'__name__': func_name})()
                    dummy_updater = RevitUpdater(dummy_func)
                    dummy_updater.stop()
                    dummy_updater.unregister()
                    print("Successfully cleaned up orphaned event: {}".format(func_name))
            except Exception as e:
                print("Could not cleanup orphaned event {}: {}".format(func_name, str(e)))



