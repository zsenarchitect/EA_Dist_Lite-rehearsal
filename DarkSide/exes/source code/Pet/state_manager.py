from enum import Enum, auto
import time

class PetActivity(Enum):
    """Enumeration of possible pet activities."""
    IDLE = auto()
    WALKING = auto()
    SLEEPING = auto()
    FARMING = auto()
    READING = auto()
    BUILDING = auto()
    JOKING = auto()
    BORED = auto()
    CHASING = auto()
    CHATTING = auto()
    WALKING_LEFT = auto()
    WALKING_RIGHT = auto()

class PetState:
    """
    Manages the state and activities of the pet.
    Handles transitions between different activities and tracks current state.
    """
    
    def __init__(self):
        self.current_activity = PetActivity.IDLE
        self.activity_start_time = time.time()
        self.is_dragging = False
        
        # Activity durations in seconds
        self.activity_durations = {
            PetActivity.WALKING: 8,  # Walking duration is handled by the pet class
            PetActivity.WALKING_LEFT: 8,
            PetActivity.WALKING_RIGHT: 8,
            PetActivity.SLEEPING: 15,
            PetActivity.FARMING: 12,
            PetActivity.READING: 20,
            PetActivity.BUILDING: 15,
            PetActivity.JOKING: 5,
            PetActivity.BORED: 8,
            PetActivity.CHASING: 10,
            PetActivity.CHATTING: 30
        }
    
    def set_activity(self, activity_name):
        """
        Set the current activity based on the activity name.
        
        Args:
            activity_name (str): Name of the activity to set
        """
        activity_map = {
            "walk": PetActivity.WALKING,
            "walk_left": PetActivity.WALKING_LEFT,
            "walk_right": PetActivity.WALKING_RIGHT,
            "sleep": PetActivity.SLEEPING,
            "farm": PetActivity.FARMING,
            "read": PetActivity.READING,
            "build": PetActivity.BUILDING,
            "joke": PetActivity.JOKING,
            "bored": PetActivity.BORED,
            "chase": PetActivity.CHASING,
            "chat": PetActivity.CHATTING,
            "idle": PetActivity.IDLE
        }
        
        if activity_name in activity_map:
            self.current_activity = activity_map[activity_name]
            self.activity_start_time = time.time()
    
    def is_busy(self):
        """
        Check if the pet is currently engaged in an activity.
        
        Returns:
            bool: True if the current activity hasn't expired, False otherwise
        """
        if self.current_activity == PetActivity.IDLE:
            return False
            
        # Walking is managed by its own timer
        if self.current_activity in [PetActivity.WALKING, PetActivity.WALKING_LEFT, PetActivity.WALKING_RIGHT]:
            return True
            
        elapsed_time = time.time() - self.activity_start_time
        duration = self.activity_durations.get(self.current_activity, 0)
        
        return elapsed_time < duration
    
    def is_chasing(self):
        """
        Check if the pet is currently in chasing mode.
        
        Returns:
            bool: True if the pet is chasing, False otherwise
        """
        return self.current_activity == PetActivity.CHASING
    
    def set_dragging(self, is_dragging):
        """
        Set the dragging state of the pet.
        
        Args:
            is_dragging (bool): Whether the pet is being dragged
        """
        self.is_dragging = is_dragging
        if is_dragging:
            self.current_activity = PetActivity.IDLE
    
    def get_current_activity(self):
        """
        Get the current activity of the pet.
        
        Returns:
            PetActivity: The current activity enum value
        """
        return self.current_activity 