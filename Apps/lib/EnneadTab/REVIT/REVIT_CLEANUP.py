#!/usr/bin/python
# -*- coding: utf-8 -*-

"""
Revit Cleanup Utilities
Handles cleanup of external events and resources when Revit closes
"""

import sys
import os

try:
    from Autodesk.Revit import DB, UI
    from Autodesk.Revit.UI import IExternalApplication
    REVIT_AVAILABLE = True
except ImportError:
    REVIT_AVAILABLE = False

# Add EnneadTab lib path
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.append(current_dir)

from EnneadTab.REVIT import REVIT_AUTO


class RevitCleanupApplication(IExternalApplication):
    """
    IExternalApplication implementation for cleanup
    Registers cleanup handlers for Revit shutdown
    """
    
    def OnStartup(self, application):
        """Called when Revit starts up"""
        try:
            # Subscribe to ApplicationClosing event
            application.ApplicationClosing += self.OnApplicationClosing
            print("RevitCleanupApplication: Registered cleanup handler")
            return 0  # Result.Succeeded
        except Exception as e:
            print("RevitCleanupApplication startup error: {}".format(str(e)))
            return 1  # Result.Failed
    
    def OnShutdown(self, application):
        """Called when Revit shuts down"""
        try:
            print("RevitCleanupApplication: OnShutdown called")
            self._perform_cleanup()
            return 0  # Result.Succeeded
        except Exception as e:
            print("RevitCleanupApplication shutdown error: {}".format(str(e)))
            return 1  # Result.Failed
    
    def OnApplicationClosing(self, sender, args):
        """Called when Revit application is closing"""
        try:
            print("RevitCleanupApplication: ApplicationClosing event triggered")
            self._perform_cleanup()
        except Exception as e:
            print("RevitCleanupApplication closing error: {}".format(str(e)))
    
    def _perform_cleanup(self):
        """Perform the actual cleanup"""
        try:
            # Clean up all RevitUpdater events
            REVIT_AUTO.RevitUpdater.cleanup_all_events()
            
            # Add any other cleanup tasks here
            print("RevitCleanupApplication: Cleanup completed")
            
        except Exception as e:
            print("RevitCleanupApplication cleanup error: {}".format(str(e)))


def register_cleanup_handler():
    """
    Register cleanup handler for Revit shutdown
    Call this from your startup script
    """
    if not REVIT_AVAILABLE:
        print("Revit API not available, skipping cleanup registration")
        return
    
    try:
        # This would need to be registered in the actual IExternalApplication
        # For now, we'll provide the cleanup function that can be called manually
        print("Cleanup handler ready - call cleanup_on_shutdown() when needed")
    except Exception as e:
        print("Error registering cleanup handler: {}".format(str(e)))


def cleanup_on_shutdown():
    """
    Manual cleanup function - call this when Revit is shutting down
    or when you want to force cleanup of all events
    """
    try:
        print("Manual cleanup initiated...")
        REVIT_AUTO.RevitUpdater.cleanup_all_events()
        print("Manual cleanup completed")
    except Exception as e:
        print("Manual cleanup error: {}".format(str(e)))


def force_cleanup_orphaned_events():
    """
    Force cleanup of any orphaned events from previous sessions
    Call this at the start of your scripts
    """
    try:
        print("Force cleanup of orphaned events...")
        REVIT_AUTO.RevitUpdater.cleanup_all_events()
        print("Orphaned events cleanup completed")
    except Exception as e:
        print("Orphaned events cleanup error: {}".format(str(e)))


# Export the main class for registration
__all__ = ['RevitCleanupApplication', 'register_cleanup_handler', 'cleanup_on_shutdown', 'force_cleanup_orphaned_events']
