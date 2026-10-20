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
edited. The C++ Core Guidelines are the baseline; this file holds the
deviations and the rules a low-latency trading codebase adds (rule ids in
brackets point into the Guidelines). In this workspace most C++ is the
vendor-SDK shim compiled by a Rust `build.rs` through the `cc` crate, plus
standalone tools and benchmarks. Latency budgets live in the `quant-trading`
skill; measurement in `systems-benchmarking`.

## Build and toolchain

- C++20, extensions off (`target_compile_features(... cxx_std_20)`,
  `CMAKE_CXX_EXTENSIONS OFF`); one compiler per repo pinned in
  `CMakePresets.json` (configure, build and test presets: dev, asan, tsan,
  release); `CMAKE_EXPORT_COMPILE_COMMANDS ON` so clangd and clang-tidy see
  the real flags.
- Targets, not variables: `target_include_directories`,
  `target_link_libraries` with `PRIVATE`/`PUBLIC` chosen deliberately.
  Dependencies pinned: `FetchContent` to a commit hash, otherwise vcpkg or
  Conan with a lockfile.
- Warnings on every own target: `-Wall -Wextra -Wpedantic -Wconversion
  -Wsign-conversion -Wshadow -Wold-style-cast -Wnon-virtual-dtor
  -Woverloaded-virtual -Wnull-dereference`; `-Werror` in CI. Vendor headers
  are `SYSTEM` includes (or `warnings(false)` only on the vendor part of a
  `cc` build), never a reason to lower the set.
- Sanitizers in CI: one ASan plus UBSan build with
  `-fno-omit-frame-pointer -fno-sanitize-recover=undefined`, a separate TSan
  build (it cannot combine with ASan); `-D_GLIBCXX_ASSERTIONS` or the libc++
  hardening mode in debug and test builds.
- A committed `.clang-format` (based on Google or LLVM, `IncludeBlocks:
  Regroup`) checked with `--dry-run -Werror`, and a committed `.clang-tidy`
  enabling `bugprone-*`, `cppcoreguidelines-*`, `performance-*`,
  `modernize-*`, `concurrency-*` with `bugprone-*` and `concurrency-*` as
  errors; disable single checks with a reason, never a whole family.

## Ownership and lifetime

- RAII for every resource [R.1]; a raw pointer is non-owning [R.3]; no
  `new`, `delete`, `malloc` or `free` in application code [R.10, R.11];
  scoped objects before heap objects [R.5].
- `unique_ptr` by default, `shared_ptr` only for genuinely shared ownership,
  `make_unique`/`make_shared`, `weak_ptr` to break cycles [R.20 to R.24];
  take a smart pointer as a parameter only to express lifetime [R.30].
- Rule of zero [C.20]; when one special member is defined, define or delete
  all five [C.21]. A polymorphic base has a public virtual or protected
  non-virtual destructor [C.35]; constructors establish the invariant [C.41];
  single-argument constructors are `explicit` [C.46]; a virtual function
  carries exactly one of `virtual`, `override`, `final` [C.128].
- Never transfer ownership through a raw pointer or reference [I.11]; a
  pointer plus length is a `std::span` [I.13]. `std::span` and
  `std::string_view` borrow and never outlive their owner; `string_view` is
  not NUL-terminated, so it never goes to a C API.
- Parameters: cheap types by value, other inputs by `const T&`, in-out by
  `T&`, sinks by `T&&` then `std::move` [F.15 to F.19]; return values over
  out-parameters [F.20]; never a pointer or reference to a local [F.43].

## Types, initialisation and arithmetic

- Always initialise [ES.20], with `{}` [ES.23]; no narrowing [ES.46];
  `nullptr` [ES.47]; never cast away `const` [ES.50]; `auto` only when the
  type is obvious from the initialiser.
- Signed integers for arithmetic, unsigned for bit manipulation only
  [ES.101, ES.102]; never mix them [ES.100]; never use unsigned to forbid
  negatives [ES.106]; `std::ptrdiff_t` or `gsl::index` for subscripts.
- Prices and quantities are scaled integers (`int64_t` with a per-instrument
  scale), never `float` or `double`; a price times quantity goes through a
  128-bit intermediate or a checked multiply.
- Reinterpretation is `std::bit_cast` or `memcpy`, never `reinterpret_cast`
  of a byte buffer to a struct (strict aliasing, alignment). Every wire or
  FFI struct carries `static_assert`s on `sizeof`, `alignof`, `offsetof` and
  `is_trivially_copyable_v`.
- `constexpr` and `consteval` for tables and constants [Per.11]; designated
  initialisers for configuration structs; `[[nodiscard]]` on any result that
  must be checked.

## Errors

- The error policy is written per target. Hot paths and the FFI shim run
  with exceptions off (`-fno-exceptions`, `noexcept`) and return
  `std::expected<T, E>` (or `tl::expected` before C++23). Exceptions, where
  a target allows them, signal failure [E.2] with purpose-built types
  [E.14], never built-in types, never `errno`-style global state [E.28].
- `noexcept` wherever a throw is impossible or unacceptable [F.6, E.12]; a
  throw escaping a `noexcept` function terminates the process.
- No exception crosses `extern "C"` or a vendor callback: every boundary
  entry point catches all and converts to an error code.
- `assert(cond && "message")` for programmer errors only; `[[maybe_unused]]`
  for values used only in asserts.

## Concurrency

- Minimise shared writable data [CP.3]; RAII locks only [CP.20];
  `std::scoped_lock` for more than one mutex [CP.21]; never call unknown
  code (a callback) while holding a lock [CP.22]; condition waits always
  carry a predicate [CP.42].
- `std::atomic` with an explicit `memory_order` and a comment stating what
  is published or acquired; `seq_cst` until a measurement justifies weaker;
  `volatile` is not synchronisation [CP.8]; no hand-written lock-free code
  or double-checked locking without a reviewed reason [CP.100, CP.110].
- `std::jthread` with `stop_token`: every thread has an owner and a stop
  path; nothing is detached.
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

## Headers and layout

- Include what you use, in the order own header, C system, C++ standard,
  third party, project; `#pragma once` or project guards, one style per
  repo; no `using namespace` in headers; forward-declare only entities the
  project owns.
- File-local names in an anonymous namespace; no globals with dynamic
  initialisation (static-initialisation order) and no non-trivial static
  destructors.
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

- clang-format clean; naming follows the repo's `.clang-format` basis
  (Google by default: `CamelCase` types, `snake_case` functions and
  variables, `member_` suffix, `kConstant`); early exits and no `else` after
  `return`; comments explain why, not what.

## References

- C++ Core Guidelines: https://isocpp.github.io/CppCoreGuidelines/CppCoreGuidelines ; GSL: https://github.com/microsoft/GSL
- Google C++ Style Guide: https://google.github.io/styleguide/cppguide.html ; LLVM Coding Standards: https://llvm.org/docs/CodingStandards.html
- clang-tidy checks: https://clang.llvm.org/extra/clang-tidy/checks/list.html ; clang-format options: https://clang.llvm.org/docs/ClangFormatStyleOptions.html
- CMake buildsystem and presets: https://cmake.org/cmake/help/latest/manual/cmake-buildsystem.7.html , https://cmake.org/cmake/help/latest/manual/cmake-presets.7.html
- Sanitizers: https://clang.llvm.org/docs/AddressSanitizer.html (ThreadSanitizer and UndefinedBehaviorSanitizer pages alongside) ; libc++ hardening: https://libcxx.llvm.org/Hardening.html
- GoogleTest: https://github.com/google/googletest ; Google Benchmark: https://github.com/google/benchmark
