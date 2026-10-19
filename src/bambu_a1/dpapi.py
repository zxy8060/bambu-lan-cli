"""Windows CurrentUser protection. No plaintext fallback or export API."""

import ctypes
from ctypes import wintypes as w
import hashlib
import os


class Blob(ctypes.Structure):
    _fields_ = [("size", w.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]


def _blob(data):
    buffer = ctypes.create_string_buffer(data)
    return Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))), buffer


def protect(data, target, decrypt=False):
    if os.name != "nt":
        raise RuntimeError(
            "Credential storage and signed dispatch currently require Windows"
        )
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    inp, inp_buffer = _blob(data)
    entropy, entropy_buffer = _blob(
        hashlib.sha256(("BambuA1Cli-v1:" + target).encode()).digest()
    )
    out = Blob()
    if decrypt:
        fn = crypt.CryptUnprotectData
        fn.argtypes = [
            ctypes.POINTER(Blob),
            ctypes.c_void_p,
            ctypes.POINTER(Blob),
            ctypes.c_void_p,
            ctypes.c_void_p,
            w.DWORD,
            ctypes.POINTER(Blob),
        ]
        args = [
            ctypes.byref(inp),
            None,
            ctypes.byref(entropy),
            None,
            None,
            1,
            ctypes.byref(out),
        ]
    else:
        fn = crypt.CryptProtectData
        fn.argtypes = [
            ctypes.POINTER(Blob),
            w.LPCWSTR,
            ctypes.POINTER(Blob),
            ctypes.c_void_p,
            ctypes.c_void_p,
            w.DWORD,
            ctypes.POINTER(Blob),
        ]
        args = [
            ctypes.byref(inp),
            "Bambu A1 CLI application credential",
            ctypes.byref(entropy),
            None,
            None,
            1,
            ctypes.byref(out),
        ]
    fn.restype = w.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    if not fn(*args):
        raise RuntimeError("Windows CurrentUser credential protection failed")
    try:
        return ctypes.string_at(out.data, out.size)
    finally:
        ctypes.memset(out.data, 0, out.size)
        kernel.LocalFree(out.data)
