---
paths:
  - "**/*.py"
  - "**/*.pyi"
---

# Python conventions

Read this rule when a `.py` file is read or edited; agents that
review Python from a diff read this file explicitly. PEP 8 and Google's
Python style guide (links at the end) are the baseline; this file holds what
they leave open, the few places it deviates, and what a trading engine adds.
Where it is silent, write idiomatic Python and match the repo: its
formatter, linter, type checker and test command win over anything here.
Engine specifics live in `quant-trading-crypto-struct`, domain rules in
`quant-trading`.

## Money and numbers

- `decimal.Decimal` for prices, quantities, balances and PnL in decision or
  accounting logic; `float` only at the wire or feed boundary, converted at
  ingress.
- Build a `Decimal` from a string or an int, never a float:
  `Decimal("0.1")`, or `Decimal(str(px))` at ingress. `Decimal(0.1)` carries
  the binary float error in.
- Don't mix `Decimal` and `float`: arithmetic raises `TypeError`, and a
  comparison silently uses the float's binary value.
- Round explicitly with `quantize()` and a named rounding mode where the
  venue requires it (at order send), not along the way.
- Absence is `None`, annotated `X | None`, tested with `is None` and
  handled; never a sentinel `0` or `-1`, and never truthiness: `if not qty`
  and `qty or 0` read a legitimate zero price, size or position as missing,
  and `Decimal("0")` is falsy too (ruff `E711`, `E712`).
- A range check is chained (`0 <= p <= 1`): the split form `p < 0 or p > 1`
  is false for NaN, which a feed can send.

## Types and data

- Type annotations on every new or changed signature: parameters as abstract
  containers (`Sequence`, `Mapping`) with their type arguments, optionals as
  explicit `X | None` (ruff `RUF013`); run the repo's mypy or pyright when it
  configures one.
- Frozen dataclasses or `NamedTuple` for value objects: events, quotes,
  fills, config.
- `typing.Protocol` for injected dependencies — venue client, clock, random
  source — so tests swap in fakes without monkeypatching.
- No mutable or call-evaluated default argument (`b=[]`, `ts=time.time()`,
  `cfg=load()`): defaults run once at import, so the list is shared and the
  timestamp frozen. Default to `None` and fill in the body (ruff `B006`,
  `B008`).
- No mutable module-level state (a client, a cache, a position dict): it
  binds the process to one instance and makes tests order-dependent. Pass it
  in; when unavoidable, name it `_private`, expose it through a function and
  say why in a comment (ruff `PLW0603`).
- `@staticmethod` is a module-level function; `@classmethod` only for a
  named constructor. A `@property` is cheap and side-effect free, or it is a
  method.

## Errors

- No bare `except:` and no `except Exception: pass`. Catch the narrowest
  exception something here can act on, around the one call that raises it (a
  wide `try` body catches the right exception from the wrong line); let the
  rest propagate. `except Exception` only to re-raise or at an isolation
  point such as a task's outermost block, where it logs and records the
  failure.
- Never turn an error into a default on a value that matters:
  `.get(key, 0)` on a position, `or 0` on a price, or a caught exception
  returning `None` that callers read as "no position".
- Re-raise with the cause attached: `raise OrderRejected(...) from err`. Own
  exception types subclass a built-in and end in `Error`.
- `assert` never guards a precondition or a risk limit: `-O` strips it, so
  the code must survive its removal. Raise `ValueError` or the domain error;
  `assert` is for tests and for invariants the code does not depend on (ruff
  `S101` outside tests).
- An error or alert message states the condition that actually failed with
  the offending value marked (`f"not a probability: {p=}"`), never a cause
  it did not verify.

## Async

- Never block the event loop inside `async def`: no `time.sleep`,
  `requests`, or sync DB and file I/O. Use `asyncio.sleep`, an async client,
  or `asyncio.to_thread`.
- Keep a reference to every task you create and handle its exception: the
  loop holds tasks weakly, so a fire-and-forget `create_task` can vanish
  mid-flight and its exception is never seen.
- Bounded queues by default (`asyncio.Queue(maxsize=...)`); decide
  explicitly what a full queue does. Across threads (`to_thread`, a feed
  reader) the same: a bounded `queue.Queue`, never a shared dict or list,
  since built-in operations are not guaranteed atomic.

## Modules, resources, logging and secrets

- Nothing connects, reads config or starts a loop at import time: an entry
  point keeps that in `main()` under `if __name__ == "__main__":`, so every
  module imports cleanly in tests and tooling. Absolute imports only (ruff
  `TID252`).
- Context managers (`with` / `async with`) for sockets, files, sessions and
  locks.
- `logging` with a module-level `logger = logging.getLogger(__name__)`, not
  `print`, in library and service code; CLIs and scripts may print their
  output. The message is always a literal pattern with lazy arguments —
  `logger.info("filled %s", qty)`, never an f-string — so a disabled level
  renders nothing and the pattern stays queryable (ruff `G004`).
- Never log API keys, secrets, signatures or auth headers.
- Read secrets from the environment or secret store once at startup and fail
  fast when one is missing — never a hard-coded fallback.

## Dependencies

- Use the repo's environment and tool (its venv, `uv`, `poetry`, the
  internal PyPI); never `pip install` into the system interpreter. A new
  dependency needs a reason, pinned the way the repo pins.

## Testing

- pytest, through the repo's documented command from its venv.
- Unit tests make no network calls and read no wall clock: inject the clock
  and the venue client, and seed every random source.
- Cover the rejection and error branches, not only the happy path; tests are
  named `test_<unit>_<state>` with no docstring that repeats the name.

## References

- Google Python style guide: https://google.github.io/styleguide/pyguide.html ; PEP 8: https://peps.python.org/pep-0008/
- Ruff rules: https://docs.astral.sh/ruff/rules/ ; asyncio tasks: https://docs.python.org/3/library/asyncio-task.html
