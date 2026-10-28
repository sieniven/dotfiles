---
paths:
  - "**/*.cpp"
  - "**/*.cc"
  - "**/*.cxx"
  - "**/*.hpp"
  - "**/*.hh"
  - "**/*.h"
  - "**/CMakeLists.txt"
  - "**/*.cmake"
---

# C++ conventions

Loaded automatically whenever a C++ source, header or CMake file is read or
edited. The C++ Core Guidelines and Google's C++ style guide are the
baseline (rule ids in brackets point into the Guidelines; links at the end);
this file holds what they leave open, the places it deviates from either, and
what a low-latency trading codebase adds. In this workspace most C++ is the
vendor-SDK shim compiled by a Rust `build.rs` through the `cc` crate, plus
standalone tools and benchmarks. Latency budgets live in the `quant-trading`
skill; measurement in `systems-benchmarking`. **Hot path** means the code a
profile shows between market data and order send; everything else is cold
and stays simple.

## Build and toolchain

- C++20, extensions off (`target_compile_features(... cxx_std_20)`,
  `CMAKE_CXX_EXTENSIONS OFF`); one compiler per repo pinned in
  `CMakePresets.json` (configure, build and test presets: dev, asan, tsan,
  release); `CMAKE_EXPORT_COMPILE_COMMANDS ON` so clangd and clang-tidy see
  the real flags. No C++20 modules; coroutines only through one vetted
  library per repo, never a hand-written promise or awaitable type.
- Targets, not variables: `target_include_directories`,
  `target_link_libraries` with `PRIVATE`/`PUBLIC` chosen deliberately.
  Dependencies pinned: `FetchContent` to a commit hash, otherwise vcpkg or
  Conan with a lockfile.
- Warnings on every own target: `-Wall -Wextra -Wpedantic -Wconversion
  -Wsign-conversion -Wshadow -Wold-style-cast -Wnon-virtual-dtor
  -Woverloaded-virtual -Wnull-dereference -Wimplicit-fallthrough` (plus
  `-Wctad-maybe-unsupported` on clang); `-Werror` in CI. Vendor headers are `SYSTEM`
  includes (or `warnings(false)` only on the vendor part of a `cc` build),
  never a reason to lower the set.
- Standard attributes and `<bit>`/`<numeric>` first; `__builtin_*`,
  intrinsics, `__attribute__`, `#pragma` and inline assembly only through
  one portability header per repo, never inline at the use site.
- Sanitizers in CI: one ASan plus UBSan build with
  `-fno-omit-frame-pointer -fno-sanitize-recover=undefined`, a separate TSan
  build (it cannot combine with ASan); `-D_GLIBCXX_ASSERTIONS` or the libc++
  hardening mode in debug and test builds.
- A committed `.clang-format` (based on Google or LLVM, `IncludeBlocks:
  Regroup`) checked with `--dry-run -Werror`, and a committed `.clang-tidy`
  enabling `bugprone-*`, `cppcoreguidelines-*`, `performance-*`,
  `modernize-*`, `concurrency-*`, `google-*` and `readability-identifier-naming`
  with `bugprone-*` and `concurrency-*` as errors; disable single checks
  with a reason, never a whole family.

## Ownership and lifetime

- RAII for every resource [R.1]; a raw pointer is non-owning [R.3]; no
  `new`, `delete`, `malloc` or `free` in application code [R.10, R.11];
  scoped objects before heap objects [R.5].
- `unique_ptr` by default; `shared_ptr` only for genuinely shared ownership
  of an immutable object (`shared_ptr<const T>`), `make_unique`/`make_shared`,
  `weak_ptr` to break cycles [R.20 to R.24]; take a smart pointer as a
  parameter only to express lifetime [R.30].
- Rule of zero for plain value types [C.20]. A class with a private section
  that owns a resource, handle, mutex or SDK object states its copy and move
  policy in its public section with `= default`/`= delete`, in pairs
  (constructor with assignment), and when one special member is defined, all
  five are defined or deleted [C.21]; a move operation on a copyable type
  exists only when measurably cheaper than the copy.
- Every constructor callable with one argument (defaults included) and every
  conversion operator is `explicit` [C.46] (`google-explicit-constructor`);
  copy, move and `initializer_list` constructors are not. Constructors
  establish the invariant [C.41] and, like destructors, never call a virtual
  function (`clang-analyzer-optin.cplusplus.VirtualCall`).
- Inheritance is public and is-a; private inheritance becomes a member;
  multiple implementation inheritance is not used; a base is abstract (pure
  virtual, or a protected constructor or destructor) so nothing slices, with
  a public virtual or protected non-virtual destructor [C.35]; data members
  private, `protected` only on member functions; a virtual function carries
  exactly one of `virtual`, `override`, `final` [C.128]; `final` on a class
  not designed as a base.
- Never transfer ownership through a raw pointer or reference [I.11]; a
  pointer plus length is a `std::span` [I.13]. `std::span` and
  `std::string_view` borrow and never outlive their owner; `string_view` is
  not NUL-terminated, so it never goes to a C API.
- Parameters: cheap types by value, other inputs by `const T&`, in-out by
  `T&`, optional in or out by pointer with nullability documented, sinks by
  value then `std::move` (a deliberate pick of Google's rule over [F.18]:
  one extra move, no dangling `T&&` that is never moved from). `T&&` only in
  move operations, forwarding references with `std::forward`, and a
  `const T&`/`T&&` overload pair with a measurement
  (`cppcoreguidelines-rvalue-reference-param-not-moved`, `-missing-std-forward`,
  `bugprone-use-after-move`). Return values over out-parameters [F.20];
  never a pointer or reference to a local [F.43].
- A parameter the callee keeps after the call (a callback target, a buffer
  the SDK writes later) is a pointer, never a reference, and the declaration
  comment says who owns it and for how long; a reference parameter is dead
  when the call returns.
- A lambda that outlives its scope (an executor, a timer, an SDK callback
  registry) names every capture; `[&]` only when the lambda dies before the
  scope does; `[=]` never captures `this` implicitly (write `this` or
  `self = shared_from_this()`); an init-capture moves an existing variable
  in, never introduces a new name.

## Types, initialisation and arithmetic

- Always initialise [ES.20], with `{}` [ES.23]; no narrowing [ES.46]:
  arithmetic narrowing goes through `T{x}` so loss fails to compile;
  `nullptr` [ES.47]; never cast away `const` [ES.50]; no C-style cast
  (`google-readability-casting`); parentheses, not braces, to call a size
  constructor on a type with an `initializer_list` constructor
  (`std::vector<int> v(100, 1)`).
- `int` or an exact-width `<cstdint>` type, never `short`/`long`/`long long`
  (`google-runtime-int`); 64-bit whenever a value or intermediate can reach
  2^31, with constants built as `uint64_t{1} << n`; `float`/`double` only,
  never `long double`. Signed integers for arithmetic, unsigned for bit
  manipulation only [ES.101, ES.102]; never mix them [ES.100]; never use
  unsigned to forbid negatives [ES.106]; `std::ptrdiff_t` or `gsl::index`
  for subscripts.
- Prices and quantities are scaled integers (`int64_t` with a per-instrument
  scale), never `float` or `double`; a price times quantity goes through a
  128-bit intermediate or a checked multiply, as a named function returning
  the notional type, not `operator*`.
- Reinterpretation is `std::bit_cast` or `memcpy`, never `reinterpret_cast`
  of a byte buffer to a struct (strict aliasing, alignment). Every wire or
  FFI struct carries `static_assert`s on `sizeof`, `alignof`, `offsetof` and
  `is_trivially_copyable_v`; the memory layout is the protocol, so no
  serialisation library in between.
- `constexpr` and `consteval` for tables and constants [Per.11]; designated
  initialisers, in field order, for configuration structs; `[[nodiscard]]`
  on any result that must be checked.
- `struct` only for passive data with no invariant between fields (wire and
  FFI layouts, options bags); anything with an invariant is a `class` with
  private data. Named fields over `std::pair`/`std::tuple` whenever the
  elements mean something.
- A `switch` on an enum lists every enumerator and has no `default`, so a
  new enumerator is a `-Wswitch` error instead of silent fall-through; a
  `switch` on anything else has a `default`, and one that must be
  unreachable aborts rather than returns; every intentional fall-through is
  `[[fallthrough]];`. A `bool` parameter whose meaning is not obvious at the
  call site is an `enum class`.
- `auto` only where the initialiser shows the type or deduction avoids a
  copy (`auto it = m.find(k)`, `auto p = std::make_unique<T>()`); no `auto`
  parameters outside lambdas, no deduced return type on a header function,
  no `decltype(auto)` when `auto` works, CTAD only for std types and
  templates with a deduction guide; structured bindings for pairs and map
  elements.
- Operators only with their built-in meaning, declared beside the type as
  non-member functions: `==` plus `<=>` (defaulted where possible,
  consistent with each other), never `&&`, `||`, comma or unary `&`; a
  comparator object instead of an unnatural `<` for a container. No
  user-defined literals of our own; `std::chrono_literals` through a
  function- or `.cc`-scope `using namespace` only, never in a header (a
  deliberate deviation from Google, which bans all literals).
- No `dynamic_cast`/`typeid` dispatch and no hand-rolled type-tag `if`
  chains outside tests: a closed set of alternatives is a `std::variant`
  visited with `std::visit`, an open one is a virtual method; `-fno-rtti`
  on hot-path targets.
- Every template parameter is constrained [T.10] with a `std::` concept
  before a hand-rolled trait; no concept that only restates the body and no
  "semantic" concept the compiler cannot check; no SFINAE or `enable_if`
  where a `requires` clause works; no recursive template metaprogramming.

## Errors

- Exceptions are off (`-fno-exceptions`, `noexcept`) on every new target,
  the hot path and the FFI shim included: failure is `std::expected<T, E>`
  (or `tl::expected` before C++23). Exceptions remain only in a target that
  already throws (a test binary, a tool on a throwing library), where they
  signal failure [E.2] with purpose-built types [E.14], never built-in
  types, never `errno`-style global state [E.28]; nothing uses
  `std::exception_ptr` or `std::nested_exception`.
- A constructor that can fail becomes a private constructor plus a
  `static std::expected<T, E> Create(...)`; no two-phase `Init()` and no
  `bool IsValid()` state a caller must remember to check.
- `noexcept` wherever a throw is impossible or unacceptable [F.6, E.12]:
  unconditional when exceptions are off, never a conditional clause; move
  constructors and move assignment are `noexcept` or standard containers
  copy instead of moving (`performance-noexcept-move-constructor`). A throw
  escaping a `noexcept` function terminates the process.
- No exception crosses `extern "C"` or a vendor callback: every boundary
  entry point catches all and converts to an error code.
- `assert(cond && "message")` for programmer errors only, the message
  saying why the invariant holds or what broke; `[[maybe_unused]]` for
  values used only in asserts.

## Concurrency

- Minimise shared writable data [CP.3]; RAII locks only [CP.20];
  `std::scoped_lock` for more than one mutex [CP.21]; never call unknown
  code (a callback) while holding a lock [CP.22]; condition waits always
  carry a predicate [CP.42].
- A `const` method is one that is safe to call concurrently with every
  other `const` method (`misc-const-correctness`,
  `readability-make-member-function-const`); a class that cannot promise
  that says "not thread-safe" in its class comment, and every class touched
  by more than one thread states its locking rule there.
- `std::atomic` with an explicit `memory_order` and a comment stating what
  is published or acquired; `seq_cst` until a measurement justifies weaker;
  `volatile` is not synchronisation [CP.8]; no hand-written lock-free code
  or double-checked locking without a reviewed reason [CP.100, CP.110].
- `std::jthread` with `stop_token`: every thread has an owner and a stop
  path; nothing is detached, and every thread is joined before static
  destruction starts.
- `alignas(std::hardware_destructive_interference_size)` (64 in practice)
  between fields written by different threads.
- Vendor SDK callbacks run on the vendor's threads: copy the data out into
  a bounded queue and return; never re-enter the SDK from its callback;
  the buffer dies when the callback returns; fixed `char` arrays from an SDK
  may lack a terminator.

## Hot path

- No allocation (a counting `operator new` in tests asserts zero per
  message), no `std::function`, no virtual dispatch, no `shared_ptr` churn,
  no iostream, `std::endl` or formatting logs (a ring buffer instead), no
  lock held across work, no syscalls.
- Preallocate, pool, or use `std::pmr::monotonic_buffer_resource` over a
  fixed buffer; borrow with `span` and `string_view`.
- Measure before optimising [Per.1]; simple code first [Per.4]; design so
  the optimiser can work [Per.7]; access memory predictably [Per.19];
  `[[likely]]`/`[[unlikely]]` only with a measured gain. LTO and `-march`
  are deployment decisions recorded with the benchmark numbers.

## Headers, namespaces and globals

- Include what you use (`misc-include-cleaner`), in the order own header, C
  system, C++ standard, third party, project; `#pragma once` (the pinned
  compilers support it; Google's `#define` guards are also fine, one style
  per repo). Include the header instead of forward-declaring; never
  forward-declare another project's or `std`'s types. A function body in a
  header is ten lines or fewer.
- All code sits in the project namespace, closed with
  `}  // namespace proj::component`; no using-directive anywhere,
  using-declarations and namespace aliases only in `.cc` files, function
  bodies or an `internal` namespace (`google-build-using-namespace`);
  nothing declared in `std`; `using`, not `typedef`; free functions in a
  namespace, not a class of statics; file-local names in an anonymous
  namespace in `.cc` files only (`google-build-namespaces`). `extern "C"`
  exports carry the project prefix, because C has no namespaces.
- No macro where an `inline`/`constexpr` function, `enum class` or
  `constexpr` variable works; one that must exist is `PROJECT_`-prefixed,
  defined next to its use and `#undef`'d after, never exported from a header
  and never part of an API (`cppcoreguidelines-macro-usage`). Vendor-SDK
  macros are wrapped once, in the shim, not spread through callers.
- Namespace-scope and `static` class data is `constexpr` or `constinit` (so
  initialisation order cannot bite) and trivially destructible (so shutdown
  order cannot either): no global `std::string`, container, mutex wrapper
  or smart pointer; a lookup table is a `constexpr std::array`; a
  heavyweight singleton is `static T& Instance() { static auto& t = *new T;
  return t; }` and is never deleted. A namespace-scope `thread_local` is
  `constinit thread_local`; a per-thread buffer with a destructor lives
  inside a function. No non-const global otherwise
  (`cppcoreguidelines-avoid-non-const-global-variables`).
- `std::array` and `std::vector` over C arrays [SL.con.1]; `std::string`
  owns, `string_view` refers [SL.str.1, SL.str.2].

## Testing

- GoogleTest (with gmock) under ctest, or Catch2 or doctest in a small tool;
  one behaviour per test; error and boundary branches covered.
- `static_assert` layout tests for every wire and FFI struct; decoders have a
  libFuzzer target seeded with captured frames; sanitizer builds run in CI.
- Micro-benchmarks with Google Benchmark (`DoNotOptimize`, `ClobberMemory`),
  reported per `systems-benchmarking`.
- The machine-local section of the global CLAUDE.md applies to C++ test and
  bench executables too: a refused binary is unverified, not failing; build
  into a directory under `~/.cache/claude-scratch/` (`cmake -B`) when the
  machine refuses fresh binaries inside the checkout.

## Style

- clang-format clean, with the formatter owning layout. Naming is Google's,
  written into `.clang-tidy` `readability-identifier-naming` so it is
  mechanical: `PascalCase` types and functions, `snake_case` variables,
  namespaces and accessors, `member_` suffix on class (not struct) data,
  `kConstant` and `kEnumerator`, `PROJECT_MACRO`. The one exception is
  interop: an `extern "C"` symbol or a type mirrored from the SDK or from
  Rust keeps the name the other side binds.
- Early exits and no `else` after `return`; a variable declared in the
  `if`/`for` header when only that statement needs it.
- A declaration comment is a verb phrase saying what the function does and
  what it assumes (ownership and nullability of pointer arguments, what
  happens to an output parameter's prior contents, blocking or allocation),
  omitted only for an obvious accessor; a class comment carries the usage
  and the synchronisation assumptions; definition comments say how, not
  what. `TODO(owner or ticket):` only.
- A call site with a literal `true`, `false`, `nullptr` or magic number is
  unreadable: an `enum class` parameter, an options struct, or at worst
  `/*param_name=*/value` (`bugprone-argument-comment`).

## References

- C++ Core Guidelines: https://isocpp.github.io/CppCoreGuidelines/CppCoreGuidelines ; GSL: https://github.com/microsoft/GSL
- Google C++ Style Guide: https://google.github.io/styleguide/cppguide.html ; LLVM Coding Standards: https://llvm.org/docs/CodingStandards.html
- clang-tidy checks: https://clang.llvm.org/extra/clang-tidy/checks/list.html ; clang-format options: https://clang.llvm.org/docs/ClangFormatStyleOptions.html
- CMake buildsystem and presets: https://cmake.org/cmake/help/latest/manual/cmake-buildsystem.7.html , https://cmake.org/cmake/help/latest/manual/cmake-presets.7.html
- Sanitizers: https://clang.llvm.org/docs/AddressSanitizer.html (ThreadSanitizer and UndefinedBehaviorSanitizer pages alongside) ; libc++ hardening: https://libcxx.llvm.org/Hardening.html
- GoogleTest: https://github.com/google/googletest ; Google Benchmark: https://github.com/google/benchmark
