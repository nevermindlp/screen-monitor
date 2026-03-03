"""
macOS-only: capture screen region at native (Retina) resolution.

Uses CoreGraphics with options that do NOT include kCGWindowImageNominalResolution,
so the same logical region returns 2x pixel dimensions on Retina displays.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import sys
from ctypes import POINTER, Structure, c_double, c_float, c_ubyte, c_uint32, c_void_p
from platform import mac_ver
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from .capture import CaptureRegion

# CoreGraphics options: without NominalResolution we get backing (2x) pixels on Retina
kCGWindowImageBoundsIgnoreFraming = 1 << 0
kCGWindowImageShouldBeOpaque = 1 << 1
# kCGWindowImageNominalResolution = 1 << 4  # omit this to get native resolution
IMAGE_OPTIONS_HD = kCGWindowImageBoundsIgnoreFraming | kCGWindowImageShouldBeOpaque

MAC_VERSION_CATALINA = 10.16


def _cgfloat() -> type[c_double | c_float]:
    return c_double if sys.maxsize > 2**32 else c_float


class CGPoint(Structure):
    _fields_ = (("x", _cgfloat()), ("y", _cgfloat()))


class CGSize(Structure):
    _fields_ = (("width", _cgfloat()), ("height", _cgfloat()))


class CGRect(Structure):
    _fields_ = (("origin", CGPoint), ("size", CGSize))


def _load_core_graphics() -> ctypes.CDLL:
    version = float(".".join(mac_ver()[0].split(".")[:2]))
    if version < MAC_VERSION_CATALINA:
        path = ctypes.util.find_library("CoreGraphics")
    else:
        path = "/System/Library/Frameworks/CoreGraphics.framework/Versions/Current/CoreGraphics"
    if not path:
        raise RuntimeError("CoreGraphics library not found")
    return ctypes.cdll.LoadLibrary(path)


_core: ctypes.CDLL | None = None


def _get_core() -> ctypes.CDLL:
    global _core
    if _core is None:
        _core = _load_core_graphics()
        _core.CGWindowListCreateImage.argtypes = [CGRect, c_uint32, c_uint32, c_uint32]
        _core.CGWindowListCreateImage.restype = c_void_p
        _core.CGImageGetWidth.argtypes = [c_void_p]
        _core.CGImageGetWidth.restype = ctypes.c_int
        _core.CGImageGetHeight.argtypes = [c_void_p]
        _core.CGImageGetHeight.restype = ctypes.c_int
        _core.CGImageGetBitsPerPixel.argtypes = [c_void_p]
        _core.CGImageGetBitsPerPixel.restype = ctypes.c_int
        _core.CGImageGetBytesPerRow.argtypes = [c_void_p]
        _core.CGImageGetBytesPerRow.restype = ctypes.c_int
        _core.CGImageGetDataProvider.argtypes = [c_void_p]
        _core.CGImageGetDataProvider.restype = c_void_p
        _core.CGDataProviderCopyData.argtypes = [c_void_p]
        _core.CGDataProviderCopyData.restype = c_void_p
        _core.CFDataGetBytePtr.argtypes = [c_void_p]
        _core.CFDataGetBytePtr.restype = c_void_p
        _core.CFDataGetLength.argtypes = [c_void_p]
        _core.CFDataGetLength.restype = ctypes.c_uint64
        _core.CGDataProviderRelease.argtypes = [c_void_p]
        _core.CGDataProviderRelease.restype = None
        _core.CFRelease.argtypes = [c_void_p]
        _core.CFRelease.restype = None
    return _core


def grab_region_bgr(region: "CaptureRegion") -> np.ndarray:
    """
    Capture the given logical region at native (Retina) resolution.
    Returns BGR image as numpy array (uint8), same contract as RegionCapturer.grab_bgr.
    """
    core = _get_core()
    rect = CGRect(
        (float(region.x), float(region.y)),
        (float(region.w), float(region.h)),
    )
    # 1 = kCGWindowListOptionOnScreenOnly, 0 = capture all windows
    image_ref = core.CGWindowListCreateImage(rect, 1, 0, IMAGE_OPTIONS_HD)
    if not image_ref:
        raise RuntimeError("CGWindowListCreateImage failed")

    width = core.CGImageGetWidth(image_ref)
    height = core.CGImageGetHeight(image_ref)
    bytes_per_row = core.CGImageGetBytesPerRow(image_ref)
    bits_per_pixel = core.CGImageGetBitsPerPixel(image_ref)
    bytes_per_pixel = (bits_per_pixel + 7) // 8

    prov = core.CGImageGetDataProvider(image_ref)
    copy_data = core.CGDataProviderCopyData(prov)
    try:
        data_ref = core.CFDataGetBytePtr(copy_data)
        buf_len = core.CFDataGetLength(copy_data)
        raw = ctypes.cast(data_ref, POINTER(c_ubyte * buf_len))
        data = bytearray(raw.contents)
    finally:
        if prov:
            core.CGDataProviderRelease(prov)
        if copy_data:
            core.CFRelease(copy_data)

    # Remove row padding if any
    if width * bytes_per_pixel != bytes_per_row:
        cropped = bytearray()
        for row in range(height):
            start = row * bytes_per_row
            end = start + width * bytes_per_pixel
            cropped.extend(data[start:end])
        data = cropped

    # CoreGraphics gives ARGB (or RGBA); convert to BGR for OpenCV
    arr = np.frombuffer(data, dtype=np.uint8)
    if bytes_per_pixel == 4:
        bgra = arr.reshape((height, width, 4))
        # On macOS, CGWindowListCreateImage commonly returns 32-bit little-endian BGRA.
        # Return BGR for OpenCV consumers.
        return np.ascontiguousarray(bgra[:, :, :3])
    if bytes_per_pixel == 3:
        arr = arr.reshape((height, width, 3))
        return np.ascontiguousarray(arr[:, :, ::-1])  # RGB -> BGR
    raise RuntimeError(f"Unsupported bits per pixel: {bits_per_pixel}")
