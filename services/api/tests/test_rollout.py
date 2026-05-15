"""Rollout bucketing helper."""

from __future__ import annotations

from app.lib.rollout import hash_bucket, is_in_rollout


class TestHashBucket:
    def test_returns_value_in_0_99_range(self) -> None:
        for key in ("a", "abc", "01234567-89ab-cdef-0123-456789abcdef", "x" * 1000):
            v = hash_bucket(key)
            assert 0 <= v < 100

    def test_deterministic(self) -> None:
        assert hash_bucket("foo") == hash_bucket("foo")
        assert hash_bucket("foo") != hash_bucket("bar")  # statistically likely

    def test_different_keys_distribute_across_range(self) -> None:
        # 200 distinct keys should hit at least 30 distinct buckets.
        # If they all collide on one bucket, the hash is broken.
        seen = {hash_bucket(f"key_{i}") for i in range(200)}
        assert len(seen) >= 30


class TestIsInRollout:
    def test_zero_pct_is_kill_switch(self) -> None:
        assert is_in_rollout(key="x", rollout_pct=0) is False
        assert is_in_rollout(key="x", rollout_pct=-1) is False

    def test_hundred_pct_always_in(self) -> None:
        assert is_in_rollout(key="x", rollout_pct=100) is True
        assert is_in_rollout(key="x", rollout_pct=200) is True

    def test_mid_pct_deterministic_per_key(self) -> None:
        for _ in range(5):
            # Same key + same pct = same answer
            a = is_in_rollout(key="abc", rollout_pct=50)
            b = is_in_rollout(key="abc", rollout_pct=50)
            assert a == b

    def test_50_pct_includes_about_half(self) -> None:
        included = sum(
            1 for i in range(1000)
            if is_in_rollout(key=f"key_{i}", rollout_pct=50)
        )
        # Allow ±10% tolerance — 1000 samples, should land near 500
        assert 400 <= included <= 600

    def test_rollout_monotonic_in_pct(self) -> None:
        """If a key is in at pct=X, it's also in at any pct > X."""
        for i in range(100):
            key = f"k{i}"
            for pct in range(0, 101, 5):
                if is_in_rollout(key=key, rollout_pct=pct):
                    # All higher pcts must also include the key
                    for higher in range(pct, 101, 5):
                        assert is_in_rollout(key=key, rollout_pct=higher)
                    break
