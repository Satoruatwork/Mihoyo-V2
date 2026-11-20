"""CacheManager: LRU eviction, disk round-trip, and response TTL."""

from __future__ import annotations

import time

from PIL import Image

from enkarender.assets.cache import CacheManager
from enkarender.config import Settings


def test_image_lru_evicts_oldest(tmp_path):
    settings = Settings(home=tmp_path, memory_image_capacity=2)
    cache = CacheManager(settings)
    for name in ("a", "b", "c"):
        cache.put_image(name, Image.new("RGBA", (1, 1)))
    assert cache.get_image("a") is None       # evicted (oldest)
    assert cache.get_image("b") is not None
    assert cache.get_image("c") is not None


def test_image_lru_marks_recently_used(tmp_path):
    settings = Settings(home=tmp_path, memory_image_capacity=2)
    cache = CacheManager(settings)
    cache.put_image("a", Image.new("RGBA", (1, 1)))
    cache.put_image("b", Image.new("RGBA", (1, 1)))
    cache.get_image("a")                       # touch a -> b becomes oldest
    cache.put_image("c", Image.new("RGBA", (1, 1)))
    assert cache.get_image("b") is None
    assert cache.get_image("a") is not None


def test_disk_bytes_round_trip(tmp_path):
    cache = CacheManager(Settings(home=tmp_path))
    assert cache.get_bytes("http://x/y.png") is None
    cache.put_bytes("http://x/y.png", b"data")
    assert cache.get_bytes("http://x/y.png") == b"data"


def test_response_ttl(tmp_path):
    cache = CacheManager(Settings(home=tmp_path, response_ttl=0.05))
    cache.set_response("k", {"v": 1})
    assert cache.get_response("k") == {"v": 1}
    time.sleep(0.06)
    assert cache.get_response("k") is None
