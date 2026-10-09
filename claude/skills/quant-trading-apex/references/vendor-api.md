# APEX vendor API facts

What APEX's own documents say, so the foreign boundary is read against the
vendor rather than against memory. Page citations: TA = TradeAPI (English)
v1.08, MD = MdUserAPI (English) v1.02, DG = Trading API Development Guide
v1.4, CF = Conformance Test Document v1.15, NW = Connecting into APEX
(Network), CB = Connectivity to APEX (Combined); the PDFs live under
`~/dev/apex/connectivity/`, and the PerpetualContracts set is the one that
matches the vendored SDK 1.3.1. `Trading` 1.2.6, `SpreadTrading` 1.3.0 and
`PerpertualContracts` 1.3.1 are three releases of one API, each a strict
superset of the one before; 1.3.1 alone has `AF_Modify`. UNCONFIRMED marks a
fact the extraction left ambiguous. Where a fact here contradicts the
middleware's venue document, the table at the end records both readings.

## Library and session model

- Classes: `CApexFtdcTraderApi` with `CApexFtdcTraderSpi` for callbacks;
  `CApexFtdcMduserApi` with `CApexFtdcMduserSpi` (TA p.11, MD p.8). Created by
  `CreateFtdcTraderApi(pszFlowPath)` / `CreateFtdcMduserApi`, released with
  `Release()`, never `new`/`delete` (TA p.106, MD p.23).
- Init sequence: create, make the SPI, `RegisterSpi`, subscribe topics,
  register name server or front, `Init()`; `Join()` waits on the API thread
  (TA p.13, p.107; MD p.9).
- `RegisterNameServer` and `RegisterFront` both take `tcp://ip:port` and must
  precede `Init`. `RegisterFront` is kept for compatibility and "will be
  removed in the next version"; APEX publishes only name servers. If both
  are registered the API tries the fronts first, then a random name server,
  takes the gateway list from it and connects to one (TA p.13, p.20, p.25-26).
- Flow directory: the API writes `.con` files there; it must exist, and
  different users need different directories or "may not be able to receive
  some data" (TA p.20, MD p.11, DG p.5). The sequence id of each
  reliable-stream message is written *after* the callback returns, so a crash
  in between replays a duplicate (TA p.21-22). `resume.con` holds TradingDay
  and DataCenterID from the last login and overrides the login request
  (TA p.22).
- Trade-session streams: `SubscribePrivateTopic` (member), `SubscribeUserTopic`
  (trader), `SubscribePublicTopic`; all before `Init`, and a stream not
  subscribed delivers nothing (TA p.109-110).
- Resume types: `TERT_RESTART` replays the trading day; `TERT_RESUME` continues
  from the local file; `TERT_QUICK` sends only what follows login. APEX
  recommends RESUME on private and user streams and does not recommend QUICK
  (TA p.22, p.109-110). RESTART resends everything, so dedupe by OrderSysID,
  OrderLocalID and TradeID; RESUME can lose data received but not processed
  (DG p.6).
- Member-managed sequencing: read `nSequenceNo` in
  `OnPackageStart/OnPackageEnd(nTopicID, nSequenceNo)` and resubscribe with
  `ReqSubscribeTopic{SequenceSeries, SequenceNo}`: 0 = RESTART, -1 = QUICK,
  any other value resumes from it. APEX calls this "more consistent and
  reliable" (TA p.22-23, p.114).
- Threading: one API worker thread drives every SPI callback; a blocking
  callback stalls all communication, so return quickly and buffer (TA p.14,
  MD p.10). The TraderApi request interface is thread-safe (TA p.14); MD says
  nothing on thread safety.
- Reconnect: on `OnFrontDisconnected(nReason)` the API reconnects by itself,
  possibly to another address; `OnFrontConnected` means TCP only, and the
  member must log in again (TA p.32-33, MD p.15). Logging out does not stop
  the auto-reconnect; terminate inside `OnRspUserLogout` to really disconnect
  (DG p.5).
- Disconnect reasons: 0x1001 read failure, 0x1002 write failure, 0x2001
  heartbeat receive timeout, 0x2002 heartbeat send timeout, 0x2003 error
  message received (TA p.33).
- Heartbeat, `SetHeartbeatTimeout(seconds)` (TA p.24, p.108): without the call
  the API sets 10 s after connecting; minimum 4 s, 10 to 30 s recommended.
  The server beats every (timeout-1)/3 s when idle;
  `OnHeartBeatWarning(nTimeLapse)` fires at timeout/2 with no message; the API
  disconnects at the timeout. The gateway drops a dead link about
  timeout + 5 s later, and until then a login from another IP is rejected.
- `GetVersion()` is static; `GetTradingDay()` is valid only after login
  (TA p.106-107, MD p.23). `OpenRequestLog` / `OpenResponseLog` audit traffic
  but not logins or queries (TA p.20, p.109). `RegisterCertificateFile` is
  listed but has no section: UNDOCUMENTED (TA p.28).
- DR: after a site switch, `OnRtnFlowMessageCancel{SequenceSeries, TradingDay,
  DataCenterID, StartSequenceNo, EndSequenceNo}` reports the messages rolled
  back in (Start, End] (TA p.27, p.88-89).
- Every enum type is a `char`; the "numerical values" are char codes ('0',
  '1', …) (TA p.156-157; DG p.7).
- Every request returns 0 ok, -1 network failure, -2 too many unprocessed
  requests, -3 over the per-second request allowance (TA p.112, MD p.26). No
  threshold is stated for -2 or -3.

## Login

- `CApexFtdcReqUserLoginField`: TradingDay, UserID, ParticipantID, Password,
  UserProductInfo, InterfaceProductInfo, ProtocolInfo, DataCenterID
  (TA p.111-112). Put the system name and version in UserProductInfo; the
  conformance test requires both product fields as `systemname_version`
  (TA p.112, MD p.25, CF p.8).
- First login: TradingDay "" and DataCenterID 0 or the primary DC; afterwards
  reuse both from the previous reply when resuming (TA p.23, p.112).
- `CApexFtdcRspUserLoginField`: TradingDay, LoginTime, MaxOrderLocalID,
  UserID, ParticipantID, TradingSystemName, DataCenterID, PrivateFlowSize,
  UserFlowSize (TA p.34). MaxOrderLocalID is the base for new OrderLocalID
  and ActionLocalID (DG p.6, TA p.116). No session or front id is returned.
- Login error codes: 3 participant not found; 45 data-group datasync not
  initialised (too early; retry every minute); 60 invalid user or password;
  62 user not active; 64 user not in this participant; 65 invalid login IP;
  100 invalid user type; 106 duplicated session; appendix adds 59 duplicated
  user login and 107 not authorised (TA p.35, p.147-148; DG p.5; CF 3.1.5).
  Wait 1 s after login before querying (CF 3.1.2).
- One login id may be logged into the trade and MD gateways at once. Logging
  into the same gateway again force-disconnects the existing session
  (DG p.4), which sits uneasily with code 106.
- User types: Single Trade sees only its own orders and trades and
  subscribes the User topic; Manage Trade sees every user of the member and
  its sponsored members and subscribes the Private topic; production issues
  Single Trade unless Manage Trade is approved; always subscribe Public for
  instrument status (DG p.5, CF 3.1.3). UserType enum: Trader 1, TradeManager
  2, MDUser 3, SingleTrader 4 (TA p.149-150).
- `ReqUserPasswordUpdate{UserID, ParticipantID, OldPassword, NewPassword}`;
  the only stated constraint is `char[41]`; no password policy is documented
  (TA p.36-37, p.113, p.155).

## Order insert

`ReqOrderInsert(CApexFtdcInputOrderField*, nRequestID)` (TA p.115-118).

- Fields: OrderSysID (exchange-filled), ParticipantID, ClientID, UserID,
  InstrumentID, OrderPriceType, Direction, CombOffsetFlag, CombHedgeFlag,
  LimitPrice, VolumeTotalOriginal, TimeCondition, GTDDate (not used),
  VolumeCondition, MinVolume (not used), ContingentCondition, StopPrice (not
  used), ForceCloseReason, OrderLocalID, IsAutoSuspend, BusinessUnit
  ("not used").
- Direction: Buy '0', Sell '1' (TA p.150). OrderPriceType: AnyPrice '1',
  LimitPrice '2', BestPrice '3' (TA p.151). TimeCondition: IOC '1', GFS '2',
  GFD '3', GTD '4', GTC '5', GFA '6', only IOC and GFD enabled (TA p.152,
  p.158; DG p.8-9). VolumeCondition: AV '1', MV '2', CV '3'; CV only with IOC
  (TA p.116, p.153). ContingentCondition only Immediately '1';
  ForceCloseReason only NotForceClose '0' (TA p.117).
- Supported combinations: Limit+AV+GFD = GFD; Limit+AV+IOC = FAK;
  Limit+CV+IOC = FOK; AnyPrice+AV+IOC = Market; nothing else (TA p.158;
  CF p.2). Best Price and Five Level rows are all "No" (DG p.8). Only GFD is
  allowed during AuctionOrdering; no entry during AuctionMatch (DG p.9).
- OffsetFlag: Open '0', Close '1', ForceClose '2', CloseToday '3',
  CloseYesterday '4' (TA p.151); the v1.01 changelog says CombOffsetFlag was
  removed from insert because the engine ignores it, yet the struct keeps it
  and the example fills "0" (TA p.2, p.142).
- HedgeFlag: Speculation '1', Arbitrage '2', Hedge '3', MarketMaker '4'
  (TA p.150-151); on insert CombHedgeFlag "can only fill in '1'" and only its
  first char is read (TA p.116-117).
- OrderLocalID and ActionLocalID are `char[13]`, compared as strings, so fill
  the whole width (TA p.116-117, p.156). They share one rising series: each
  new id must exceed max(last OrderLocalID, last ActionLocalID); DG suggests
  member id + trading day + timestamp + counter (DG p.6). Error 12 means
  "alphabetically less than" the last id (TA p.41). nRequestID must not
  repeat within a session (TA p.117).
- IsAutoSuspend is an int bool; its semantics are not described (TA p.143,
  p.157). BusinessUnit is `char[21]` free text, echoed on the order ack and
  trade report per the appendix and CF 3.6.4, while the struct comments mark
  it "not used" on insert, order return and trade return (TA p.77, p.79,
  p.116, p.159).
- `OnRspOrderInsert`: ErrorID 0 accepted; only OrderSysID and OrderLocalID are
  meaningful; take details from the private stream (TA p.39-43). Rejects
  after acceptance come as `OnErrRtnOrderInsert` (TA p.89-90).
- `OnRtnOrder` fires on every status change and reaches the user's stream and
  the member's private stream (TA p.15-16, p.77). Its fields include
  OrderSysID, OrderLocalID, OrderStatus, VolumeTraded, VolumeTotal
  (remaining), InsertDate/Time, ActiveTime, SuspendTime, UpdateTime,
  CancelTime, Priority, TimeSortID, BusinessUnit, CalendarDate,
  Insert/Update/CancelMillisec; on the return copy TradingDay, VolumeTraded,
  InsertTime, CancelTime, OrderType, Priority and TimeSortID are marked "not
  used" (TA p.55-57, p.77-79).
- OrderStatus: AllTraded '0', PartTradedQueueing '1', PartTradedNotQueueing
  '2', NoTradeQueueing '3', NoTradeNotQueueing '4', Canceled '5'; no
  suspended or touched value (TA p.152). OrderType: Normal '0',
  DeriveFromQuote '1', DeriveFromCombination '2'; OrderSource Participant '0',
  Administrator '1' (TA p.152-153).
- OrderSysID is unique within a trading day and resets daily; night-session
  orders carry into the next sessions of the same trading day (DG p.6). At
  Closed ('6') the exchange deletes every order; cancels then are rejected
  (DG p.6-7, CF 3.6.6).

## Order action

`ReqOrderAction(CApexFtdcOrderActionField*, nRequestID)` (TA p.118-119).

- Fields: OrderSysID, OrderLocalID, ActionFlag, ParticipantID, ClientID,
  UserID, LimitPrice, ActionLocalID, VolumeChange, BusinessUnit ("not used").
  The target is named by either OrderSysID or OrderLocalID (TA p.119).
- ActionFlag: Delete '0', Suspend '1', Active '2', Modify '3' (TA p.153); the
  field note says only deletion and modification are supported, and 5.3
  lists order action as "Partially open" (TA p.31, p.118).
- Modify, new in v1.08 (31 Jul 2024): LimitPrice is the absolute new price;
  VolumeChange is relative, positive adds and negative removes (TA p.2,
  p.118-119; example LimitPrice 570, VolumeChange -3 on p.19). In v1.06 both
  were "not used" and only delete existed.
- Returns: `OnRspOrderAction`; async errors as `OnErrRtnOrderAction`; a
  successful cancel produces `OnRtnOrder` with Canceled (TA p.43-45, p.90-91;
  DG p.11). The modify diagram shows only "Modification response: success";
  whether an `OnRtnOrder` follows a modify, and whether queue priority is
  kept, are NOT STATED (TA p.19).
- Action errors: 3, 4, 8 bad action field, 15, 22/23 not in sync, 24 order
  not found, 26 invalid in current status, 28 fully traded, 29 already
  cancelled, 32/34 position limits on modify, 35, 36, 37 invalid volume, 48
  tick, 49/50 limit price, 57, 58, 1, 76/77 already suspended/activated, 96,
  97 duplicated action (ActionLocalID not greater than the last), 99 cannot
  act for another user (TA p.44-45).
- Production support: CF 3.4.1 tests modify on price and quantity (CF p.10)
  while CF 3.6.16 still says "APEX does not support order modification"
  (CF p.17).

## Trades, executions, positions and funds

- `OnRtnTrade` fields: TradingDay, SettlementGroupID, SettlementID, TradeID
  (`char[13]`), Direction, OrderSysID, ParticipantID, ClientID, InstrumentID,
  OffsetFlag, HedgeFlag, Price, Volume, TradeTime, UserID, OrderLocalID,
  CalendarDate, TradeMillisec; TradingRole, AccountID, TradeType,
  PriceSource, ClearingPartID and BusinessUnit are "not used" (TA p.76-77).
  Both sides of one match carry the same TradeID in the example (TA p.18).
- Ordering: the order return arrives before the trade return and its traded
  volume already reflects the fill, so do not add trade volumes to it again
  (TA p.16); yet `OnRtnOrder`'s VolumeTraded is marked "not used" (TA p.78).
  VolumeTotal, the remaining volume, carries no caveat.
- Spread fills produce three `OnRtnTrade` calls: one spread trade at a
  synthetic price and two leg trades (DG p.11).
- Positions: `ReqQryPartPosition{PartID range, InstID range}` at member level
  returns HedgeFlag, PosiDirection, YdPosition, Position, Long/ShortFrozen,
  YdLong/YdShortFrozen, InstrumentID, ParticipantID, TradingRole;
  `ReqQryClientPosition{PartID, ClientID, InstID ranges, ClientType}` adds
  BuyTradeVolume, SellTradeVolume, PositionCost, YdPositionCost, UseMargin,
  FrozenMargin, Long/ShortFrozenMargin, FrozenPremium, ClientID
  (TA p.63-66, p.129-130). Volumes are unsigned ints; the side is
  PosiDirection Net '1', Long '2', Short '3'; the instrument's PositionType is
  Net '1' or Gross '2'. No signed-quantity convention is documented
  (TA p.150).
- Funds: `ReqQryPartAccount{PartID range, AccountID optional}` returns
  PreBalance, CurrMargin, CloseProfit, Premium, Deposit, Withdraw, Balance,
  Available, AccountID, FrozenMargin, FrozenPremium, BaseReserve, all
  `double`; currency and units are not stated (TA p.53-54, p.125).
  `ReqQryCreditLimit{ParticipantID, ClearingPartID}` returns the same
  figures per clearing member (TA p.103-104, p.139-140).

## Queries and limits

- Shape: `Req*` then repeated `OnRsp*(data, RspInfo, nRequestID, bIsLast)`;
  RspInfo may be NULL after the first callback (TA p.11-12, p.35). Request
  ids are the member's to keep unique (TA p.11). Query and dialog streams are
  unreliable: no retransmission, in-flight data lost on failure (TA p.9-10,
  p.21). Incomplete queries are removed after a timeout whose value is not
  given (TA p.124).
- Filters, empty optional fields ignored (TA p.125): `ReqQryOrder` PartID
  range (own member only), OrderSysID, InstrumentID, ClientID, UserID,
  TimeStart, TimeEnd (p.125-126); `ReqQryTrade` PartID range, InstID range,
  TradeID, ClientID, UserID, TimeStart/End (p.127-128); `ReqQryClient` PartID
  and ClientID ranges (p.128); `ReqQryInstrument` SettlementGroupID,
  ProductGroupID, ProductID, InstrumentID (p.131); `ReqQryInstrumentStatus`
  InstID range (p.131); `ReqQryCombinationLeg` (p.132); `ReqQryMarketData`
  ProductID, InstrumentID (p.133); `ReqQryBulletin` (p.133-134);
  `ReqQryMBLMarketData` InstID range and Direction, returning per-price
  rows (p.74, p.134); `ReqQryHedgeVolume` (p.135); `ReqQryTopic`
  SequenceSeries (p.114).
- Time and date fields are `char[9]`; their format is NOT STATED (TA p.155).
  No paging and no maximum instruments per query are documented.
- Permission errors: 80 user has no permission (only your own participant),
  57 cannot operate for another participant (TA p.54, p.57, p.61, p.63,
  p.65-66).
- Send quota: each seat has a per-second instruction quota; past it,
  instructions "will be blocked in the network"; ask the exchange for the
  number. No figure appears in any document (TA p.106).
- Not open in this version: ReqCombOrderInsert, quotes, ExecOrder,
  ReqQryCombOrder, OnRtnIns/DelCombinationLeg, OnRtnDelInstrument,
  OnRtnAliasDefine, SubscribeForQuote (TA p.31-32, p.84-86, p.110).

## Market data (MdUserAPI)

- Topics: one topic is one stream; its contracts, depth, sample frequency and
  delay are announced by the exchange (MD p.7). `SubscribeMarketDataTopic(
  nTopicID, resumeType)` before `Init`; `ReqSubscribeTopic` and `ReqQryTopic`
  after login (MD p.25-27). Resume: RESTART replays the day, RESUME continues
  from the last transmission, QUICK sends a snapshot first then everything
  after; MD recommends QUICK for fast recovery (MD p.25), and TA says RESUME
  on a market-data stream also sends a per-contract snapshot first
  (TA p.21-22). With member-managed resume and SequenceNo ≠ 0, snapshots of
  every contract come first with `nSequenceNo = 0` (TA p.23).
- Gap detection: each topic has its own sequence number in
  `OnPackageStart/End`; no explicit gap procedure is documented (MD p.15-16).
  `OnRspSubscribeTopic` / `OnRspQryTopic` return
  `CApexFtdcDisseminationField{SequenceSeries, SequenceNo}`; on a query
  SequenceNo is the topic's message count (MD p.17-18).
- `OnRtnDepthMarketData` is called "whenever there is any change"; each call
  is a full record; cadence is NOT STATED (MD p.21).
- Depth fields (MD p.21-22): TradingDay, SettlementGroupID, SettlementID,
  LastPrice, PreSettlementPrice, PreClosePrice, PreOpenInterest, OpenPrice,
  HighestPrice, LowestPrice, Volume (int), Turnover, OpenInterest,
  ClosePrice, SettlementPrice, UpperLimitPrice, LowerLimitPrice, PreDelta and
  CurrDelta (not used), UpdateTime (`char[9]`), UpdateMillisec, InstrumentID,
  Bid/AskPrice1-5, Bid/AskVolume1-5 (int), BandingUpperPrice,
  BandingLowerPrice, ReferencePrice, CalendarDate,
  BestBid/BestAskImpliedPrice and Volume.
- Empty floating fields are sent as DBL_MAX: show 0 for volume, blank
  otherwise (DG p.9). Upper/LowerLimitPrice breaches give errors 49/50;
  BandingUpper/LowerPrice breaches give 125/126 (TA p.146, p.149). The
  meaning of ReferencePrice and how the band is computed are NOT STATED.
- Implied prices: only first-level implieds are shown; they may appear among
  the five levels, and the best implied bid and ask go in the
  BestBid/AskImplied fields (DG p.11).
- Instrument status arrives on the **trade** session's public stream as
  `OnRtnInstrumentStatus{SettlementGroupID, InstrumentID, InstrumentStatus,
  TradingSegmentSN, EnterTime, EnterReason, CalendarDate}` (TA p.83); MD v1.02
  documents only `ReqQryInstrumentStatus`, although CF 3.1.4 expects
  `SubscribePublicTopic` on the MD API too (MD p.20, p.28; CF p.2, p.7).
- InstrumentStatus (TA p.150, DG p.7): '0' BeforeTrading, '1' NoTrading
  (pause, orders kept), '2' Continuous (orders and matching), '3'
  AuctionOrdering (orders, no matching), '4' AuctionBalance (not in use), '5'
  AuctionMatch (matching only), '6' Closed. EnterReason: Automatic '1',
  Manual '2', Fuse '3', FuseManual '4' (TA p.151).
- `OnRtnMarketData` on the trade session (added v1.07) fires when the
  previous settlement price updates; DSP is sent after market close
  (TA p.104-105, CF 3.7.5, DG p.9).
- Instrument record `CApexFtdcRspInstrumentField`: ProductClass,
  VolumeMultiple, PriceTick, Max/MinMarketOrderVolume,
  Max/MinLimitOrderVolume, CurrencyID, IsTrading, ExpireDate and more
  (MD p.18-19, TA p.67-68).

## Error codes

TradeAPI appendix p.144-149, titled "To Translate Upon Request"; local
return codes are not ErrorIDs.

| Code | Meaning |
| --- | --- |
| -1 / -2 / -3 | local: network failure / too many unprocessed requests / over the per-second allowance |
| 1 | not logged in (66 "user not login" in ExecOrder) |
| 2 / 3 / 4 | instrument / participant / client not found |
| 6 / 8 | bad order field / bad order action field |
| 12 | duplicate order: OrderLocalID not greater than the last order or action id |
| 15 | client does not belong to participant |
| 16 / 17 / 18 / 19 / 20 / 21 | IOC only in continuous trading / GFA only in auction / market order cannot queue / volume constraint only with IOC / GTD expired / volume below minimum |
| 22 / 23 | exchange / settlement group not in sync: retry later |
| 24 / 26 / 27 / 28 / 29 | order not found / invalid action in current status / invalid status shift / fully traded / already cancelled |
| 31 / 32 / 34 | not enough position to close / client position limit / participant position limit |
| 35 / 36 / 37 | account not found / insufficient balance or credit / invalid volume (not a multiple of the minimum, or above the maximum) |
| 45 | data-group datasync not initialised: login too early |
| 48 / 49 / 50 | price not a tick multiple / above upper limit / below lower limit |
| 51 / 52 / 53 | no trading right / close only / invalid trading role |
| 57 / 58 | cannot operate for another participant / user mismatch |
| 59 / 60 / 62 / 64 / 65 / 67 / 68 | duplicated user login / invalid user or password / user not active / user not in participant / invalid login IP / not logged in by this user / by this participant |
| 76 / 77 | order already suspended / already activated |
| 78 / 79 / 80 | GTD date missing / unsupported order type / user has no permission |
| 96 / 97 / 99 | not enough hedge volume / duplicated action (ActionLocalID not greater than last) / cannot act for another user, also "force close only by administrator" |
| 100 / 103 / 106 / 107 | invalid user type / cannot close today's hedge position / duplicated session / not authorised for this function |
| 108-113 | credit administration; 111 insufficient credit |
| 114 | best-price order cannot queue |
| 125 / 126 / 127 | price above upper band / below lower band / market order only in continuous trading |
| 128 / 129 / 130 | bad time condition for any-price / best-price / five-level order |
| 131-135 | combination and leg position errors |

## Network

- Two Singapore data centres: Equinix SG3 (primary) and Singtel KC2 (DR).
  NW calls them active-active; TA says the main DC processes and the backup
  is an asynchronous standby, so part of the data may be lost on switchover
  (NW p.3, p.6; CB p.2; TA p.27).
- Links: dual point-to-point, hybrid, cross-connect, MPLS or financial
  extranet (BT Radianz, Colt PrizmNet). IPSec over the internet is prohibited
  for production and allowed only for DR, with the pages disagreeing on
  where (NW p.6-11). Source NAT is required and assigned by APEX; members
  handle their own failover routing (NW p.6).
- Production has four name servers, two primary and two DR; register all four,
  primaries first (DG p.4, CF 3.1.1). Sample addresses
  `tcp://10.32.100.31-34:4901` (trade) and `:4903` (MD) are samples only
  (DG p.4); the API examples use 17001 and 17011 (TA p.144, MD p.32).
  Failover through a name server is transparent: it hands back the new
  gateway, and the API walks the announced list on failure (TA p.20, p.25).
- UAT endpoints, clock discipline, NTP and time zone appear in no document.
- DMA onboarding: member consent, conformance test, seat id and MD
  subscription, clearing member sets PTRC parameters (CB p.6). The documents
  are published at `github.com/apex-dev/connectivity` (CB p.11).

## Conformance test (v1.15)

- Records connection type, server spec, platform version and the assigned
  Participant, User and Client ids (CF p.4-5). Each case is Pass/Fail/NA with
  evidence; the sign-off is PASSED or NOT PASSED (CF p.6, p.22).
- 3.1 Login: four name servers; wait 1 s after login; user type; subscription
  methods and resume type; retry on 45; override `OnHeartBeatWarning`; able
  to disconnect despite auto-reconnect; password change then re-login;
  ProductInfo fields (CF p.6-8).
- 3.2 Instruments: query list and status, query spread legs, receive status
  updates (CF p.9). 3.3 Bulletin, optional (CF p.9-10).
- 3.4 Futures orders: GFD in eight scenarios including modify then cancel,
  modify then partial fill, modify then full fill; FAK; FOK; Market; rejects
  for price out of bounds, invalid client, unsupported type; multiple fills;
  filter spreads if unsupported (CF p.10-12). 3.5 Spread orders, as 3.4
  without modify, plus "not allowed in auction" (CF p.12-14).
- 3.6 Basic trading: TradingDay from login; two ClientIDs on one user; omnibus
  (two Single Trade users each seeing only its own); BusinessUnit echoed in
  trades; CalendarDate; purge after close; reconciliation on start and
  reconnect; order and trade book survive restart; Manage Trade (optional);
  night-session carry-over; capacity of at least 100 000 orders and 50 000
  trades a day; questionnaire on synthetic modify, iceberg, spread records;
  reject handling; query orders, trades and status on startup and reconnect;
  instrument status subscription (CF p.15-19).
- 3.7 Market data: snapshot on login, all updates, level 2 = top 5, best
  implied in the five levels, previous settlement via `OnRtnMarketData`
  (CF p.19). 3.8 risk questionnaire; 3.9 system information (CF p.20-21).

## Spread trading

- Calendar spreads (`SP_` prefix, same underlying) and inter-commodity
  spreads (`SPC_`); tell them apart from the legs, not the id (DG p.9-10).
  ProductClass Combination '3'; futures '1' (DG p.10, TA p.150).
- `ReqQryCombinationLeg` returns {SettlementGroupID, CombInstrumentID, LegID,
  LegInstrumentID, Direction, LegMultiple, ImplyLevel}: three rows per
  spread, LegID 0 the spread and 1, 2 the legs; LegMultiple is 1 for
  calendars; ImplyLevel is not in use (TA p.70, MD p.20-21, DG p.10).
- Spread orders use ordinary `ReqOrderInsert` with the spread instrument id
  (Market, Limit, FAK, FOK) and cancel with `ReqOrderAction`; they are not
  allowed in auctions, and leftovers in a later auction are cancelled at its
  end (DG p.10-11). `ReqCombOrderInsert` is "Not open" (TA p.31).
- Spread limits: upper = leg1 upper − leg2 lower; lower = leg1 lower − leg2
  upper; prices may be zero or negative. Spread status derives from the
  legs; spread DSP is the difference of the leg DSPs (DG p.11-12).

## Where the documents and the middleware module disagree

| Topic | Vendor documents | Module (`docs/venues/APEX.md`) |
| --- | --- | --- |
| Heartbeat default | 10 s when `SetHeartbeatTimeout` is not called (TA p.24, DG p.6); 19 appears only in the MD example (MD p.31) | 19 s unless the document sets it, called "the venue's own default" |
| Seat quota | exists, blocked in the network, figure on request (TA p.106) | 50 a second by default |
| Local -2 and -3 | confirmed, thresholds unstated (TA p.112) | mapped to `RateLimited`; V5 asks the figures |
| Trader library | `APEXtraderapi.so` (TA p.7) | `libapextraderapi.so`, the shipped file |
| Local ids | `char[13]`, string compare, pad to width (TA p.116, p.156); one series with actions (DG p.6) | twelve digits, one series: consistent |
| Suspended orders | no suspended status (TA p.152), yet Suspend/Active flags and errors 76/77 exist | read as `Canceled`; V2 open |
| Modify | new in v1.08; CF 3.4.1 tests it, CF 3.6.16 denies it | sent as `AF_Modify`; the venue says unsupported in production (V11) |
| Modify ack | only `OnRspOrderAction` in the diagram (TA p.19); `OnRtnOrder` after modify and queue priority unstated | no `AmendAck`; V3 asks about priority |
| `BusinessUnit` | echoed (TA p.159, CF 3.6.4) and "not used" (TA p.77, p.79, p.116) | the `OURS` label |
| `HedgeFlag` | insert accepts '1' only (TA p.117) | document offers four values |
| Depth record | five levels confirmed, plus settlement, open/high/low/close and implied fields (MD p.21-22); full record per change | `Reference`, `MarketStats`, `Clear`, ten levels |
| Absent values | DBL_MAX (DG p.9) | `f64::MAX`, NaN for unset limits |
| Price errors | 49/50 limits, 125/126 bands (TA p.146, p.149) | both `InvalidPrice` |
| Login refusals | 3, 45, 60, 62, 64, 65, 100, 106, plus 59 and 107 (TA p.35, p.147-148) | 60 named; any refusal is `Fatal` on order entry |
| Second login | 106 "duplicated session" (TA p.35) vs force-disconnect of the first (DG p.4) | not described |
| Positions | two queries, member and client level (TA p.129-130); no sign convention | one member-level ask; `NET` sign unverified |
