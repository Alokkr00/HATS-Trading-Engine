"""Event-driven Message Bus for decoupled component communication (supports Redis and mock fallbacks)."""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, List
from src.utils import get_logger

logger = get_logger(__name__)

# Try to import redis, fallback to mock if missing
try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False


class RedisMessageBus:
    """Thread-safe event-driven message router supporting Redis pub/sub and in-memory mock fallback."""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6379,
        db: int = 0,
        use_mock: bool = False,
    ) -> None:
        """Initialize the message bus.

        Args:
            host: Redis hostname.
            port: Redis port.
            db: Redis database number.
            use_mock: Force the mock in-memory queue fallback even if Redis is installed.
        """
        self.use_mock = use_mock or not REDIS_AVAILABLE
        self.client: Any = None
        self.pubsub: Any = None
        
        # Mock storage for in-memory pub/sub emulation
        self.mock_subscribers: Dict[str, List[Callable[[Dict[str, Any]], None]]] = {}

        if not self.use_mock:
            try:
                self.client = redis.Redis(
                    host=host,
                    port=port,
                    db=db,
                    socket_timeout=2.0,
                    decode_responses=True
                )
                # Quick connection health ping
                self.client.ping()
                self.pubsub = self.client.pubsub()
                logger.info(f"Successfully connected to Redis at {host}:{port} (db={db}).")
            except Exception as e:
                logger.warning(
                    f"Failed to connect to Redis ({e}). Falling back to mock in-memory message bus."
                )
                self.use_mock = True

        if self.use_mock:
            logger.info("Operating in MOCK mode (in-memory message routing active).")

    def publish(self, channel: str, message: Any) -> None:
        """Publish a message to a channel.

        Args:
            channel: Target event channel.
            message: Message payload (dictionary, list, or string).
        """
        serialized = json.dumps(message) if isinstance(message, (dict, list)) else str(message)

        if self.use_mock:
            logger.debug(f"[Mock Pub] {channel} <- {serialized}")
            if channel in self.mock_subscribers:
                for callback in self.mock_subscribers[channel]:
                    try:
                        # Emulate receiving by parsing payload
                        payload = json.loads(serialized) if isinstance(message, (dict, list)) else message
                        callback(payload)
                    except Exception as err:
                        logger.error(f"Error in mock callback execution on channel {channel}: {err}")
        else:
            try:
                self.client.publish(channel, serialized)
                logger.debug(f"[Redis Pub] {channel} <- {serialized}")
            except Exception as e:
                logger.error(f"Failed to publish message to Redis channel {channel}: {e}")

    def subscribe(self, channel: str, callback: Callable[[Any], None]) -> None:
        """Register a subscriber callback for a channel.

        Args:
            channel: Target event channel.
            callback: Function to run when a message arrives.
        """
        if self.use_mock:
            if channel not in self.mock_subscribers:
                self.mock_subscribers[channel] = []
            self.mock_subscribers[channel].append(callback)
            logger.info(f"[Mock Sub] Registered callback for channel: {channel}")
        else:
            try:
                def redis_handler(msg: Dict[str, Any]) -> None:
                    try:
                        data = msg.get("data")
                        if data:
                            try:
                                payload = json.loads(data)
                            except ValueError:
                                payload = data
                            callback(payload)
                    except Exception as err:
                        logger.error(f"Error in Redis message handler callback: {err}")

                self.pubsub.subscribe(**{channel: redis_handler})
                logger.info(f"[Redis Sub] Subscribed to channel: {channel}")
            except Exception as e:
                logger.error(f"Failed to subscribe to Redis channel {channel}: {e}")

    def start_listening(self) -> None:
        """Starts the subscription listening loop (non-blocking thread for Redis)."""
        if not self.use_mock and self.pubsub:
            try:
                # Start listener thread using redis-py pubsub built-in thread runner
                self.pubsub.run_in_thread(sleep_time=0.01)
                logger.info("Started Redis Pub/Sub background listener thread.")
            except Exception as e:
                logger.error(f"Failed to start Redis Pub/Sub listener thread: {e}")
        else:
            logger.info("Mock message bus active; listener thread skipped (direct synchronous callbacks).")
