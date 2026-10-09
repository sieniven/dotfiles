---
paths:
  - "**/*.py"
  - "**/*.pyi"
---

# Python conventions

Loaded automatically whenever a `.py` file is read or edited; agents that
review Python from a diff read this file explicitly. These are deviations
from textbook defaults — where this file is silent, write idiomatic Python
and match the repo: its formatter, linter, type checker and test command win
over anything here. Engine specifics live in `quant-trading-crypto-struct`,
domain rules in `quant-trading`.

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

## Types and data

- Type annotations on every new or changed function signature; run the
  repo's mypy or pyright when it configures one.
- Frozen dataclasses or `NamedTuple` for value objects: events, quotes,
  fills, config.
- `typing.Protocol` for injected dependencies — venue client, clock, random
  source — so tests swap in fakes without monkeypatching.
- Absence is `None`, annotated `X | None` and handled — never a sentinel `0`
  or `-1` for a price, quantity or position.

## Errors

- No bare `except:` and no `except Exception: pass`. Catch the narrowest
  exception something here can act on; let the rest propagate.
- Never turn an error into a default on a value that matters:
  `.get(key, 0)` on a position, `or 0` on a price, or a caught exception
  returning `None` that callers read as "no position".
- Re-raise with the cause attached: `raise OrderRejected(...) from err`.

## Async

- Never block the event loop inside `async def`: no `time.sleep`,
  `requests`, or sync DB and file I/O. Use `asyncio.sleep`, an async client,
  or `asyncio.to_thread`.
- Keep a reference to every task you create and handle its exception: the
  loop holds tasks weakly, so a fire-and-forget `create_task` can vanish
  mid-flight and its exception is never seen.
- Bounded queues by default (`asyncio.Queue(maxsize=...)`); decide
  explicitly what a full queue does.

## Resources, logging and secrets

- Context managers (`with` / `async with`) for sockets, files, sessions and
  locks.
- `logging` with a module-level `logger = logging.getLogger(__name__)`, not
  `print`, in library and service code; CLIs and scripts may print their
  output. Pass arguments lazily on hot paths: `logger.info("filled %s", qty)`.
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
- Cover the rejection and error branches, not only the happy path.
