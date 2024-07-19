from .base import (
    Store,
    ContextStore,
    Driver,
    DriverClient,
    drivercall,
    streamingdrivercall,
)
from .registry import _registry


def register(cls):
    _registry.register(cls)


def get(name):
    return _registry.get(name)


def __iter__():
    return iter(_registry)


def __len__():
    return len(_registry)


def __getitem__(name):
    return _registry.get(name)


def __contains__(name):
    return name in _registry


__all__ = [
    "Store",
    "ContextStore",
    "Driver",
    "DriverClient",
    "drivercall",
    "streamingdrivercall",
]
