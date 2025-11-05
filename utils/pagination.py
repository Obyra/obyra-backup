"""
Pagination utilities for OBYRA IA
Handles Flask-SQLAlchemy 3.x pagination compatibility
"""

try:
    # Flask-SQLAlchemy 3.x
    from flask_sqlalchemy.pagination import Pagination
except ImportError:
    # Flask-SQLAlchemy 2.x fallback
    try:
        from flask_sqlalchemy import Pagination
    except ImportError:
        # If all else fails, create a simple pagination class
        class Pagination:
            """Simple pagination class fallback"""
            def __init__(self, query, page, per_page, total, items):
                self.query = query
                self.page = page
                self.per_page = per_page
                self.total = total
                self.items = items
                self.pages = (total + per_page - 1) // per_page if per_page > 0 else 0
                self.has_prev = page > 1
                self.has_next = page < self.pages
                self.prev_num = page - 1 if self.has_prev else None
                self.next_num = page + 1 if self.has_next else None

            def iter_pages(self, left_edge=2, left_current=2, right_current=5, right_edge=2):
                """Iterate over page numbers"""
                last = 0
                for num in range(1, self.pages + 1):
                    if (num <= left_edge or
                        (num > self.page - left_current - 1 and num < self.page + right_current) or
                        num > self.pages - right_edge):
                        if last + 1 != num:
                            yield None
                        yield num
                        last = num


__all__ = ['Pagination']
