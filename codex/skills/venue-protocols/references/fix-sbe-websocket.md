# FIX, SBE and WebSocket reference

Items marked [V] were read from the source on 2026-10-20 (the SBE repository
and its design-principles page, the Binance spot stream documentation, the
Bybit v5 order-book page, the Gate v4 WebSocket page, part of the OKX v5
page). FIX tag semantics are working knowledge to confirm against the
vendored dictionary; venue rules change, so the venue page wins.

## FIX 4.4 session and order-entry tags

| Purpose | Tags |
|---|---|
| Envelope | 8 BeginString, 9 BodyLength, 35 MsgType, 49 SenderCompID, 56 TargetCompID, 34 MsgSeqNum, 52 SendingTime, 10 CheckSum |
| Logon A | 98 EncryptMethod (0), 108 HeartBtInt, 141 ResetSeqNumFlag |
| Heartbeat 0, TestRequest 1 | 112 TestReqID |
| ResendRequest 2 | 7 BeginSeqNo, 16 EndSeqNo (0 = to the end) |
| SequenceReset 4 | 123 GapFillFlag, 36 NewSeqNo |
| Resend markers | 43 PossDupFlag, 122 OrigSendingTime, 97 PossResend (application-level) |
| Reject 3 | 45 RefSeqNum, 371 RefTagID, 372 RefMsgType, 373 SessionRejectReason |
| BusinessMessageReject j | application-level rejects |
| NewOrderSingle D | 11 ClOrdID, 55 Symbol, 54 Side, 38 OrderQty, 40 OrdType, 44 Price, 59 TimeInForce, 60 TransactTime |
| OrderCancelRequest F, OrderCancelReplaceRequest G | 41 OrigClOrdID plus a new 11 |
| ExecutionReport 8 | 150 ExecType (0 New, F Trade, 4 Canceled, 5 Replaced, 8 Rejected, 6 PendingCancel, A PendingNew, E PendingReplace, C Expired, H TradeCancel), 39 OrdStatus (0, 1, 2, 4, 5, 6, 8, A, E), 17 ExecID, 31 LastPx, 32 LastQty, 14 CumQty, 151 LeavesQty, 6 AvgPx |
| OrderCancelReject 9 | 434 CxlRejResponseTo (1 cancel, 2 replace), 102 CxlRejReason (0 too late, 1 unknown order, 3 already pending, 6 duplicate ClOrdID, 99 other) |
| OrderMassCancelRequest q, Report r | 530 MassCancelRequestType, 531 MassCancelResponse, 532 MassCancelRejectReason |
| MarketDataRequest V | 262 MDReqID, 263 SubscriptionRequestType (0 snapshot, 1 snapshot and updates, 2 unsubscribe), 264 MarketDepth, 265 MDUpdateType, groups 267 NoMDEntryTypes and 146 NoRelatedSym |
| Snapshot W, Incremental X | group 268 NoMDEntries with 279 MDUpdateAction (0 New, 1 Change, 2 Delete, 3 Delete thru, 4 Delete from, 5 Overlay), 269 MDEntryType (0 Bid, 1 Offer, 2 Trade, 4 Open, 5 Close, 7 High, 8 Low, B Volume), 270 MDEntryPx, 271 MDEntrySize, 290 MDEntryPositionNo |

Body length counts bytes after the length field's delimiter up to and
including the delimiter before `10=`; the checksum is the byte sum modulo
256 as three digits. Timestamps are `YYYYMMDD-HH:MM:SS[.sss[sss[sss]]]` in
UTC. User-defined tags are 5000 to 9999; venue tags often sit above 20000.
A test-request margin of about 1.2 times the heartbeat interval and a logout
reply timeout of about two seconds are the common defaults.

## SBE layout

- Message header composite: `blockLength` u16, `templateId` u16, `schemaId`
  u16, `version` u16 (eight bytes); group header `blockLength` u16 plus
  `numInGroup` (u16, or u8 in some schemas: read `groupSizeEncoding`);
  var-data is a length prefix then bytes, after the groups.
- Design principles [V]: copy-free flyweights over the buffer, native types,
  allocation-free, streaming forward access, word alignment with fields
  sorted by type and descending size, backwards compatibility; optional
  fields may be appended as extensions, a mandatory or structural change is
  a new message type.
- Code generation [V]: the reference tool is the Java `sbe-all` jar
  (`-Dsbe.target.language=...`); the Rust target is generated with
  `./gradlew generateRustCodecs` and tested with `./gradlew runRustTests` or
  `cargo test` in `rust/`; the output is safe Rust with no runtime
  dependency (`-Dsbe.target.language=Rust`).
- CME MDP 3.0 as the public example: a 12-byte packet header (sequence u32,
  sending time u64), each message prefixed by a 2-byte size, then the SBE
  header; prices as mantissa with a fixed exponent; a packet-sequence gap
  triggers the snapshot recovery feed.
- Databento DBN: zstd-compressed, self-describing records with a common
  header (length in 4-byte units, record type, publisher, instrument,
  event time), int64 prices at a 1e-9 scale with an undefined sentinel,
  u64 nanosecond timestamps, zero-copy record references; Rust crates `dbn`
  and `dbn-cli`.
- ITCH and OUCH style feeds: 2-byte big-endian length then a type byte,
  fixed-width big-endian fields, u32 prices with four implied decimals,
  6-byte nanosecond timestamps since midnight, a transport (MoldUDP64)
  session and sequence for gaps.

## Per-venue book maintenance

- Binance spot [V]: connection lives at most 24 hours (a shutdown event
  warns); the server pings every 20 s and expects the pong payload back
  within a minute; at most 5 incoming messages per second per connection
  (pings, pongs and subscriptions count; exceeding disconnects, repeats
  ban); up to 1024 streams per connection; 300 connection attempts per IP
  per 5 minutes. Local book: buffer diff events, note the first `U`, fetch
  the REST snapshot (refetch while its `lastUpdateId` is below the first
  buffered `U`), drop events with `u <= lastUpdateId`, apply the rest; per
  event ignore `u` below the book id, restart if `U` exceeds book id plus
  one, else set quantities (zero removes) and advance to `u`; the snapshot
  holds at most 5000 levels per side. Futures use `pu` equal to the previous
  `u` for continuity.
- Bybit v5 [V]: a snapshot then deltas; a new snapshot resets the book; size
  zero removes a level; `u=1` marks a post-restart snapshot; push rates L1
  10 ms, L50 20 ms, L200 100 ms, L1000 200 ms (L1 is snapshots only); `seq`
  compares across depths, `ts` is system time, `cts` matching-engine time.
- OKX v5 [V partial]: keepalive is a text `ping` answered by `pong`; the
  server drops a connection with no subscription or data for 30 s, so keep
  a sub-30-second timer reset on every message. Book channels carry
  `seqId` and `prevSeqId`: each message's `prevSeqId` must equal the previous
  `seqId` (a snapshot has `prevSeqId` -1, an idle heartbeat repeats
  `prevSeqId == seqId`, and `seqId < prevSeqId` is a legitimate reset after
  maintenance); any other break means rebuild from a new snapshot. The
  `checksum` field is deprecated and fixed at 0 on `books`, `books-l2-tbt` and
  `books50-l2-tbt`; only the spread channel still carries a 25-level signed CRC32.
- Gate spot [V]: `spot.order_book_update` at 20 ms or 100 ms; `U` and `u`
  bound each message; `full=true` replaces the book; cache messages, fetch
  the REST book with `with_id=true` for `baseID`, apply from the first
  message with `U <= baseID+1 <= u`, drop `u < baseID+1`, refetch when
  `baseID+1` is below the first cached `U`, rebuild when a later `U` exceeds
  `baseID+1`; amounts are absolute, zero removes; standard ping and pong
  frames plus an optional application-level ping.
- Authentication: Binance spot user-data streams are subscribed through the
  authenticated WebSocket API (`userDataStream.subscribe`) since February 2026,
  the listen-key endpoints having been removed; futures still use listen keys
  renewed before expiry; signed login messages on Bybit and OKX;
  re-authenticate after every reconnect. Weight headers (`X-MBX-USED-WEIGHT-*`,
  `X-Bapi-Limit-Status`) feed the local budget. Cancel-on-disconnect: Bybit's DCP is enabled per account through
  `POST /v5/order/disconnected-cancel-all` (`timeWindow` 3 to 300 s, default 10,
  institutional accounts) with the private socket subscribed to the `dcp`
  topic; OKX's is `POST /api/v5/trade/cancel-all-after` (`timeOut` 0 or 10 to
  120 s, one request per second, a heartbeat every second); Binance spot has
  none.

## Libraries

- Rust FIX: `hotfix` (session engine with stores, initiator focus; FIX 4.4
  supported for buy-side use, 4.2 untested, 5.0 planned; 0.13 at the time of
  writing), `quickfix` bindings over
  the C++ QuickFIX engine (full engine, C++ build dependency), `fefix` and
  its forks (codec only), `fixer`. QuickFIX (C++, Python, Java) is the
  reference engine and a good test peer but slow on a hot path; fix8 (C++)
  compiles schemas to classes with a session layer.
- The lean hot-path design is a borrow-only tag-value scanner over a
  vendored dictionary plus an owned session state machine, with QuickFIX or
  hotfix as the counterparty in tests.
- JSON: `serde_json` with borrowed fields as the baseline; `simd-json` (in
  place, needs a mutable buffer) and `sonic-rs` for large frames, measured on
  the real payloads; decimals parsed from bytes into scaled integers.
- Fuzzing: `cargo-fuzz` targets per decoder seeded from captures.

## Primary references

- FIX 4.4 and FIXT 1.1 specifications: https://www.fixtrading.org/standards/fix-4-4/ and https://www.fixtrading.org/standards/fixt-1-1/ ; tag dictionary https://www.onixs.biz/fix-dictionary/4.4/index.html
- SBE: https://www.fixtrading.org/standards/sbe/ ; https://github.com/aeron-io/simple-binary-encoding [V] and its design principles https://github.com/aeron-io/simple-binary-encoding/wiki/Design-Principles [V]
- Databento DBN: https://github.com/databento/dbn ; https://databento.com/docs/standards-and-conventions/databento-binary-encoding
- CME MDP 3.0: https://www.cmegroup.com/confluence/display/EPICSANDBOX/MDP+3.0
- Venue docs: Binance spot streams https://developers.binance.com/docs/binance-spot-api-docs [V] ; Bybit v5 order book https://bybit-exchange.github.io/docs/v5/websocket/public/orderbook [V] ; OKX v5 https://www.okx.com/docs-v5/en/ [V partial] ; Gate v4 WebSocket https://www.gate.com/docs/developers/apiv4/ws/en/ [V]
- Libraries: https://github.com/Validus-Risk-Management/hotfix ; https://docs.rs/quickfix ; https://github.com/quickfix/quickfix ; https://github.com/ferrumfix/ferrumfix ; https://docs.rs/fixer ; https://github.com/rust-fuzz/cargo-fuzz
