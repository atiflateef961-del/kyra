from __future__ import annotations

import ctypes
import os
import uuid
from ctypes import wintypes


class AudioEndpointError(RuntimeError):
    """Raised when the Windows default output volume cannot be read or changed."""


class _Guid(ctypes.Structure):
    _fields_ = (
        ("data1", ctypes.c_uint32),
        ("data2", ctypes.c_uint16),
        ("data3", ctypes.c_uint16),
        ("data4", ctypes.c_ubyte * 8),
    )

    @classmethod
    def parse(cls, value: str) -> "_Guid":
        return cls.from_buffer_copy(uuid.UUID(value).bytes_le)


class WindowsCoreAudioVolume:
    """Reads and adjusts the default Windows render endpoint through Core Audio."""

    _MMDEVICE_ENUMERATOR = "BCDE0395-E52F-467C-8E3D-C4579291692E"
    _IMMDEVICE_ENUMERATOR = "A95664D2-9614-4F35-A746-DE8DB63617E6"
    _IMMDEVICE = "D666063F-1587-4E43-81F1-B948E807363F"
    _IAUDIO_ENDPOINT_VOLUME = "5CDF2C82-841E-4546-9722-0CF74078229A"
    _CLSCTX_ALL = 0x17

    def get_volume(self) -> float:
        return self._with_endpoint(self._read_volume)

    def set_volume(self, value: float) -> float:
        if not 0 <= value <= 1:
            raise ValueError("Windows endpoint volume must be between 0 and 1.")

        def set_and_read(endpoint: ctypes.c_void_p) -> float:
            self._set_volume(endpoint, value)
            actual = self._read_volume(endpoint)
            if abs(actual - value) > 0.002:
                raise AudioEndpointError("Windows did not apply the requested output volume.")
            return actual

        return self._with_endpoint(set_and_read)

    def adjust_volume(self, delta: float) -> tuple[float, float]:
        if delta == 0 or abs(delta) > 1:
            raise ValueError("Volume adjustment must be non-zero and no greater than 1.")

        def adjust(endpoint: ctypes.c_void_p) -> tuple[float, float]:
            before = self._read_volume(endpoint)
            target = min(1.0, max(0.0, before + delta))
            if target == before:
                raise AudioEndpointError("Windows output volume is already at that limit.")
            muted = self._is_muted(endpoint)
            self._set_volume(endpoint, target)
            if delta > 0 and muted:
                self._set_muted(endpoint, False)
            after = self._read_volume(endpoint)
            if abs(after - target) > 0.002 or (delta > 0 and muted and self._is_muted(endpoint)):
                raise AudioEndpointError("Windows did not apply the requested output volume.")
            return before, after

        return self._with_endpoint(adjust)

    def _with_endpoint(self, operation):
        if os.name != "nt":
            raise AudioEndpointError("Windows Core Audio is only available on Windows.")

        ole32 = ctypes.WinDLL("ole32", use_last_error=True)
        ole32.CoInitializeEx.argtypes = (ctypes.c_void_p, wintypes.DWORD)
        ole32.CoInitializeEx.restype = ctypes.c_long
        ole32.CoUninitialize.argtypes = ()
        ole32.CoCreateInstance.argtypes = (
            ctypes.POINTER(_Guid), ctypes.c_void_p, wintypes.DWORD,
            ctypes.POINTER(_Guid), ctypes.POINTER(ctypes.c_void_p),
        )
        ole32.CoCreateInstance.restype = ctypes.c_long

        init_result = ole32.CoInitializeEx(None, 0x2)  # COINIT_APARTMENTTHREADED
        changed_mode = init_result == -2147417850  # RPC_E_CHANGED_MODE; this thread already has a COM apartment.
        self._check_hresult(init_result, "initialize COM")
        enumerator = ctypes.c_void_p()
        device = ctypes.c_void_p()
        endpoint = ctypes.c_void_p()
        try:
            self._check_hresult(
                ole32.CoCreateInstance(
                    ctypes.byref(_Guid.parse(self._MMDEVICE_ENUMERATOR)), None,
                    self._CLSCTX_ALL, ctypes.byref(_Guid.parse(self._IMMDEVICE_ENUMERATOR)),
                    ctypes.byref(enumerator),
                ),
                "create audio device enumerator",
            )
            self._check_hresult(
                self._method(enumerator, 4, ctypes.c_long, ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p))(
                    enumerator, 0, 1, ctypes.byref(device),
                ),
                "find default audio output",
            )
            self._check_hresult(
                self._method(
                    device, 3, ctypes.c_long, ctypes.POINTER(_Guid), wintypes.DWORD,
                    ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p),
                )(
                    device, ctypes.byref(_Guid.parse(self._IAUDIO_ENDPOINT_VOLUME)),
                    self._CLSCTX_ALL, None, ctypes.byref(endpoint),
                ),
                "open default audio output",
            )
            return operation(endpoint)
        finally:
            self._release(endpoint)
            self._release(device)
            self._release(enumerator)
            if not changed_mode:
                ole32.CoUninitialize()

    @classmethod
    def _read_volume(cls, endpoint: ctypes.c_void_p) -> float:
        level = ctypes.c_float()
        cls._check_hresult(
            cls._method(endpoint, 9, ctypes.c_long, ctypes.POINTER(ctypes.c_float))(endpoint, ctypes.byref(level)),
            "read output volume",
        )
        return float(level.value)

    @classmethod
    def _set_volume(cls, endpoint: ctypes.c_void_p, value: float) -> None:
        context = _Guid()
        cls._check_hresult(
            cls._method(
                endpoint, 7, ctypes.c_long, ctypes.c_float, ctypes.POINTER(_Guid),
            )(endpoint, value, ctypes.byref(context)),
            "set output volume",
        )

    @classmethod
    def _is_muted(cls, endpoint: ctypes.c_void_p) -> bool:
        muted = wintypes.BOOL()
        cls._check_hresult(
            cls._method(endpoint, 15, ctypes.c_long, ctypes.POINTER(wintypes.BOOL))(endpoint, ctypes.byref(muted)),
            "read mute state",
        )
        return bool(muted.value)

    @classmethod
    def _set_muted(cls, endpoint: ctypes.c_void_p, muted: bool) -> None:
        context = _Guid()
        cls._check_hresult(
            cls._method(
                endpoint, 14, ctypes.c_long, wintypes.BOOL, ctypes.POINTER(_Guid),
            )(endpoint, muted, ctypes.byref(context)),
            "update mute state",
        )

    @staticmethod
    def _method(interface, index: int, result_type, *argument_types):
        vtable = ctypes.cast(interface, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        return ctypes.WINFUNCTYPE(result_type, ctypes.c_void_p, *argument_types)(vtable[index])

    @classmethod
    def _release(cls, interface: ctypes.c_void_p) -> None:
        if interface:
            cls._method(interface, 2, ctypes.c_ulong)(interface)

    @staticmethod
    def _check_hresult(result: int, operation: str) -> None:
        if result < 0:
            raise AudioEndpointError(f"Windows could not {operation} (HRESULT 0x{result & 0xFFFFFFFF:08X}).")
