# Every edge was a bug

*A case study in measuring a trading system honestly.*

I built a research and paper-trading system for Indian equities and F&O,
then tried to find a strategy worth trading on it. Over 25 pre-registered
hypotheses, none survived. That result isn't the interesting part. The
interesting part is how many times the system *said* it had found something,
and why.

Again and again, a number that looked good turned out to be a bug. None of
these bugs crashed anything. Each one made a losing system look profitable,
or a broken one look healthy, and kept quiet about it. This document is
about those bugs: how each one was caught, and the guard that now stops it
coming back.

---

## The rules I held myself to

The guardrails are described in the [README](README.md#research-guardrails).
In short:

- **Register first.** Every hypothesis goes in an append-only ledger before
  it is tested, and the trial count feeds the multiple-testing correction.
- **Beat holding, not zero.** A result has to beat simply holding the same
  stocks for the same period, after costs and after adjusting for market
  exposure (beta).
- **Holdout once.** The last part of the sample is evaluated exactly once.
- **Shuffled null.** A result also has to beat a matched null: the same
  universe, sizing and costs, but with random signals.
- **An unrun gate is a fail.** Missing data never counts as a pass.

These rules caught most of what follows. The bugs they couldn't catch on
their own are the reason the rules are now enforced in code, not kept as a
checklist.

---

## The bugs

### 1. The monitor that could never fire

**Symptom.** The dashboard reported a profit factor far higher than any real
strategy produces, and the drift alarm stayed quiet.

**Cause.** The metric summed option-premium percentages. A long option that
doubles reads +100%, so the number measured premium swings, not account
returns. The alarm only fired when the metric was *too low*, so an inflated
number could never trip it.

**Guard.** The metric is now computed on the underlying's move. The alarm
also fires when a result is *implausibly good*, because a number that is too
good is a bug until proven otherwise.

### 2. Signals built on half-formed candles

**Symptom.** A daily-close swing screen produced dozens of signals a day.

**Cause.** It ran at 09:15–09:50 on the broker's daily series, which
includes *today's* bar while it is still forming. A "close above the base"
was often just the first half hour of a session. When I re-ran the same
screen on finished bars, from two independent data sources, it almost never
fired.

**Guard.** Daily signals are now built only on completed sessions. Each one
is stamped with the bar it was computed from, and it can only be filled at a
*later* session's close. In this repo,
[`test_a_signal_never_trades_on_its_own_bar`](tests/test_backtest_gbm.py)
pins the same rule for the backtester.

### 3. A universe made only of survivors

**Symptom.** Mid- and small-cap backtests looked far healthier than
large-cap ones.

**Cause.** The free data source only lists companies that still exist. Of 25
mid/small caps I could confirm were trading in 2018, only 5 were still there;
the rest had been delisted, merged or renamed. The missing names had
typically fallen 70–95% before they disappeared. A backtest that can't see
the failures can't lose money on them.

**Guard.** I built a point-in-time archive from the exchange's own
end-of-day files: 3,526 symbols, including delisted ones up to their last
trading day. `core/leakage_audit.py` flags any study whose universe is
today's survivors.

### 4. A stock split read as a crash

**Symptom.** An index ETF portfolio measured an annual volatility above
180%, with a single day of about −90%.

**Cause.** The ETF had a 1:10 split. The "adjusted" data came back
unadjusted. The exchange's own previous-close field isn't adjusted either,
so raw history shows every split as a crash, and every bonus issue as a
breakout.

**Guard.** [`core/corporate_actions.py`](core/corporate_actions.py)
`flag_panel()` detects ex-dates at standard split and bonus ratios and
neutralises them. Every price panel goes through it before anything is
measured. A 3-for-4 ratio is deliberately excluded, so that a genuine 25%
gap isn't erased.

### 5. A stand-in that matched on price but not on range

**Symptom.** The market-regime gate blocked every trade, on days the index
was clearly trending.

**Cause.** The gate used the index ETF as a stand-in for the index itself.
Their closes correlate at 0.97, but the ETF's daily highs and lows are
noisier. On the same day the trend-strength indicator (ADX) read 12.1 on the
ETF and 38.1 on the index: "no trend" against "strong trend".

**Guard.** The gate now reads the real index. If it ever has to fall back to
the ETF, the series is flagged and the gate reports *unknown* rather than
passing or blocking. **Lesson:** test a stand-in on the statistic you
actually compute, not on its price chart.

### 6. Profit and loss from a moving reference point

**Symptom.** In the paper fund, one sleeve showed a loss over a period when
it had actually gained.

**Cause.** Sleeve values were rebased on a *rolling* price window, so the
reference price moved every day. A sleeve's value changed without any trade
happening.

**Guard.** Prices are anchored once, when a position is opened. A ledger
invariant (`cash + cost basis == capital + realised P&L`) is checked on every
write, and it raises rather than warns. A P&L number from a ledger that leaks
is worthless.

### 7. Gates that switched themselves off

Two separate safety gates failed *open* in the same way.

- **The ML filter.** The saved model had schema version 1; the code expected
  version 2. The loader logged a mismatch, returned nothing, and the filter
  treated "no model" as "pass everything". When I retrained it properly, it
  chose the *worst* trades more often than chance. It was removed: a filter
  cannot rescue a signal that loses money on average.
- **The liquidity veto.** It read its thresholds from a data file that wasn't
  tracked in git. In any fresh clone the file was missing, the veto silently
  allowed everything, and a large position in a stock below the liquidity
  floor was sized and filled with the reason `"ok"`.

**Guard.** [`core/selection.py`](core/selection.py) `is_measured()`
distinguishes *"failed the floor"* from *"there was no floor"*, and an
unmeasured symbol is not tradeable. **Lesson:** when a gate depends on a data
file, check that the file is tracked. If it isn't, the gate is off on every
machine but yours, and your tests pass only on yours.

### 8. Five weeks of silence that looked like a quiet market

**Symptom.** The scanner reported "0 signals passed all gates" every day for
five weeks, and the paper account reported itself healthy.

**Cause.** The broker token was a 7-character placeholder, so every data
request was rejected. Each failure was logged at debug level and skipped, and
an empty universe printed exactly the same line as a quiet day. The
placeholder had been written into the real credential store **by the test
suite itself**.

**Guard.**
- The scan counts symbols with no data, and raises once more than half the
  universe is missing.
- The test suite runs against an isolated credential store, and a tripwire
  raises if any test touches the real one.
- In this repo, [`core/secrets.py`](core/secrets.py) has no write path at all
  ([`test_the_module_has_no_write_path`](tests/test_secrets_env_only.py)).

**Lesson:** a clean zero is a claim about the market, and it has to be
earned.

### 9. The validator that certified a loser

**Symptom.** A strategy with a *negative* Sharpe ratio passed the Deflated
Sharpe Ratio test, with a score of 0.999.

**Cause.** When no trial dispersion was supplied, the code used the observed
Sharpe ratio as a stand-in for it. For a losing strategy that value is
negative, but a standard deviation never is. The negative value produced a
negative benchmark, which the loser then "beat".

**Guard.** [`core/deflated_sharpe.py`](core/deflated_sharpe.py) now takes
the absolute value, and a strategy that loses money can never pass. That
rule is pinned by
[`test_a_losing_strategy_is_never_validated`](tests/test_deflated_sharpe.py).
I found this bug only because I ran the gate on a known loser. **Lesson:**
every gate needs a test against a null and against a known failure, not
just against a known success.

---

## The shape they share

None of these bugs threw an exception. Every one of them pushed the result
in the flattering direction: higher returns, a healthier system, a passing
test. That is not a coincidence. Bugs that make a backtest look *worse* get
investigated the same day. Bugs that make it look better get celebrated.

The habits that came out of it:

1. **Too good is a bug until proven otherwise.** Alarms fire on implausibly
   good numbers, not just bad ones.
2. **Fail closed, and announce it.** A missing input is a fail with a
   reason, never a silent pass.
3. **Test every gate on noise.** The backtester runs on a random walk (GBM)
   across five seeds and must find nothing
   ([`test_no_significant_edge_over_buy_and_hold_on_a_random_walk`](tests/test_backtest_gbm.py)).
4. **Change the future, check the past.** Rescaling every price after a
   cutoff must not change any trade that closed before it
   ([`test_changing_the_future_does_not_change_the_past`](tests/test_backtest_gbm.py)).
5. **Count every trial.** I once searched 2,700 rule combinations. Hundreds
   met the hit-rate target, dozens were profitable after costs, and none were
   both. The best of them was *weaker* than the typical best-of-2,700 result
   on pure noise. Without the trial count, it would have looked like a
   discovery.

## What the research actually found

On liquid NSE stocks, choosing *when* to enter did no better than holding
the same stocks for the same period:

- Breakouts, retests, mean reversion, post-earnings drift and momentum were
  all tested. All were rejected, either on the holding baseline or on
  year-by-year stability.
- The effects that did look real lived in illiquid names, where trading
  costs eat them.
- The one-shot holdout caught a textbook overfit. One event study passed
  discovery comfortably, then showed the *opposite sign* on the holdout.

The only result that cleared a matched null was outside this universe: a
cross-asset trend sleeve, whose value is as a diversifier, not as an edge on
Indian equities.

So this repository is published for its engineering: the data plumbing, the
cost model, the backtester, and above all the measurement discipline. It is
not a strategy.

## Where to look in the code

| Guard | Where |
|---|---|
| Signal never trades on its own bar | `tests/test_backtest_gbm.py` |
| No lookahead (change future, past unchanged) | `tests/test_backtest_gbm.py` |
| Random walk stays a random walk | `tests/test_backtest_gbm.py` |
| Split / bonus neutralisation | `core/corporate_actions.py` |
| Liquidity gate fails closed | `core/selection.py`, `core/sizing.py` |
| Losing strategy never validated | `core/deflated_sharpe.py`, `tests/test_deflated_sharpe.py` |
| Survivorship, duplicate and timing checks | `core/leakage_audit.py` |
| Pre-registration and trial count | `core/hypothesis_registry.py` |
| One-shot holdout | `backtest/engine.py` (`HoldoutLedger`) |
| Credentials have no write path | `core/secrets.py`, `tests/test_secrets_env_only.py` |
| Live orders cannot be sent | `core/api_dhan.py`, `tests/test_live_trading_disabled.py` |
