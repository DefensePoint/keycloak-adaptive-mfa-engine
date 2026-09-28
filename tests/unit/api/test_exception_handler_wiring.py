from src.core.exception import (
    DataValidationException,
    RateLimitException,
    RejectedAuthException,
    TimeOutException,
)


def test_exception_handlers_are_registered_before_first_asgi_scope():
    """Regression: exception handlers must be registered synchronously at
    import time (module level, right after `app = FastAPI()`), never from
    inside the async startup event.

    Starlette builds its middleware stack -- which snapshots the
    exception_handlers dict into ServerErrorMiddleware/ExceptionMiddleware --
    on the very first ASGI scope it receives, including the `lifespan` scope
    itself, which arrives before any startup-event callback runs. A handler
    registered from inside such a callback (as `server_init.py` used to do,
    calling `register_exception_handlers` from within the async `__init()`
    invoked by the "startup" event) is added to the dict one step too late:
    the middleware was already built without it, so every matching error
    silently falls through to Starlette's generic plain-text 500 instead of
    the specific status code the handler was written to return.

    This was found by manually triggering a real TimeOutException against a
    running deployment and observing HTTP 500 (Starlette's raw default, 21
    bytes of plain text) instead of the registered 408 JSON response, then
    confirmed in isolation with a minimal FastAPI app reproducing the same
    registration-timing pattern.

    Asserting registration at plain import time (rather than driving the
    full ASGI lifespan protocol here) is sufficient to guard against a
    regression: if the handlers are present in the dict before any scope is
    ever processed, they are necessarily present before the middleware stack
    is built on the first one.
    """
    import src.server_init as server_init_mod

    handlers = server_init_mod.app.exception_handlers
    assert TimeOutException in handlers
    assert RateLimitException in handlers
    assert DataValidationException in handlers
    assert RejectedAuthException in handlers
    assert Exception in handlers
