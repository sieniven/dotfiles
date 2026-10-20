---
paths:
  - "**/*.ts"
  - "**/*.tsx"
  - "**/tsconfig*.json"
---

# TypeScript conventions

Loaded automatically whenever a TypeScript file or `tsconfig` is read or
edited. Everything in `~/.codex/rules/javascript.md` applies as well, and a
`.ts` edit does not load it, so read it first. In this workspace the
frontends are Vite with React 18 and Next.js with React 19 on TypeScript 5.5
or newer, each with a `typecheck` script and no lint config yet.

## tsconfig

- `strict` plus the strictest extras: `exactOptionalPropertyTypes`,
  `noUncheckedIndexedAccess`, `noPropertyAccessFromIndexSignature`,
  `noImplicitOverride`, `noImplicitReturns`, `noFallthroughCasesInSwitch`,
  `noUnusedLocals`, `noUnusedParameters`, `verbatimModuleSyntax`,
  `isolatedModules` (Vite, esbuild and swc need it); `skipLibCheck` is
  acceptable, own code is never exempted.
- `moduleResolution: bundler` for Vite and Next apps, `nodenext` for Node;
  `target` is the oldest runtime deployed; monorepos use project references
  with `composite`; `tsc --noEmit` (the `typecheck` script) runs in CI.
- Node 22.18 and newer strip types by default: only erasable syntax runs (no
  `enum`, runtime `namespace`, parameter properties or decorators),
  `tsconfig` `paths` are ignored (use `#` subpath imports), `.tsx` is not
  supported, relative imports carry the `.ts` extension and type-only
  imports use `import type`. Set `erasableSyntaxOnly` and
  `rewriteRelativeImportExtensions` for such scripts; use `tsx` when full
  TypeScript is needed.

## Types

- `unknown`, never `any`; narrow with type guards and discriminated unions;
  a `never` check in every `default` branch, backed by the
  `switch-exhaustiveness-check` lint rule.
- `satisfies` for configuration objects, `as const` for literal tables,
  `readonly` and `ReadonlyArray` on inputs; branded types for ids and money
  (`type OrderId = string & { readonly __brand: "OrderId" }`), template
  literal types for id formats.
- No `enum` and no `namespace`: `as const` objects or union literals (this
  also keeps the code erasable). `interface` for object shapes that are
  extended, `type` for unions and aliases, one convention per repo.
- No non-null `!`; no `as` assertion except immediately after a runtime
  validation, with a comment saying why it is safe; generics constrained and
  minimal; unions over overloads when return types agree; never the boxed
  `Number`, `String`, `Boolean`, `Object` types; callbacks whose result is
  ignored return `void`.

## Boundaries

- Every external input is validated at runtime and its type inferred from
  the schema (zod, valibot or arktype): HTTP bodies, WebSocket frames,
  `JSON.parse` results, query strings, environment variables. A `fetch`
  result is never typed by assertion.
- Environment is parsed once at startup into a typed config that fails fast;
  catch variables are `unknown` and narrowed with `instanceof Error`.
- Prices, quantities and balances cross the boundary as strings and become a
  decimal type or `bigint`; a 64-bit on-chain integer is `bigint` or `BN`,
  never `number`.

## Lint

- `typescript-eslint` `strictTypeChecked` plus `stylisticTypeChecked` with
  `parserOptions.projectService: true`; add `switch-exhaustiveness-check`
  and `consistent-type-imports`, which the strict set omits; relax
  `restrict-template-expressions` to allow numbers; `disableTypeChecked` on
  plain `.js` files; `eslint-config-prettier` last.
- `@ts-expect-error` with a description, never `@ts-ignore`; exported
  functions of a shared package carry explicit types, locals rely on
  inference; a `no-unnecessary-condition` report means a type is lying
  (often a missing `noUncheckedIndexedAccess` or guard), so fix the type.

## React and TSX

- Props as `readonly` interfaces or discriminated unions; event handler
  types from React, never `any`; forms through react-hook-form with a zod
  resolver so the schema is the single source of the shape; query keys
  declared `as const` and typed through the query function.

## Anchor tests

- `anchor.AnchorProvider.env()` with the wallet and cluster from
  `ANCHOR_WALLET` and `ANCHOR_PROVIDER_URL`; no key in the repo; localnet or
  a local validator only.
- `BN` or `bigint` for every 64-bit value, compared with `.eq()` or as
  strings; failure cases assert the error code or name through
  `chai-as-promised` (`await expect(p).to.be.rejectedWith(...)`), and a call
  that must fail is followed by `expect.fail` so a silent success cannot
  pass; PDAs through `PublicKey.findProgramAddressSync`; confirmations
  awaited before reading accounts.

## References

- TypeScript handbook, do's and don'ts: https://www.typescriptlang.org/docs/handbook/declaration-files/do-s-and-don-ts.html ; tsconfig reference: https://www.typescriptlang.org/tsconfig ; strict bases: https://github.com/tsconfig/bases
- Google TypeScript Style Guide: https://google.github.io/styleguide/tsguide.html
- typescript-eslint configs and rules: https://typescript-eslint.io/users/configs , https://typescript-eslint.io/rules/
- Node.js type stripping: https://nodejs.org/api/typescript.html
- Anchor testing: https://www.anchor-lang.com/docs (testing section)
