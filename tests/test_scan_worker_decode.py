"""decode_barcodes_bgr / sort_zbar_results_qr_first (không cần camera)."""

from __future__ import annotations

from unittest.mock import MagicMock

from packrecorder.barcode_decode import sort_zbar_results_qr_first


def test_sort_zbar_results_qr_first():
    qr = MagicMock()
    qr.type = b"QRCODE"
    qr.data = b"qr1"
    c128 = MagicMock()
    c128.type = b"CODE128"
    c128.data = b"bar1"
    out = sort_zbar_results_qr_first([c128, qr])
    assert out[0] is qr
    assert out[1] is c128


def test_sort_prefers_qr_before_other_1d():
    e13 = MagicMock()
    e13.type = "EAN13"
    e13.data = b"x"
    qr = MagicMock()
    qr.type = "QRCODE"
    qr.data = b"y"
    out = sort_zbar_results_qr_first([e13, qr])
    assert out[0] is qr
