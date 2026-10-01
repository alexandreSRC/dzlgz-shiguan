"""大周列国志 · 史馆 —— 左手翻实录，右手修谱牒，中间一座桥。

应用装配层在项目根的 `main.py`；本包只提供各层能力，不导入视图。
"""
from .contract import (APP_NAME, APP_VER, DEFAULT_VIEW, LAYER_NAME, VIEWS,
                       VIEW_KEYS, VIEW_LABEL, VIEW_LAYER, WINDOW_SIZE, WINDOW_TITLE)

VERSION = "2.0.0"

__all__ = ["VERSION", "APP_NAME", "APP_VER", "WINDOW_TITLE", "WINDOW_SIZE",
           "VIEWS", "VIEW_KEYS", "VIEW_LABEL", "VIEW_LAYER", "DEFAULT_VIEW",
           "LAYER_NAME"]
