# TT FIX and REST facts

What TT's own documentation says, read on 2026-10-09 from
`https://library.tradingtechnologies.com` (a few pages from a 2026-09-08
copy, marked so). Each fact names its page by a short key; the key table is
at the end. UNCONFIRMED marks what no fetched page settles. TT publishes
schema files for UAT and production separately, stamped on line 2; the
middleware vendors the UAT 2026-08-03 schema.

## FIX session

**Versions and schema**

- TT FIX supports a subset of FIX 4.2 (Errata 20010501) and FIX 4.4. Only
  documented messages and tags may be sent; anything else "can produce
  unexpected results" [SYS]. Tag 8 must be `FIX.4.2` or `FIX.4.4`; a
  4.4-only tag in a 4.2 Logon gets the logon rejected [LOGON] [OPS].
- Schemas come in a legacy and a component format, for PROD and UAT; last
  seen PROD stamped 2026-05-29/30 and UAT 2026-08-03 [SYS].

**Logon (A)**

- 49 `SenderCompID` is the client id and must equal the session's Remote
  Comp Id in Setup; TT echoes it in its own 56 [CROR] [OSR].
- 56 `TargetCompID`: "TT FIX does not validate this field"; keep one value
  for the session's life, and TT returns it in its 49 [OSR]. The [LOGON]
  flow text says TT checks 56 against LocalCompId; treat 56 as fixed.
- 57 `TargetSubID` is required when the session has a Target Sub Id; Remote
  Comp Id plus Target Sub Id is unique across sessions [CROR].
- The password goes in 96 `RawData`, required; in 4.4 only, 553/554 are an
  optional alternative. Session passwords never expire [LOGON] [CROR].
- 98 `EncryptMethod`=0; 108 `HeartBtInt` in seconds [LOGON].
- 141 `ResetSeqNumFlag` defaults to N; if Y the client must also send 34=1.
  Security-definition (that is, FIX Market Data) and recovery sessions must
  always use 141=Y and 34=1, or TT sends Logout with 58 "MsgSeqNum must be set to 1"
  [LOGON] [U2].
- Flow: TT checks 56 and 96 against Setup and on failure sends Logout with
  the reason in 58 and closes the socket. With 141=N, a 34 lower than
  expected is a Logout and disconnect; a higher one is accepted and TT then
  sends a Resend Request. TT replies with its own Logon [LOGON].
- TT-only logon tags 916/917 StartDate/EndDate and 18002 CustomMode are for
  recovery; 16567 is internal to TT [LOGON].

**Heartbeat and test request**

- Send a Heartbeat every HeartBtInt when idle, resetting the timer after
  every message sent. With no data for one interval, send Test Request (1);
  the other side answers with Heartbeat carrying 112. With no Heartbeat "in a
  reasonable amount of time", treat the connection as lost; no numeric grace
  is given [HB]. Drop-copy clients must heartbeat every 30 seconds [DCF].

**Sequence numbers, resend and gap fill**

- Resend Request uses 7 and 16; a single message has 7=16; "all after" is
  16=0; both sides may send it [RR].
- Sequence Reset uses 123 `GapFillFlag` (default N, reset mode) and 36
  `NewSeqNo`; non-gap-fill resets only when the mismatch cannot otherwise be
  resolved [SR].
- TT sets 43 `PossDupFlag` and 122 on resends, and 97 `PossResend` while
  restarting after a corrupt message cache [LOGON].
- **A D, G, AB or AC with 43=Y is rejected with Business Message Reject
  (j).** Never replay orders: gap-fill them [OSR] [NOS].

**Reconnect recovery**

- On reconnect TT queries its order-book database and delivers every unsent
  execution report with incrementing sequence numbers; the client need not
  detect gaps; News (35=B) marks the replay complete [OPS] [ORSM]. The same
  holds after a 141=Y/34=1 relogon: Logon is 34=1 and the missed executions
  follow as 34=2, 3, … [OPS].
- A standard Resend Request is honoured. A client that reset sequence
  numbers and also lost the messages recovers executions over REST [OPS].

**Schedule and availability**

- Order-routing sessions reset on Saturday at 22:00 UTC by default; a
  custom daily reset time (UTC) can be set per session; a client still
  connected at reset time gets a Logout [OPS] [CROR].
- FIX is available 24/7 except deployments on Friday evenings, roughly every
  two weeks in UAT and monthly in production [OPS].
- The market-data session page repeats the order-routing reset text; a
  schedule specific to market-data sessions is UNCONFIRMED [MDSM].

**Transport, hosts and ports**

- SSL-wrapped TCP with server certificates only, no client certificates;
  authentication is 49 plus 96. TT ships `TTFIX.crt` in `stunnel.zip` and
  recommends stunnel with `verify = 3` for engines without native TLS. UAT
  accepts plain internet or stunnel; production is SSL only; port 443 is
  also open for these hosts [MGS].

| Service | UAT (plain / SSL) | Production (SSL) |
| --- | --- | --- |
| Order routing | `fixorderrouting-ext-uat-cert.trade.tt:11502 / 11702` | `fixorderrouting-ext-prod-live.trade.tt:11702` |
| Market data | `fixmarketdata-ext-uat-cert.trade.tt:11503 / 11703` | `fixmarketdata-ext-prod-live.trade.tt:11703` |
| Drop copy | `fixdropcopy-ext-uat-cert.trade.tt:11501 / 11701` | `fixdropcopy-ext-prod-live.trade.tt:11701` |
| Inbound drop copy | 11506 / 11706 | 11706 |
| Recovery (drop copy) | `fixrecovery-ext-uat-cert.trade.tt:11505 / 11705` | `fixrecovery-ext-prod-live.trade.tt:11705` |
| Recovery (order routing) | 11508 / 11708 | 11708 |

Sources [MGS] [CERT]. The [MGS] stunnel examples for recovery and drop copy
point at `fixsecurityinfo-ext-*` hosts, contradicting the table; trust the
table and confirm with TT. The market-data connectivity page shows only
order-routing hosts, a copy-paste error.

**Concurrent sessions**

- A second logon on the same session logs out the first unless Setup's
  "Disable Forceful Logout Due to Duplicate Session Detection" is on [FXS].
  No limit on sessions per company is documented: UNCONFIRMED.

## Order routing

**Scope and setup**

- Create a "FIX Order Routing" session in Setup, assign users, configure
  connectivity; certification in UAT with session-level sequence-mismatch
  tests precedes production [CERT]. Order routing covers DMA orders, TT
  Order Types (synthetic parents managing children), Autospreader spreads,
  ADL and Algo SDK algos, staged orders, strategy creation and RFQ [ORO].

**NewOrderSingle (D)**

- Required: 11, 1 `Account`, 38, 40, 54, plus instrument identification
  [NOS] [OCRR]. Account is required on D and G and is **case-sensitive**;
  116 `OnBehalfOfSubID` (the user alias) is required when several users share
  the account [NOS] [OSR].
- Conditional: 44 when 40 is 2 or 4; 99 when 40 is 3, 4 or K; 432 when 59=6;
  110 for minimum-volume orders; 18 for held orders; 21=3 for staged orders;
  528/529/1724 on MiFID II venues; 2404 on some Eurex and EEX orders
  [NOS] [OCRR].
- 40 `OrdType`: 1 market, 2 limit, 3 stop, 4 stop-limit, 5 MOC, B LOC, J MIT,
  K market-leftover-as-limit, Q MLM, S stop-market-to-limit, T, U, p limit
  post-only; per-exchange support is in the Setup help "Supported Order
  Types and TIFs", not fetched [NOS].
- 59 `TimeInForce` defaults to 0 Day: 1 GTC, 2 OPG, 3 IOC, 4 FOK, 5, 6 GTD,
  7 at-close, 8, 9, A auction, V, W Day+, X GTC+, Y GTD+; S/T/U are OSE
  at-close values not usable over FIX. CME uses 59=3 for IOC and FOK: with
  110 it is FOK, without it IOC [NOS].
- 18 `ExecInst`: 2 work (default), 6 PDI, G AON, S suspend, o
  cancel-on-connection-loss, q release; an unsupported value is substituted.
  Eurex book-or-cancel is 40=2, 18=6, 59=0 [NOS].
- Free text: 58, 16556 TextA, 16557 TextB. Other TT tags: 18218
  TTCustomerName, 18219 SecondaryAccount, 16999 ClearingAccountOverride
  [NOS] [OSR]. 21 `HandlInst` takes 1, 2, 3 (3 = staged) [OCRR].

**Instrument identification**

- TT resolves instruments through PDS; 48 plus 22 works everywhere. 22 values
  unique on their own: 96 TT id, 5 RIC, 4 ISIN, X series key; A Bloomberg
  and S OpenFIGI need 207; 8 exchange symbol, 97 alias and 98 name need 207
  or 100 [INST].
- Alternatives: 455/456 with 207/100, or 55 + 167/461 + 200 (+205) or 541 +
  207/100; options also need 201 and 202; MLEG through the 555 leg group
  with 624 [INST]. A lookup matching more than one instrument is rejected;
  send 200+205 or 541, never both; if both 461 and 201 are sent, 461 wins.
  TT recommends 22=96 [INST].
- Outbound ERs and cancel rejects carry 48 with 22=96 by default; outbound
  symbology is configurable per session [FXS]. TT ids such as
  `17287808984235357550` exceed `i64::MAX`, so parse 48 and 602 as `u64` or
  text (inferred from doc examples, not stated) [MDSUB].

**OrderCancelRequest (F) and OrderCancelReplaceRequest (G)**

- F requires 11 and 41; 37 only when 41 is absent; its table has no 38, 54
  or 55 [OCR]. G requires 11, 41 (or 37), 1, 38, 40, 54 and the same
  conditional tags as D; modifiable fields are not listed [OCRR]. 54 values
  B and C are rejected except on AB/AC [OCRR].

**ClOrdID rules**

- 11 is at most **20 characters** and unique within a FIX trading session
  [NOS]. TT enforces uniqueness against every order since the last reset
  plus GTC/GTD orders still working from earlier sessions; values may be
  reused after the reset [OPS]. A duplicate is a Business Message Reject
  [BMR]. 41 must equal the order's **current** 11, which changes over time;
  37 `OrderID` is TT's key and constant for the order's life [OCR].

**ExecutionReport (8)**

- Normal flow: D gives 150=0 or 150=8, then 150=1 or 2 for fills; F gives
  150=4 or a Cancel Reject; G gives 150=5 or a Cancel Reject [FLOW].
- 150 values: 0–9, A pending new, B, C expired, D restated, E pending
  replace, F trade, G trade correction, H trade cancel, I–L. 39 values: 0–9,
  A–E; z is internal and never sent. 20 exists only in 4.2 [ER].
- 103 `OrdRejReason` has about 90 codes and 378 `ExecRestatementReason`
  about 70, including 9000 unsolicited recovery, 9001 timeout, 9002 pending
  [ER]. For HKEX, JPX and SGX a slow exchange ack produces a pending ER with
  150=D, 39=A, 378=9002 [ER].
- 17 `ExecID` is the exchange's: "do not try to interpret or parse"; 16612
  `UniqueExecID` is TT's, unique for the order's life [ER]. 32/31 are
  present only with 150=1 or 2; 442 is 1 outright, 2 leg, 3 spread summary;
  16611 links leg executions to the spread execution [ER].
- Fills may arrive aggregated in `FillsGrp`/`LegFillsGrp` (1362) in one ER;
  the session option "Send FillsGrp as Individual Execution Reports" splits
  them [ER] [CROR]. 16131 `RejectSource` says where a reject originated;
  18101/18102 are sent only when enabled [ER] [CROR].

**Rejects, status and order book download**

- Cancel Reject (9): 434 is 1 for an F and 2 for a G; 102 is 0 too late, 1
  unknown order, 3 already pending, 6 duplicate ClOrdID, and others [OCJ].
- Business Message Reject (j) when nothing else fits: duplicate ClOrdID,
  PossDup on D or G; 380 is 0 other, 1 unknown id, 2 unknown security, 3
  unsupported MsgType, 4 app unavailable, 5 conditional field missing [BMR].
- Order Status Request (H) is answered by an ER with 150=D. H without 11 and
  37 downloads the order book: one ER per working order with 16728
  `TotalNumOrders`; with no orders, an ER with 39=8/150=8 [OSR].

**Cancel-on-disconnect**

- Per order: `18=o 2` (or `o S` for held orders), `o` first. The ack carries
  18=2 or 18=S. On logout or TCP loss TT makes **one** cancel attempt per
  flagged order on that connection; the notes say GTC/GTD orders are
  rejected when flagged (written as "18=0", an apparent typo for `o`).
  **Not honoured if the TT FIX server itself crashes** [NOS].
- Exchange-level cancel-on-disconnect per market is configured by the
  exchange or TT: CME, ICE, Eurex, SGX and others supported; LME, OSE,
  Coinbase and others not [COD].

**Mass cancel and throttles**

- No mass-cancel message is documented; 102=4 "unable to process Order Mass
  Cancel Request" exists only as a code: UNCONFIRMED.
- No FIX message-rate limit is stated on any FIX page: UNCONFIRMED. The .NET
  SDK FAQ gives 750 price subscriptions, 5 instrument lookups and 50 RFQs a
  second, for the SDK only; `ttaccount /account/{id}/algosettings` caps
  cancels per millisecond for Autospreader and TT Order Type orders, an
  account setting [TTACC].
- IFOA: after an IFOA timeout (30 s) the account, market and connection
  combination is blocked for new orders until a test request succeeds;
  orders on that route are polled until definitive, else reported dead or
  rejected [OPS].

## Market data over FIX

- A separate "FIX Market Data" session also carries Security Definition
  (c/d) and Security Status (e/f); an entitlement per exchange is needed. A
  Security Definition Request is an active subscription by default and not
  a prerequisite for a Market Data Request [MDF] [MDSUB] [SECDEF].
- Market Data Request (V): required 262 (echoed), 263, 267, the 269 group,
  146, and 48+22 or symbol identification [MDV]. 263: 0 snapshot, 1 snapshot
  plus updates, 2 unsubscribe. 264 required with 263 0 or 1: 0 full book, 1
  top, N levels. 265 required with 263=1: 0 full refresh (repeated W), 1
  incremental (one W then X). 266 `AggregatedBook`: only Y. 18214=Y requests
  346 `NumberOfOrders` [MDV] [MDX] [MDF].
- 269 `MDEntryType`: 0 bid, 1 ask, 2 trade, 4 open, 5 close, 6 settle, 7
  high, 8 low, 9 VWAP, A imbalance, B volume, J empty book, L leg trade,
  **Y implied bid, Z implied ask**, m OTC trade, n/o, p–t indicative, u/v
  exchange timestamps, w internal, x last traded. Implied prices are flagged
  only by Y and Z [MDV] [MDW] [MDX].
- Rates: 263=0 updates at ≥1 s; 263=1 at ≥100 ms; incremental coalesced at
  100 ms and full refresh at 1 s; uncoalesced data "by special request" on
  dedicated infrastructure at extra cost; the general pool is multi-tenant
  [MDV] [MDO].
- W groups start with 269; X groups start with 279 `MDUpdateAction` (0 new,
  1 change, 2 delete). 290 `MDEntryPositionNo` is 1-based per side and in X
  is "the position of the entry before processing the current message"; TT
  documents a two-ladder apply algorithm (inserts into "after", changes and
  deletes applied to "before", then merged) [MDW] [MDX].
- Other X tags: 18210 `PriceFeedStatus` only on change; 2446
  `AggressorSide`; 16052/16060 exchange timestamps in µs since the epoch;
  18225 exchange sequence, internal [MDX]. **83 `RptSeq` is not documented**;
  there is no per-instrument sequence for gap detection [MDX].
- **Lost updates are not replayed**: updates during a disruption "are not
  recoverable"; TT recommends redundant live-live sessions; no historical
  ticks over FIX [MDO]. Resubscribing after a reconnect is UNCONFIRMED;
  assume it is needed. Market Data Request Reject (Y) carries the reason in
  58 plus 48, no code [MDY]. No subscription limit is documented.

## Drop copy and recovery

- "FIX Drop Copy" is a separate session type with every FIX function except
  routing; TT is normally the acceptor; outbound 8, 9, AE; the client may
  send H and AR [DCO] [MGS] [FXS] [DCF]. The "Compliance Feed" option adds
  copies of D, G, F, AB, AC and pending ERs for every order flow with MiFID
  II RTS 25 timestamps [DCO] [DCF]. "Assign All Accounts" (default) includes
  every company account dynamically [FXS].
- TT FIX Recovery is a non-persistent session on separate hosts, driven by
  one U2 message, a Logon with 916/917, or 18002 CustomMode for "unsent
  since the last reset"; the window is 720 h for companies under 250
  accounts and 168 h otherwise; only the final state of restated reports is
  returned [REC] [U2]. Inbound drop copy (exchange drop copy into TT) is a
  further session type where TT initiates [FXS].

## TT REST 2.0

- Base `https://ttrestapi.trade.tt/<service>/<env>`, env `ext_uat_cert` or
  `ext_prod_live`; the service segment is lowercase (uppercase gives 403);
  follow 303 redirects; on a 413 send `Accept-Encoding: gzip`; no
  certificate pinning. REST 1.0 was deprecated 2021-06-30 [RINTRO] [RMIG].
- Services: ttid (auth), ttpds (exchanges, products, instruments), ttledger
  (orders, fills), ttmonitor (positions, SOD, credit), ttaccount (account
  risk, users); also ttuser, ttgroup, ttsetup, ttbacktest [RINTRO].
- Auth: header `x-api-key: <appKey>` (a GUID) on every call; most calls also
  need `Authorization: Bearer <token>`. Token: `POST /ttid/<env>/token`,
  `Content-Type: application/x-www-form-urlencoded`, body
  `grant_type=user_app&app_key=<appKey>:<secret>`; reply
  `{status:"Ok", access_token, token_type, seconds_until_expiry}`, errors
  `{status:"Fail"|"StatusFail", status_message}`. Fetch a new token before
  expiry; no refresh grant; the numeric lifetime is UNCONFIRMED
  [RAUTH] [TTID].
- Every request needs `requestId=<app>-<company>--<guid>`, exact case, fresh
  GUID, no spaces or special characters [RAUTH]. App keys are per
  environment, inherit the creating user's permissions, and the secret is
  shown once [RBYB]. ttid also has `GET /keyusage` and
  `GET /healthcheckstatus` [TTID].
- Rate plans: Free (UAT only) 3 req/s and 10k/day; Low 5/s and 15k/day;
  Medium 10/s and 30k/day; High 25/s and 75k/day [RBYB]. POST pacing
  conflicts: "one POST every ten seconds" [RBYB] against "at most 20 list
  items per POST and a 1 s pause after each ack" on the service pages
  [TTMON] [TTLED] [TTPDS] [TTACC].
- Accounts: `ttaccount GET /accounts` (`mineOnly`, `nextPageKey`),
  `/account/{id}`, `/users`, `/children`, `/limits` [TTACC].
- Positions, from today's fills plus SOD, P&L in the instrument's currency:
  `ttmonitor GET /position[?accountIds=…&includeSpreadPositions=1&scaleQty=0|1]`,
  `/position/{accountId}`, `/productposition`, `/productfamilyposition`,
  `/sod/{accountId}`, `/creditutilization?accountId=`; filter by account to
  avoid timeouts [TTMON].
- Orders and fills: `ttledger GET /orders?accounts=` takes at most 50
  accounts and returns at most 1 000 orders with **no paging**;
  `/orders/{orderId}`; `GET /fills` (also `/tradingaccountfills`,
  `/tcrfills`) with `minTimestamp`/`maxTimestamp` in **epoch nanoseconds**
  plus accountId, orderId, productId, at most 500 per call, paged by setting
  `minTimestamp` to the last timestamp plus one; `/positionmodifications`
  for SOD and manual fills [TTLED]. Instruments: `ttpds GET /instruments`,
  `/instrument/{id}`, `/products?marketId=`, `/markets` [TTPDS].
- Pagination: `nextPageKey` in, `lastPage` out, about 500 records a page;
  `lastPage` became a string in v2. ttledger and ttmonitor are "not intended
  to be used as a real-time feed" [TTMON] [TTLED] [RMIG].

## Gotchas TT flags

- Unsolicited cancels are normalised: IOC and FOK leftovers as 39=4/150=4;
  every other unsolicited cancel, end-of-day expiry and SMP included, as
  39=4/150=C [OPS].
- For HKEX, OSE, SGX, TOCOM, NDAQ_EU and NFI, exchange fill updates arrive
  as Trade Capture Report (AE) unless "Send Exchange Fill Updates as Trade
  Correction Execution Reports" is set [CROR].
- Spreads: leg fills 442=2, summary fills 442=3; head fills can be forced
  before leg fills (4.4 only); "Send unsolicited order and fill messages" and
  "Send Staged / Synthetic Child order/fill messages" are per-session
  options [CROR]. Synthetic parents also produce ERs unless "Drop Synthetic
  Parent Execution Reports" is set; 16615 appears only on synthetic spreads
  [FXS] [ER].
- "Instrument Not Found" rejects are routed to drop copy with the lookup
  field and value in 58 [OPS].
- All timestamps are UTC; 60 `TransactTime` is in µs by default (ns
  optional) and only on drop copy with the compliance feed [NOS] [FXS].
- Price formats and fractional ticks: UNCONFIRMED; [OCRR] mentions "price
  conversion via symbol mappings" without detail.

## Source keys

All under `https://library.tradingtechnologies.com`.

| Key | Page |
| --- | --- |
| SYS | `/tt-fix/tt-fix-general/getting-started-tt-fix-general/system-overview/` (2026-09-08 copy) |
| MGS | `…/getting-started-tt-fix-general/managing-fix-sessions/` |
| OPS | `…/getting-started-tt-fix-general/operational-notes/` |
| CERT | `…/getting-started-tt-fix-general/tt-fix-certification/` |
| LOGON, HB, RR, SR | `/tt-fix/tt-fix-general/session-messages/` logon-a, heartbeat-0, resend-request-2, sequence-reset-4 |
| ORO | `/tt-fix/tt-fix-order-routing/overview-tt-fix-order-routing/fix-order-routing-overview/` |
| ORSM, CROR | `…/overview-tt-fix-order-routing/` fix-session-management, creating-a-fix-order-routing-session |
| FXS | `/setup/fix-support/fix-sessions/task-fix-sessions/adding-and-configuring-a-fix-session/` |
| NOS, OCR, OCRR, ER, OCJ, BMR | `/tt-fix/tt-fix-order-routing/supported-application-messages/` new-order-single-d, order-cancel-request-f, order-cancel-replace-g, execution-report-8, order-cancel-reject-9, business-message-reject-j |
| OSR | `/tt-fix/drop-copy/Msg_OrderStatusRequest_H.html` (2026-09-08 copy) |
| FLOW, INST | `/tt-fix/tt-fix-order-routing/tt-fix-message-conversations/` order-routing-message-flows, identifying-instruments-in-order-routing-messages (the latter a 2026-09-08 copy) |
| COD | `/setup/company-administration/connections/reference-connections/cancel-on-disconnect-support/` |
| MDO, MDF, MDSUB, SECDEF, MDSM | `/tt-fix/tt-fix-market-data/` overview and message-conversation pages (MDO, MDSUB, SECDEF from the 2026-09-08 copy) |
| MDV, MDW, MDX, MDY | `/tt-fix/tt-fix-market-data/supported-application-messages-tt-fix-market-data/` market-data-request-v, snapshot-w, incremental-refresh-x, request-reject-y |
| DCO, DCF | `/tt-fix/tt-fix-drop-copy-out/overview-tt-fix-drop-copy-out/tt-fix-drop-copy-overview/`, `/tt-fix/drop-copy/dc-message-flows.html` (2026-09-08 copy) |
| REC, U2 | `/tt-fix/tt-fix-recovery/overview-tt-fix-recovery/fix-recovery-service/`, `/tt-fix/Msg_RecoveryRequest_U2.html` (2026-09-08 copy) |
| RINTRO, RBYB, RAUTH, RMIG | `/apis/tt-rest-api-2-0/getting-started-tt-rest-api-2-0/` introduction, before-you-begin, authentication-and-request-ids, migrating-from-1-0 |
| TTID, TTACC | `/apis/tt-rest-api-2-0/api-reference-tt-rest-api-2-0/` ttid-documentation, ttaccount-documentation |
| TTMON, TTLED, TTPDS | `/apis/tt-rest-api-2-0-uat/api-reference-tt-rest-api-2-0-uat/` ttmonitor, ttledger, ttpds (UAT copies, 2026-09-08) |
