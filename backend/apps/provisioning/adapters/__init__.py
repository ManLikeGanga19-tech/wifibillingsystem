from .base import (
    ActiveSession,
    ProvisioningAdapter,
    ProvisioningAuthError,
    ProvisioningError,
    ProvisionResult,
)
from .dummy import DummyAdapter
from .mikrotik import MikroTikRestAdapter

_BACKENDS = {
    "mikrotik_rest": MikroTikRestAdapter,
    "dummy": DummyAdapter,
}


def get_adapter(router) -> ProvisioningAdapter:
    try:
        return _BACKENDS[router.provisioning_backend](router)
    except KeyError as exc:
        raise ProvisioningError(
            f"Unknown provisioning backend {router.provisioning_backend!r}"
        ) from exc


__all__ = [
    "ActiveSession",
    "DummyAdapter",
    "MikroTikRestAdapter",
    "ProvisioningAdapter",
    "ProvisioningAuthError",
    "ProvisioningError",
    "ProvisionResult",
    "get_adapter",
]
