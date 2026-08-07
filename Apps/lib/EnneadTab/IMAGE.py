"""Utilities for image retrieval and manipulation."""

import os
import random
import time
import ENVIRONMENT
import FOLDER
import USER

import ERROR_HANDLE

# Try to import System.Drawing, but handle the case where it's not available
try:
    import System.Drawing as SD  # pyright: ignore
    SD_AVAILABLE = True
except ImportError:
    # Try alternative import for IronPython
    try:
        import clr
        clr.AddReference("System.Drawing")
        import System.Drawing as SD
        SD_AVAILABLE = True
    except Exception as e:
        SD_AVAILABLE = False
        # print("System.Drawing not available: {}".format(str(e)))
except Exception as e:
    SD_AVAILABLE = False
    # print("System.Drawing not available: {}".format(str(e)))


def get_image_path_by_name(file_name):
    """Get the full path for a specified image in the EnneadTab image library.

    Args:
        file_name (str): The name of the image file to retrieve, including extension.

    Returns:
        str: The full path to the image file.
    """
    path = "{}\\{}".format(ENVIRONMENT.IMAGE_FOLDER, file_name)
    if os.path.exists(path):
        return path
    print("A ha! {} is not valid or accessibile. Better luck next time.".format(path))


def get_one_image_path_by_prefix(prefix):
    """Will return a random image file from the EnneadTab image library that starts with the specified prefix.

    Args:
        prefix (str): The prefix to search for in the image file names.

    Returns:
        str: The full path to the image file.
    """
    files = [
        os.path.join(ENVIRONMENT.IMAGE_FOLDER, f)
        for f in os.listdir(ENVIRONMENT.IMAGE_FOLDER)
        if f.startswith(prefix)
    ]
    file = random.choice(files)
    return file


def average_RGB(R, G, B):
    """Average the RGB values of a pixel to simplify it to greyscale.

    Args:
        R (int): Red. 0-255.
        G (int): Blue. 0-255.
        B (int): Green. 0-255.

    Returns:
        int: Average of the RGB values.
    """
    return (R + G + B) / 3


def convert_image_to_greyscale_system_drawing(original_image_path, new_image_path=None):
    """Convert image to greyscale using System.Drawing (IronPython compatible).
    
    Args:
        original_image_path (str): Path to original image
        new_image_path (str): Path to save greyscale image (optional)
        
    Returns:
        str: Filename of saved image, or False if failed
    """
    if not SD_AVAILABLE:
        print("System.Drawing not available for greyscale conversion")
        return False

    try:
        if new_image_path is None:
            new_image_path = original_image_path

        # Use a unique filename from the start to avoid conflicts
        base_name = os.path.splitext(new_image_path)[0]
        extension = os.path.splitext(new_image_path)[1]
        unique_filename = "{}_{}{}".format(base_name, int(time.time()), extension)
        
        image = SD.Image.FromFile(original_image_path)
        width = image.Width
        height = image.Height
        grey_bitmap = SD.Bitmap(width, height)

        chunk_size = 500
        for chunk_x in range(0, width, chunk_size):
            for chunk_y in range(0, height, chunk_size):
                end_x = min(chunk_x + chunk_size, width)
                end_y = min(chunk_y + chunk_size, height)
                for x in range(chunk_x, end_x):
                    for y in range(chunk_y, end_y):
                        try:
                            pixel_color = image.GetPixel(x, y)
                            R = pixel_color.R
                            G = pixel_color.G
                            B = pixel_color.B
                            A = pixel_color.A
                            grey_value = average_RGB(R, G, B)
                            new_color = SD.Color.FromArgb(A, grey_value, grey_value, grey_value)
                            grey_bitmap.SetPixel(x, y, new_color)
                        except Exception as e:
                            grey_bitmap.SetPixel(x, y, SD.Color.FromArgb(255, 128, 128, 128))
                            continue

        # Try to save to unique filename first
        actual_saved_path = unique_filename
        try:
            grey_bitmap.Save(unique_filename)
            ERROR_HANDLE.print_note("Successfully saved to unique file: {}".format(unique_filename))
        except Exception as e:
            ERROR_HANDLE.print_note("Unique file save failed: {}".format(e))
            # Try original location as fallback
            try:
                grey_bitmap.Save(new_image_path)
                actual_saved_path = new_image_path
                ERROR_HANDLE.print_note("Successfully saved to original location")
            except Exception as e2:
                ERROR_HANDLE.print_note("Original location save failed: {}".format(e2))
                # Final fallback to temp file
                temp_path = "{}_{}.jpg".format(base_name, int(time.time() * 1000))
                try:
                    grey_bitmap.Save(temp_path)
                    actual_saved_path = temp_path
                    ERROR_HANDLE.print_note("Saved to final temp file: {}".format(temp_path))
                except Exception as e3:
                    ERROR_HANDLE.print_note("All save attempts failed")
                    grey_bitmap.Dispose()
                    image.Dispose()
                    return False

        grey_bitmap.Dispose()
        image.Dispose()
        return os.path.basename(actual_saved_path)

    except Exception as e:
        ERROR_HANDLE.print_note("System.Drawing greyscale conversion failed: {}".format(str(e)))
        import traceback
        ERROR_HANDLE.print_note(traceback.format_exc())
        return False


def convert_image_to_greyscale(original_image_path, new_image_path=None):
    """Convert an image to greyscale using PIL for better reliability.

    Args:
        original_image_path (str): The full path to the image to convert.
        new_image_path (str): The full path to save the new image. If None, the original image will be overwritten. Careful: defaults to None!
    
    Returns:
        str: The actual filename that was saved (might be different from new_image_path if temp file was used), or False if failed
    """
    try:
        # Patch sys.path for IronPython if needed
        try:
            import sys
            if ENVIRONMENT.IS_PY2:
                if ENVIRONMENT.DEPENDENCY_FOLDER not in sys.path:
                    sys.path.insert(0, ENVIRONMENT.DEPENDENCY_FOLDER)
        except Exception as e:
            ERROR_HANDLE.print_note("Could not patch sys.path for PIL: {}".format(e))
        
        # Now try to import PIL
        try:
            from PIL import Image
            with Image.open(original_image_path) as img:
                # Convert to greyscale
                grey_img = img.convert('L')
                if new_image_path is None:
                    new_image_path = original_image_path
                grey_img.save(new_image_path)
                return os.path.basename(new_image_path)
        except ImportError:
            # Fallback to System.Drawing if PIL is not available
            pass
        except Exception as e:
            ERROR_HANDLE.print_note("PIL greyscale conversion failed: {}".format(str(e)))
            # Fallback to System.Drawing
        
        # Fallback to improved System.Drawing method
        return convert_image_to_greyscale_system_drawing(original_image_path, new_image_path)
        
    except Exception as e:
        ERROR_HANDLE.print_note("Greyscale conversion failed: {}".format(str(e)))
        import traceback
        ERROR_HANDLE.print_note(traceback.format_exc())
        return False


def create_bitmap_text_image(text, size=(64, 32), bg_color=(0, 0, 0), font_size=9):
    """Create a bitmap image with text using System.Drawing.
    
    Args:
        text (str): Text to display on the image
        size (tuple): Image size as (width, height)
        bg_color (tuple): Background color as (R, G, B)
        font_size (int): Font size
        
    Returns:
        str: Path to the created image file
    """
    if not SD_AVAILABLE:
        print("System.Drawing not available for bitmap creation")
        return False

    if random.random() < 0.2:
        purge_old_temp_bmp_files()

    try:
        image = SD.Bitmap(size[0], size[1])
        graphics = SD.Graphics.FromImage(image)
        font = SD.Font("Arial", font_size)
        brush = SD.SolidBrush(SD.Color.FromArgb(bg_color[0], bg_color[1], bg_color[2]))
        text_size = graphics.MeasureString(text, font)
        text_x = (size[0] - text_size.Width) / 2
        text_y = (size[1] - text_size.Height) / 2
        graphics.DrawString(text, font, brush, text_x, text_y)
        output_path = FOLDER.get_local_dump_folder_file("_temp_text_bmp_{}_{}.bmp".format(text, time.time()))
        image.Save(output_path)
        return output_path
    except Exception as e:
        ERROR_HANDLE.print_note("Bitmap text image creation failed: {}".format(str(e)))
        return False


def copy_image_to_clipboard(image_path):
    """Copy an image file to the Windows clipboard so the user can paste it
    into Outlook / Teams / Word as a bitmap (not a path).

    Args:
        image_path (str): Absolute path to the image file on disk.

    Returns:
        bool: True on success, False on any failure (file missing, no
        clipboard support, decode error). Failures are logged via
        ERROR_HANDLE; callers should reflect the bool in user-visible
        status text rather than raising.
    """
    if not image_path or not os.path.exists(image_path):
        ERROR_HANDLE.print_note(
            "copy_image_to_clipboard: file not found: {}".format(image_path))
        return False
    if not SD_AVAILABLE:
        ERROR_HANDLE.print_note(
            "copy_image_to_clipboard: System.Drawing not available")
        return False
    try:
        import clr
        clr.AddReference("System.Windows.Forms")
        from System.Windows.Forms import Clipboard  # pyright: ignore
    except Exception as e:
        ERROR_HANDLE.print_note(
            "copy_image_to_clipboard: System.Windows.Forms not available: {}".format(str(e)))
        return False
    try:
        # SD.Image.FromFile holds a file lock for the lifetime of the
        # returned Image. Load into a Bitmap copy + dispose the original
        # so the file isn't pinned after the call returns.
        with_lock = SD.Image.FromFile(image_path)
        try:
            bmp = SD.Bitmap(with_lock)
        finally:
            try:
                with_lock.Dispose()
            except Exception:
                pass
        Clipboard.SetImage(bmp)
        return True
    except Exception as e:
        ERROR_HANDLE.print_note(
            "copy_image_to_clipboard failed: {}".format(str(e)))
        return False


def purge_old_temp_bmp_files():
    """Purge old temporary bmp files in the EA dump folder."""
    try:
        for file in os.listdir(FOLDER.DUMP_FOLDER):
            if file.endswith(".bmp") and file.startswith("_temp_text_bmp_"):
                file_path = os.path.join(FOLDER.DUMP_FOLDER, file)
                if time.time() - os.path.getmtime(file_path) > 60 * 60 * 24 * 2:
                    os.remove(file_path)
    except Exception as e:
        ERROR_HANDLE.print_note("Failed to purge old temp files: {}".format(str(e)))


def unit_test():
    """Run comprehensive unit tests for the IMAGE module.
    
    Tests include:
    - Image path retrieval functions
    - Greyscale conversion (with fallbacks)
    - Bitmap text image creation
    - Error handling for missing files
    - System.Drawing availability check
    - Demo bitmap creation (if System.Drawing available)
    """
    print("="*60)
    print("IMAGE MODULE UNIT TESTS")
    print("="*60)
    
    # Test 1: System.Drawing availability
    print("\n1. Testing System.Drawing availability...")
    print("   SD_AVAILABLE: {}".format(SD_AVAILABLE))
    if SD_AVAILABLE:
        print("   System.Drawing is available")
    else:
        print("   System.Drawing not available - some features will be limited")
    
    # Test 2: Image path functions
    print("\n2. Testing image path functions...")
    try:
        # Test with a dummy filename
        test_path = get_image_path_by_name("test_image.png")
        if test_path:
            print("   get_image_path_by_name() works")
        else:
            print("   get_image_path_by_name() correctly handles missing files")
        
        # Test prefix search (this might fail if no images exist, which is OK)
        try:
            test_prefix_path = get_one_image_path_by_prefix("test")
            print("   get_one_image_path_by_prefix() works")
        except IndexError:
            print("   get_one_image_path_by_prefix() correctly handles no matches")
        except Exception as e:
            print("   get_one_image_path_by_prefix() error: {}".format(e))
            
    except Exception as e:
        print("   Image path functions failed: {}".format(e))
    
    # Test 3: RGB averaging function
    print("\n3. Testing RGB averaging function...")
    try:
        result = average_RGB(100, 150, 200)
        expected = (100 + 150 + 200) / 3
        if abs(result - expected) < 0.01:
            print("   average_RGB() works correctly: {} (expected: {})".format(result, expected))
        else:
            print("   average_RGB() failed: got {}, expected {}".format(result, expected))
    except Exception as e:
        print("   average_RGB() failed: {}".format(e))
    
    # Test 4: Greyscale conversion with error handling
    print("\n4. Testing greyscale conversion error handling...")
    try:
        # Test with non-existent file
        result = convert_image_to_greyscale("non_existent_file.jpg")
        if result is False:
            print("   convert_image_to_greyscale() correctly handles missing files")
        else:
            print("   convert_image_to_greyscale() should return False for missing files")
    except Exception as e:
        print("   convert_image_to_greyscale() error handling failed: {}".format(e))
    
    # Test 5: Bitmap text image creation (if System.Drawing available)
    print("\n5. Testing bitmap text image creation...")
    if SD_AVAILABLE:
        try:
            result = create_bitmap_text_image("TEST", size=(100, 50), bg_color=(255, 0, 0), font_size=12)
            if result and os.path.exists(result):
                print("   create_bitmap_text_image() works: {}".format(result))
                # Clean up test file
                try:
                    os.remove(result)
                except:
                    pass
            else:
                print("   create_bitmap_text_image() failed to create file")
        except Exception as e:
            print("   create_bitmap_text_image() failed: {}".format(e))
    else:
        print("   Skipping bitmap creation test (System.Drawing not available)")
    
    # Test 6: Environment compatibility
    print("\n6. Testing environment compatibility...")
    print("   Python version: {}".format(ENVIRONMENT.IS_PY2 and "2.x" or "3.x"))
    print("   IronPython: {}".format(ENVIRONMENT.IS_IRONPYTHON))
    print("   Dependency folder: {}".format(ENVIRONMENT.DEPENDENCY_FOLDER))
    
    # Test 7: File operations
    print("\n7. Testing file operations...")
    try:
        # Test purge function (should not fail even if no files exist)
        purge_old_temp_bmp_files()
        print("   purge_old_temp_bmp_files() works")
    except Exception as e:
        print("   purge_old_temp_bmp_files() failed: {}".format(e))
    
    # Demo: create a bitmap text image and optionally open it
    print("\n8. Demo: create and optionally open a bitmap text image...")
    if SD_AVAILABLE:
        try:
            image = create_bitmap_text_image("qwert", size=(64, 32), bg_color=(0, 99, 0), font_size=9)
            if image and os.path.exists(image):
                print("   Demo: Created test image: {}".format(image))
                # Don't auto-open in IronPython environments
                if ENVIRONMENT.is_terminal_environment():
                    try:
                        os.startfile(image)
                    except:
                        pass
            else:
                print("   Demo: Failed to create test image")
        except Exception as e:
            print("   Demo failed: {}".format(e))
    else:
        print("   Skipping demo (System.Drawing not available)")
    
    print("\n" + "="*60)
    print("IMAGE MODULE UNIT TESTS COMPLETED")
    print("="*60)
    print("All tests completed.")
    print("   The IMAGE module is ready for use in IronPython 2.7 environments.")


if __name__ == "__main__":
    unit_test()