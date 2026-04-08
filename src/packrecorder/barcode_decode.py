"""pyzbar decode on BGR frames — dùng chung ScanWorker và tiến trình scanner (không Qt)."""

from __future__ import annotations

import packrecorder.opencv_video  # noqa: F401 — OPENCV_* env + log trước khi nạp cv2

import cv2

try:
    from pyzbar.pyzbar import ZBarSymbol, decode as zbar_decode
except ImportError:
    ZBarSymbol = None  # type: ignore[misc, assignment]
    zbar_decode = None  # type: ignore[misc, assignment]

_ZBAR_SCAN_SYMS: tuple = ()
if ZBarSymbol is not None:
    _ZBAR_SCAN_SYMS = (
        ZBarSymbol.QRCODE,
        ZBarSymbol.SQCODE,
        ZBarSymbol.CODE128,
        ZBarSymbol.CODE39,
        ZBarSymbol.CODE93,
        ZBarSymbol.EAN13,
        ZBarSymbol.EAN8,
        ZBarSymbol.EAN5,
        ZBarSymbol.EAN2,
        ZBarSymbol.UPCA,
        ZBarSymbol.UPCE,
        ZBarSymbol.CODABAR,
        ZBarSymbol.I25,
        ZBarSymbol.PDF417,
        ZBarSymbol.DATABAR,
        ZBarSymbol.DATABAR_EXP,
    )


def _zbar_type_str(obj: object) -> str:
    t = getattr(obj, "type", b"")
    if isinstance(t, bytes):
        return t.decode("ascii", errors="replace").upper()
    return str(t).upper()


def _is_qr_like(obj: object) -> bool:
    name = _zbar_type_str(obj)
    return name in ("QRCODE", "SQCODE")


def sort_zbar_results_qr_first(results: list) -> list:
    """Ổn định thứ tự: QR trước, còn lại theo type."""
    return sorted(results, key=lambda o: (0 if _is_qr_like(o) else 1, _zbar_type_str(o)))


def decode_barcodes_bgr(bgr: object) -> list:
    """
    pyzbar trên BGR + thử thêm grayscale; gộp kết quả, trùng data thì giữ bản QR nếu có.
    """
    if zbar_decode is None or not _ZBAR_SCAN_SYMS:
        return []
    acc: list = []
    acc.extend(zbar_decode(bgr, symbols=_ZBAR_SCAN_SYMS) or [])
    try:
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        acc.extend(zbar_decode(gray, symbols=_ZBAR_SCAN_SYMS) or [])
    except Exception:
        pass
    by_data: dict[bytes, object] = {}
    for o in acc:
        try:
            d = o.data
        except Exception:
            continue
        if d not in by_data:
            by_data[d] = o
        elif _is_qr_like(o) and not _is_qr_like(by_data[d]):
            by_data[d] = o
    return sort_zbar_results_qr_first(list(by_data.values()))
