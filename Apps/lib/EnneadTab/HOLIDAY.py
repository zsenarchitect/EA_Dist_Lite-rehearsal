# -*- coding: utf-8 -*-
# https://python-holidays.readthedocs.io/en/latest/index.html

"""
Holiday Greeting System for EnneadTab.

This module provides customized holiday greetings for office employees based on the current date.
Supports multiple cultural and seasonal celebrations with images and sound effects.
"""


import datetime
import os
import random


import FOLDER
import SOUND
import ENVIRONMENT
import NOTIFICATION
import OUTPUT
import DATA_FILE
from __init__ import dream

# Python 2/3 compatibility
try:
    basestring  # Python 2 # pyright: ignore
except NameError:
    basestring = str  # Python 3


def _get_holiday_name(greeting_func):
    """Map holiday greeting function to a unique holiday identifier string.
    
    Args:
        greeting_func: The greeting function object
        
    Returns:
        str: Holiday identifier string (e.g., "christmas", "chinese_new_year")
    """
    # Map function names to holiday identifiers (works with forward references)
    # Using __name__ attribute for compatibility with IronPython 2.7
    name_map = {
        "greeting_chinese_new_year": "chinese_new_year",
        "greeting_mid_moon": "mid_autumn",
        "greeting_xmas": "christmas",
        "greeting_pi": "pi_day",
        "greeting_april_fools": "april_fools",
        "greeting_may_force": "may_force",
        "greeting_halloween": "halloween"
    }
    
    func_name = getattr(greeting_func, "__name__", "unknown")
    return name_map.get(func_name, "unknown")


def _was_greeting_shown_this_year(holiday_name):
    """Check if a holiday greeting was already shown this year.
    
    Args:
        holiday_name (str): Holiday identifier string
        
    Returns:
        bool: True if greeting was shown this year, False otherwise
    """
    try:
        tracking_data = DATA_FILE.get_data("holiday_greeting_tracking", is_local=True)
        if not isinstance(tracking_data, dict):
            return False
        
        current_year = datetime.datetime.now().year
        stored_year = tracking_data.get(holiday_name)
        
        if stored_year is None:
            return False
        
        return stored_year == current_year
    except Exception:
        return False


def _mark_greeting_shown(holiday_name):
    """Mark a holiday greeting as shown for the current year.
    
    Args:
        holiday_name (str): Holiday identifier string
    """
    try:
        tracking_data = DATA_FILE.get_data("holiday_greeting_tracking", is_local=True)
        if not isinstance(tracking_data, dict):
            tracking_data = dict()
        
        current_year = datetime.datetime.now().year
        tracking_data[holiday_name] = current_year
        
        DATA_FILE.set_data(tracking_data, "holiday_greeting_tracking", is_local=True)
    except Exception:
        # Silently fail if tracking cannot be saved
        pass


class HolidayDateChecker:
    """Utility class to check holiday dates for any year."""
    
    @staticmethod
    def is_valid_date(start_date, end_date):
        """
        Check if current date falls within the given range.
        
        Args:
            start_date (datetime.date): Start date of holiday period
            end_date (datetime.date): End date of holiday period
            
        Returns:
            bool: True if current date is within range
        """
        today = datetime.datetime.now().date()
        return start_date <= today <= end_date

    @staticmethod
    def get_chinese_new_year_dates(year):
        """Get Chinese New Year celebration period for given year."""
        # Dates from Chinese calendar (approximate, can be adjusted)
        dates = {
            2024: (datetime.date(2024, 2, 10), datetime.date(2024, 2, 11)),  # Year of Dragon
            2025: (datetime.date(2025, 1, 29), datetime.date(2025, 1, 30)),   # Year of Snake
            2026: (datetime.date(2026, 2, 17), datetime.date(2026, 2, 18)),   # Year of Horse
            2027: (datetime.date(2027, 2, 6), datetime.date(2027, 2, 7)),   # Year of Goat
            2028: (datetime.date(2028, 1, 26), datetime.date(2028, 1, 27)),   # Year of Monkey
            2029: (datetime.date(2029, 2, 13), datetime.date(2029, 2, 14)),  # Year of Rooster
            2030: (datetime.date(2030, 2, 3), datetime.date(2030, 2, 4)),   # Year of Dog
            2031: (datetime.date(2031, 1, 23), datetime.date(2031, 1, 24)),   # Year of Pig
            2032: (datetime.date(2032, 2, 11), datetime.date(2032, 2, 12)),  # Year of Rat
            2033: (datetime.date(2033, 1, 31), datetime.date(2033, 2, 1)),  # Year of Ox
            2034: (datetime.date(2034, 2, 19), datetime.date(2034, 2, 20)),   # Year of Tiger
            2035: (datetime.date(2035, 2, 8), datetime.date(2035, 2, 9)),   # Year of Rabbit
            2036: (datetime.date(2036, 1, 28), datetime.date(2036, 1, 29)),  # Year of Dragon
            2037: (datetime.date(2037, 2, 15), datetime.date(2037, 2, 16)),   # Year of Snake
            2038: (datetime.date(2038, 2, 4), datetime.date(2038, 2, 5)),   # Year of Horse
            2039: (datetime.date(2039, 1, 24), datetime.date(2039, 1, 25)),   # Year of Goat
            2040: (datetime.date(2040, 2, 12), datetime.date(2040, 2, 13)),  # Year of Monkey
            2041: (datetime.date(2041, 2, 1), datetime.date(2041, 2, 2)),   # Year of Rooster
            2042: (datetime.date(2042, 1, 22), datetime.date(2042, 1, 23)),   # Year of Dog
            2043: (datetime.date(2043, 2, 10), datetime.date(2043, 2, 11)),  # Year of Pig
            2044: (datetime.date(2044, 1, 30), datetime.date(2044, 1, 31)),  # Year of Rat
            # Add more years as needed
        }
        return dates.get(year, (None, None))

    @staticmethod
    def get_mid_autumn_dates(year):
        """Get Mid-Autumn Festival dates for given year."""
        dates = {
            2024: (datetime.date(2024, 9, 17), datetime.date(2024, 9, 18)),
            2025: (datetime.date(2025, 10, 6), datetime.date(2025, 10, 7)),
            2026: (datetime.date(2026, 9, 25), datetime.date(2026, 9, 26)),
            2027: (datetime.date(2027, 9, 15), datetime.date(2027, 9, 16)),
            2028: (datetime.date(2028, 10, 3), datetime.date(2028, 10, 4)),
            2029: (datetime.date(2029, 9, 22), datetime.date(2029, 9, 23)),
            2030: (datetime.date(2030, 9, 12), datetime.date(2030, 9, 13)),
            2031: (datetime.date(2031, 10, 1), datetime.date(2031, 10, 2)),
            2032: (datetime.date(2032, 9, 19), datetime.date(2032, 9, 20)),
            2033: (datetime.date(2033, 9, 8), datetime.date(2033, 9, 9)),
            2034: (datetime.date(2034, 9, 28), datetime.date(2034, 9, 29)),
            2035: (datetime.date(2035, 9, 17), datetime.date(2035, 9, 18)),
            2036: (datetime.date(2036, 10, 5), datetime.date(2036, 10, 6)),
            2037: (datetime.date(2037, 9, 24), datetime.date(2037, 9, 25)),
            2038: (datetime.date(2038, 9, 13), datetime.date(2038, 9, 14)),
            2039: (datetime.date(2039, 10, 2), datetime.date(2039, 10, 3)),
            2040: (datetime.date(2040, 9, 20), datetime.date(2040, 9, 21)),
            2041: (datetime.date(2041, 9, 10), datetime.date(2041, 9, 11)),
            2042: (datetime.date(2042, 9, 29), datetime.date(2042, 9, 30)),
            2043: (datetime.date(2043, 9, 18), datetime.date(2043, 9, 19)),
            2044: (datetime.date(2044, 10, 7), datetime.date(2044, 10, 8)),
            # Add more years as needed
        }
        return dates.get(year, (None, None))

    @staticmethod
    def get_xmas_dates(year):
        """Get Christmas celebration period."""
        return (
            datetime.date(year, 12, 24),
            datetime.date(year, 12, 25)
        )

    @staticmethod
    def get_pi_day_dates(year):
        """Get Pi Day celebration period."""
        return (
            datetime.date(year, 3, 14),
            datetime.date(year, 3, 15)
        )

    @staticmethod
    def get_april_fools_dates(year):
        """Get April Fools' Day celebration period."""
        return (
            datetime.date(year, 4, 1),
            datetime.date(year, 4, 1)
        )

    @staticmethod
    def get_may_force_dates(year):
        """Get Star Wars Day celebration period."""
        return (
            datetime.date(year, 5, 4),
            datetime.date(year, 5, 4)
        )

    @staticmethod
    def get_halloween_dates(year):
        """Get Halloween celebration period."""
        return (
            datetime.date(year, 10, 30),
            datetime.date(year, 10, 31)
        )
    @staticmethod
    def _get_nth_weekday_of_month(year, month, weekday_index, n):
        """
        Get the date of the nth occurrence of a weekday in a month.
        weekday_index: 0=Mon, 6=Sun
        n: 1=1st, 2=2nd, ... -1=last
        """
        if n > 0:
            date = datetime.date(year, month, 1)
            while date.weekday() != weekday_index:
                date += datetime.timedelta(days=1)
            date += datetime.timedelta(weeks=n-1)
        else:
            if month == 12:
                next_month = datetime.date(year + 1, 1, 1)
            else:
                next_month = datetime.date(year, month + 1, 1)
            date = next_month - datetime.timedelta(days=1)
            while date.weekday() != weekday_index:
                date -= datetime.timedelta(days=1)
            date -= datetime.timedelta(weeks=(-n)-1)
            
        if date.month != month:
            return None
        return date

    @staticmethod
    def get_dragon_boat_dates(year):
        """Get Dragon Boat Festival dates."""
        dates = {
            2024: datetime.date(2024, 6, 10),
            2025: datetime.date(2025, 5, 31),
            2026: datetime.date(2026, 6, 19),
            2027: datetime.date(2027, 6, 9),
            2028: datetime.date(2028, 5, 28),
            2029: datetime.date(2029, 6, 16),
            2030: datetime.date(2030, 6, 5),
            2031: datetime.date(2031, 6, 24),
            2032: datetime.date(2032, 6, 12),
            2033: datetime.date(2033, 5, 31),
            2034: datetime.date(2034, 6, 19),
            2035: datetime.date(2035, 6, 10),
            2036: datetime.date(2036, 5, 30),
            2037: datetime.date(2037, 6, 18),
            2038: datetime.date(2038, 6, 7),
            2039: datetime.date(2039, 6, 27),
            2040: datetime.date(2040, 6, 15),
            2041: datetime.date(2041, 6, 3),
            2042: datetime.date(2042, 6, 23),
            2043: datetime.date(2043, 6, 12),
            2044: datetime.date(2044, 5, 31),
            2045: datetime.date(2045, 6, 19)
        }
        d = dates.get(year)
        if d:
            return (d, d)
        return (None, None)

    @staticmethod
    def get_donut_day_dates(year):
        """1st Friday of June."""
        d = HolidayDateChecker._get_nth_weekday_of_month(year, 6, 4, 1) # 4=Fri
        return (d, d)

    @staticmethod
    def get_hot_dog_day_dates(year):
        """3rd Wednesday of July."""
        d = HolidayDateChecker._get_nth_weekday_of_month(year, 7, 2, 3) # 2=Wed
        return (d, d)

    @staticmethod
    def get_ice_cream_day_dates(year):
        """3rd Sunday of July."""
        d = HolidayDateChecker._get_nth_weekday_of_month(year, 7, 6, 3) # 6=Sun
        return (d, d)



    @staticmethod
    def get_pirate_day_dates(year):
        """September 19."""
        return (datetime.date(year, 9, 19), datetime.date(year, 9, 19))



    @staticmethod
    def get_towel_day_dates(year):
        """May 25."""
        return (datetime.date(year, 5, 25), datetime.date(year, 5, 25))



    @staticmethod
    def get_ufo_day_dates(year):
        """July 2."""
        return (datetime.date(year, 7, 2), datetime.date(year, 7, 2))

    @staticmethod
    def get_coffee_day_dates(year):
        """September 29."""
        return (datetime.date(year, 9, 29), datetime.date(year, 9, 29))

    @staticmethod
    def get_pizza_day_dates(year):
        """February 9."""
        return (datetime.date(year, 2, 9), datetime.date(year, 2, 9))

    @staticmethod
    def get_duckie_day_dates(year):
        """January 13."""
        return (datetime.date(year, 1, 13), datetime.date(year, 1, 13))

    @staticmethod
    def get_mario_day_dates(year):
        """March 10."""
        return (datetime.date(year, 3, 10), datetime.date(year, 3, 10))

    @staticmethod
    def get_hobbit_day_dates(year):
        """September 22."""
        return (datetime.date(year, 9, 22), datetime.date(year, 9, 22))

    @staticmethod
    def get_ninja_day_dates(year):
        """December 5."""
        return (datetime.date(year, 12, 5), datetime.date(year, 12, 5))


def display_greeting(image_name, title_text="Greeting from EnneadTab", 
                    sound_file=None, md_text=None):
    """
    Display holiday greeting with image and optional sound.
    
    Args:
        image_name (str or list): Filename of image to display, or list of image names to randomly choose from.
                                 Images will be prefixed with 'holiday_' if not already present.
        title_text (str): Window title text
        sound_file (str, optional): Sound file to play
        md_text (str, optional): Markdown text to display
    """
    # Handle list of images by randomly selecting one
    if isinstance(image_name, list):
        if not image_name:  # Empty list check
            return
        image_name = random.choice(image_name)
        
    # Add 'holiday_' prefix if not already present
    if isinstance(image_name, basestring) and not image_name.startswith("holiday_"):
        image_name = "holiday_" + image_name
        
    image_file = os.path.join(ENVIRONMENT.IMAGE_FOLDER, image_name)
    
    output = OUTPUT.get_output()
    output.write(title_text, OUTPUT.Style.Title)
    if os.path.exists(image_file):
        output.write(image_file)
    
    if md_text:
        output.write(md_text)
        
    output.plot()
    
    if sound_file:
        # Check if sound file needs folder prefix for standard location
        if not os.path.isfile(sound_file) and not sound_file.startswith("holiday_"):
            sound_file = os.path.join(ENVIRONMENT.AUDIO_FOLDER, sound_file)
        SOUND.play_sound(sound_file)


def festival_greeting():
    """Check current date and display appropriate holiday greetings."""
    

    
    year = datetime.datetime.now().year
    checker = HolidayDateChecker()
    
    # Dictionary mapping holiday check functions to greeting functions
    holiday_checks = [
        # Chinese New Year
        (checker.get_chinese_new_year_dates(year), greeting_chinese_new_year),
        # Mid-Autumn Festival
        (checker.get_mid_autumn_dates(year), greeting_mid_moon),
        # Christmas
        (checker.get_xmas_dates(year), greeting_xmas),
        # Pi Day
        (checker.get_pi_day_dates(year), greeting_pi),
        # April Fools' Day
        (checker.get_april_fools_dates(year), greeting_april_fools),
        # Star Wars Day
        (checker.get_may_force_dates(year), greeting_may_force),
        # Halloween
        (checker.get_halloween_dates(year), greeting_halloween),
        
        # New Holidays
        (checker.get_dragon_boat_dates(year), greeting_dragon_boat),
        (checker.get_donut_day_dates(year), greeting_donut),
        (checker.get_hot_dog_day_dates(year), greeting_hot_dog),
        (checker.get_ice_cream_day_dates(year), greeting_ice_cream),

        (checker.get_pirate_day_dates(year), greeting_pirate),

        (checker.get_towel_day_dates(year), greeting_towel),

        (checker.get_ufo_day_dates(year), greeting_ufo),
        (checker.get_coffee_day_dates(year), greeting_coffee),
        (checker.get_pizza_day_dates(year), greeting_pizza),
        (checker.get_duckie_day_dates(year), greeting_duckie),
        (checker.get_mario_day_dates(year), greeting_mario),
        (checker.get_hobbit_day_dates(year), greeting_hobbit),
        (checker.get_ninja_day_dates(year), greeting_ninja)
    ]
    
    # Check each holiday and display greeting if date is valid
    for (start, end), greeting_func in holiday_checks:
        if start and checker.is_valid_date(start, end):
            holiday_name = _get_holiday_name(greeting_func)
            if not _was_greeting_shown_this_year(holiday_name):
                greeting_func()
                _mark_greeting_shown(holiday_name)
            return

    # ramdon print dream
    if random.random() < 0.00005:
        output = OUTPUT.get_output()
        output.write(dream(), OUTPUT.Style.MainBody)
        output.plot()


def greeting_april_fools():
    """Display April Fool's Day greeting and pranks."""
    year = datetime.datetime.now().year
    start, end = HolidayDateChecker.get_april_fools_dates(year)
    
    if not HolidayDateChecker.is_valid_date(start, end):
        return

    import JOKE

    for _ in range(random.randint(1, 5)):
        JOKE.prank_dvd()

    # Use some fun sounds for April Fools
    fun_sounds = [
        "meme_bruh.wav",
        "meme_oof.wav",
        "meme_what.wav",
        "sound_effect_mario_die.wav",
        "sound_effect_duck.wav"
    ]
    
    NOTIFICATION.messenger(JOKE.random_loading_message())
    SOUND.play_sound(os.path.join(ENVIRONMENT.AUDIO_FOLDER, random.choice(fun_sounds)))


def greeting_may_force():
    """Display Star Wars Day greeting."""
    year = datetime.datetime.now().year
    start, end = HolidayDateChecker.get_may_force_dates(year)
    
    if not HolidayDateChecker.is_valid_date(start, end):
        return

    display_greeting(
        image_name="may_force.jpg",
        title_text="Happy Star Wars Day: May the Force be with you!",
        sound_file="sound_effect_mario_powerup.wav"  # Use a fun sound for Star Wars Day
    )


def greeting_pi():
    """Display Pi Day greeting."""
    year = datetime.datetime.now().year
    start, end = HolidayDateChecker.get_pi_day_dates(year)
    
    if not HolidayDateChecker.is_valid_date(start, end):
        return

    display_greeting(
        image_name="pi_day.jpeg",
        title_text="Happy Pi Day: 3.14",
        sound_file="sound_effect_happy_bell.wav"
    )


def greeting_xmas():
    """Display Christmas greeting."""
    year = datetime.datetime.now().year
    start, end = HolidayDateChecker.get_xmas_dates(year)
    
    if not HolidayDateChecker.is_valid_date(start, end):
        return

    display_greeting(
        image_name="xmax_tree_drawing.png",
        title_text="Merry Christmas!",
        sound_file="holiday_xmas.wav"  # Updated to use the correct holiday sound file
    )


def greeting_chinese_new_year():
    """Display Chinese New Year greeting."""
    year = datetime.datetime.now().year
    start, end = HolidayDateChecker.get_chinese_new_year_dates(year)
    
    if not start or not HolidayDateChecker.is_valid_date(start, end):
        return

    # Zodiac animals in order (0=Monkey, 1=Rooster, etc. for year % 12)
    # The sequence starting from 0 AD (Monkey) is:
    # 0: Monkey, 1: Rooster, 2: Dog, 3: Pig, 4: Rat, 5: Ox, 
    # 6: Tiger, 7: Rabbit, 8: Dragon, 9: Snake, 10: Horse, 11: Goat
    zodiacs = [
        "MONKEY", "ROOSTER", "DOG", "PIG", "RAT", "OX",
        "TIGER", "RABBIT", "DRAGON", "SNAKE", "HORSE", "GOAT"
    ]
    
    zodiac_index = year % 12
    zodiac_name = zodiacs[zodiac_index]
    
    # Handle Rabbit/Bunny alias
    if zodiac_name == "RABBIT":
        # Check if BUNNY exists, otherwise default to RABBIT
        # (Current asset is holiday_YEAR OF BUNNY.png)
        zodiac_name = "BUNNY" 

    # Look for images matching "holiday_YEAR OF [ZODIAC]*.png"
    # normalize name for search
    search_name = "YEAR OF {}".format(zodiac_name)
    
    import glob
    image_folder = ENVIRONMENT.IMAGE_FOLDER
    pattern = os.path.join(image_folder, "holiday_{}*.png".format(search_name))
    found_images = glob.glob(pattern)
    
    # Extract just the filenames
    valid_images = [os.path.basename(f) for f in found_images]
    
    if not valid_images:
        # Fallback if no specific image found
        # Maybe use a generic "Happy New Year" or just log warning?
        # For now, let's just return to avoid crashing
        return
        
    display_greeting(
        image_name=valid_images,
        title_text="Happy Chinese New Year: Year of the {}!".format(zodiac_name.title()),
        sound_file="holiday_chinese_new_year.wav"
    )


def greeting_mid_moon():
    """Display Mid-Autumn Festival greeting."""
    year = datetime.datetime.now().year
    start, end = HolidayDateChecker.get_mid_autumn_dates(year)
    
    if not start or not HolidayDateChecker.is_valid_date(start, end):
        return

    # Use the display_greeting function for consistency
    display_greeting(
        image_name="mid moon.jpg",
        title_text="Happy Mid-Autumn Festival!"
    )
    
    # Additional moon cake image
    output = OUTPUT.get_output()
    output.write("## Also known as the Moon-Festival, it is a family reunion holiday shared in many east asian culture.", OUTPUT.Style.Subtitle)
    output.write("## An important part is the moon-cake. You may find the technical drawing below.", OUTPUT.Style.Subtitle)
    
    moon_cake_image = "holiday_moon-cake-drawing.png"
    moon_cake_image_file = os.path.join(ENVIRONMENT.IMAGE_FOLDER, moon_cake_image)
    output.write(moon_cake_image_file)
    
    output.plot()
    
    # SOUND.play_sound(os.path.join(ENVIRONMENT.AUDIO_FOLDER, "holiday_chinese_new_year.wav"))

    # Occasional export to HTML
    if random.random() > 0.2:
        return
        
    dest_file = FOLDER.get_local_dump_folder_file("Moon Festival.html")
    try:
        output.save_contents(dest_file)
        output.close()
        os.startfile(dest_file)
    except Exception:
        # Handle errors more generically for Python 2 compatibility
        pass


def greeting_halloween():
    """Display Halloween greeting."""
    year = datetime.datetime.now().year
    start, end = HolidayDateChecker.get_halloween_dates(year)
    
    if not HolidayDateChecker.is_valid_date(start, end):
        return
    
    # Use duck images for fun Halloween greeting
    halloween_images = [
        "duck.png",
        "duck_pop_green_bg.png",
        "duck_pop_green_bg2.png"
    ]
    
    # Duck-themed Halloween greeting
    display_greeting(
        image_name=halloween_images,
        title_text="Happy Halloween!",
        sound_file="sound_effect_duck.wav",
        md_text="## Trick or Treat! The EnneadTab duck is here to spook you!"
    )


def greeting_dragon_boat():
    """Display Dragon Boat Festival greeting."""
    year = datetime.datetime.now().year
    start, end = HolidayDateChecker.get_dragon_boat_dates(year)
    if not HolidayDateChecker.is_valid_date(start, end): return
    display_greeting(
        image_name="holiday_dragon_boat.jpg",
        title_text="Happy Dragon Boat Festival!",
        md_text="## Eating Zongzi and racing boats!"
    )

def greeting_donut():
    """Display National Donut Day greeting."""
    year = datetime.datetime.now().year
    start, end = HolidayDateChecker.get_donut_day_dates(year)
    if not HolidayDateChecker.is_valid_date(start, end): return
    display_greeting(
        image_name="holiday_donut.jpg",
        title_text="Happy National Donut Day!",
        sound_file="sound_effect_mario_powerup.wav"
    )

def greeting_hot_dog():
    """Display National Hot Dog Day greeting."""
    year = datetime.datetime.now().year
    start, end = HolidayDateChecker.get_hot_dog_day_dates(year)
    if not HolidayDateChecker.is_valid_date(start, end): return
    display_greeting(
        image_name="holiday_hot_dog.jpg",
        title_text="Happy National Hot Dog Day!"
    )

def greeting_ice_cream():
    """Display National Ice Cream Day greeting."""
    year = datetime.datetime.now().year
    start, end = HolidayDateChecker.get_ice_cream_day_dates(year)
    if not HolidayDateChecker.is_valid_date(start, end): return
    display_greeting(
        image_name="holiday_ice_cream.jpg",
        title_text="Happy National Ice Cream Day!",
        sound_file="sound_effect_happy_bell.wav"
    )



def greeting_pirate():
    """Display Talk Like a Pirate Day greeting."""
    year = datetime.datetime.now().year
    start, end = HolidayDateChecker.get_pirate_day_dates(year)
    if not HolidayDateChecker.is_valid_date(start, end): return
    display_greeting(
        image_name="holiday_pirate.jpg",
        title_text="Ahoy! It's Talk Like a Pirate Day!",
        md_text="## Arrr matey!"
    )



def greeting_towel():
    """Display Towel Day greeting."""
    year = datetime.datetime.now().year
    start, end = HolidayDateChecker.get_towel_day_dates(year)
    if not HolidayDateChecker.is_valid_date(start, end): return
    display_greeting(
        image_name="holiday_towel.jpg",
        title_text="Happy Towel Day! Don't Panic."
    )



def greeting_ufo():
    """Display World UFO Day greeting."""
    year = datetime.datetime.now().year
    start, end = HolidayDateChecker.get_ufo_day_dates(year)
    if not HolidayDateChecker.is_valid_date(start, end): return
    display_greeting(
        image_name="holiday_ufo.jpg",
        title_text="Happy World UFO Day! (Roswell Tribute)",
        md_text="## The truth is out there."
    )

def greeting_coffee():
    """Display National Coffee Day greeting."""
    year = datetime.datetime.now().year
    start, end = HolidayDateChecker.get_coffee_day_dates(year)
    if not HolidayDateChecker.is_valid_date(start, end): return
    display_greeting(
        image_name="holiday_coffee.jpg",
        title_text="Happy National Coffee Day!"
    )

def greeting_pizza():
    """Display National Pizza Day greeting."""
    year = datetime.datetime.now().year
    start, end = HolidayDateChecker.get_pizza_day_dates(year)
    if not HolidayDateChecker.is_valid_date(start, end): return
    display_greeting(
        image_name="holiday_pizza.jpg",
        title_text="Happy National Pizza Day!"
    )

def greeting_duckie():
    """Display Rubber Duckie Day greeting."""
    year = datetime.datetime.now().year
    start, end = HolidayDateChecker.get_duckie_day_dates(year)
    if not HolidayDateChecker.is_valid_date(start, end): return
    display_greeting(
        image_name=["duck.png", "duck_pop_green_bg.png"],
        title_text="Happy Rubber Duckie Day!",
        sound_file="sound_effect_duck.wav"
    )

def greeting_mario():
    """Display Mario Day greeting."""
    year = datetime.datetime.now().year
    start, end = HolidayDateChecker.get_mario_day_dates(year)
    if not HolidayDateChecker.is_valid_date(start, end): return
    display_greeting(
        image_name="holiday_mario.jpg",
        title_text="It's Mario Day! (Mar10)",
        sound_file="sound_effect_mario_powerup.wav"
    )

def greeting_hobbit():
    """Display Hobbit Day greeting."""
    year = datetime.datetime.now().year
    start, end = HolidayDateChecker.get_hobbit_day_dates(year)
    if not HolidayDateChecker.is_valid_date(start, end): return
    display_greeting(
        image_name="holiday_hobbit.jpg",
        title_text="Happy Hobbit Day!",
        md_text="## In a hole in the ground there lived a hobbit..."
    )

def greeting_ninja():
    """Display Day of the Ninja greeting."""
    year = datetime.datetime.now().year
    start, end = HolidayDateChecker.get_ninja_day_dates(year)
    if not HolidayDateChecker.is_valid_date(start, end): return
    display_greeting(
        image_name="holiday_ninja.jpg",
        title_text="Happy Day of the Ninja!",
        md_text="## ..."
    )


if __name__ == "__main__":
    festival_greeting()
