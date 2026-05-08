import json
import logging
import os
import random
import string
import sys
import threading
import time
import traceback as tb_module
import uuid
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel
from typing import List, Optional
from sqlalchemy import create_engine, Column, String, Integer, Float, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# =============================================================================
# Inventory Service v1.4.3
#
# Changelog v1.4.3:
#   - Documentation-only changelog refresh (no behavioral change).
#
# Changelog v1.4.2 (deployed 2026-02-18T14:30:00Z):
#   - Added Redis caching layer for stock lookups (perf improvement)
#   - Added low-stock alerting via Redis pub/sub
#   - Added background cache-refresh thread to keep cache warm
#   - Added /metrics endpoint for Prometheus scraping
#
# Changelog v1.4.1:
#   - Fixed race condition in concurrent reservations
#   - Added DB connection pooling
#
# Changelog v1.4.0:
#   - Migrated from in-memory store to PostgreSQL/SQLite
#   - Added reservation system
# =============================================================================

SERVICE_NAME = "inventory-service"
SERVICE_VERSION = "1.4.3"
DEPLOY_SHA = "a3f7c2e"  # git short sha of the deploy
DEPLOY_TIME = "2026-02-18T14:30:00Z"

# ---------------------------------------------------------------------------
# Structured JSON logger (production-grade)
# ---------------------------------------------------------------------------
class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "service": SERVICE_NAME,
            "version": SERVICE_VERSION,
            "message": record.getMessage(),
        }
        if hasattr(record, "trace_id"):
            log_entry["trace_id"] = record.trace_id
        if hasattr(record, "span_id"):
            log_entry["span_id"] = record.span_id
        if hasattr(record, "extra_fields"):
            log_entry.update(record.extra_fields)
        if record.exc_info and record.exc_info[0] is not None:
            log_entry["exception"] = {
                "type": record.exc_info[0].__name__,
                "message": str(record.exc_info[1]),
                "stacktrace": tb_module.format_exception(*record.exc_info),
            }
        return json.dumps(log_entry)

handler = logging.StreamHandler()
handler.setFormatter(JSONFormatter())
logger = logging.getLogger(SERVICE_NAME)
logger.setLevel(logging.INFO)
logger.handlers = [handler]
logger.propagate = False

# Suppress noisy uvicorn access logs
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def log_with_context(level, message, trace_id=None, span_id=None, exc_info=None, **extra):
    record = logger.makeRecord(
        SERVICE_NAME, level, "(inventory)", 0, message, (), None
    )
    if trace_id:
        record.trace_id = trace_id
    if span_id:
        record.span_id = span_id
    if extra:
        record.extra_fields = extra
    if exc_info:
        record.exc_info = exc_info
    logger.handle(record)


# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------
app = FastAPI(title="Inventory Service", version=SERVICE_VERSION)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./inventory.db")
engine = create_engine(DATABASE_URL, pool_size=5, max_overflow=2, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
REDIS_POOL_MAX_SIZE = int(os.getenv("REDIS_POOL_MAX_SIZE", "50"))
REDIS_POOL_TIMEOUT = float(os.getenv("REDIS_POOL_TIMEOUT", "5.0"))
LOW_STOCK_THRESHOLD = int(os.getenv("LOW_STOCK_THRESHOLD", "30"))
CACHE_REFRESH_INTERVAL = int(os.getenv("CACHE_REFRESH_INTERVAL", "30"))
CACHE_TTL = int(os.getenv("CACHE_TTL", "30"))


# ===========================================================================
#  Redis Connection Pool (simulated — mirrors redis-py ConnectionPool)
# ===========================================================================
class RedisConnectionPool:
    """Connection pool for Redis. Thread-safe. Max connections configurable."""

    def __init__(self, url: str, max_connections: int, timeout: float):
        self._url = url
        self._max_connections = max_connections
        self._timeout = timeout
        self._available = max_connections
        self._lock = threading.Lock()
        self._total_created = 0
        self._total_released = 0
        self._leaked = 0
        self._peak_active = 0
        self._timeout_count = 0

    @property
    def active(self):
        return self._max_connections - self._available

    @property
    def available(self):
        return self._available

    def get_connection(self, caller: str = ""):
        """Acquire a connection from the pool. Blocks up to timeout."""
        with self._lock:
            current_active = self.active
            if current_active > self._peak_active:
                self._peak_active = current_active

            # --- Progressive degradation ---
            # As pool drains, simulate increasing contention/wait time.
            # Real redis-py blocks on a semaphore; we simulate with sleep.
            utilization = current_active / self._max_connections if self._max_connections > 0 else 0

            if self._available <= 3 and self._available > 0:
                log_with_context(
                    logging.WARNING,
                    f"Connection pool reaching limit",
                    pool_active=current_active,
                    pool_max=self._max_connections,
                    pool_available=self._available,
                    pool_leaked=self._leaked,
                    pool_utilization_pct=round(utilization * 100),
                    component="redis-pool",
                )

            if self._available <= 0:
                self._timeout_count += 1
                # Simulate blocking then timeout
                time.sleep(self._timeout)
                try:
                    raise TimeoutError(
                        f"redis.exceptions.TimeoutError: Timeout getting connection "
                        f"from pool (active={current_active}, max={self._max_connections})"
                    )
                except TimeoutError:
                    log_with_context(
                        logging.ERROR,
                        f"RedisTimeout: pool exhausted, no connections available "
                        f"after {self._timeout}s",
                        exc_info=sys.exc_info(),
                        pool_active=current_active,
                        pool_max=self._max_connections,
                        pool_timeout_total=self._timeout_count,
                        pool_leaked=self._leaked,
                        component="redis-pool",
                    )
                    raise

            # Contention delay: as pool fills up, each acquire takes longer
            # This simulates real connection pool behavior where threads
            # compete for a shrinking number of available connections.
            #
            # 0-40% utilized:  no extra delay (healthy)
            # 40-60% utilized: 0.1-0.5s delay (first signs of slowdown)
            # 60-75% utilized: 0.5-1.5s delay (noticeable degradation)
            # 75-90% utilized: 1.5-3.0s delay (significant impact)
            # 90-100% utilized: 3.0-5.0s delay (near-timeout, requests start failing)
            contention_delay = 0.0
            if utilization > 0.9:
                contention_delay = random.uniform(3.0, 5.0)
            elif utilization > 0.75:
                contention_delay = random.uniform(1.5, 3.0)
            elif utilization > 0.6:
                contention_delay = random.uniform(0.5, 1.5)
            elif utilization > 0.4:
                contention_delay = random.uniform(0.1, 0.5)

            if contention_delay > 0:
                log_with_context(
                    logging.WARNING,
                    f"Connection pool contention: waiting {contention_delay:.2f}s "
                    f"for available connection",
                    pool_active=current_active,
                    pool_max=self._max_connections,
                    pool_available=self._available,
                    contention_delay_s=round(contention_delay, 2),
                    pool_utilization_pct=round(utilization * 100),
                    caller=caller,
                    component="redis-pool",
                )

            self._available -= 1
            self._total_created += 1

        # Release lock before sleeping (don't hold lock during contention wait)
        if contention_delay > 0:
            time.sleep(contention_delay)

        return _PooledRedisConnection(self)

    def return_connection(self, conn):
        with self._lock:
            if self._available < self._max_connections:
                self._available += 1
                self._total_released += 1

    def _register_leak(self):
        with self._lock:
            self._leaked += 1

    def metrics(self):
        return {
            "redis_pool_max_connections": self._max_connections,
            "redis_pool_active_connections": self.active,
            "redis_pool_available_connections": self._available,
            "redis_pool_leaked_connections": self._leaked,
            "redis_pool_peak_active": self._peak_active,
            "redis_pool_timeout_total": self._timeout_count,
            "redis_pool_created_total": self._total_created,
            "redis_pool_released_total": self._total_released,
        }


class _PooledRedisConnection:
    """Represents a single pooled Redis connection."""

    def __init__(self, pool: RedisConnectionPool):
        self._pool = pool
        self._closed = False

    def get(self, key: str) -> Optional[str]:
        time.sleep(random.uniform(0.001, 0.008))  # 1-8ms simulated latency
        return None  # cache miss

    def setex(self, key: str, ttl: int, value: str) -> bool:
        time.sleep(random.uniform(0.001, 0.005))
        return True

    def publish(self, channel: str, message: str) -> int:
        time.sleep(random.uniform(0.001, 0.003))
        return 1

    def close(self):
        """Return this connection to the pool."""
        if not self._closed:
            self._closed = True
            self._pool.return_connection(self)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


# Global pool
redis_pool = RedisConnectionPool(
    url=REDIS_URL,
    max_connections=REDIS_POOL_MAX_SIZE,
    timeout=REDIS_POOL_TIMEOUT,
)


# ---------------------------------------------------------------------------
# Database model
# ---------------------------------------------------------------------------
class InventoryItem(Base):
    __tablename__ = "inventory"
    item_id = Column(String, primary_key=True)
    name = Column(String, nullable=False, default="")
    quantity = Column(Integer, nullable=False, default=0)
    reserved = Column(Integer, nullable=False, default=0)
    price = Column(Float, nullable=False, default=0.0)
    warehouse = Column(String, nullable=False, default="WH-EAST-1")

Base.metadata.create_all(engine)


class ItemRequest(BaseModel):
    item_id: str
    quantity: int

class CheckoutRequest(BaseModel):
    user_email: str
    items: List[ItemRequest]
    payment_method: str


def init_inventory():
    db = SessionLocal()
    try:
        count = db.query(InventoryItem).count()
        if count == 0:
            items = [
                InventoryItem(item_id="SKU-1001", name="Wireless Headphones", quantity=150, reserved=0, price=79.99, warehouse="WH-EAST-1"),
                InventoryItem(item_id="SKU-1002", name="USB-C Hub", quantity=200, reserved=0, price=45.00, warehouse="WH-EAST-1"),
                InventoryItem(item_id="SKU-2001", name="Mechanical Keyboard", quantity=28, reserved=0, price=129.99, warehouse="WH-WEST-1"),
                InventoryItem(item_id="SKU-2002", name="Monitor Stand", quantity=18, reserved=0, price=34.99, warehouse="WH-WEST-1"),
                InventoryItem(item_id="SKU-3001", name="Laptop Sleeve", quantity=9, reserved=0, price=24.99, warehouse="WH-CENTRAL-1"),
            ]
            db.add_all(items)
            db.commit()
            for it in items:
                log_with_context(
                    logging.INFO,
                    f"Seeded inventory: {it.item_id} ({it.name}) qty={it.quantity} warehouse={it.warehouse}",
                    component="init",
                )
    finally:
        db.close()


# ===========================================================================
# Stock check with Redis cache
#
# Normal path: acquire conn → GET cache → (miss) query DB → SET cache → close
# Low-stock path: also acquires a SECOND connection for pub/sub alert
#
# >>> BUG: The second connection on line ~290 is never closed <<<
#
# ===========================================================================
def check_stock_cached(item_id: str, trace_id: str = None) -> dict:
    """
    Check stock level for an item, using Redis as a read-through cache.
    If stock is below LOW_STOCK_THRESHOLD, publishes alert to Redis pub/sub.
    """
    conn = redis_pool.get_connection(caller="check_stock_cached")
    cache_key = f"inventory:stock:{item_id}"

    try:
        # Try cache first
        cached_value = conn.get(cache_key)

        if cached_value is not None:
            available = int(cached_value)
            log_with_context(
                logging.DEBUG, f"Cache HIT for {item_id}: {available}",
                trace_id=trace_id, item_id=item_id, cache="hit",
                component="stock-check",
            )
        else:
            # Cache miss — read from DB
            db = SessionLocal()
            try:
                row = db.query(InventoryItem).filter_by(item_id=item_id).first()
                if row is None:
                    return {"item_id": item_id, "available": 0, "found": False, "low_stock": False}
                available = row.quantity - row.reserved
            finally:
                db.close()

            # Populate cache
            conn.setex(cache_key, CACHE_TTL, str(available))
            log_with_context(
                logging.DEBUG, f"Cache MISS for {item_id}, loaded from DB: {available}",
                trace_id=trace_id, item_id=item_id, cache="miss",
                component="stock-check",
            )

        is_low_stock = available <= LOW_STOCK_THRESHOLD

        # -----------------------------------------------------------------
        # Low-stock alert path — THIS IS WHERE THE BUG IS
        # -----------------------------------------------------------------
        if is_low_stock:
            # Acquire a dedicated connection to publish the low-stock alert
            alert_conn = redis_pool.get_connection(caller="low_stock_alert")  # line ~290

            alert_payload = json.dumps({
                "item_id": item_id,
                "available": available,
                "threshold": LOW_STOCK_THRESHOLD,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            alert_conn.publish("inventory:alerts:low_stock", alert_payload)

            log_with_context(
                logging.WARNING,
                f"Low stock alert published for {item_id}: "
                f"{available} units remaining (threshold={LOW_STOCK_THRESHOLD})",
                trace_id=trace_id,
                item_id=item_id,
                available=available,
                threshold=LOW_STOCK_THRESHOLD,
                component="stock-alert",
            )

            # !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
            # BUG: alert_conn.close() is MISSING here!
            #
            # The developer assumed the connection would be auto-returned
            # when the variable goes out of scope (garbage collected), but
            # Python's GC is non-deterministic. Under load the pool drains
            # before GC kicks in.
            #
            # FIX: Add  alert_conn.close()  here, or use:
            #   with redis_pool.get_connection() as alert_conn:
            #       alert_conn.publish(...)
            # !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
            redis_pool._register_leak()  # (simulation bookkeeping)

        return {
            "item_id": item_id,
            "available": available,
            "found": True,
            "low_stock": is_low_stock,
        }

    except TimeoutError:
        log_with_context(
            logging.ERROR,
            f"RedisTimeout in check_stock_cached for {item_id}: "
            f"connection pool exhausted",
            trace_id=trace_id,
            exc_info=sys.exc_info(),
            item_id=item_id,
            component="stock-check",
            error_type="RedisTimeout",
        )
        raise
    except Exception as e:
        log_with_context(
            logging.ERROR,
            f"Unexpected error in stock check for {item_id}: {e}",
            trace_id=trace_id, item_id=item_id, component="stock-check",
            exception_type=type(e).__name__,
        )
        raise

    finally:
        conn.close()


# ===========================================================================
# NON-CRITICAL ISSUE #1: Deprecated header warning
# The service still reads X-Request-ID from the old API gateway format
# instead of the new traceparent W3C header. Logs a deprecation warning
# every time. Noisy but harmless.
# ===========================================================================
def extract_trace_id(request: Request) -> str:
    # Check new W3C format first
    traceparent = request.headers.get("traceparent")
    if traceparent:
        parts = traceparent.split("-")
        if len(parts) >= 2:
            return parts[1]

    # Fall back to legacy header
    legacy_id = request.headers.get("x-request-id")
    if legacy_id:
        log_with_context(
            logging.ERROR,
            "Received deprecated X-Request-ID header instead of W3C traceparent. "
            "Distributed tracing may be incomplete. API gateway migration overdue.",
            trace_id=legacy_id,
            component="tracing",
            error_type="DeprecatedTraceHeader",
            deprecated_header="X-Request-ID",
        )
        return legacy_id

    return uuid.uuid4().hex[:16]


# ===========================================================================
# NON-CRITICAL ISSUE #2: Slow query on /inventory (missing index)
# The full inventory scan logs a slow-query warning when items > 100.
# Not causing failures, just a performance smell.
# ===========================================================================


# ===========================================================================
# NON-CRITICAL ISSUE #3: Stale cache entries
# On successful reservation, we update the DB but DON'T invalidate the
# Redis cache. The background refresh will eventually catch up, but for
# a few seconds the cache can serve stale data.
# ===========================================================================


# ===========================================================================
# Background cache-refresh thread
# Runs every CACHE_REFRESH_INTERVAL seconds. Refreshes cache for all items.
# This is what causes CONTINUOUS log output and the gradual pool drain.
# ===========================================================================
def _background_cache_refresh():
    """
    Periodically refresh Redis cache for all inventory items.
    Added in v1.4.2 to reduce DB load from cache misses.
    """
    log_with_context(
        logging.INFO,
        f"Background cache-refresh thread started",
        refresh_interval_s=CACHE_REFRESH_INTERVAL,
        component="cache-refresh",
    )
    cycle = 0

    while True:
        time.sleep(CACHE_REFRESH_INTERVAL)
        cycle += 1
        pool_metrics = redis_pool.metrics()
        cycle_trace = f"cache-refresh-{cycle:04d}"

        log_with_context(
            logging.INFO,
            f"Cache refresh cycle {cycle} started",
            trace_id=cycle_trace,
            cycle=cycle,
            component="cache-refresh",
            **pool_metrics,
        )

        items_refreshed = 0
        items_failed = 0
        low_stock_count = 0
        db = SessionLocal()

        try:
            all_items = db.query(InventoryItem).all()
            item_ids = [it.item_id for it in all_items]

            for item_id in item_ids:
                try:
                    result = check_stock_cached(item_id, trace_id=cycle_trace)
                    items_refreshed += 1
                    if result.get("low_stock"):
                        low_stock_count += 1
                except TimeoutError:
                    items_failed += 1
                    log_with_context(
                        logging.ERROR,
                        f"RedisTimeout: cache refresh failed for {item_id}",
                        trace_id=cycle_trace,
                        exc_info=sys.exc_info(),
                        item_id=item_id,
                        component="cache-refresh",
                        error_type="RedisTimeout",
                    )
                except Exception as e:
                    items_failed += 1
                    log_with_context(
                        logging.ERROR,
                        f"Cache refresh error for {item_id}: {e}",
                        trace_id=cycle_trace,
                        item_id=item_id,
                        component="cache-refresh",
                        error_type=type(e).__name__,
                    )
        except Exception as e:
            log_with_context(
                logging.ERROR,
                f"Cache refresh cycle {cycle} DB error: {e}",
                trace_id=cycle_trace,
                component="cache-refresh",
            )
        finally:
            db.close()

        pool_after = redis_pool.metrics()
        log_with_context(
            logging.INFO,
            f"Cache refresh cycle {cycle} completed: "
            f"{items_refreshed} refreshed, {items_failed} failed, "
            f"{low_stock_count} low-stock alerts",
            trace_id=cycle_trace,
            cycle=cycle,
            items_refreshed=items_refreshed,
            items_failed=items_failed,
            low_stock_count=low_stock_count,
            component="cache-refresh",
            **pool_after,
        )

        # NON-CRITICAL ISSUE #4: GC pressure warning
        # The refresh thread detects leaked connections growing but can't fix them
        if pool_after["redis_pool_leaked_connections"] > 0:
            log_with_context(
                logging.WARNING,
                f"Detected {pool_after['redis_pool_leaked_connections']} "
                f"potentially leaked Redis connections. Pool utilization: "
                f"{pool_after['redis_pool_active_connections']}/{pool_after['redis_pool_max_connections']}",
                component="pool-monitor",
                **pool_after,
            )


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------
@app.on_event("startup")
async def startup():
    init_inventory()
    log_with_context(
        logging.INFO,
        f"Inventory Service started",
        version=SERVICE_VERSION,
        deploy_sha=DEPLOY_SHA,
        deploy_time=DEPLOY_TIME,
        redis_url=REDIS_URL,
        redis_pool_max=REDIS_POOL_MAX_SIZE,
        redis_pool_timeout=REDIS_POOL_TIMEOUT,
        low_stock_threshold=LOW_STOCK_THRESHOLD,
        cache_refresh_interval=CACHE_REFRESH_INTERVAL,
        cache_ttl=CACHE_TTL,
        database_url=DATABASE_URL.split("@")[-1] if "@" in DATABASE_URL else "(local)",
        component="startup",
    )
    # Start background cache refresh
    t = threading.Thread(target=_background_cache_refresh, daemon=True, name="cache-refresh")
    t.start()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    """
    Health check. Returns healthy even when Redis pool is degraded.
    This is an oversight — the probe doesn't check Redis pool health,
    so Kubernetes thinks the pod is fine.
    """
    return {"status": "healthy", "version": SERVICE_VERSION}


@app.get("/ready")
async def ready():
    """Readiness probe — also doesn't check Redis. Another oversight."""
    return {"ready": True}


@app.get("/metrics")
async def metrics():
    """Prometheus-compatible metrics endpoint."""
    pool = redis_pool.metrics()
    db = SessionLocal()
    try:
        item_count = db.query(InventoryItem).count()
    finally:
        db.close()

    lines = [
        f'# HELP redis_pool_active_connections Current active Redis connections',
        f'# TYPE redis_pool_active_connections gauge',
        f'redis_pool_active_connections {pool["redis_pool_active_connections"]}',
        f'# HELP redis_pool_max_connections Maximum Redis pool connections',
        f'# TYPE redis_pool_max_connections gauge',
        f'redis_pool_max_connections {pool["redis_pool_max_connections"]}',
        f'# HELP redis_pool_available_connections Available Redis pool connections',
        f'# TYPE redis_pool_available_connections gauge',
        f'redis_pool_available_connections {pool["redis_pool_available_connections"]}',
        f'# HELP redis_pool_leaked_connections Leaked Redis pool connections',
        f'# TYPE redis_pool_leaked_connections counter',
        f'redis_pool_leaked_connections {pool["redis_pool_leaked_connections"]}',
        f'# HELP redis_pool_timeout_total Total Redis pool timeouts',
        f'# TYPE redis_pool_timeout_total counter',
        f'redis_pool_timeout_total {pool["redis_pool_timeout_total"]}',
        f'# HELP inventory_items_total Total inventory items',
        f'# TYPE inventory_items_total gauge',
        f'inventory_items_total {item_count}',
        f'# HELP service_info Service metadata',
        f'# TYPE service_info gauge',
        f'service_info{{version="{SERVICE_VERSION}",deploy_sha="{DEPLOY_SHA}"}} 1',
    ]
    return PlainTextResponse("\n".join(lines) + "\n", media_type="text/plain")


@app.get("/inventory")
async def get_inventory(request: Request):
    trace_id = extract_trace_id(request)
    db = SessionLocal()
    query_start = time.time()
    try:
        items = db.query(InventoryItem).all()
        query_time_ms = (time.time() - query_start) * 1000

        # NON-CRITICAL ISSUE #2: slow query warning
        if query_time_ms > 50:
            log_with_context(
                logging.ERROR,
                f"Slow query on /inventory: {query_time_ms:.1f}ms for {len(items)} items. "
                f"Missing index on inventory table suspected.",
                trace_id=trace_id,
                error_type="SlowQuery",
                query_time_ms=round(query_time_ms, 1),
                item_count=len(items),
                component="db",
            )

        return {
            "items": [
                {
                    "item_id": item.item_id,
                    "name": item.name,
                    "quantity": item.quantity,
                    "reserved": item.reserved,
                    "available": item.quantity - item.reserved,
                    "warehouse": item.warehouse,
                }
                for item in items
            ]
        }
    finally:
        db.close()


@app.post("/reserve")
async def reserve_stock(request: CheckoutRequest, req: Request):
    """Reserve inventory for a checkout. Called by checkout-service."""
    trace_id = extract_trace_id(req)
    span_id = uuid.uuid4().hex[:8]

    log_with_context(
        logging.INFO,
        f"Stock reservation request: user={request.user_email}, "
        f"items={[i.item_id for i in request.items]}",
        trace_id=trace_id,
        span_id=span_id,
        user_email=request.user_email,
        item_count=len(request.items),
        component="reserve",
    )

    db = SessionLocal()
    reserved_items = []
    reservation_start = time.time()

    try:
        for item in request.items:
            # Stock check with cache (this is where connections leak)
            try:
                stock_info = check_stock_cached(item.item_id, trace_id=trace_id)
            except TimeoutError:
                elapsed = time.time() - reservation_start
                log_with_context(
                    logging.ERROR,
                    f"Stock check timed out for {item.item_id} "
                    f"after {elapsed:.2f}s",
                    trace_id=trace_id,
                    span_id=span_id,
                    exc_info=sys.exc_info(),
                    item_id=item.item_id,
                    elapsed_s=round(elapsed, 2),
                    component="reserve",
                    error_type="RedisTimeout",
                )
                raise HTTPException(
                    status_code=503,
                    detail="Service temporarily unavailable",
                )

            if not stock_info.get("found"):
                raise HTTPException(status_code=404, detail=f"Item {item.item_id} not found")

            if stock_info["available"] < item.quantity:
                raise HTTPException(
                    status_code=409,
                    detail=f"Insufficient stock for {item.item_id}",
                )

            # DB reservation
            result = db.execute(
                text("""
                    UPDATE inventory
                    SET reserved = reserved + :qty
                    WHERE item_id = :item_id
                    AND (quantity - reserved) >= :qty
                    RETURNING item_id, quantity, reserved
                """),
                {"qty": item.quantity, "item_id": item.item_id},
            )
            updated = result.fetchone()

            if not updated:
                db.rollback()
                raise HTTPException(status_code=409, detail=f"Reservation conflict for {item.item_id}")

            remaining = updated[1] - updated[2]
            reserved_items.append({
                "item_id": item.item_id,
                "reserved_qty": item.quantity,
                "remaining": remaining,
            })

            # NON-CRITICAL ISSUE #3: cache not invalidated after reservation
            # Stale cache will serve old stock count until next refresh cycle

            log_with_context(
                logging.INFO,
                f"Reserved {item.quantity}x {item.item_id}, remaining={remaining}",
                trace_id=trace_id,
                span_id=span_id,
                item_id=item.item_id,
                reserved_qty=item.quantity,
                remaining=remaining,
                component="reserve",
            )

        db.commit()
        elapsed = time.time() - reservation_start

        log_with_context(
            logging.INFO,
            f"Reservation completed for {request.user_email}: "
            f"{len(reserved_items)} items in {elapsed:.3f}s",
            trace_id=trace_id,
            span_id=span_id,
            user_email=request.user_email,
            items_reserved=len(reserved_items),
            elapsed_s=round(elapsed, 3),
            component="reserve",
        )

        return {"success": True, "reserved_items": reserved_items}

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        log_with_context(
            logging.ERROR,
            f"Reservation failed: {e}",
            trace_id=trace_id,
            span_id=span_id,
            component="reserve",
            error_type=type(e).__name__,
        )
        raise HTTPException(status_code=500, detail="Internal error")
    finally:
        db.close()


@app.post("/checkout")
async def checkout(request: CheckoutRequest, req: Request):
    """Legacy endpoint — forwards to /reserve."""
    return await reserve_stock(request, req)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)
