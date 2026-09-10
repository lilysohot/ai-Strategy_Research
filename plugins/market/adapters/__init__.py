"""adapters 层：把供应商响应解析成领域对象（业务语义在这一层）。"""

from plugins.market.adapters.base import as_of_ms, extract_items, guard_batch, now_ms, num
from plugins.market.adapters.fuyao_rest import FuyaoRestAdapter
from plugins.market.adapters.mock import MockAdapter

__all__ = [
    "FuyaoRestAdapter",
    "MockAdapter",
    "as_of_ms",
    "extract_items",
    "guard_batch",
    "now_ms",
    "num",
]
