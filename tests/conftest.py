"""Release native UI test resources before another test starts worker threads."""
from __future__ import annotations

import gc

import pytest


_TK_TEST = pytest.StashKey[bool]()


@pytest.fixture
def tk_main_thread_cleanup(request):
    request.node.stash[_TK_TEST] = True


@pytest.hookimpl(wrapper=True)
def pytest_runtest_protocol(item, nextitem):
    result = yield
    if item.stash.get(_TK_TEST, False):
        # Fixture teardown alone is too early: pytest still owns the yielded App
        # through item.funcargs. The protocol clears those references last. Tk
        # image/variable cycles must then be collected on their creating thread,
        # before a later engine worker can trigger automatic garbage collection.
        gc.collect()
    return result
