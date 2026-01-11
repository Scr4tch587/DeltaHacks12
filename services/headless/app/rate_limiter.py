import asyncio
import time
from collections import deque

class AsyncRateLimiter:
    """
    Asynchronous rate limiter using a sliding window algorithm.
    Enforces a maximum number of requests within a specified time window.
    """
    def __init__(self, max_requests: int, time_window: float):
        """
        Initialize the rate limiter.

        Args:
            max_requests: Maximum number of requests allowed.
            time_window: Time window in seconds.
        """
        self.max_requests = max_requests
        self.time_window = time_window
        self.timestamps = deque()
        self._lock = asyncio.Lock()

    async def acquire(self):
        """
        Acquire permission to proceed. 
        Waits if the limit has been reached until a slot is available.
        """
        async with self._lock:
            while True:
                now = time.monotonic()
                
                # Remove timestamps outside the current window
                while self.timestamps and now - self.timestamps[0] > self.time_window:
                    self.timestamps.popleft()

                if len(self.timestamps) < self.max_requests:
                    self.timestamps.append(now)
                    return
                
                # Wait until the oldest timestamp expires
                wait_time = self.timestamps[0] + self.time_window - now
                if wait_time > 0:
                    await asyncio.sleep(wait_time)

# Global rate limiters
# 50 requests per 10 seconds
job_rate_limiter = AsyncRateLimiter(max_requests=50, time_window=10.0)
embedding_rate_limiter = AsyncRateLimiter(max_requests=50, time_window=10.0)
# AI (Gemini) rate limiter: 10 requests per second
ai_rate_limiter = AsyncRateLimiter(max_requests=10, time_window=1.0)

# Browser semaphore: limit concurrent browser instances (each uses ~200-400MB RAM)
BROWSER_SEMAPHORE = asyncio.Semaphore(10)
