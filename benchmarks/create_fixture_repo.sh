#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# create_fixture_repo.sh
#
# Creates a fixture git repository for benchmarking a code-review agent.
# Each benchmark case gets two tags: bench/<case_id>/base and bench/<case_id>/head.
#
# Idempotent: deletes and recreates the fixture_repo directory on each run.
# Compatible with Git Bash on Windows.
# ---------------------------------------------------------------------------
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="${SCRIPT_DIR}/fixture_repo"

# ── Idempotent: wipe and recreate ──────────────────────────────────────────
rm -rf "$REPO_DIR"
mkdir -p "$REPO_DIR"
cd "$REPO_DIR"

git init
git config user.email "bench@lgtm.dev"
git config user.name "LGTM Benchmark"

# ── Helper: write a file and ensure parent dirs exist ──────────────────────
write_file() {
    local path="$1"
    shift
    mkdir -p "$(dirname "$path")"
    cat > "$path"
}

# ── Helper: commit all changes with a message ─────────────────────────────
commit_all() {
    git add -A
    git commit -m "$1" --allow-empty
}

###########################################################################
#                     SHARED BASE FILES (written once)                    #
###########################################################################
write_base_files() {
# ── app/__init__.py ────────────────────────────────────────────────────
write_file app/__init__.py << 'PYEOF'
"""Mini FastAPI-style application for benchmark testing."""
PYEOF

# ── app/config.py ──────────────────────────────────────────────────────
write_file app/config.py << 'PYEOF'
"""Application configuration."""

APP_NAME = "benchmark-app"
VERSION = "0.1.0"
DEBUG = False
MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 20
PYEOF

# ── app/routes/__init__.py ─────────────────────────────────────────────
write_file app/routes/__init__.py << 'PYEOF'
"""Route handlers."""
PYEOF

# ── app/routes/users.py ───────────────────────────────────────────────
write_file app/routes/users.py << 'PYEOF'
"""User route handlers."""
from app.services import user_service
from app.utils import auth


def get_user(user_id: int, token: str) -> dict:
    """GET /users/{user_id}"""
    auth.require_auth(token)
    user = user_service.get_user_profile(user_id)
    if user is None:
        return {"error": "not found", "status": 404}
    return {"data": user, "status": 200}


def list_users(token: str) -> dict:
    """GET /users"""
    auth.require_auth(token)
    users = user_service.list_all_users()
    return {"data": users, "status": 200}


def create_user(payload: dict, token: str) -> dict:
    """POST /users"""
    auth.require_auth(token)
    user = user_service.create_user(payload)
    return {"data": user, "status": 201}
PYEOF

# ── app/routes/products.py ────────────────────────────────────────────
write_file app/routes/products.py << 'PYEOF'
"""Product route handlers."""
from app.services import product_service
from app.utils import auth


def get_product(product_id: int, token: str) -> dict:
    """GET /products/{product_id}"""
    auth.require_auth(token)
    product = product_service.get_product(product_id)
    if product is None:
        return {"error": "not found", "status": 404}
    return {"data": product, "status": 200}


def list_products(page: int, page_size: int, token: str) -> dict:
    """GET /products"""
    auth.require_auth(token)
    products = product_service.get_products_page(page, page_size)
    return {"data": products, "status": 200}
PYEOF

# ── app/routes/orders.py ──────────────────────────────────────────────
write_file app/routes/orders.py << 'PYEOF'
"""Order route handlers."""
from app.services import order_service
from app.utils import auth


def create_order(payload: dict, token: str) -> dict:
    """POST /orders"""
    auth.require_auth(token)
    order = order_service.create_order(payload)
    return {"data": order, "status": 201}


def get_order(order_id: int, token: str) -> dict:
    """GET /orders/{order_id}"""
    auth.require_auth(token)
    order = order_service.get_order(order_id)
    if order is None:
        return {"error": "not found", "status": 404}
    return {"data": order, "status": 200}
PYEOF

# ── app/services/__init__.py ──────────────────────────────────────────
write_file app/services/__init__.py << 'PYEOF'
"""Business-logic services."""
PYEOF

# ── app/services/user_service.py ──────────────────────────────────────
write_file app/services/user_service.py << 'PYEOF'
"""User service — business logic for user operations."""
from app.models import database as db


def get_user_profile(user_id: int) -> dict | None:
    """Return user profile dict or None if not found."""
    user = db.find_user(user_id)
    if user is None:
        return None
    return {
        "id": user["id"],
        "name": user["name"],
        "email": user["email"],
    }


def list_all_users() -> list[dict]:
    """Return all users."""
    return list(db.USERS.values())


def create_user(payload: dict) -> dict:
    """Create a new user and return it."""
    new_id = max(db.USERS.keys(), default=0) + 1
    user = {"id": new_id, "name": payload["name"], "email": payload["email"]}
    db.USERS[new_id] = user
    return user
PYEOF

# ── app/services/product_service.py ───────────────────────────────────
write_file app/services/product_service.py << 'PYEOF'
"""Product service — business logic for product operations."""
from app.models import database as db


def get_product(product_id: int) -> dict | None:
    """Return a single product or None."""
    return db.find_product(product_id)


def get_products_page(page: int, page_size: int) -> list[dict]:
    """Return a page of products (1-indexed page number)."""
    all_products = list(db.PRODUCTS.values())
    start = (page - 1) * page_size
    end = start + page_size
    return all_products[start:end]


def list_all_products() -> list[dict]:
    """Return every product."""
    return list(db.PRODUCTS.values())
PYEOF

# ── app/services/order_service.py ─────────────────────────────────────
write_file app/services/order_service.py << 'PYEOF'
"""Order service — business logic for order operations."""
from app.models import database as db


# In-memory inventory tracker
inventory: dict[int, int] = {1: 50, 2: 30, 3: 100}


def create_order(payload: dict) -> dict:
    """Create an order after checking inventory."""
    product_id = payload["product_id"]
    quantity = payload["quantity"]
    if inventory.get(product_id, 0) < quantity:
        raise ValueError("Insufficient inventory")
    inventory[product_id] -= quantity
    new_id = max(db.ORDERS.keys(), default=0) + 1
    order = {
        "id": new_id,
        "product_id": product_id,
        "quantity": quantity,
        "status": "confirmed",
    }
    db.ORDERS[new_id] = order
    return order


def get_order(order_id: int) -> dict | None:
    """Return a single order or None."""
    return db.ORDERS.get(order_id)
PYEOF

# ── app/models/__init__.py ────────────────────────────────────────────
write_file app/models/__init__.py << 'PYEOF'
"""Data models and database layer."""
PYEOF

# ── app/models/database.py ────────────────────────────────────────────
write_file app/models/database.py << 'PYEOF'
"""Mock database — dict-backed storage with parameterized query helpers."""

USERS: dict[int, dict] = {
    1: {"id": 1, "name": "Alice", "email": "alice@example.com"},
    2: {"id": 2, "name": "Bob", "email": "bob@example.com"},
}

PRODUCTS: dict[int, dict] = {
    1: {"id": 1, "name": "Widget", "price": 9.99},
    2: {"id": 2, "name": "Gadget", "price": 24.99},
    3: {"id": 3, "name": "Doohickey", "price": 4.50},
}

ORDERS: dict[int, dict] = {}


def find_user(user_id: int) -> dict | None:
    """Look up a user by ID. Returns None if not found."""
    return USERS.get(user_id)


def find_product(product_id: int) -> dict | None:
    """Look up a product by ID. Returns None if not found."""
    return PRODUCTS.get(product_id)


def query_users_param(field: str, value: str) -> list[dict]:
    """Parameterized query helper — safe from injection."""
    return [u for u in USERS.values() if u.get(field) == value]
PYEOF

# ── app/models/user.py ────────────────────────────────────────────────
write_file app/models/user.py << 'PYEOF'
"""User model definition."""


class User:
    """Simple user model."""

    def __init__(self, user_id: int, name: str, email: str):
        self.id = user_id
        self.name = name
        self.email = email

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "email": self.email}

    def __repr__(self) -> str:
        return f"User(id={self.id}, name={self.name!r})"
PYEOF

# ── app/models/product.py ─────────────────────────────────────────────
write_file app/models/product.py << 'PYEOF'
"""Product model definition."""


class Product:
    """Simple product model."""

    def __init__(self, product_id: int, name: str, price: float):
        self.id = product_id
        self.name = name
        self.price = price

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "price": self.price}

    def __repr__(self) -> str:
        return f"Product(id={self.id}, name={self.name!r})"
PYEOF

# ── app/utils/__init__.py ─────────────────────────────────────────────
write_file app/utils/__init__.py << 'PYEOF'
"""Utility modules."""
PYEOF

# ── app/utils/formatting.py ───────────────────────────────────────────
write_file app/utils/formatting.py << 'PYEOF'
"""Formatting utilities."""


def fmt_currency(amount: float) -> str:
    """Format a number as USD currency string."""
    return f"${amount:,.2f}"


def fmt_percentage(value: float) -> str:
    """Format a decimal as a percentage string."""
    return f"{value * 100:.1f}%"


def truncate(text: str, max_len: int = 50) -> str:
    """Truncate text to max_len, appending '...' if needed."""
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."
PYEOF

# ── app/utils/validation.py ───────────────────────────────────────────
write_file app/utils/validation.py << 'PYEOF'
"""Input validation utilities."""
import re


def validate_email(e: str) -> bool:
    """Return True if the string looks like a valid email."""
    pattern = r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"
    return bool(re.match(pattern, e))


def validate_positive_int(value) -> bool:
    """Return True if value is a positive integer."""
    return isinstance(value, int) and value > 0


def validate_price(price) -> bool:
    """Return True if price is a non-negative number."""
    return isinstance(price, (int, float)) and price >= 0
PYEOF

# ── app/utils/auth.py ─────────────────────────────────────────────────
write_file app/utils/auth.py << 'PYEOF'
"""Authentication utilities."""

VALID_TOKENS = {"tok_admin_001", "tok_user_002", "tok_service_003"}


def require_auth(token: str) -> None:
    """Raise if token is invalid. Call at start of every route."""
    if token not in VALID_TOKENS:
        raise PermissionError(f"Invalid or missing auth token: {token!r}")


def is_admin(token: str) -> bool:
    """Check if token has admin privileges."""
    return token == "tok_admin_001"
PYEOF
}


###########################################################################
#              CASE 1: null_deref_001                                     #
###########################################################################
echo "=== Case 1: null_deref_001 ==="
write_base_files
commit_all "bench: null_deref_001 base state"
git tag "bench/null_deref_001/base"

# HEAD: add get_user_display_name with null deref + clean rename in formatting.py
write_file app/services/user_service.py << 'PYEOF'
"""User service — business logic for user operations."""
from app.models import database as db


def get_user_profile(user_id: int) -> dict | None:
    """Return user profile dict or None if not found."""
    user = db.find_user(user_id)
    if user is None:
        return None
    return {
        "id": user["id"],
        "name": user["name"],
        "email": user["email"],
    }


def list_all_users() -> list[dict]:
    """Return all users."""
    return list(db.USERS.values())


def create_user(payload: dict) -> dict:
    """Create a new user and return it."""
    new_id = max(db.USERS.keys(), default=0) + 1
    user = {"id": new_id, "name": payload["name"], "email": payload["email"]}
    db.USERS[new_id] = user
    return user


def get_user_display_name(user_id: int) -> str:
    """Return the display name for a user.

    BUG: db.find_user can return None, but we access .name
    without checking.
    """
    user = db.find_user(user_id)
    # Missing null check — will raise AttributeError if user_id not found
    return user["name"]
PYEOF

write_file app/utils/formatting.py << 'PYEOF'
"""Formatting utilities."""


def format_display_name(first: str, last: str) -> str:
    """Format a full display name from parts."""
    return f"{first} {last}".strip()


def fmt_currency(amount: float) -> str:
    """Format a number as USD currency string."""
    return f"${amount:,.2f}"


def fmt_percentage(value: float) -> str:
    """Format a decimal as a percentage string."""
    return f"{value * 100:.1f}%"


def truncate(text: str, max_len: int = 50) -> str:
    """Truncate text to max_len, appending '...' if needed."""
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."
PYEOF

commit_all "bench: null_deref_001 head — add get_user_display_name (null deref bug)"
git tag "bench/null_deref_001/head"


###########################################################################
#              CASE 2: sql_injection_002                                  #
###########################################################################
echo "=== Case 2: sql_injection_002 ==="
write_base_files
commit_all "bench: sql_injection_002 base state"
git tag "bench/sql_injection_002/base"

# HEAD: add search_users with f-string SQL + clean field on User model
write_file app/services/user_service.py << 'PYEOF'
"""User service — business logic for user operations."""
from app.models import database as db


def get_user_profile(user_id: int) -> dict | None:
    """Return user profile dict or None if not found."""
    user = db.find_user(user_id)
    if user is None:
        return None
    return {
        "id": user["id"],
        "name": user["name"],
        "email": user["email"],
    }


def list_all_users() -> list[dict]:
    """Return all users."""
    return list(db.USERS.values())


def create_user(payload: dict) -> dict:
    """Create a new user and return it."""
    new_id = max(db.USERS.keys(), default=0) + 1
    user = {"id": new_id, "name": payload["name"], "email": payload["email"]}
    db.USERS[new_id] = user
    return user


def search_users(query: str) -> list[dict]:
    """Search users by name.

    BUG: Uses f-string interpolation to build a SQL-style query
    instead of parameterized queries — classic SQL injection vector.
    """
    # Simulating a SQL query built via string interpolation (UNSAFE)
    sql = f"SELECT * FROM users WHERE name LIKE '%{query}%'"
    # In a real DB this would be exploitable; here we just filter the dict
    return [
        u for u in db.USERS.values()
        if query.lower() in u["name"].lower()
    ]
PYEOF

write_file app/models/user.py << 'PYEOF'
"""User model definition."""


class User:
    """Simple user model."""

    def __init__(self, user_id: int, name: str, email: str, role: str = "user"):
        self.id = user_id
        self.name = name
        self.email = email
        self.role = role

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "email": self.email,
            "role": self.role,
        }

    def __repr__(self) -> str:
        return f"User(id={self.id}, name={self.name!r}, role={self.role!r})"
PYEOF

commit_all "bench: sql_injection_002 head — add search_users (SQL injection bug)"
git tag "bench/sql_injection_002/head"


###########################################################################
#              CASE 3: off_by_one_003                                     #
###########################################################################
echo "=== Case 3: off_by_one_003 ==="
write_base_files
commit_all "bench: off_by_one_003 base state"
git tag "bench/off_by_one_003/base"

# HEAD: add get_product_range with off-by-one + clean validation helper
write_file app/services/product_service.py << 'PYEOF'
"""Product service — business logic for product operations."""
from app.models import database as db


def get_product(product_id: int) -> dict | None:
    """Return a single product or None."""
    return db.find_product(product_id)


def get_products_page(page: int, page_size: int) -> list[dict]:
    """Return a page of products (1-indexed page number)."""
    all_products = list(db.PRODUCTS.values())
    start = (page - 1) * page_size
    end = start + page_size
    return all_products[start:end]


def list_all_products() -> list[dict]:
    """Return every product."""
    return list(db.PRODUCTS.values())


def get_product_range(start: int, end: int) -> list[dict]:
    """Return products from index ``start`` up to (exclusive) ``end``.

    BUG: Uses ``range(start, end + 1)`` which includes one extra
    element beyond the intended exclusive upper bound.  The list is
    0-indexed, so ``end`` should NOT be incremented.
    """
    all_products = list(db.PRODUCTS.values())
    # Off-by-one: end is supposed to be exclusive, but +1 makes it inclusive
    indices = range(start, end + 1)
    return [all_products[i] for i in indices if i < len(all_products)]
PYEOF

write_file app/utils/validation.py << 'PYEOF'
"""Input validation utilities."""
import re


def validate_email(e: str) -> bool:
    """Return True if the string looks like a valid email."""
    pattern = r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"
    return bool(re.match(pattern, e))


def validate_positive_int(value) -> bool:
    """Return True if value is a positive integer."""
    return isinstance(value, int) and value > 0


def validate_price(price) -> bool:
    """Return True if price is a non-negative number."""
    return isinstance(price, (int, float)) and price >= 0


def validate_page_params(page: int, page_size: int) -> bool:
    """Return True if pagination parameters are valid."""
    return (
        isinstance(page, int) and page >= 1
        and isinstance(page_size, int) and 1 <= page_size <= 100
    )
PYEOF

commit_all "bench: off_by_one_003 head — add get_product_range (off-by-one bug)"
git tag "bench/off_by_one_003/head"


###########################################################################
#              CASE 4: race_condition_004                                 #
###########################################################################
echo "=== Case 4: race_condition_004 ==="
write_base_files
commit_all "bench: race_condition_004 base state"
git tag "bench/race_condition_004/base"

# HEAD: add process_concurrent_orders without lock + clean log helper
write_file app/services/order_service.py << 'PYEOF'
"""Order service — business logic for order operations."""
from app.models import database as db


# In-memory inventory tracker
inventory: dict[int, int] = {1: 50, 2: 30, 3: 100}


def create_order(payload: dict) -> dict:
    """Create an order after checking inventory."""
    product_id = payload["product_id"]
    quantity = payload["quantity"]
    if inventory.get(product_id, 0) < quantity:
        raise ValueError("Insufficient inventory")
    inventory[product_id] -= quantity
    new_id = max(db.ORDERS.keys(), default=0) + 1
    order = {
        "id": new_id,
        "product_id": product_id,
        "quantity": quantity,
        "status": "confirmed",
    }
    db.ORDERS[new_id] = order
    return order


def get_order(order_id: int) -> dict | None:
    """Return a single order or None."""
    return db.ORDERS.get(order_id)


def process_concurrent_orders(order_list: list[dict]) -> list[dict]:
    """Process multiple orders that may arrive concurrently.

    BUG: Reads inventory, checks availability, then decrements
    without any locking.  Concurrent calls can read the same count
    and both succeed, overselling inventory.
    """
    results = []
    for order in order_list:
        product_id = order["product_id"]
        quantity = order["quantity"]
        # TOCTOU race: read and check are not atomic with the decrement
        current_stock = inventory.get(product_id, 0)
        if current_stock >= quantity:
            # Another thread could have decremented between check and here
            inventory[product_id] = current_stock - quantity
            results.append({"product_id": product_id, "status": "confirmed"})
        else:
            results.append({"product_id": product_id, "status": "rejected"})
    return results
PYEOF

write_file app/utils/formatting.py << 'PYEOF'
"""Formatting utilities."""


def fmt_currency(amount: float) -> str:
    """Format a number as USD currency string."""
    return f"${amount:,.2f}"


def fmt_percentage(value: float) -> str:
    """Format a decimal as a percentage string."""
    return f"{value * 100:.1f}%"


def truncate(text: str, max_len: int = 50) -> str:
    """Truncate text to max_len, appending '...' if needed."""
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def fmt_log_entry(level: str, message: str) -> str:
    """Format a structured log entry string."""
    from datetime import datetime, timezone
    ts = datetime.now(timezone.utc).isoformat()
    return f"[{ts}] {level.upper()}: {message}"
PYEOF

commit_all "bench: race_condition_004 head — add process_concurrent_orders (race bug)"
git tag "bench/race_condition_004/head"


###########################################################################
#              CASE 5: clean_refactor_005                                 #
###########################################################################
echo "=== Case 5: clean_refactor_005 ==="
write_base_files
commit_all "bench: clean_refactor_005 base state"
git tag "bench/clean_refactor_005/base"

# HEAD: rename fmt_currency -> format_currency everywhere; rename param e -> email_address
write_file app/utils/formatting.py << 'PYEOF'
"""Formatting utilities."""


def format_currency(amount: float) -> str:
    """Format a number as USD currency string."""
    return f"${amount:,.2f}"


def fmt_percentage(value: float) -> str:
    """Format a decimal as a percentage string."""
    return f"{value * 100:.1f}%"


def truncate(text: str, max_len: int = 50) -> str:
    """Truncate text to max_len, appending '...' if needed."""
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."
PYEOF

write_file app/utils/validation.py << 'PYEOF'
"""Input validation utilities."""
import re


def validate_email(email_address: str) -> bool:
    """Return True if the string looks like a valid email."""
    pattern = r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"
    return bool(re.match(pattern, email_address))


def validate_positive_int(value) -> bool:
    """Return True if value is a positive integer."""
    return isinstance(value, int) and value > 0


def validate_price(price) -> bool:
    """Return True if price is a non-negative number."""
    return isinstance(price, (int, float)) and price >= 0
PYEOF

commit_all "bench: clean_refactor_005 head — rename fmt_currency and param (clean)"
git tag "bench/clean_refactor_005/head"


###########################################################################
#              CASE 6: auth_bypass_006                                    #
###########################################################################
echo "=== Case 6: auth_bypass_006 ==="
write_base_files
commit_all "bench: auth_bypass_006 base state"
git tag "bench/auth_bypass_006/base"

# HEAD: add delete_user without auth check + clean health_check route
write_file app/routes/users.py << 'PYEOF'
"""User route handlers."""
from app.services import user_service
from app.utils import auth


def get_user(user_id: int, token: str) -> dict:
    """GET /users/{user_id}"""
    auth.require_auth(token)
    user = user_service.get_user_profile(user_id)
    if user is None:
        return {"error": "not found", "status": 404}
    return {"data": user, "status": 200}


def list_users(token: str) -> dict:
    """GET /users"""
    auth.require_auth(token)
    users = user_service.list_all_users()
    return {"data": users, "status": 200}


def create_user(payload: dict, token: str) -> dict:
    """POST /users"""
    auth.require_auth(token)
    user = user_service.create_user(payload)
    return {"data": user, "status": 201}


def delete_user(user_id: int, token: str) -> dict:
    """DELETE /users/{user_id}

    BUG: Forgets to call auth.require_auth(token) before
    performing the deletion — any caller can delete any user.
    """
    from app.models import database as db
    if user_id not in db.USERS:
        return {"error": "not found", "status": 404}
    del db.USERS[user_id]
    return {"message": "deleted", "status": 200}


def health_check() -> dict:
    """GET /health — no auth required."""
    return {"status": "ok"}
PYEOF

commit_all "bench: auth_bypass_006 head — add delete_user (missing auth check)"
git tag "bench/auth_bypass_006/head"


###########################################################################
#              CASE 7: perf_n_plus_1_007                                  #
###########################################################################
echo "=== Case 7: perf_n_plus_1_007 ==="
write_base_files
commit_all "bench: perf_n_plus_1_007 base state"
git tag "bench/perf_n_plus_1_007/base"

# HEAD: add get_order_summaries with N+1 query + clean constants in config.py
write_file app/services/order_service.py << 'PYEOF'
"""Order service — business logic for order operations."""
from app.models import database as db


# In-memory inventory tracker
inventory: dict[int, int] = {1: 50, 2: 30, 3: 100}


def create_order(payload: dict) -> dict:
    """Create an order after checking inventory."""
    product_id = payload["product_id"]
    quantity = payload["quantity"]
    if inventory.get(product_id, 0) < quantity:
        raise ValueError("Insufficient inventory")
    inventory[product_id] -= quantity
    new_id = max(db.ORDERS.keys(), default=0) + 1
    order = {
        "id": new_id,
        "product_id": product_id,
        "quantity": quantity,
        "status": "confirmed",
    }
    db.ORDERS[new_id] = order
    return order


def get_order(order_id: int) -> dict | None:
    """Return a single order or None."""
    return db.ORDERS.get(order_id)


def get_order_summaries() -> list[dict]:
    """Build a summary for every order, including product name.

    BUG: Calls db.find_product inside the loop for each order
    (N+1 query pattern).  Should batch-load all needed products
    before the loop.
    """
    summaries = []
    for order_id, order in db.ORDERS.items():
        # N+1: individual DB lookup per order instead of batch
        product = db.find_product(order["product_id"])
        product_name = product["name"] if product else "Unknown"
        summaries.append({
            "order_id": order_id,
            "product_name": product_name,
            "quantity": order["quantity"],
            "status": order["status"],
        })
    return summaries
PYEOF

write_file app/config.py << 'PYEOF'
"""Application configuration."""

APP_NAME = "benchmark-app"
VERSION = "0.1.0"
DEBUG = False
MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 20

# Order processing constants
ORDER_STATUS_PENDING = "pending"
ORDER_STATUS_CONFIRMED = "confirmed"
ORDER_STATUS_CANCELLED = "cancelled"
ORDER_STATUS_SHIPPED = "shipped"
PYEOF

commit_all "bench: perf_n_plus_1_007 head — add get_order_summaries (N+1 bug)"
git tag "bench/perf_n_plus_1_007/head"


###########################################################################
#                          SUMMARY                                        #
###########################################################################
echo ""
echo "════════════════════════════════════════════════════════════════"
echo "  Fixture repo created at: $REPO_DIR"
echo "════════════════════════════════════════════════════════════════"
echo ""
echo "Tags:"
git tag -l 'bench/*' | sort
echo ""
echo "Done."
