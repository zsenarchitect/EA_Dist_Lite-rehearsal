import _Exe_Util
import cv2
import numpy as np
import os
import time
import threading
import traceback
import gc
import signal
import sys
from datetime import datetime
from typing import Dict, Tuple, Optional, List, Any, Union

class ImageHandler:
    """
    A handler for continuously processing image files from task requests.
    
    This handler runs as a persistent service that:
    1. Monitors the DUMP folder for new tasks
    2. Processes images according to specified tasks
    3. Outputs results back to the DUMP folder
    4. Manages resources efficiently for continuous operation
    
    Supported image processing tasks:
    - convert_to_grey: Converts an image to greyscale
    - flip_horizontally: Flips an image horizontally
    
    Usage:
        handler = ImageHandler(debug_mode=True)
        handler.start()
    """
    
    # Class-level configuration
    _polling_interval: float = 2.0
    _running: bool = False
    _shutdown_requested: bool = False
    
    def __init__(self, debug_mode: bool = False) -> None:
        """
        Initializes the ImageHandler service.
        
        Args:
            debug_mode: If True, enables verbose logging and faster polling
        """
        self.debug_mode = debug_mode
        
        # Setup signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        # Initialize statistics
        self.stats: Dict[str, Any] = {
            "tasks_processed": 0,
            "errors": 0,
            "start_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        
        if self.debug_mode:
            print("ImageHandler: DEBUG mode enabled")
            self._polling_interval = 1.0  # Faster polling in debug mode
    
    def _signal_handler(self, sig: int, frame: Any) -> None:
        """
        Handles shutdown signals gracefully.
        
        Args:
            sig: Signal number
            frame: Current stack frame
        """
        print(f"ImageHandler: Received signal {sig}, shutting down gracefully...")
        self._shutdown_requested = True
    
    def start(self) -> None:
        """
        Starts the image handler service.
        
        If the service is already running, this method will return without action.
        """
        if ImageHandler._running:
            print("ImageHandler: Service already running")
            return
            
        ImageHandler._running = True
        self._shutdown_requested = False
        
        print(f"ImageHandler: Service started at {self.stats['start_time']}")
        self._process_loop()
    
    def _process_loop(self) -> None:
        """
        Main processing loop that continuously monitors for tasks.
        
        This method runs until the service is stopped or an unhandled exception occurs.
        """
        try:
            while ImageHandler._running and not self._shutdown_requested:
                # Process a single task if available
                task_processed = self._process_next_task()
                
                # Force garbage collection occasionally to prevent memory leaks
                if self.stats["tasks_processed"] % 10 == 0:
                    gc.collect()
                
                # Sleep between polling attempts
                if not task_processed:
                    time.sleep(self._polling_interval)
        except Exception as e:
            print(f"ImageHandler: Critical error in main loop: {str(e)}")
            traceback.print_exc()
            self.stats["errors"] += 1
        finally:
            self._cleanup()
    
    def _cleanup(self) -> None:
        """
        Performs cleanup operations when shutting down.
        """
        ImageHandler._running = False
        print(f"ImageHandler: Service stopped. Stats: {self.stats}")
    
    def _process_next_task(self) -> bool:
        """
        Processes the next available task from the DUMP folder.
        
        Returns:
            bool: True if a task was processed, False otherwise
        """
        try:
            # Find the next pending task
            task_path, task_data = self._find_next_task()
            
            if not task_data:
                return False
                
            # Process the task
            print(f"ImageHandler: Processing task from {os.path.basename(task_path)}")
            result = self._execute_task(task_data, task_path)
            
            self.stats["tasks_processed"] += 1
            return True
            
        except Exception as e:
            print(f"ImageHandler: Error processing task: {str(e)}")
            traceback.print_exc()
            self.stats["errors"] += 1
            return False
    
    def _find_next_task(self) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
        """
        Finds the next pending task in the DUMP folder.
        
        Returns:
            tuple: (task_path, task_data) or (None, None) if no tasks found
        """
        dump_folder = _Exe_Util.get_dump_folder()
        
        for filename in os.listdir(dump_folder):
            if filename.startswith("IMAGE_HANDLER_INPUT_") and filename.endswith(_Exe_Util.PLUGIN_EXTENSION):
                task_path = os.path.join(dump_folder, filename)
                
                try:
                    task_data = _Exe_Util.get_data(task_path)
                    if task_data and task_data.get("status") == "pending":
                        return task_path, task_data
                except Exception as e:
                    print(f"ImageHandler: Error reading task file {filename}: {str(e)}")
                    continue
        
        return None, None
    
    def _execute_task(self, task_data: Dict[str, Any], task_path: str) -> Dict[str, Any]:
        """
        Executes a single image processing task.
        
        Args:
            task_data: The task configuration data
            task_path: Path to the task file
            
        Returns:
            dict: Result data with success status and output path
        """
        output: Dict[str, Any] = {}
        
        try:
            # Get the image path
            image_path = task_data.get("image_source")
            if not image_path or not isinstance(image_path, str):
                raise ValueError("Invalid or missing image source path")
                
            # Load the image
            image = self._load_image_safely(image_path)
            if image is None:
                raise ValueError(f"Failed to load image from {image_path}")
                
            # Process each requested task
            result_image = image
            for task in task_data.get("tasks", []):
                if task == "convert_to_grey":
                    result_image = self._convert_to_greyscale(result_image)
                elif task == "flip_horizontally":
                    result_image = self._flip_horizontally(result_image)
                else:
                    print(f"ImageHandler: Unknown task '{task}', skipping")
            
            # Save the result
            target_path = task_data.get("target_address")
            if not target_path:
                # Create default output path
                filename = os.path.basename(image_path)
                name, ext = os.path.splitext(filename)
                target_path = _Exe_Util.get_file_in_dump_folder(f"{name}_processed{ext}")
            
            self._save_image(result_image, target_path)
            output["result_path"] = target_path
            output["success"] = True
            
            # Mark task as complete
            self._mark_task_complete(task_data, task_path, output)
            return output
            
        except Exception as e:
            error_msg = f"Error processing task: {str(e)}"
            print(f"ImageHandler: {error_msg}")
            
            # Mark task as errored but still completed
            output["success"] = False
            output["error"] = error_msg
            self._mark_task_complete(task_data, task_path, output)
            self.stats["errors"] += 1
            return output
    
    def _mark_task_complete(self, task_data: Dict[str, Any], task_path: str, output: Dict[str, Any]) -> None:
        """
        Marks a task as complete and saves output data.
        
        Args:
            task_data: The task data
            task_path: Path to the task file
            output: The processing results
        """
        # Update task status
        task_data["status"] = "finished"
        _Exe_Util.set_data(task_data, task_path)
        
        # Create output file with matching identifier
        filename = os.path.basename(task_path)
        if filename.startswith("IMAGE_HANDLER_INPUT_") and filename.endswith(_Exe_Util.PLUGIN_EXTENSION):
            identifier = filename[len("IMAGE_HANDLER_INPUT_"):-len(_Exe_Util.PLUGIN_EXTENSION)]
            output_filename = f"IMAGE_HANDLER_OUTPUT_{identifier}{_Exe_Util.PLUGIN_EXTENSION}"
        else:
            output_filename = f"IMAGE_HANDLER_OUTPUT_{int(time.time())}{_Exe_Util.PLUGIN_EXTENSION}"
        
        # Add processing metadata
        output["processing_info"] = {
            "finished_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "tasks_performed": task_data.get("tasks", []),
            "source_image": task_data.get("image_source"),
            "processed_by": "ImageHandler"
        }
        
        # Save output
        output_path = os.path.join(_Exe_Util.get_dump_folder(), output_filename)
        _Exe_Util.set_data(output, output_path)
        print(f"ImageHandler: Task completed, output saved to {output_filename}")
    
    def _load_image_safely(self, image_path: str, max_attempts: int = 3, delay: int = 1) -> Optional[np.ndarray]:
        """
        Loads an image with retry mechanism and resource management.
        
        Args:
            image_path: Path to the image file
            max_attempts: Maximum number of loading attempts
            delay: Delay between attempts in seconds
            
        Returns:
            numpy.ndarray or None: The loaded image or None if failed
        """
        attempts = 0
        while attempts < max_attempts:
            try:
                if os.path.exists(image_path):
                    image = cv2.imread(image_path)
                    if image is not None:
                        return image
            except Exception as e:
                print(f"ImageHandler: Error loading image: {str(e)}")
            
            print(f"ImageHandler: Image not ready, attempt {attempts+1}/{max_attempts}")
            time.sleep(delay)
            attempts += 1
        
        return None
    
    def _convert_to_greyscale(self, image: np.ndarray) -> np.ndarray:
        """
        Converts a color image to greyscale.
        
        Args:
            image: The image to convert
            
        Returns:
            numpy.ndarray: Greyscale image
        """
        return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    
    def _flip_horizontally(self, image: np.ndarray) -> np.ndarray:
        """
        Flips an image horizontally.
        
        Args:
            image: The image to flip
            
        Returns:
            numpy.ndarray: Flipped image
        """
        return cv2.flip(image, 1)  # 1 means horizontal flip
    
    def _save_image(self, image: np.ndarray, path: str) -> None:
        """
        Saves an image to the specified path.
        
        Args:
            image: The image to save
            path: Path where to save the image
        """
        directory = os.path.dirname(path)
        if directory and not os.path.exists(directory):
            os.makedirs(directory)
            
        cv2.imwrite(path, image)
        print(f"ImageHandler: Image saved to {path}")


def run_service(debug_mode: bool = False) -> None:
    """
    Main entry point to run the ImageHandler service.
    
    Args:
        debug_mode: If True, enables verbose logging and faster polling
    """
    handler = ImageHandler(debug_mode=debug_mode)
    handler.start()


if __name__ == "__main__":
    """
    Entry point for the script.
    
    To run in debug mode: python ImageHandler.py debug
    """
    debug_mode = len(sys.argv) > 1 and sys.argv[1].lower() == "debug"
    run_service(debug_mode=debug_mode)
