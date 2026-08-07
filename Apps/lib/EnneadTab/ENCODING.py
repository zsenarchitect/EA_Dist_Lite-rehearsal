# -*- coding: utf-8 -*-
"""
EnneadTab Encoding Utilities

Provides comprehensive UTF-8 encoding support for Windows systems to prevent
codepage issues when working with international characters and file operations.

Usage:
    Import this module at the top of any script that handles text files or
    prints international characters:
    
    from EnneadTab import ENCODING
    ENCODING.fix_windows_encoding()

Features:
    - Automatic UTF-8 configuration for stdout/stderr/stdin
    - Environment variable setup for subprocess calls
    - Safe fallbacks for different Python versions
    - IronPython and CPython compatibility
"""

import sys
import os


def fix_windows_encoding():
    """
    Configure UTF-8 encoding for the current Python process on Windows.
    
    This function should be called at the start of any script that:
    - Reads/writes files with international characters
    - Prints non-ASCII text to console
    - Spawns subprocesses that handle text
    
    Safe to call multiple times - will skip if already configured.
    
    Returns:
        bool: True if encoding was configured successfully, False otherwise
    """
    if sys.platform != 'win32':
        return True  # Nothing to do on non-Windows platforms
    
    try:
        # Set environment variable for current process and subprocesses
        os.environ['PYTHONIOENCODING'] = 'utf-8'
        
        # Enable ANSI color support in Windows Console
        try:
            os.system('chcp 65001 > nul 2>&1')
            os.environ['ENABLE_VIRTUAL_TERMINAL_PROCESSING'] = '1'
        except Exception:
            pass  # Not critical
        
        # Reconfigure standard streams for UTF-8
        # Python 3.7+: Use reconfigure method
        if hasattr(sys.stdout, 'reconfigure'):
            if sys.stdout.encoding != 'utf-8':
                sys.stdout.reconfigure(encoding='utf-8', errors='replace')
            if sys.stderr.encoding != 'utf-8':
                sys.stderr.reconfigure(encoding='utf-8', errors='replace')
            if hasattr(sys.stdin, 'reconfigure') and sys.stdin.encoding != 'utf-8':
                sys.stdin.reconfigure(encoding='utf-8', errors='replace')
        else:
            # Fallback for Python 2.7 / IronPython / older Python 3
            import codecs
            if hasattr(sys.stdout, 'buffer') and sys.stdout.encoding != 'utf-8':
                sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'replace')
            if hasattr(sys.stderr, 'buffer') and sys.stderr.encoding != 'utf-8':
                sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'replace')
            if hasattr(sys.stdin, 'buffer') and sys.stdin.encoding != 'utf-8':
                sys.stdin = codecs.getreader('utf-8')(sys.stdin.buffer, 'replace')
        
        return True
        
    except Exception as e:
        # Print warning but don't fail
        print("Warning: Could not configure UTF-8 encoding: {}".format(str(e)))
        return False


def safe_encode(text, encoding='utf-8'):
    """
    Safely encode text to bytes, handling both Python 2 and Python 3.
    
    Args:
        text (str/unicode): Text to encode
        encoding (str): Target encoding (default: utf-8)
    
    Returns:
        bytes: Encoded text
    """
    if sys.version_info[0] >= 3:
        # Python 3
        if isinstance(text, bytes):
            return text
        return text.encode(encoding, errors='replace')
    else:
        # Python 2 / IronPython
        if isinstance(text, unicode):
            return text.encode(encoding, errors='replace')
        return text


def safe_decode(data, encoding='utf-8'):
    """
    Safely decode bytes to text, handling both Python 2 and Python 3.
    
    Args:
        data (bytes/str): Data to decode
        encoding (str): Source encoding (default: utf-8)
    
    Returns:
        str/unicode: Decoded text
    """
    if sys.version_info[0] >= 3:
        # Python 3
        if isinstance(data, str):
            return data
        return data.decode(encoding, errors='replace')
    else:
        # Python 2 / IronPython
        if isinstance(data, unicode):
            return data
        return data.decode(encoding, errors='replace')


def safe_print(*args, **kwargs):
    """
    Print function that safely handles unicode/international characters.
    
    Works around Windows console encoding issues by encoding text properly
    before printing.
    
    Args:
        *args: Values to print
        **kwargs: Keyword arguments (sep, end, file, flush)
    """
    # Extract keyword arguments with defaults
    sep = kwargs.get('sep', ' ')
    end = kwargs.get('end', '\n')
    file_obj = kwargs.get('file', sys.stdout)
    
    try:
        # Join all arguments with separator
        text = sep.join(str(arg) for arg in args) + end
        
        # Try to write directly
        file_obj.write(text)
        if kwargs.get('flush', False) and hasattr(file_obj, 'flush'):
            file_obj.flush()
    except (UnicodeEncodeError, UnicodeDecodeError):
        # Fallback: encode and decode with error handling
        try:
            encoded = text.encode(file_obj.encoding or 'utf-8', errors='replace')
            decoded = encoded.decode(file_obj.encoding or 'utf-8', errors='replace')
            file_obj.write(decoded)
            if kwargs.get('flush', False) and hasattr(file_obj, 'flush'):
                file_obj.flush()
        except Exception:
            # Last resort: ASCII-only output
            ascii_text = text.encode('ascii', errors='replace').decode('ascii')
            file_obj.write(ascii_text)
            if kwargs.get('flush', False) and hasattr(file_obj, 'flush'):
                file_obj.flush()


# Automatically fix encoding when module is imported
# Comment this line if you want manual control
fix_windows_encoding()

