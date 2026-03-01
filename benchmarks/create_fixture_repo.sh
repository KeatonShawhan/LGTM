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
#              CASE 8: js_promise_rejection_008                           #
###########################################################################
echo "=== Case 8: js_promise_rejection_008 ==="
write_base_files
commit_all "bench: js_promise_rejection_008 base state"
git tag "bench/js_promise_rejection_008/base"

# HEAD: add fetchUserData with unhandled promise rejection + clean helper
write_file app_js/src/services/userService.js << 'JSEOF'
/**
 * User service — async operations for user data.
 */

const db = require('../db');

/**
 * Fetch a user by ID with retry logic.
 * @param {number} userId
 * @returns {Promise<Object>}
 */
async function getUserById(userId) {
  const user = await db.findUser(userId);
  if (!user) {
    throw new Error(`User ${userId} not found`);
  }
  return user;
}

/**
 * Fetch user data from remote API and cache it locally.
 *
 * BUG: The inner async callback passed to setTimeout is never
 * awaited and has no try/catch.  If fetchRemote() rejects,
 * the rejection is unhandled and will crash Node >=15 or
 * silently swallow the error in older versions.
 *
 * @param {number} userId
 * @param {Function} fetchRemote
 */
function fetchUserData(userId, fetchRemote) {
  // Unhandled promise rejection: async callback inside setTimeout
  setTimeout(async () => {
    const data = await fetchRemote(userId);
    await db.cacheUser(userId, data);
  }, 0);
}

module.exports = { getUserById, fetchUserData };
JSEOF

write_file app_js/src/utils/format.js << 'JSEOF'
/**
 * Formatting utilities for the JS service.
 */

/**
 * Format a user object for API response.
 * @param {Object} user
 * @returns {Object}
 */
function formatUserResponse(user) {
  return {
    id: user.id,
    name: user.name,
    email: user.email,
    createdAt: user.created_at,
  };
}

/**
 * Truncate a string to maxLen characters.
 * @param {string} str
 * @param {number} maxLen
 * @returns {string}
 */
function truncate(str, maxLen = 50) {
  if (str.length <= maxLen) return str;
  return str.slice(0, maxLen - 3) + '...';
}

module.exports = { formatUserResponse, truncate };
JSEOF

commit_all "bench: js_promise_rejection_008 head — add fetchUserData (unhandled rejection)"
git tag "bench/js_promise_rejection_008/head"


###########################################################################
#              CASE 9: js_prototype_pollution_009                         #
###########################################################################
echo "=== Case 9: js_prototype_pollution_009 ==="
write_base_files
commit_all "bench: js_prototype_pollution_009 base state"
git tag "bench/js_prototype_pollution_009/base"

# HEAD: add mergeConfig with prototype pollution + clean deepClone helper
write_file app_js/src/utils/merge.js << 'JSEOF'
/**
 * Object merge utilities.
 */

/**
 * Safely clone a plain object (no prototype traversal).
 * @param {Object} obj
 * @returns {Object}
 */
function deepClone(obj) {
  return JSON.parse(JSON.stringify(obj));
}

/**
 * Merge user-supplied config into a defaults object.
 *
 * BUG: Iterates over all keys in the user-supplied object and
 * assigns them directly — including __proto__, constructor, or
 * prototype.  An attacker can pass {"__proto__": {"isAdmin": true}}
 * to pollute Object.prototype for the entire process.
 *
 * @param {Object} defaults
 * @param {Object} userConfig
 * @returns {Object}
 */
function mergeConfig(defaults, userConfig) {
  const result = Object.assign({}, defaults);
  for (const key in userConfig) {
    // BUG: no hasOwnProperty guard and no key denylist
    result[key] = userConfig[key];
  }
  return result;
}

module.exports = { deepClone, mergeConfig };
JSEOF

write_file app_js/src/services/userService.js << 'JSEOF'
/**
 * User service — async operations for user data.
 */

const db = require('../db');

/**
 * Fetch a user by ID.
 * @param {number} userId
 * @returns {Promise<Object>}
 */
async function getUserById(userId) {
  const user = await db.findUser(userId);
  if (!user) {
    throw new Error(`User ${userId} not found`);
  }
  return user;
}

module.exports = { getUserById };
JSEOF

commit_all "bench: js_prototype_pollution_009 head — add mergeConfig (prototype pollution)"
git tag "bench/js_prototype_pollution_009/head"


###########################################################################
#              CASE 10: ts_type_assertion_010                             #
###########################################################################
echo "=== Case 10: ts_type_assertion_010 ==="
write_base_files
commit_all "bench: ts_type_assertion_010 base state"
git tag "bench/ts_type_assertion_010/base"

# HEAD: add parseApiResponse with unsafe 'as any' cast + clean type guard
write_file app_js/src/utils/types.ts << 'TSEOF'
/**
 * Type utilities for API response handling.
 */

export interface UserRecord {
  id: number;
  name: string;
  email: string;
}

/**
 * Type guard: verify an unknown value conforms to UserRecord.
 */
export function isUserRecord(value: unknown): value is UserRecord {
  return (
    typeof value === 'object' &&
    value !== null &&
    typeof (value as Record<string, unknown>).id === 'number' &&
    typeof (value as Record<string, unknown>).name === 'string' &&
    typeof (value as Record<string, unknown>).email === 'string'
  );
}

/**
 * Parse an API response payload into a UserRecord.
 *
 * BUG: Casts the raw JSON payload directly to UserRecord via
 * `as any` without any runtime validation.  If the API returns
 * unexpected data (null, wrong shape, missing fields), downstream
 * code will receive a broken object and TypeScript's type safety
 * provides no protection because the cast bypasses the type checker.
 *
 * @param rawPayload - raw value from JSON.parse or fetch response
 * @returns UserRecord (potentially malformed at runtime)
 */
export function parseApiResponse(rawPayload: unknown): UserRecord {
  // Unsafe: 'as any' discards all type information and skips validation
  const user = rawPayload as any;
  return {
    id: user.id,
    name: user.name,
    email: user.email,
  };
}
TSEOF

write_file app_js/src/services/userService.js << 'JSEOF'
/**
 * User service — async operations for user data.
 */

const db = require('../db');

/**
 * Fetch a user by ID.
 * @param {number} userId
 * @returns {Promise<Object>}
 */
async function getUserById(userId) {
  const user = await db.findUser(userId);
  if (!user) {
    throw new Error(`User ${userId} not found`);
  }
  return user;
}

module.exports = { getUserById };
JSEOF

commit_all "bench: ts_type_assertion_010 head — add parseApiResponse (unsafe 'as any')"
git tag "bench/ts_type_assertion_010/head"


###########################################################################
#              CASE 11: js_clean_refactor_011                             #
###########################################################################
echo "=== Case 11: js_clean_refactor_011 ==="
write_base_files
# Set up a base with the original verbose response builder
write_file app_js/src/routes/orders.js << 'JSEOF'
/**
 * Order route handlers.
 */

const db = require('../db');
const auth = require('../utils/auth');

/**
 * GET /orders/:id
 */
async function getOrder(req, res) {
  auth.requireAuth(req.token);
  const order = await db.findOrder(req.params.id);
  if (!order) {
    res.status(404).json({ error: 'not found' });
    return;
  }
  const productName = order.product ? order.product.name : 'Unknown';
  const formattedTotal = '$' + (order.quantity * order.unit_price).toFixed(2);
  const statusLabel = order.status.charAt(0).toUpperCase() + order.status.slice(1);
  res.status(200).json({
    id: order.id,
    productName: productName,
    total: formattedTotal,
    status: statusLabel,
  });
}

module.exports = { getOrder };
JSEOF

commit_all "bench: js_clean_refactor_011 base state"
git tag "bench/js_clean_refactor_011/base"

# HEAD: extract helper functions — pure refactor, no bugs introduced
write_file app_js/src/routes/orders.js << 'JSEOF'
/**
 * Order route handlers.
 */

const db = require('../db');
const auth = require('../utils/auth');

function formatTotal(quantity, unitPrice) {
  return '$' + (quantity * unitPrice).toFixed(2);
}

function capitalize(str) {
  return str.charAt(0).toUpperCase() + str.slice(1);
}

function buildOrderResponse(order) {
  return {
    id: order.id,
    productName: order.product ? order.product.name : 'Unknown',
    total: formatTotal(order.quantity, order.unit_price),
    status: capitalize(order.status),
  };
}

/**
 * GET /orders/:id
 */
async function getOrder(req, res) {
  auth.requireAuth(req.token);
  const order = await db.findOrder(req.params.id);
  if (!order) {
    res.status(404).json({ error: 'not found' });
    return;
  }
  res.status(200).json(buildOrderResponse(order));
}

module.exports = { getOrder };
JSEOF

commit_all "bench: js_clean_refactor_011 head — extract helper functions (clean refactor)"
git tag "bench/js_clean_refactor_011/head"


###########################################################################
#              CASE 12: go_goroutine_leak_012                             #
###########################################################################
echo "=== Case 12: go_goroutine_leak_012 ==="
write_base_files
commit_all "bench: go_goroutine_leak_012 base state"
git tag "bench/go_goroutine_leak_012/base"

# HEAD: add ProcessJobs with goroutine leak + clean server setup
write_file app_go/internal/handlers/jobs.go << 'GOEOF'
package handlers

import (
	"context"
	"fmt"
	"log"
)

// Job represents a unit of work to be processed.
type Job struct {
	ID      int
	Payload string
}

// processOne handles a single job.
func processOne(ctx context.Context, job Job) error {
	// Simulate work
	if job.Payload == "" {
		return fmt.Errorf("empty payload for job %d", job.ID)
	}
	log.Printf("processed job %d", job.ID)
	return nil
}

// ProcessJobs launches a goroutine per job to process them concurrently.
//
// BUG: Each goroutine is launched without any coordination mechanism
// (no WaitGroup, no done channel, no context cancellation propagation).
// If the caller returns early or the context is cancelled, the goroutines
// keep running with no way to stop them — classic goroutine leak.
func ProcessJobs(ctx context.Context, jobs []Job) {
	for _, job := range jobs {
		// BUG: goroutine launched with no WaitGroup or done-channel
		go func(j Job) {
			if err := processOne(ctx, j); err != nil {
				log.Printf("job %d failed: %v", j.ID, err)
			}
		}(job)
	}
	// Returns immediately; goroutines may outlive the caller
}
GOEOF

write_file app_go/cmd/server/main.go << 'GOEOF'
package main

import (
	"log"
	"net/http"
)

func main() {
	mux := http.NewServeMux()
	mux.HandleFunc("/healthz", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("ok"))
	})
	log.Println("starting server on :8080")
	if err := http.ListenAndServe(":8080", mux); err != nil {
		log.Fatalf("server error: %v", err)
	}
}
GOEOF

commit_all "bench: go_goroutine_leak_012 head — add ProcessJobs (goroutine leak)"
git tag "bench/go_goroutine_leak_012/head"


###########################################################################
#              CASE 13: go_error_ignored_013                              #
###########################################################################
echo "=== Case 13: go_error_ignored_013 ==="
write_base_files
commit_all "bench: go_error_ignored_013 base state"
git tag "bench/go_error_ignored_013/base"

# HEAD: add SaveSnapshot with ignored error + clean read helper
write_file app_go/internal/store/cache.go << 'GOEOF'
package store

import (
	"encoding/json"
	"os"
)

// CacheEntry holds a serialised value with a key.
type CacheEntry struct {
	Key   string
	Value interface{}
}

// LoadSnapshot reads the on-disk cache file into entries.
func LoadSnapshot(path string) ([]CacheEntry, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	var entries []CacheEntry
	if err := json.Unmarshal(data, &entries); err != nil {
		return nil, err
	}
	return entries, nil
}

// SaveSnapshot persists entries to disk.
//
// BUG: os.WriteFile returns an error that is explicitly discarded
// with `_`.  If the write fails (disk full, permission denied, etc.)
// the caller receives no signal and assumes the snapshot was saved.
func SaveSnapshot(path string, entries []CacheEntry) {
	data, err := json.Marshal(entries)
	if err != nil {
		return
	}
	// BUG: error from WriteFile is silently discarded
	_ = os.WriteFile(path, data, 0644)
}
GOEOF

write_file app_go/cmd/server/main.go << 'GOEOF'
package main

import (
	"log"
	"net/http"
)

func main() {
	mux := http.NewServeMux()
	mux.HandleFunc("/healthz", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("ok"))
	})
	log.Println("starting server on :8080")
	if err := http.ListenAndServe(":8080", mux); err != nil {
		log.Fatalf("server error: %v", err)
	}
}
GOEOF

commit_all "bench: go_error_ignored_013 head — add SaveSnapshot (ignored error return)"
git tag "bench/go_error_ignored_013/head"


###########################################################################
#              CASE 14: go_nil_map_write_014                              #
###########################################################################
echo "=== Case 14: go_nil_map_write_014 ==="
write_base_files
commit_all "bench: go_nil_map_write_014 base state"
git tag "bench/go_nil_map_write_014/base"

# HEAD: add WorkerPool with nil map panic + clean server main
write_file app_go/internal/worker/processor.go << 'GOEOF'
package worker

import "fmt"

// Result holds the outcome of processing a single task.
type Result struct {
	TaskID int
	Output string
	Err    error
}

// WorkerPool processes a list of task IDs and collects results.
//
// BUG: `results` is declared as `var results map[int]Result` which
// initialises it to nil.  Writing to a nil map (results[id] = ...)
// causes a runtime panic: "assignment to entry in nil map".
// The fix is to use `results := make(map[int]Result)`.
func WorkerPool(taskIDs []int, process func(int) (string, error)) map[int]Result {
	// BUG: nil map — writing to it will panic at runtime
	var results map[int]Result
	for _, id := range taskIDs {
		output, err := process(id)
		results[id] = Result{TaskID: id, Output: output, Err: err}
	}
	return results
}

// Describe formats a Result for logging.
func Describe(r Result) string {
	if r.Err != nil {
		return fmt.Sprintf("task %d failed: %v", r.TaskID, r.Err)
	}
	return fmt.Sprintf("task %d ok: %s", r.TaskID, r.Output)
}
GOEOF

write_file app_go/cmd/server/main.go << 'GOEOF'
package main

import (
	"log"
	"net/http"
)

func main() {
	mux := http.NewServeMux()
	mux.HandleFunc("/healthz", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("ok"))
	})
	log.Println("starting server on :8080")
	if err := http.ListenAndServe(":8080", mux); err != nil {
		log.Fatalf("server error: %v", err)
	}
}
GOEOF

commit_all "bench: go_nil_map_write_014 head — add WorkerPool (nil map panic)"
git tag "bench/go_nil_map_write_014/head"


###########################################################################
#              CASE 15: go_race_condition_015                             #
###########################################################################
echo "=== Case 15: go_race_condition_015 ==="
write_base_files
commit_all "bench: go_race_condition_015 base state"
git tag "bench/go_race_condition_015/base"

# HEAD: add RequestCounter with data race + clean server main
write_file app_go/internal/handlers/counter.go << 'GOEOF'
package handlers

import (
	"fmt"
	"net/http"
	"sync"
)

// RequestCounter tracks the number of handled HTTP requests.
//
// BUG: `count` is an ordinary int incremented by multiple goroutines
// without synchronisation.  Concurrent HTTP handlers will race on
// this field, causing lost updates and non-deterministic counts.
// The fix is to use sync/atomic or protect count with a mutex.
type RequestCounter struct {
	// BUG: unprotected shared counter — concurrent writes are a data race
	count int
	mu    sync.Mutex // declared but NOT used in Increment
}

// Increment increments the counter for each incoming request.
func (c *RequestCounter) Increment() {
	// BUG: mu is not locked; concurrent calls race on c.count
	c.count++
}

// Value returns the current count.
func (c *RequestCounter) Value() int {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.count
}

// Handler wraps an http.HandlerFunc and counts each call.
func (c *RequestCounter) Handler(next http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		c.Increment()
		next(w, r)
	}
}

// Stats returns a formatted statistics string.
func (c *RequestCounter) Stats() string {
	return fmt.Sprintf("total requests: %d", c.Value())
}
GOEOF

write_file app_go/cmd/server/main.go << 'GOEOF'
package main

import (
	"log"
	"net/http"
)

func main() {
	mux := http.NewServeMux()
	mux.HandleFunc("/healthz", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("ok"))
	})
	log.Println("starting server on :8080")
	if err := http.ListenAndServe(":8080", mux); err != nil {
		log.Fatalf("server error: %v", err)
	}
}
GOEOF

commit_all "bench: go_race_condition_015 head — add RequestCounter (data race on count)"
git tag "bench/go_race_condition_015/head"


###########################################################################
#              CASE 16: py_exception_swallow_016                          #
###########################################################################
echo "=== Case 16: py_exception_swallow_016 ==="
write_base_files
commit_all "bench: py_exception_swallow_016 base state"
git tag "bench/py_exception_swallow_016/base"

# HEAD: add import_users_from_csv with bare except + clean file reader
write_file app/services/import_service.py << 'PYEOF'
"""Import service — bulk data ingestion helpers."""
import csv
import io
from app.models import database as db


def parse_user_row(row: dict) -> dict:
    """Parse and validate a single CSV row into a user dict."""
    return {
        "name": row["name"].strip(),
        "email": row["email"].strip().lower(),
    }


def import_users_from_csv(csv_text: str) -> int:
    """Read users from CSV text and insert them into the database.

    Returns the number of successfully imported users.

    BUG: Uses a bare ``except: pass`` block which silently swallows
    every exception — including KeyboardInterrupt, SystemExit, and
    MemoryError.  If a row is malformed, a network call inside
    ``db.USERS`` mutation raises, or anything else goes wrong, the
    error is completely hidden and the caller has no way to know.
    """
    reader = csv.DictReader(io.StringIO(csv_text))
    imported = 0
    for row in reader:
        try:
            user = parse_user_row(row)
            new_id = max(db.USERS.keys(), default=0) + 1
            db.USERS[new_id] = {"id": new_id, **user}
            imported += 1
        except:  # noqa: E722  BUG: bare except swallows all exceptions
            pass
    return imported
PYEOF

write_file app/utils/csv_reader.py << 'PYEOF'
"""CSV reading helpers."""
import csv
import io


def read_csv_rows(csv_text: str) -> list[dict]:
    """Parse CSV text and return a list of row dicts."""
    reader = csv.DictReader(io.StringIO(csv_text))
    return list(reader)


def get_csv_headers(csv_text: str) -> list[str]:
    """Return column header names from CSV text."""
    reader = csv.DictReader(io.StringIO(csv_text))
    return reader.fieldnames or []
PYEOF

commit_all "bench: py_exception_swallow_016 head — add import_users_from_csv (bare except)"
git tag "bench/py_exception_swallow_016/head"


###########################################################################
#              CASE 17: py_mutable_default_arg_017                        #
###########################################################################
echo "=== Case 17: py_mutable_default_arg_017 ==="
write_base_files
commit_all "bench: py_mutable_default_arg_017 base state"
git tag "bench/py_mutable_default_arg_017/base"

# HEAD: add tag/cart functions with mutable default args + clean formatter
write_file app/services/tag_service.py << 'PYEOF'
"""Tag service — manage product tags and user shopping carts."""
from app.models import database as db


def add_tag(product_id: int, tag: str, existing_tags: list[str] = []) -> list[str]:
    """Return updated tag list for a product.

    BUG: ``existing_tags`` defaults to a mutable list literal ``[]``.
    Python creates this list once at function-definition time and
    reuses the same object across every call that omits the argument.
    Tags accumulate across calls: the second call with no
    ``existing_tags`` argument will see tags from the first call.
    """
    existing_tags.append(tag)
    return existing_tags


def build_cart(item: dict, cart: dict = {}) -> dict:
    """Add an item to a cart and return it.

    BUG: Same mutable-default-argument antipattern applied to a dict.
    All callers that omit ``cart`` share the same dict object, so
    items from previous calls accumulate invisibly.
    """
    product_id = item["product_id"]
    cart[product_id] = item
    return cart
PYEOF

write_file app/utils/tag_formatter.py << 'PYEOF'
"""Tag formatting utilities."""


def format_tag(tag: str) -> str:
    """Normalise a tag to lowercase, stripped, hyphenated."""
    return tag.strip().lower().replace(" ", "-")


def format_tag_list(tags: list[str]) -> str:
    """Return a comma-separated, sorted tag string."""
    return ", ".join(sorted(format_tag(t) for t in tags))
PYEOF

commit_all "bench: py_mutable_default_arg_017 head — add tag/cart funcs (mutable defaults)"
git tag "bench/py_mutable_default_arg_017/head"


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
