"""
simulation.py — Multi-year retirement simulation wrapper around TaxPlanning.

Usage:
    from simulation import SimulationConfig, run_simulation, compare_strategies
    from simulation import plot_results, plot_comparison, no_conversion, convert_to_22pct

    cfg = SimulationConfig(
        age=62, filing='MFJ', taxyear=2025,
        pretax_funds=500_000, roth_funds=50_000,
        expenses=80_000, healthcare='ACA', n_years=20,
        strategy=convert_to_22pct,
    )
    results = run_simulation(cfg)
    plot_results(results, cfg=cfg, title='Baseline')

Advanced scenarios (multiple properties, inheritance, survivor SS benefit, one-off
mid-loop tweaks) are supported via SimulationConfig's inherit_pretax_funds/inherit_age/
inherit_timeline, SS_survivor_benefit, withdrawal_sequence, home_sales, year_overrides,
infl_adjust_start, and healthcare_before_itemized fields — see the SimulationConfig
docstring below for details on each.
"""
from __future__ import annotations

import dataclasses
import importlib
from typing import Callable, Dict, List, Union

import numpy as np
import matplotlib.pyplot as plt

try:
    import yaml
    _YAML_AVAILABLE = True
except ImportError:
    _YAML_AVAILABLE = False

from tax_planning import TaxPlanning


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _broadcast(param, i: int):
    """Return param[i] for lists/arrays, or param itself for scalars/strings."""
    if isinstance(param, (list, np.ndarray)):
        return param[i]
    return param


def _load_taxyear(year: int):
    """Dynamically import taxyear_YYYY module (e.g. taxyear_2025)."""
    return importlib.import_module(f'taxyear_{year}')


# ---------------------------------------------------------------------------
# Built-in strategies
# ---------------------------------------------------------------------------

def no_conversion(tp: TaxPlanning, year: int) -> None:
    """No Roth conversion — no-op."""
    pass


def convert_to_bracket(rate: float) -> Callable:
    """Factory: returns a strategy that fills the Roth conversion up to *rate* bracket.

    The returned strategy calls roth_convert_up_to() then settle_taxes(acct='brokerage'),
    mirroring the pattern used in retirement_taxes.ipynb.
    """
    def strategy(tp: TaxPlanning, year: int) -> None:
        tp.roth_convert_up_to(rate)
        tp.settle_taxes(acct='brokerage')
    strategy.__name__ = f'convert_to_{int(rate * 100)}pct'
    return strategy


def convert_amount(amt: float) -> Callable:
    """Factory: returns a strategy that converts a fixed dollar amount to Roth.

    The returned strategy calls make_roth_conversion(amt) then settle_taxes(acct='brokerage'),
    mirroring the notebook pattern of a fixed-dollar (rather than bracket-fill) conversion.
    """
    def strategy(tp: TaxPlanning, year: int) -> None:
        tp.make_roth_conversion(amt)
        tp.settle_taxes(acct='brokerage')
    strategy.__name__ = f'convert_amount_{int(amt)}'
    return strategy


convert_to_22pct = convert_to_bracket(0.22)
convert_to_24pct = convert_to_bracket(0.24)
convert_to_32pct = convert_to_bracket(0.32)

STRATEGY_REGISTRY: Dict[str, Callable] = {
    'no_conversion':    no_conversion,
    'convert_to_22pct': convert_to_22pct,
    'convert_to_24pct': convert_to_24pct,
    'convert_to_32pct': convert_to_32pct,
}


# ---------------------------------------------------------------------------
# SimulationConfig
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class SimulationConfig:
    """Configuration for a multi-year retirement simulation.

    Per-year parameters (expenses, work_income, pension_income, fixed_income,
    healthcare, property_tax, mortgage_int, home_principal, medical_exp, charity)
    accept either a scalar (same value every year) or a list/array with one entry
    per simulation year.

    Notes
    -----
    - When mortgage_int > 0, home_principal must also be > 0.
    - healthcare='medicare' with age < 65 will skip the premium call silently,
      unless healthcare_before_itemized=True (see below), in which case it's
      always called and TaxPlanning's own medicare/ACA branching applies.
    - strategy callable signature: fn(tp: TaxPlanning, year: int) -> None.
      The wrapper calls settle_taxes() once before invoking the strategy.
      Strategies are responsible for calling settle_taxes() again after any
      Roth conversion (see convert_to_bracket/convert_amount factories).

    Advanced fields (opt-in, default to no-op for simple single-property scenarios):
    - inherit_pretax_funds/inherit_age/inherit_timeline, SS_survivor_benefit: passed
      straight through to TaxPlanning for inherited-IRA and survivor-benefit scenarios.
    - withdrawal_sequence: custom draw order + fallback cascade (e.g. draw down an
      inherited account before the owner's own pretax funds). None = TaxPlanning's default.
    - home_sales: list of one-off property-sale events (see field docstring below).
    - year_overrides: {year_index: fn(tp)} for arbitrary one-off mid-loop tweaks.
    - infl_adjust_start: call tp.infl_adjust_brackets()+reset() before the loop, for
      planning a tax year whose brackets aren't released yet.
    - healthcare_before_itemized: reorders the loop so the healthcare premium is paid
      before (and counted toward) itemized medical deductions, rather than after the
      Roth-conversion strategy step and excluded from deductions.
    """

    # --- TaxPlanning init params ---
    age: int = 65
    filing: str = 'single'
    state: str = 'CA'
    taxyear: int = 2025
    pretax_funds: float = 0.0
    roth_funds: float = 0.0
    brokerage_funds: float = 0.0
    savings: float = 0.0
    brokerage_cost_basis: float = 0.0
    SS_benefit: float = 0.0
    SS_age: int = 67
    SS_survivor_benefit: float = 0.0
    inherit_pretax_funds: float = 0.0
    inherit_age: int = None
    inherit_timeline: str = 'lifetime'
    RMD_age: int = 75
    growth_rate: float = 0.07
    dividend_rate: float = 0.017
    savings_rate: float = 0.035
    calc_int_div: bool = True
    qual_div: bool = True
    reinvest_div: bool = True
    dollars: str = 'today'
    inflation_rate: float = 0.03
    ACA_premium_rate: float = 0.02
    n_dependents: int = 0
    check_medicare_age: bool = True
    verbose: bool = False

    # Account draw order + fallback cascade, passed to TaxPlanning(withdrawal_sequence=...).
    # None means "use TaxPlanning's own default". A copy is always passed to TaxPlanning
    # (which mutates the list it receives), so this field is never mutated in place.
    withdrawal_sequence: List[str] = None

    # --- Per-year parameters (scalar or list/array, one value per year) ---
    expenses: Union[float, List[float]] = 0.0
    work_income: Union[float, List[float]] = 0.0
    pension_income: Union[float, List[float]] = 0.0
    fixed_income: Union[float, List[float]] = 0.0
    healthcare: Union[str, List[str]] = 'medicare'

    # --- Account routing (which account to draw from for each operation) ---
    settle_acct: str = 'pretax'
    meet_income_acct: str = 'pretax'
    healthcare_acct: str = 'savings'

    # --- Healthcare ---
    # skip_healthcare=True disables pay_healthcare_premium() entirely (e.g. pension covers premiums)
    skip_healthcare: bool = False

    # --- Spending breakdown for plot_results ---
    # Total annual mortgage payment (principal + interest) per year, used for the spending subplot.
    # Separate from mortgage_int (interest-only) which goes to calc_itemized_deductions.
    home_payment: Union[float, List[float]] = 0.0

    # Itemized deduction inputs — all zero means itemized step is skipped.
    # When mortgage_int > 0, home_principal must also be > 0.
    property_tax: Union[float, List[float]] = 0.0
    mortgage_int: Union[float, List[float]] = 0.0
    home_principal: Union[float, List[float]] = 0.0
    medical_exp: Union[float, List[float]] = 0.0
    charity: Union[float, List[float]] = 0.0

    # --- Simulation control ---
    n_years: int = 20
    strategy: Callable = dataclasses.field(default_factory=lambda: no_conversion)

    # If True, call tp.infl_adjust_brackets() + tp.reset() immediately after construction,
    # before the loop starts. Workaround for planning a tax year whose brackets aren't
    # released yet (e.g. taxyear=2025 standing in for 2026) — see infl_adjust_brackets()
    # docstring in tax_planning.py.
    infl_adjust_start: bool = False

    # One-off property sale events. Each dict: {'year', 'purchase_price', 'sale_price',
    # 'closing_cost_fact', 'loan_balance', 'primary', 'acct'}. tp.sell_house(...) is called
    # with the matching entry's fields at the top of the iteration where results['age'] - age
    # == entry['year'] (i.e. loop index i == entry['year']).
    home_sales: List[dict] = dataclasses.field(default_factory=list)

    # Arbitrary one-off per-year tweaks: {year_index: fn(tp) -> None}, applied at the very
    # top of iteration `year_index`, before home_sales. e.g. {3: lambda tp: setattr(tp, 'OBBB_senior_deduction', 0)}
    year_overrides: Dict[int, Callable] = dataclasses.field(default_factory=dict)

    # If True, pay_healthcare_premium() runs right after meet_income_need() (unconditionally —
    # ignoring the medicare-and-age<65 skip below) and its result is folded into
    # calc_itemized_deductions()'s medical_exp_paid, instead of being paid after the strategy
    # step and left out of itemized deductions. Default False preserves the original order.
    healthcare_before_itemized: bool = False

    # ------------------------------------------------------------------
    # YAML serialization
    # ------------------------------------------------------------------

    def to_yaml(self, path: str) -> None:
        """Serialize config to YAML. Strategy is stored by __name__.

        year_overrides holds Callables and is not YAML-serializable — it's dropped
        from the output (from_yaml always loads it back as an empty dict).
        """
        if not _YAML_AVAILABLE:
            raise ImportError('PyYAML is required for YAML serialization. pip install pyyaml')
        d = {}
        for f in dataclasses.fields(self):
            if f.name == 'strategy':
                d['strategy'] = getattr(self.strategy, '__name__', 'no_conversion')
            elif f.name == 'year_overrides':
                continue
            else:
                val = getattr(self, f.name)
                if isinstance(val, np.ndarray):
                    val = val.tolist()
                d[f.name] = val
        with open(path, 'w') as fh:
            yaml.dump(d, fh, default_flow_style=False)

    @classmethod
    def from_yaml(cls, path: str) -> SimulationConfig:
        """Deserialize from YAML. Unknown strategy names fall back to no_conversion."""
        if not _YAML_AVAILABLE:
            raise ImportError('PyYAML is required for YAML serialization. pip install pyyaml')
        with open(path) as fh:
            d = yaml.safe_load(fh)
        strategy_name = d.pop('strategy', 'no_conversion')
        strategy = STRATEGY_REGISTRY.get(strategy_name, no_conversion)
        return cls(strategy=strategy, **d)


# ---------------------------------------------------------------------------
# run_simulation
# ---------------------------------------------------------------------------

def run_simulation(cfg: SimulationConfig) -> dict:
    """Run a multi-year simulation and return arrays of key metrics.

    Annual loop (for each year i), default (healthcare_before_itemized=False):
        0. year_overrides[i](tp)                 — if i in year_overrides
        0. sell_house(...) for any home_sales entries with entry['year'] == i
        1. meet_income_need(expenses[i])         — if expenses[i] > 0
        2. calc_itemized_deductions(...)         — if any deduction input > 0
        3. settle_taxes()                        — always
        4. strategy(tp, i)                       — handles conversion + 2nd settle
        5. pay_healthcare_premium()              — skipped if medicare and age < 65
        6. balance_year()
        7. record outputs
        8. advance_year(work_income, fixed_income, healthcare)  — skip on last year

    When healthcare_before_itemized=True, step 5 instead runs right after step 1
    (unconditionally — the medicare/age<65 skip is not applied) and its premium is
    folded into step 2's medical_exp_paid; step 5 is not run again later.

    Returns
    -------
    dict with numpy array values (one entry per year) for each of:
        age, net_worth, pretax, inherit_pretax, roth, brokerage, savings,
        pretax_dist, roth_dist, brokerage_sales,
        total_income, fixed_income_out,
        fed_tax, ca_tax, ltcg_tax, total_tax,
        taxable_income, taxable_ltcg,
        fed_bracket, ca_bracket, ltcg_bracket

    Plus these one-time (non per-year) bracket reference arrays, captured right after
    construction/infl_adjust_start -- see the note above their assignment for how to
    project them forward to a given year:
        ord_income_rates, ord_income_brackets,
        LTCG_rates, LTCG_brackets,
        state_income_rates, state_income_brackets
    """
    n = cfg.n_years

    tp_kwargs = dict(
        age=cfg.age,
        filing=cfg.filing,
        state=cfg.state,
        taxyear=cfg.taxyear,
        pretax_funds=cfg.pretax_funds,
        roth_funds=cfg.roth_funds,
        brokerage_funds=cfg.brokerage_funds,
        savings=cfg.savings,
        brokerage_cost_basis=cfg.brokerage_cost_basis,
        SS_benefit=cfg.SS_benefit,
        SS_age=cfg.SS_age,
        SS_survivor_benefit=cfg.SS_survivor_benefit,
        inherit_pretax_funds=cfg.inherit_pretax_funds,
        inherit_age=cfg.inherit_age,
        inherit_timeline=cfg.inherit_timeline,
        RMD_age=cfg.RMD_age,
        growth_rate=cfg.growth_rate,
        dividend_rate=cfg.dividend_rate,
        savings_rate=cfg.savings_rate,
        calc_int_div=cfg.calc_int_div,
        qual_div=cfg.qual_div,
        reinvest_div=cfg.reinvest_div,
        dollars=cfg.dollars,
        inflation_rate=cfg.inflation_rate,
        ACA_premium_rate=cfg.ACA_premium_rate,
        n_dependents=cfg.n_dependents,
        check_medicare_age=cfg.check_medicare_age,
        verbose=cfg.verbose,
        work_income=_broadcast(cfg.work_income, 0),
        pension_income=_broadcast(cfg.pension_income, 0),
        fixed_income=_broadcast(cfg.fixed_income, 0),
        healthcare=_broadcast(cfg.healthcare, 0),
    )
    if cfg.withdrawal_sequence is not None:
        # Pass a copy — TaxPlanning.__init__ mutates the list it receives (appends None),
        # and cfg.withdrawal_sequence may be shared across dataclasses.replace() clones.
        tp_kwargs['withdrawal_sequence'] = list(cfg.withdrawal_sequence)

    tp = TaxPlanning(**tp_kwargs)

    if cfg.infl_adjust_start:
        tp.infl_adjust_brackets()
        tp.reset()

    results = {k: np.zeros(n) for k in [
        'age', 'net_worth', 'pretax', 'inherit_pretax', 'roth', 'brokerage', 'savings',
        'pretax_dist', 'roth_dist', 'brokerage_sales',
        'total_income', 'fixed_income_out',
        'fed_tax', 'ca_tax', 'ltcg_tax', 'total_tax',
        'taxable_income', 'taxable_ltcg', 'state_taxable_income',
        'housing_expense', 'living_expense',
        'fed_bracket', 'ca_bracket', 'ltcg_bracket',
    ]}

    # Starting bracket cutoffs/rates -- captured once, right after construction (and any
    # infl_adjust_start bump), so callers can draw "taxable income vs. bracket limit"
    # reference lines without re-deriving tax-year tables themselves. These grow at
    # cfg.inflation_rate per year in nominal-dollars mode, same as TaxPlanning's own
    # advance_year() -- e.g. bracket_limit_at_year_i = results['ord_income_brackets'] * (1+cfg.inflation_rate)**i
    # when cfg.dollars == 'nominal'.
    results['ord_income_rates'] = tp.ord_income_rates
    results['ord_income_brackets'] = tp.ord_income_brackets.copy()
    results['LTCG_rates'] = tp.LTCG_rates
    results['LTCG_brackets'] = tp.LTCG_brackets.copy()
    results['state_income_rates'] = tp.state_income_rates
    results['state_income_brackets'] = tp.state_income_brackets.copy()

    for i in range(n):
        exp    = _broadcast(cfg.expenses,      i)
        pt     = _broadcast(cfg.property_tax,  i)
        mi     = _broadcast(cfg.mortgage_int,  i)
        hp     = _broadcast(cfg.home_principal, i)
        me     = _broadcast(cfg.medical_exp,   i)
        ch     = _broadcast(cfg.charity,       i)
        hp_pay = _broadcast(cfg.home_payment,  i)

        # 0a. One-off per-year tweaks (e.g. zeroing a deduction for a specific year)
        if i in cfg.year_overrides:
            cfg.year_overrides[i](tp)

        # 0b. Property sales scheduled for this year
        for sale in cfg.home_sales:
            if sale['year'] == i:
                tp.sell_house(
                    sale['purchase_price'], sale['sale_price'], sale['closing_cost_fact'],
                    sale['loan_balance'], primary=sale.get('primary', True), acct=sale.get('acct', 'brokerage'),
                )

        # 1. Meet income need
        if exp > 0:
            tp.meet_income_need(exp, acct=cfg.meet_income_acct)

        premium = 0.0
        if cfg.healthcare_before_itemized:
            # 1b. Pay healthcare premium before itemizing, unconditionally, and fold it
            # into the medical expense deduction (matches masi_retirement.ipynb's order).
            if not cfg.skip_healthcare:
                premium = tp.pay_healthcare_premium(acct=cfg.healthcare_acct)

        # 2. Itemized deductions (skip entirely if all inputs are zero)
        if any(v > 0 for v in [pt, mi, me, ch, premium]):
            # Guard against /0 when home_principal omitted but mortgage_int is set
            tp.calc_itemized_deductions(
                property_tax_paid=pt,
                mortgage_int_paid=mi,
                home_principal=hp if hp > 0 else 1.0,
                medical_exp_paid=me + premium,
                charity_paid=ch,
            )

        # 3. First settle_taxes pass
        tp.settle_taxes(acct=cfg.settle_acct)

        # 4. Strategy (may do Roth conversion + second settle internally)
        cfg.strategy(tp, i)

        # 5. Pay healthcare premium (skipped here if already paid in step 1b)
        if not cfg.healthcare_before_itemized:
            if not cfg.skip_healthcare and not (tp.healthcare == 'medicare' and tp.age < 65):
                tp.pay_healthcare_premium(acct=cfg.healthcare_acct)

        # 6. Close out the year
        tp.balance_year()

        # 7. Record outputs
        results['age'][i]               = tp.age
        results['net_worth'][i]         = tp.net_worth
        results['pretax'][i]            = tp.pretax_funds
        results['inherit_pretax'][i]    = tp.inherit_pretax_funds
        results['roth'][i]              = tp.roth_funds
        results['brokerage'][i]         = tp.brokerage_funds
        results['savings'][i]           = tp.savings
        results['pretax_dist'][i]       = tp.year_pretax_distributions
        results['roth_dist'][i]         = tp.year_roth_distributions
        results['brokerage_sales'][i]   = tp.year_brokerage_sales
        results['total_income'][i]      = tp.year_total_income
        results['fixed_income_out'][i]  = tp.pension_income + tp.fixed_income + tp.SS_income
        results['fed_tax'][i]           = tp.year_income_tax
        results['ca_tax'][i]            = tp.year_state_tax
        results['ltcg_tax'][i]          = tp.year_LTCG_tax
        results['total_tax'][i]         = tp.year_total_tax
        results['taxable_income'][i]       = tp.taxable_income
        results['taxable_ltcg'][i]         = tp.taxable_LTCG
        results['state_taxable_income'][i] = tp.state_taxable_income
        results['housing_expense'][i]      = hp_pay + pt
        results['living_expense'][i]       = max(0.0, exp - hp_pay - pt)
        results['fed_bracket'][i]          = tp.fed_marginal_bracket
        results['ca_bracket'][i]        = tp.state_marginal_bracket
        results['ltcg_bracket'][i]      = tp.LTCG_marginal_bracket

        # 8. Advance year — skip on final iteration
        if i < n - 1:
            tp.advance_year(
                work_income=_broadcast(cfg.work_income,    i + 1),
                pension_income=_broadcast(cfg.pension_income, i + 1),
                fixed_income=_broadcast(cfg.fixed_income,  i + 1),
                healthcare=_broadcast(cfg.healthcare,      i + 1),
            )

    return results


# ---------------------------------------------------------------------------
# compare_strategies
# ---------------------------------------------------------------------------

def compare_strategies(cfg: SimulationConfig, strategies: dict) -> dict:
    """Run one simulation per strategy and return a dict of results.

    Parameters
    ----------
    cfg : SimulationConfig
        Base configuration. Cloned for each strategy via dataclasses.replace().
    strategies : dict
        Mapping of display name → strategy callable.

    Returns
    -------
    dict mapping display name → results dict from run_simulation().

    Example
    -------
    all_results = compare_strategies(cfg, {
        'No conversion':  no_conversion,
        'Convert to 22%': convert_to_22pct,
        'Convert to 24%': convert_to_24pct,
    })
    """
    return {
        name: run_simulation(dataclasses.replace(cfg, strategy=fn))
        for name, fn in strategies.items()
    }


# ---------------------------------------------------------------------------
# Plot helpers
# ---------------------------------------------------------------------------

def plot_results(results: dict, cfg: SimulationConfig = None, title: str = '') -> None:
    """9-subplot figure (3×3) matching the dad_retirement.ipynb layout.

    Parameters
    ----------
    results : dict
        Output of run_simulation().
    cfg : SimulationConfig, optional
        If provided, adds bracket reference lines to income/LTCG/state subplots.
        In nominal mode (cfg.dollars == 'nominal') bracket limits are
        inflation-adjusted so they grow alongside nominal income.
    title : str
        Figure suptitle.

    Subplots
    --------
    (0,0) Account balances — pretax, brokerage, roth, savings
    (0,1) Income sources — fixed/SS/pension, pretax dist, roth dist, brokerage sales
    (0,2) Spending — housing (mortgage + property tax) and daily living
    (1,0) Taxable ordinary income vs. bracket limits
    (1,1) Taxable LTCG vs. bracket limits
    (1,2) State taxable income vs. bracket limits
    (2,0) Annual tax breakdown — fed, CA, LTCG, total
    (2,1) Annual + cumulative total tax
    (2,2) [hidden]
    """
    ages = results['age']
    n    = len(ages)

    fig, axes = plt.subplots(3, 3, figsize=(14, 10))
    if title:
        fig.suptitle(title, fontsize=13)

    # Inflation multiplier for bracket limit lines in nominal mode
    if cfg is not None and getattr(cfg, 'dollars', 'today') == 'nominal':
        mult = (1 + cfg.inflation_rate) ** np.arange(n, dtype=float)
    else:
        mult = np.ones(n)

    # ── (0,0) Account balances ──────────────────────────────────────────────
    ax = axes[0, 0]
    ax.plot(ages, results['pretax'],    label='Pretax')
    ax.plot(ages, results['brokerage'], label='Brokerage')
    ax.plot(ages, results['roth'],      label='Roth')
    ax.plot(ages, results['savings'],   label='Savings')
    ax.yaxis.set_major_formatter('${x:,.0f}')
    ax.set_xlabel('Age'); ax.set_title('Balances'); ax.legend(); ax.grid(True)

    # ── (0,1) Income sources ────────────────────────────────────────────────
    ax = axes[0, 1]
    ax.plot(ages, results['fixed_income_out'], label='Fixed / SS')
    ax.plot(ages, results['pretax_dist'],      label='Pretax dist.')
    ax.plot(ages, results['roth_dist'],        label='Roth dist.')
    ax.plot(ages, results['brokerage_sales'],  label='Brokerage sales')
    ax.yaxis.set_major_formatter('${x:,.0f}')
    ax.set_xlabel('Age'); ax.set_title('Income'); ax.legend(); ax.grid(True)

    # ── (0,2) Spending breakdown ─────────────────────────────────────────────
    ax = axes[0, 2]
    ax.plot(ages, results.get('housing_expense', np.zeros(n)), label='Housing')
    ax.plot(ages, results.get('living_expense',  np.zeros(n)), label='Daily living')
    ax.yaxis.set_major_formatter('${x:,.0f}')
    ax.set_xlabel('Age'); ax.set_title('Spending'); ax.legend(); ax.grid(True)

    # ── (1,0) Taxable ordinary income ───────────────────────────────────────
    ax = axes[1, 0]
    ax.plot(ages, results['taxable_income'])
    if cfg is not None:
        try:
            ty = _load_taxyear(cfg.taxyear)
            for idx, rate in enumerate(ty.ord_income_rates[:4]):
                lim = ty.ord_income_brackets[cfg.filing][idx + 1]
                ax.plot(ages, lim * mult, ls='--', alpha=0.4, label=f'{rate * 100:.0f}% lim')
        except Exception:
            pass
    ax.yaxis.set_major_formatter('${x:,.0f}')
    ax.set_xlabel('Age'); ax.set_title('Taxable ord. income'); ax.legend(); ax.grid(True)

    # ── (1,1) Taxable LTCG ──────────────────────────────────────────────────
    ax = axes[1, 1]
    ax.plot(ages, results['taxable_ltcg'])
    if cfg is not None:
        try:
            ty = _load_taxyear(cfg.taxyear)
            for idx, rate in enumerate(ty.LTCG_rates[:-1]):
                lim = ty.LTCG_brackets[cfg.filing][idx + 1]
                ax.plot(ages, lim * mult, ls='--', alpha=0.4, label=f'{rate * 100:.0f}% lim')
        except Exception:
            pass
    ax.yaxis.set_major_formatter('${x:,.0f}')
    ax.set_xlabel('Age'); ax.set_title('Taxable LTCG'); ax.legend(); ax.grid(True)

    # ── (1,2) State taxable income ───────────────────────────────────────────
    ax = axes[1, 2]
    ax.plot(ages, results.get('state_taxable_income', np.zeros(n)))
    if cfg is not None:
        try:
            ty = _load_taxyear(cfg.taxyear)
            s_ind = 2
            state_brackets = ty.state_income_brackets
            if isinstance(state_brackets, dict):
                state_brackets = state_brackets[cfg.filing]
            for idx, rate in enumerate(ty.state_income_rates[s_ind:6]):
                lim = state_brackets[idx + s_ind + 1]
                ax.plot(ages, lim * mult, ls='--', alpha=0.4, label=f'{rate * 100:.1f}% lim')
        except Exception:
            pass
    ax.yaxis.set_major_formatter('${x:,.0f}')
    ax.set_xlabel('Age'); ax.set_title('State taxable income'); ax.legend(loc='upper right'); ax.grid(True)

    # ── (2,0) Annual tax breakdown ───────────────────────────────────────────
    ax = axes[2, 0]
    ax.plot(ages, results['fed_tax'],   label='Ord. Income Tax')
    ax.plot(ages, results['ltcg_tax'],  label='LT Cap Gains Tax')
    ax.plot(ages, results['ca_tax'],    label='CA Tax')
    ax.plot(ages, results['total_tax'], label='Total Tax')
    ax.yaxis.set_major_formatter('${x:,.0f}')
    ax.set_xlabel('Age'); ax.set_title('Tax'); ax.legend(); ax.grid(True)

    # ── (2,1) Annual + cumulative total tax ──────────────────────────────────
    ax = axes[2, 1]
    cum_tax = np.cumsum(results['total_tax'])
    ax.plot(ages, results['total_tax'], label='Annual')
    ax.plot(ages, cum_tax,              label='Cumulative')
    ax.yaxis.set_major_formatter('${x:,.0f}')
    ax.set_xlabel('Age')
    ax.set_title(f"Total Tax: ${cum_tax[-1]:,.0f}")
    ax.legend(); ax.grid(True)

    # ── (2,2) unused ─────────────────────────────────────────────────────────
    axes[2, 2].set_visible(False)

    plt.tight_layout()
    plt.show()


def plot_comparison(
    all_results: dict,
    metrics: List[str] = None,
    title: str = '',
) -> None:
    """One subplot per metric, one line per strategy.

    Parameters
    ----------
    all_results : dict
        Output of compare_strategies() — mapping of strategy name → results dict.
    metrics : list of str, optional
        Keys from the results dict to plot.
        Defaults to ['net_worth', 'total_tax', 'pretax', 'roth'].
    title : str
        Figure suptitle.
    """
    if metrics is None:
        metrics = ['net_worth', 'total_tax', 'pretax', 'roth']

    ncols = 2
    nrows = (len(metrics) + 1) // ncols
    fig, axes = plt.subplots(nrows, ncols, figsize=(12, 4 * nrows))
    axes = np.array(axes).reshape(-1)   # flatten for uniform indexing

    if title:
        fig.suptitle(title, fontsize=13)

    for ax_idx, metric in enumerate(metrics):
        ax = axes[ax_idx]
        for strategy_name, res in all_results.items():
            ax.plot(res['age'], res[metric], label=strategy_name)
        ax.yaxis.set_major_formatter('${x:,.0f}')
        ax.set_xlabel('Age')
        ax.set_title(metric.replace('_', ' ').title())
        ax.legend()
        ax.grid(True)

    # Hide unused subplots when metrics count is odd
    for ax_idx in range(len(metrics), len(axes)):
        axes[ax_idx].set_visible(False)

    plt.tight_layout()
    plt.show()


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    cfg = SimulationConfig(
        age=62,
        filing='single',
        taxyear=2025,
        pretax_funds=1_500_000,
        roth_funds=200_000,
        brokerage_funds=200_000,
        brokerage_cost_basis=150_000,
        savings=100_000,
        SS_benefit=30_000,
        SS_age=67,
        RMD_age=75,
        fixed_income=0,
        expenses=75_000,
        healthcare='ACA',
        growth_rate=0.07,
        n_years=20,
        strategy=no_conversion,
    )

    strategies = {
        'No conversion':  no_conversion,
        'Convert to 22%': convert_to_22pct,
    }

    print('\n=== Running comparison')
    all_results = compare_strategies(cfg, strategies)

    for name, res in all_results.items():
        print(f'{name}: final net worth = ${res["net_worth"][-1]:,.0f}')

    # YAML round-trip verification
    print('\n=== YAML round-trip ===')
    cfg.to_yaml('/tmp/sim_test.yaml')
    cfg2 = SimulationConfig.from_yaml('/tmp/sim_test.yaml')
    res2 = run_simulation(cfg2)
    delta = abs(res2['net_worth'][-1] - all_results['No conversion']['net_worth'][-1])
    print(f'Round-trip net_worth delta: ${delta:,.2f}')

    plot_results(all_results['No conversion'], cfg=cfg, title='No Conversion — detailed view')
    plot_results(all_results['Convert to 22%'], cfg=cfg, title='Convert to 22% — detailed view')
    plot_comparison(all_results, title='Roth Conversion Strategy Comparison')
