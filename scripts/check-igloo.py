#!/usr/bin/env python3
"""Check the actual Icecast libigloo runtime, not just headers/dpkg metadata."""
import ctypes
import sys


def main():
    try:
        library = ctypes.CDLL('libigloo.so.0')
        version = library.igloo_version_get
        version.argtypes = [ctypes.POINTER(ctypes.c_char_p),
                            *([ctypes.POINTER(ctypes.c_int)] * 3)]
        version.restype = ctypes.c_int
        label = ctypes.c_char_p()
        numbers = [ctypes.c_int() for _ in range(3)]
        code = version(ctypes.byref(label), *(ctypes.byref(number) for number in numbers))
        actual = tuple(number.value for number in numbers)
        if code or actual < (0, 9, 4):
            raise ValueError('loaded version ' + '.'.join(map(str, actual)))
        print('Loaded libigloo runtime ' + '.'.join(map(str, actual)))
        return 0
    except (OSError, AttributeError, ValueError) as error:
        print('Icecast needs libigloo runtime >= 0.9.4: ' + str(error) +
              '. Check apt-cache policy libigloo-dev libigloo0 and dpkg-query -S '
              '"*/libigloo.so.0*"; an older libigloo0t64 may own the shared library. '
              'Resolve the conflicting runtime before retrying; no build or activation performed.',
              file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
