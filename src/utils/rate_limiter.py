"""Thread-safe Token Bucket rate limiter for API throttling."""

from __future__ import annotations

import time
import threading

class TokenBucketRateLimiter:
    """Thread-safe Token Bucket Rate Limiter to enforce request pacing constraints."""

    def __init__(self, rate: float, capacity: float) -> None:
        """
        Initialize the rate limiter.
        
        Args:
            rate: The rate at which tokens are added to the bucket (tokens per second).
            capacity: The maximum capacity of the bucket.
        """
        self.rate = rate
        self.capacity = capacity
        self.tokens = capacity
        self.last_refill = time.time()
        self.lock = threading.Lock()

    def consume(self, amount: float = 1.0) -> bool:
        """
        Attempt to consume a given amount of tokens.
        
        Args:
            amount: The number of tokens to consume.
            
        Returns:
            True if tokens were consumed, False otherwise.
        """
        with self.lock:
            self._refill()
            if self.tokens >= amount:
                self.tokens -= amount
                return True
            return False

    def wait_and_consume(self, amount: float = 1.0) -> None:
        """
        Consume a given amount of tokens, blocking the current thread if not enough are available.
        
        Args:
            amount: The number of tokens to consume.
        """
        while True:
            with self.lock:
                self._refill()
                if self.tokens >= amount:
                    self.tokens -= amount
                    return
                # Calculate sleep duration required for missing tokens
                needed = amount - self.tokens
                sleep_time = needed / self.rate
            time.sleep(sleep_time)

    def _refill(self) -> None:
        """Add tokens to the bucket based on time elapsed since the last refill operation."""
        now = time.time()
        elapsed = now - self.last_refill
        self.last_refill = now
        self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
