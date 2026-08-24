# Retirement Engine — Claude Code Context

## Project Purpose
The shared tax-planning and retirement-simulation engine behind several personal
retirement apps/notebooks. The core `TaxPlanning` class models multi-year retirement
scenarios with accurate federal + California tax calculations, IRMAA Medicare
premiums, ACA subsidies, Roth conversions, RMDs, inheritance, and multi-account
withdrawal sequencing. `simulation.py` wraps the annual `TaxPlanning` loop into a
reusable `SimulationConfig`/`run_simulation()` interface.

This repo is consumed as a **git submodule** (checked out at `engine/`) by other
repos — a personal `finance/` notebook workspace, and one or more deployed
Streamlit apps (e.g. `masi-app`) — rather than being imported as an installed
package. Those repos add `engine/` to `sys.path` (or, for local notebook/test use,
via a `.pth` file in the relevant conda env) so existing `from tax_planning import
...`-style imports keep working unchanged regardless of where the submodule is
checked out.

---

## File Map

| File | Purpose |
|------|---------|
| `tax_planning.py` | Core `TaxPlanning` class |
| `simulation.py` | Multi-year simulation wrapper (`SimulationConfig`, `run_simulation`, `compare_strategies`, plot helpers) |
| `taxyear_2025.py` | Tax constants (brackets, deductions, IRMAA, ACA, FPL) — only tax year currently wired up in `TaxPlanning.__init__` |
| `RMD.py` | RMD factor lookup table (ages 72–100) + single-life-expectancy factors for inherited accounts |
| `mortgage_calculator.py` | Amortization helpers (`amortize()`) used by scenario builders that model property loans |

---

## TaxPlanning Class — Key Patterns

### Annual simulation loop (typical pattern)
```python
tp = TaxPlanning(pretax_funds=500000, filing='MFJ', age=62, taxyear=2025, ...)
for _ in range(20):
    tp.meet_income_need(80000)
    tp.calc_itemized_deductions(property_tax=15000, mortgage_int=20000)
    tp.settle_taxes()
    tp.roth_convert_up_to(0.22)   # fill 22% bracket
    tp.settle_taxes()
    tp.pay_healthcare_premium()
    tp.balance_year()             # stores MAGI, sweeps surplus to brokerage
    tp.advance_year()
```

### Account withdrawal cascade
Configurable via `withdrawal_sequence` (default `['brokerage','pretax','savings','roth']`)
— each account's cascade fallback is simply "the next account in this list." An
inherited pretax account (`inherit_pretax_funds`) can be included in the sequence too.
`take_pretax_distributions()` (and the other `take_*`/`withdraw_*`/`make_*` methods)
automatically cascade to the configured fallback if the primary account is exhausted.

### Iterative tax settlement
`settle_taxes()` loops until `tax_owed - tax_withdrawn < $1`. Pretax withdrawals and
brokerage sales themselves generate taxable income, so taxes must be recalculated
each iteration. `acct` may be `'pretax'`, `'inherit_pretax'`, `'brokerage'`, `'roth'`,
or anything else (falls through to `'savings'`).

### IRMAA lookback
`calc_medicare_premium()` uses `MAGI_arr[1]` (2 years prior). `balance_year()` prepends
current MAGI to `MAGI_arr`, so at the time premiums are calculated mid-year, index
`[1]` is correctly 2 years back.

### Roth conversion fill
`roth_convert_up_to(rate)` fills the current bracket then binary-searches the
remaining space. `make_roth_conversion(amt)` converts a fixed dollar amount instead.

### Inheritance
`inherit_pretax_funds`/`inherit_age`/`inherit_timeline` (`'lifetime'` or `'10year'`)
model an inherited IRA. `'lifetime'` takes annual RMDs via the single-life-expectancy
factor (`RMD.single_life_exectancy_factor[inherit_age]`); `'10year'` empties the
account entirely 10 years after `inherit_age`. `SS_survivor_benefit` models a
survivor Social Security benefit, automatically applied once work income stops and
before the survivor reaches their own claiming age.

### Property sales
`sell_house(purchase_price, sale_price, closing_cost_fact, loan_balance, primary, acct)`
— a one-off event (not part of the per-year loop) that realizes any taxable gain
(capped by the primary-residence exclusion when `primary=True`) and deposits the net
sale proceeds into the given account.

---

## Simulation Wrapper (`simulation.py`)

`SimulationConfig` + `run_simulation()` wraps the annual `TaxPlanning` loop into a
reusable interface. Use `compare_strategies()` to run multiple Roth conversion levels
against the same config.

### Quick start
```python
from simulation import SimulationConfig, run_simulation, compare_strategies
from simulation import plot_results, plot_comparison, no_conversion, convert_to_22pct

cfg = SimulationConfig(
    age=62, filing='single', taxyear=2025,
    pretax_funds=1_500_000, roth_funds=200_000,
    brokerage_funds=200_000, brokerage_cost_basis=150_000,
    savings=100_000, SS_benefit=30_000, SS_age=67,
    expenses=75_000, healthcare='ACA', n_years=20,
)
results = run_simulation(cfg)
plot_results(results, cfg=cfg, title='Baseline')

# Compare strategies
all_results = compare_strategies(cfg, {
    'No conversion':  no_conversion,
    'Convert to 22%': convert_to_22pct,
})
plot_comparison(all_results)
```

### Per-year parameters
`expenses`, `work_income`, `pension_income`, `fixed_income`, `healthcare`, `property_tax`, `mortgage_int`, `home_principal`, `medical_exp`, `charity` all accept either a scalar (same every year) or a list/array (one value per year).

### Advanced fields (opt-in — default to no-op for simple single-property scenarios)
- `state`, `SS_survivor_benefit`, `inherit_pretax_funds`/`inherit_age`/`inherit_timeline`, `qual_div`, `withdrawal_sequence` — passed straight through to `TaxPlanning`'s constructor (`withdrawal_sequence=None` uses `TaxPlanning`'s own default; when set, a *copy* of the list is passed each run, since `TaxPlanning.__init__` mutates the list it receives).
- `home_sales: List[dict]` — one-off property-sale events, each `{'year', 'purchase_price', 'sale_price', 'closing_cost_fact', 'loan_balance', 'primary', 'acct'}`. `tp.sell_house(...)` is called with the matching entry at the top of that year's iteration.
- `year_overrides: Dict[int, Callable[[TaxPlanning], None]]` — arbitrary one-off mid-loop tweaks (e.g. zeroing a deduction for one specific year), applied at the very top of that year's iteration, before `home_sales`.
- `infl_adjust_start: bool` — if `True`, calls `tp.infl_adjust_brackets(); tp.reset()` right after construction, before the loop starts — a workaround for planning a tax year whose brackets aren't released yet (e.g. using inflated 2025 brackets to stand in for 2026).
- `healthcare_before_itemized: bool` — if `True`, reorders the loop so the healthcare premium is paid immediately after `meet_income_need` (unconditionally — the medicare/age<65 skip doesn't apply) and is folded into `calc_itemized_deductions`'s `medical_exp_paid`, instead of being paid after the strategy step and excluded from itemized deductions.
- `convert_amount(amt)` — strategy factory alongside `convert_to_bracket(rate)`, for a fixed-dollar (rather than bracket-fill) Roth conversion.

These advanced fields were added to let `SimulationConfig`/`run_simulation` express a
scenario with multiple properties (each with scheduled sales), an inherited IRA, a
survivor SS benefit, and a one-off tax-law tweak — see the consuming repo (e.g.
`masi-app`'s `masi_scenario.py`) for a worked example, validated to exact parity
against a hand-written manual simulation loop.

### YAML save/load
```python
cfg.to_yaml('scenario.yaml')
cfg2 = SimulationConfig.from_yaml('scenario.yaml')
```
Unknown strategy names in YAML fall back to `no_conversion`. Requires PyYAML (`pip install pyyaml`). `year_overrides` (holds Callables) is not serializable and is dropped from the output; `from_yaml` always loads it back as an empty dict.

### Built-in strategies
| Name | Callable |
|------|----------|
| `no_conversion` | No Roth conversion |
| `convert_to_22pct` | Fill 22% bracket |
| `convert_to_24pct` | Fill 24% bracket |
| `convert_to_32pct` | Fill 32% bracket |
| `convert_to_bracket(rate)` | Factory for custom rate |
| `convert_amount(amt)` | Factory for a fixed-dollar conversion |

Custom strategies have signature `fn(tp: TaxPlanning, year: int) -> None`. The wrapper calls `settle_taxes()` once before invoking the strategy. Strategies are responsible for calling `settle_taxes()` a second time after any Roth conversion.

### Annual loop order
0. `year_overrides[year](tp)` then any matching `home_sales` entries — applied first, before anything else
1. `meet_income_need(expenses)` — if expenses > 0
2. `calc_itemized_deductions(...)` — if any deduction > 0
3. `settle_taxes()` — always
4. `strategy(tp, year)` — conversion + 2nd settle if applicable
5. `pay_healthcare_premium()` — skipped silently if medicare and age < 65
6. `balance_year()`
7. Record outputs → result arrays
8. `advance_year(work_income, fixed_income, healthcare)` — skip on last year

When `healthcare_before_itemized=True`, step 5 instead runs right after step 1 (unconditionally) and its result is folded into step 2's `medical_exp_paid`; step 5 does not run again later.

### Result dict keys
Per-year arrays: `age`, `net_worth`, `pretax`, `inherit_pretax`, `roth`, `brokerage`, `savings`, `pretax_dist`, `roth_dist`, `brokerage_sales`, `total_income`, `fixed_income_out`, `fed_tax`, `ca_tax`, `ltcg_tax`, `total_tax`, `taxable_income`, `taxable_ltcg`, `state_taxable_income`, `housing_expense`, `living_expense`, `fed_bracket`, `ca_bracket`, `ltcg_bracket`.

Plus one-time bracket reference arrays (not per-year — the starting cutoffs/rates right after construction/`infl_adjust_start`, which grow at `inflation_rate` per year in nominal-dollars mode): `ord_income_rates`, `ord_income_brackets`, `LTCG_rates`, `LTCG_brackets`, `state_income_rates`, `state_income_brackets`.

---

## Tax Year Modules

Each `taxyear_YYYY.py` exports the same set of constants (federal/CA brackets, deductions, IRMAA tables, ACA rates/FPL). `import_taxyear()` in `TaxPlanning` copies the right year's values into instance attributes at init. Only `taxyear_2025.py` is currently wired up (`TaxPlanning.__init__` raises `ValueError` for any other year).

**To add a new tax year:** create `taxyear_YYYY.py` and add an `elif` branch in `import_taxyear()`.

**When adding a new year, always verify ACA contribution rates** — they depend on whether Congress has extended the enhanced subsidies (ARP/IRA). If extended: use 0% up to 150% FPL, 8.5% cap above 400% FPL, and `unsub_premium=None`. If expired: use pre-ARP rates starting at 2.1% at 100% FPL and set `unsub_premium` to the actual unsubsidized benchmark premium. Check KFF or healthcare.gov for the current year's status.

---

## ACA Notes

- ACA coverage year uses the *prior year's* FPL (e.g., 2026 coverage uses 2025 FPL: $15,650 single / $21,150 two-person)
- `ACA_contr_rates` has three variants: `'expansion'`, `'non-expansion'`, `'WI/GA'` — currently hardcoded to `'expansion'` in `import_taxyear()`; can be parameterized if needed
- `unsub_premium=None`: enhanced subsidies apply at all incomes; `right_val = ACA_contr_rates[-1]`
- `unsub_premium=<amount>`: above 400% FPL, contribution = full unsubsidized premium; `right_val = unsub_premium/MAGI`

---

## Real-Return Framing & Nominal Adjustments

`dollars='today'` treats `growth_rate` etc. as **real** (inflation-adjusted) returns, so cash flows/balances are implicitly in today's dollars and tax brackets/expenses/income don't need inflating year-over-year. `dollars='nominal'` instead grows brackets, balances, and (optionally) income/expenses at the nominal rate each year via `advance_year()`'s `infl_adjust_brackets()` call.

Three items behave slightly differently over long horizons regardless of mode:
- **IRMAA thresholds**: CPI-adjusted annually by CMS — already handled correctly by the real-return framing (MAGI and thresholds move together).
- **Social Security benefits**: COLA-adjusted to track CPI — already correctly modeled as flat in real terms; enter `SS_benefit` in today's dollars.
- **ACA premiums**: historically grow ~2–4%/yr in *real* terms. Holding `unsub_premium` flat understates costs in later years for long ACA windows (5+ years pre-Medicare) — scale it up ~2%/yr in the simulation loop if that matters for a given scenario.

---

## Filing Status
`'single'` or `'MFJ'`. Used to index all bracket/threshold dictionaries. MFJ IRMAA charges are doubled (assumes both spouses enrolled in Medicare Part B+D).
