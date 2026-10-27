---
paths:
  - "**/*.js"
  - "**/*.jsx"
  - "**/*.mjs"
  - "**/*.cjs"
  - "**/package.json"
---

# JavaScript conventions

Loaded automatically whenever a JavaScript file or `package.json` is read or
edited; `~/.codex/rules/typescript.md` builds on this file for `.ts` and
`.tsx`. Google's TypeScript style guide is the baseline for both files (its
JavaScript guide is frozen and defers to it); this file holds what it
leaves open, the places it deviates, and the rules a trading desk's
frontends and Node services need. In this workspace the frontends are
Vite with React and Next.js, all ESM, and the Node code is scripts and
services; none of them ships a lint config yet, so the first change to a repo
adds one.

## Modules and packages

- ES modules only: `"type": "module"`, `.cjs` only where a tool forces it,
  never `require` and `import` in one file; built-ins imported with the
  `node:` prefix.
- One package manager per repo with its lockfile committed; CI installs with
  `npm ci` or `pnpm install --frozen-lockfile` and runs `audit`; `engines`
  pinned; a published package declares `exports`; unused dependencies are
  removed in the change that orphans them.
- Named exports everywhere a framework does not force a default (Next.js
  pages and layouts, config files; `import-x/no-default-export` with
  per-glob overrides); no `export let` (a re-exported binding does not
  update: expose a getter); no class of statics as a namespace, the module
  is the namespace. `import * as x` for many symbols from one large module,
  named imports otherwise; relative paths inside a package, the alias only
  across packages.
- Secrets never enter the repo or the bundle: `.env` files are ignored,
  `--env-file` or dotenv only in development, keys and tokens redacted at
  the logger. Only `VITE_`- or `NEXT_PUBLIC_`-prefixed variables reach the
  browser, and those are public.

## Language

- `const` by default, `let` when reassigned, never `var`; `===` always
  (`== null` is the one allowed loose comparison).
- `??` for defaults, not `||`, which swallows `0` and `""`; `?.` for optional
  access; `Object.hasOwn`, `structuredClone`, `at`, `toSorted` over their
  older forms; inputs are not mutated.
- Rest parameters, never `arguments`; arrow functions for callbacks,
  `function` or methods where `this` matters; `for...of` or array methods,
  never `for...in` over an array, and `for...of` over
  `Object.keys`/`values`/`entries` for an object (`guard-for-in`).
- A dictionary keyed at runtime is a `Map` or `Set`, not an object
  (prototype keys, string-only keys); an index signature names its key
  (`{ [orderId: string]: Order }`). Spread arrays into arrays and objects
  into objects only (`[...(cond ? xs : [])]`, never `...(cond && xs)`);
  `[]` and `{}` literals, never `Array(n)` or `new Object()`.
- A named function goes to `map`/`filter`/`forEach` wrapped in an arrow
  (`xs.map((x) => f(x))`), so the index and array never leak into an
  optional parameter (`["11", "5"].map(parseInt)` gives `[11, NaN]`;
  `unicorn/no-array-callback-reference`). An arrow whose result is
  discarded has a block body or a `void` prefix
  (`no-confusing-void-expression`).
- More than two optional parameters become one options object, destructured
  with defaults in the parameter (`{ retries = 3, signal }: Opts = {}`); a
  default never has a side effect. A bare `true`/`false` argument gets a
  `/* name= */` comment or the call becomes an options object.
- `addEventListener(x, this.f.bind(this))` can never be removed: a listener
  that must be uninstalled is an arrow-function property, every other
  callback an inline arrow. A private static method is a module-level
  function; no `this` in a static method; never patch a builtin prototype
  or the global object (`no-extend-native`).
- Naming: `UpperCamelCase` for types, classes and components,
  `lowerCamelCase` for the rest, `CONSTANT_CASE` only for module-level
  constants; acronyms as words (`orderId`, `parseHttpUrl`); no `_` prefix
  for private and no `I` prefix on an interface; a single-letter name only
  inside ten lines (`@typescript-eslint/naming-convention`). JSDoc on every
  export says what the name and signature do not, with no types in
  `@param`.

## Async

- No floating promise: every promise is awaited, returned, or explicitly
  `void`ed with a `catch`; an `async` callback inside `forEach` or an event
  handler is a bug unless it catches.
- `Promise.all` when one failure should abort the batch, `allSettled` when
  each result matters; no `await` inside a loop unless the steps are
  sequential by design; bounded fan-out through a limiter.
- Every network call has `AbortSignal.timeout(ms)` and a controller for
  cancellation; `fetch` has no default timeout and does not reject on HTTP
  errors, so `response.ok` is checked.
- No synchronous filesystem or crypto on a request path; streams through
  `stream/promises` `pipeline` for backpressure; CPU work in
  `worker_threads`.
- `process.on("unhandledRejection")` and `"uncaughtException"` at the top of
  every entry point: log, then exit non-zero; never keep running.

## Errors

- Throw `Error` subclasses with `{ cause }`, never strings or plain objects;
  catch narrowly and rethrow what cannot be handled, with the `try` wrapping
  only the call that throws; no empty `catch` without a comment saying why
  nothing is done; `finally` for cleanup; one top-level boundary per entry
  point (the process in Node, an error boundary in the UI).

## Numbers, money and time

- Never floats for prices, quantities or balances: they arrive as strings,
  stay strings on the wire, and are parsed into a decimal type or `BigInt`
  minor units for arithmetic. `Number.isSafeInteger` before trusting an
  integer; `JSON.stringify` throws on `BigInt` (explicit replacer) and
  `JSON.parse` silently loses precision on large ids (keep them strings).
- Every other number is parsed with `Number(s)` and rejected on
  `!Number.isFinite(n)` (`""` parses as `0`, `"1e400"` as `Infinity`);
  never unary `+`, `parseInt` or `parseFloat`, which accept `"12 dwarves"`;
  `parseInt` only with a radix for a non-decimal string.
- UTC ISO-8601 strings on the wire; `new Date("YYYY-MM-DD HH:mm")` parses
  as local time; a date library used in UTC until `Temporal` ships in every
  target runtime.

## Tooling

- ESLint flat config (`eslint.config.js`) with `@eslint/js` recommended plus
  `eslint-plugin-n`, `eslint-plugin-promise` and `eslint-plugin-import-x`;
  `eslint-plugin-unicorn` only rule by rule. Prettier with a committed config
  and `eslint-config-prettier` last, or Biome as the single tool, never both.
- Tests with `vitest` in Vite and Next projects and `node:test` in Node
  services and scripts; coverage thresholds and `npm run build` in CI.

## React

- No business logic in components: plain modules that can be tested without
  rendering. `eslint-plugin-react-hooks` with `rules-of-hooks` and
  `exhaustive-deps` as errors.
- Stable keys, never array indexes for reorderable lists; every subscribing
  effect returns a cleanup; derived values are computed during render or
  memoised, never copied into state.
- Data fetching through TanStack Query (or SWR) with the abort signal passed
  so unmount cancels; no `dangerouslySetInnerHTML` with untrusted input; a
  content security policy on every app; inputs labelled, actions on buttons,
  keyboard focus preserved.

## References

- Node.js: packages and `"type"` https://nodejs.org/api/packages.html ; `node:test` https://nodejs.org/api/test.html ; the event loop https://nodejs.org/en/learn/asynchronous-work/dont-block-the-event-loop
- MDN: `AbortSignal.timeout` https://developer.mozilla.org/en-US/docs/Web/API/AbortSignal/timeout_static ; `BigInt` https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/BigInt ; `Temporal` https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Temporal
- ESLint flat config: https://eslint.org/docs/latest/use/configure/configuration-files
- Google TypeScript style guide (covers JavaScript too): https://google.github.io/styleguide/tsguide.html
- React rules: https://react.dev/reference/rules ; derived state: https://react.dev/learn/you-might-not-need-an-effect
