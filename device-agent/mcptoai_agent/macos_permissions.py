from __future__ import annotations
import ctypes, ctypes.util, platform

def _cg():
    if platform.system()!='Darwin': return None
    p=ctypes.util.find_library('CoreGraphics') or '/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics'
    return ctypes.CDLL(p)

def screen_status()->str:
    cg=_cg()
    if not cg: return 'unsupported'
    cg.CGPreflightScreenCaptureAccess.restype=ctypes.c_bool
    return 'granted' if cg.CGPreflightScreenCaptureAccess() else 'not-granted'

def request_screen()->bool:
    cg=_cg()
    if not cg: return False
    cg.CGRequestScreenCaptureAccess.restype=ctypes.c_bool
    return bool(cg.CGRequestScreenCaptureAccess())
