import numpy as np

from packrecorder.pip_composite import composite_pip_bgr


def test_composite_keeps_main_shape():
    main = np.zeros((1080, 1920, 3), dtype=np.uint8)
    sub = np.ones((480, 640, 3), dtype=np.uint8) * 200
    out = composite_pip_bgr(main, sub, sub_max_width=320, margin=10)
    assert out.shape == main.shape
    assert out[100, 100, 0] == 0
    br = out[-20, -20]
    assert br[0] > 100
