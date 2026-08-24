import numpy as np
import RMD
import taxyear_2025

###### TODO ######
## TaxPlanning class:
# Clean up CA/MD exemptions/credits
# Allow for 2 individuals in MFJ - different ages, pensions/SS, account balances
##################

def calc_SS_benefit(SS_benefit_FRA, FRA, SS_age):
    ann_SS_increase = 0.08
    ann_SS_decrease_first3yrs = -0.05/9*12
    ann_SS_decrease = -0.05

    gap = SS_age - FRA
    if gap >= 0:
        frac_change = gap*ann_SS_increase
    else:
        n_early = -gap
        if n_early <= 3:
            frac_change = n_early*ann_SS_decrease_first3yrs
        else:
            frac_change = 3*ann_SS_decrease_first3yrs + (n_early-3)*ann_SS_decrease
            
    SS_benefit = (1 + frac_change) * SS_benefit_FRA
    return SS_benefit


def calc_survivor_SS_benefit(deceased_SS_benefit, survivor_FRA, survivor_age):
    single = False
    if isinstance(survivor_age, int):
        single = True
        survivor_age = np.array([survivor_age])
    earliest_age = 60
    max_years_early = survivor_FRA - earliest_age
    max_reduction = 0.285

    years_early = survivor_FRA-survivor_age
    years_early[np.where(years_early < 0)[0]] = 0

    survivor_benefit = deceased_SS_benefit * (1 - years_early*max_reduction/max_years_early)
    if single:
        survivor_benefit = survivor_benefit[0]
    return survivor_benefit


class TaxPlanning(object):

    def __init__(self, work_income=0, pension_income=0, fixed_income=0, SS_benefit=0, pretax_funds=0, roth_funds=0, brokerage_funds=0,
                 savings=0, brokerage_cost_basis=0, SS_age=67, RMD_age=75, calc_int_div=True, qual_div=True, reinvest_div=True, 
                 SS_survivor_benefit=0, inherit_pretax_funds=0, inherit_age=None, inherit_timeline='lifetime', renter=False,
                 dividend_rate=0.017, growth_rate=0.1, savings_rate=0.035, inflation_rate=0.03, ACA_premium_rate=0.05, pension_COLA_rate=0.02,
                 n_dependents=0, healthcare='medicare', check_medicare_age=True, withdrawal_sequence=['brokerage', 'pretax','savings','roth'],
                 state='CA', filing='single', age=None, taxyear=2025, dollars='nominal', verbose=False):
        
        self.age          = age
        self.state        = state
        self.filing       = filing
        self.n_dependents = n_dependents
        self.renter       = renter
        self.verbose      = verbose
        
        if taxyear == 2025:
            self.y = taxyear_2025
        else:
            raise ValueError('Tax year not supported.')
        self.taxyear = taxyear
        self.import_taxyear()
        
        self.pretax_funds         = pretax_funds
        self.roth_funds           = roth_funds
        self.brokerage_funds      = brokerage_funds
        self.savings              = savings
        self.brokerage_cost_basis = brokerage_cost_basis
        self.dividend_rate        = dividend_rate
        self.growth_rate          = growth_rate
        self.savings_rate         = savings_rate
        self.inflation_rate       = inflation_rate
        self.dollars              = dollars
        self.work_income          = work_income
        self.pension_income       = pension_income
        self.fixed_income         = fixed_income
        self.SS_benefit           = SS_benefit
        self.SS_age               = SS_age
        self.SS_survivor_benefit  = SS_survivor_benefit
        self.inherit_pretax_funds = inherit_pretax_funds
        self.inherit_age          = inherit_age
        self.inherit_timeline     = inherit_timeline
        self.RMD_age              = RMD_age
        self.healthcare           = healthcare
        self.ACA_premium_rate     = ACA_premium_rate
        self.pension_COLA_rate    = pension_COLA_rate
        self.calc_int_div         = calc_int_div
        self.reinvest_div         = reinvest_div
        self.qual_div             = qual_div
        self.check_medicare_age   = check_medicare_age
        self.MAGI_arr             = np.array([])
        self.withdrawal_sequence  = {}

        acct_map = {'pretax':self.take_pretax_distributions,
                    'inherit_pretax':self.take_inherit_pretax_distributions,
                    'brokerage':self.make_brokerage_sales,
                    'savings':self.withdraw_savings,
                    'roth':self.take_roth_distributions, None:None}
        withdrawal_sequence.append(None)

        for i, acct in enumerate(withdrawal_sequence[:-1]):
            self.withdrawal_sequence[acct] = acct_map[withdrawal_sequence[i+1]]

        if self.inherit_timeline not in ['lifetime', '10year']:
            raise ValueError('Inheritance timeline must be lifetime or 10year.')
        self.inherit_RMD_factor = RMD.single_life_exectancy_factor[self.inherit_age] if self.inherit_pretax_funds > 0 else None

        if dollars == 'today':
            self.eff_growth_rate = growth_rate - inflation_rate
            self.eff_savings_rate = savings_rate - inflation_rate
            self.eff_ACA_premium_rate = ACA_premium_rate - inflation_rate
            self.eff_pension_COLA_rate = pension_COLA_rate - inflation_rate
            self.SS_benefit *= (1+inflation_rate)**(age - SS_age)

        elif dollars == 'nominal':
            self.eff_growth_rate = growth_rate
            self.eff_savings_rate = savings_rate
            self.eff_ACA_premium_rate = ACA_premium_rate
            self.eff_pension_COLA_rate = pension_COLA_rate
        else:
            raise ValueError('Dollars must be today or nominal.')

        if self.verbose:
            print('----------------')
            print('Age {}'.format(self.age))
            print('----------------')
        self.reset()

    def advance_year(self, work_income=None, pension_income=None, fixed_income=None, healthcare=None):
        self.age += 1 
        if self.inherit_RMD_factor is not None:
            self.inherit_RMD_factor -= 1

        if self.dollars == 'nominal':
            self.work_income *= (1+self.inflation_rate)
            self.fixed_income *= (1+self.inflation_rate)
            self.SS_survivor_benefit *= (1+self.inflation_rate)
            if self.age > self.SS_age:
                self.SS_benefit *= (1+self.inflation_rate)
            self.infl_adjust_brackets()
        self.pension_income *= (1+self.eff_pension_COLA_rate)   
        
        if work_income is not None:
            self.work_income = work_income
        if pension_income is not None:
            self.pension_income = pension_income
        if fixed_income is not None:
            self.fixed_income = fixed_income
        if healthcare is not None:
            self.healthcare = healthcare

        if self.ACA_unsub_premium is not None:
            self.ACA_unsub_premium *= (1+self.eff_ACA_premium_rate)

        self.pretax_funds *= (1+self.eff_growth_rate)
        self.roth_funds *= (1+self.eff_growth_rate)
        self.brokerage_funds *= (1+self.eff_growth_rate)
        self.inherit_pretax_funds *= (1+self.eff_growth_rate)

        if self.verbose:
            print('----------------')
            print('Advancing 1 year: Age {}'.format(self.age))
            print('----------------')
        self.reset()
    
    def reset(self):
        self.year_pretax_distributions = 0
        self.year_roth_distributions = 0
        self.year_brokerage_sales = 0
        self.year_savings_withdrawal = 0
        self.year_realized_gains = 0
        self.year_pretax_income = 0
        self.SS_income       = 0
        self.year_dividend_income = 0
        self.year_interest_income = 0
        self.state_nontaxable_int = 0
        self.foreign_tax_paid = 0
        self.year_total_income = 0
        self.year_surplus = 0
        self.AGI = 0
        self.MAGI = 0
        self.state_AGI = 0
        self.state_MAGI = 0
        self.pretax_contribution = 0
        self.roth_contribution = 0
        self.contribution_401k = 0
        self.taxable_income = 0
        self.taxable_LTCG = 0
        self.state_taxable_income = 0
        self.year_fed_ref_credit = 0
        self.year_fed_nref_credit = 0
        self.year_state_ref_credit = 0
        self.year_state_nref_credit = 0
        self.year_income_tax = 0
        self.year_LTCG_tax = 0
        self.year_fed_tax = 0
        self.year_state_tax = 0
        self.year_total_tax = 0
        self.year_fed_tax_owed = 0
        self.year_state_tax_owed = 0
        self.year_tax_owed = 0
        self.year_tax_withdrawn = 0
        self.fed_tax_withheld = 0
        self.state_tax_withheld = 0
        self.healthcare_premium = 0

        self.calc_standard_deductions()
        self.calc_income_social_security()
        self.calc_RMDs()
        if self.calc_int_div:
            self.calc_interest_dividends()
        self.calc_marginal_brackets(quiet=True)

        self.update_net_worth()
        if self.verbose:
            print('')
            # self.print_balances()

    def import_taxyear(self):
        self.ord_income_rates      = self.y.ord_income_rates
        self.ord_income_brackets   = self.y.ord_income_brackets[self.filing]
        self.LTCG_rates            = self.y.LTCG_rates
        self.LTCG_brackets         = self.y.LTCG_brackets[self.filing]
        self.SS_rates              = self.y.SS_rates
        self.SS_brackets           = self.y.SS_brackets[self.filing]
        self.standard_deduction    = self.y.standard_deduction[self.filing]
        self.deduction_bonus       = self.y.deduction_bonus[self.filing]
        self.SALT_deduction_cap    = self.y.SALT_deduction_cap
        self.OBBB_senior_deduction = self.y.OBBB_senior_deduction[self.filing]
        self.OBBB_thresh_phaseout  = self.y.OBBB_thresh_phaseout[self.filing]
        self.ira_cont_lim          = self.y.ira_cont_lim[self.filing]
        self.ira_cont_bonus        = self.y.ira_cont_bonus[self.filing]
        self.ret_cont_lim          = self.y.ret_cont_lim[self.filing]
        self.ret_cont_bonus        = self.y.ret_cont_bonus[self.filing]
        self.IRMAA_charges         = self.y.IRMAA_charges_ann[self.filing]
        self.IRMAA_thresholds      = self.y.IRMAA_thresholds[self.filing]
        self.ACA_contr_rates       = self.y.ACA_contr_rates['expansion'] # can make this a var later
        self.ACA_thresholds        = self.y.ACA_thresholds[self.filing]
        self.ACA_unsub_premium     = self.y.unsub_premium
        self.home_gain_exclusion   = self.y.home_sale_exclusion[self.filing]

        if self.state=='CA':
            self.state_income_rates       = self.y.ca_income_rates
            self.state_income_brackets    = self.y.ca_income_brackets[self.filing]
            self.state_standard_deduction = self.y.ca_standard_deduction[self.filing]
            self.state_local_rate         = self.y.ca_local_rate
            self.ca_exemption_agi_increment = self.y.ca_exemption_agi_increment
            self.ca_exemption_agi_thresholds = self.y.ca_exemption_agi_thresholds
            self.ca_exemption_credits     = self.y.ca_exemption_credits
            self.ca_renter_credit         = self.y.ca_renter_credit
            self.ca_renter_ca_agi_lim     = self.y.ca_renter_ca_agi_lim
            self.state_SS_exempt          = self.y.ca_ss_exempt

        elif self.state=='MD':
            self.state_income_rates       = self.y.md_income_rates
            self.state_income_brackets    = self.y.md_income_brackets[self.filing]
            self.state_standard_deduction = self.y.md_standard_deduction[self.filing]
            self.state_local_rate         = self.y.md_local_rate
            self.md_personal_exemption    = self.y.md_personal_exemption
            self.md_exemption_agi_thresholds = self.y.md_exemption_agi_thresholds
            self.md_senior_exemption      = self.y.md_senior_exemption
            self.md_senior_credit         = self.y.md_senior_credit
            self.md_senior_credit_agi_lim = self.y.md_senior_credit_agi_lim
            self.md_pension_exclusion_max = self.y.md_pension_exclusion_max
            self.md_ira_dist_included     = self.y.md_ira_dist_included
            self.state_SS_exempt          = self.y.md_ss_exempt
        else:
            raise ValueError('State not supported.')
    
    def infl_adjust_brackets(self):
        mult = (1+self.inflation_rate)
        self.ord_income_brackets = self.ord_income_brackets * mult
        self.LTCG_brackets = self.LTCG_brackets * mult
        self.standard_deduction = self.standard_deduction * mult
        self.deduction_bonus = self.deduction_bonus * mult
        self.state_income_brackets = self.state_income_brackets * mult
        self.state_standard_deduction = self.state_standard_deduction * mult
        self.ira_cont_lim = self.ira_cont_lim * mult
        self.ira_cont_bonus = self.ira_cont_bonus * mult
        self.ret_cont_lim = self.ret_cont_lim * mult
        self.ret_cont_bonus = self.ret_cont_bonus * mult
        self.IRMAA_charges = self.IRMAA_charges * mult
        self.IRMAA_thresholds = self.IRMAA_thresholds * mult
        self.ACA_thresholds = self.ACA_thresholds * mult

    def print_balances(self):
        print('')
        print('Pretax funds: ${:,.2f}'.format(self.pretax_funds))
        print('Roth funds: ${:,.2f}'.format(self.roth_funds))
        print('Brokerage funds: ${:,.2f}'.format(self.brokerage_funds))
        print('Brokerage cost basis: ${:,.2f}'.format(self.brokerage_cost_basis))
        print('Savings: ${:,.2f}'.format(self.savings))
        if self.inherit_pretax_funds > 0:
            print('Inherited pretax funds: ${:,.2f}'.format(self.inherit_pretax_funds))
        print('Net Worth: ${:,.2f}'.format(self.net_worth))
        print('')

    def update_net_worth(self, quiet=True):
        self.net_worth = self.pretax_funds+self.roth_funds+self.brokerage_funds+self.savings+self.inherit_pretax_funds

        if np.logical_and(self.verbose, quiet is False):
            print('Net worth: ${:,.2f}'.format(self.net_worth))
        
    def calc_standard_deductions(self):
        self.deduction = self.standard_deduction
        if self.age >= 65:
            self.deduction += self.deduction_bonus
        
        self.state_deduction = self.state_standard_deduction

        self.cont_lim_ira = self.ira_cont_lim
        self.cont_lim_401k = self.ret_cont_lim
        if self.age >= 50:
            self.cont_lim_ira += self.ira_cont_bonus
            self.cont_lim_401k += self.ret_cont_bonus

        if self.verbose:
            print('Standard federal deduction: ${:,.2f}'.format(self.deduction))
            print('Standard {} deduction: ${:,.2f}'.format(self.state, self.state_deduction))

    def calc_itemized_deductions(self, property_tax_paid=0, mortgage_int_paid=0, home_principal=0,
                                 medical_exp_paid=0, charity_paid=0):

        SALT_deduction = min(property_tax_paid+self.state_tax_withheld, self.SALT_deduction_cap)
        mortgage_int_deduction = min(1, 7.5e5/home_principal) * mortgage_int_paid if home_principal > 0 else mortgage_int_paid
        medical_exp_deduction = max(medical_exp_paid - 0.075*self.AGI, 0) ## note that this should be called again last
        itemized_deduction = medical_exp_deduction + SALT_deduction + mortgage_int_deduction + charity_paid

        state_mortgage_int_deduction = min(1, 1e6/home_principal) * mortgage_int_paid if home_principal > 0 else mortgage_int_paid
        state_itemized_deduction = medical_exp_deduction + property_tax_paid + state_mortgage_int_deduction + charity_paid

        if self.state == 'MD':
            reduction = max((self.AGI - 200000) * 0.075, 0)
            state_itemized_deduction -= reduction

        if itemized_deduction > self.deduction:
            self.deduction = itemized_deduction
            if self.verbose:
                print('Using itemized deductions: ${:,.2f}'.format(self.deduction))

        if state_itemized_deduction > self.state_deduction:
            self.state_deduction = state_itemized_deduction
            if self.verbose:
                print('Using itemized {} deductions: ${:,.2f}'.format(self.state, self.state_deduction))

        self.calc_marginal_brackets(quiet=True)

    def calc_OBBB_senior_deduction(self, quiet=False):
        if self.age < 65:
            self.final_deduction = self.deduction
            return
        
        threshold = self.OBBB_thresh_phaseout[0]
        phaseout_range = self.OBBB_thresh_phaseout[1] - threshold
        senior_deduction = self.OBBB_senior_deduction * max(0, 1 - max(0, (self.MAGI-threshold)/phaseout_range))
        self.final_deduction = self.deduction + senior_deduction

        if np.logical_and(self.verbose, quiet is False):
            print('OBBB additional senior deduction: ${:,.2f}'.format(senior_deduction))

    def calc_credits_fed(self, us_taxable_income, quiet=False):

        deminimis_thresh = {'single':300,'MFJ':600}[self.filing] # doesn't change
        if self.foreign_tax_paid <= deminimis_thresh:
            foreign_credit = self.foreign_tax_paid
        else:
            max_credit = self.foreign_taxable_income/self.taxable_income * us_taxable_income
            foreign_credit = min(self.foreign_tax_paid, max_credit)

        if np.logical_and(self.verbose, quiet is False):
            print(f'Foreign tax credit: ${foreign_credit:,.2f}')

        return foreign_credit

    def calc_pension_excl_MD(self, quiet=False):

        if self.age < 65:
            return 0
        ret_income_pool = self.pension_income + self.year_pretax_income ## in reality this only counts if it's pretax 401k
        if self.md_ira_dist_included:
            pass

        allowable_exclusion = max(0, self.md_pension_exclusion_max[self.filing] - self.SS_income)
        final_subtraction = min(ret_income_pool, allowable_exclusion)

        if np.logical_and(self.verbose, quiet is False):
            print(f'MD pension exclusion: ${final_subtraction:,.2f}')

        return final_subtraction

    def calc_exemptions_MD(self, quiet=False):
        n_exempt = {'MFJ':2, 'single':1}

        exemption_agi_thresholds = self.md_exemption_agi_thresholds[self.filing]
        for i, thresh in enumerate(exemption_agi_thresholds[::-1]):
            if self.AGI < thresh:
                continue
            exemption_amt = self.md_personal_exemption[::-1][i]
            break

        personal_exemption = (n_exempt[self.filing] + self.n_dependents) * exemption_amt
        senior_exemption = n_exempt[self.filing]*self.md_senior_exemption if self.age >= 65 else 0
        exemptions = personal_exemption + senior_exemption

        if np.logical_and(self.verbose, quiet is False):
            print(f'MD personal exemptions: ${exemptions:,.2f}')

        return exemptions
    
    def calc_exemptions_CA(self, quiet=False):
        return 0
    
    def calc_credits_MD(self, quiet=False):
        if np.logical_or(self.AGI > self.md_senior_credit_agi_lim[self.filing], self.age < 65):
            return 0 
        credit = self.md_senior_credit['amt'][self.filing]

        if np.logical_and(self.verbose, quiet is False):
            print(f'MD senior credit: ${credit:,.2f}')

        return credit

    def calc_credits_CA(self, quiet=False):
        n_exempt = {'MFJ':2, 'single':1}
        n_increment = max(np.floor((self.AGI - self.ca_exemption_agi_thresholds[self.filing])/self.ca_exemption_agi_increment), 0)

        personal_credit = max(self.ca_exemption_credits['personal']['amt'] - self.ca_exemption_credits['personal']['step']*n_increment, 0)
        senior_credit = (self.ca_exemption_credits['senior']['amt'] - self.ca_exemption_credits['senior']['step']*n_increment) if self.age >= 65 else 0
        senior_credit = max(senior_credit, 0)
        dependent_credit = max(self.ca_exemption_credits['dependent']['amt'] - self.ca_exemption_credits['dependent']['step']*n_increment, 0)

        exemption_credits = n_exempt[self.filing] * (personal_credit + senior_credit) + self.n_dependents * dependent_credit

        renters_credit = 0
        if self.renter:
            if self.state_AGI <= self.ca_renter_ca_agi_lim[self.filing]:
                renters_credit = self.ca_renter_credit['amt']
                if self.n_dependents > 0:
                    renters_credit *= 2

        total_credits = exemption_credits + renters_credit
        if np.logical_and(self.verbose, quiet is False):
            print(f'CA exemption/renters credits: ${total_credits:,.2f}')

        return total_credits

    def calc_medicare_premium(self, lookback_yrs):
        try:
            past_MAGI = self.MAGI_arr[lookback_yrs-1]
        except:
            past_MAGI = self.MAGI
            if self.verbose:
                print('MAGI from {} years prior not available.'.format(lookback_yrs))

        for i, amt in enumerate(self.IRMAA_thresholds[::-1]):
            if past_MAGI <= amt:
                continue
            medicare_premium = self.IRMAA_charges[::-1][i]
            break
        self.healthcare_premium = medicare_premium

        if self.verbose:
            print('Medicare Part B+D premium: ${:,.2f}'.format(medicare_premium))
    
    def calc_ACA_premium(self):
        if self.ACA_unsub_premium is None:
            right_val = self.ACA_contr_rates[-1]
        else:
            right_val = self.ACA_unsub_premium[self.filing]/self.MAGI # contribution not capped; premium = ACA_unsub_premium

        contr_rate = np.interp(self.MAGI, self.ACA_thresholds, self.ACA_contr_rates, right=right_val)
        ACA_premium = self.MAGI*contr_rate
        self.healthcare_premium = ACA_premium

        if self.verbose:
            print('ACA rate: {:.2f}%. Expected premium: ${:,.2f}'.format(contr_rate*100, ACA_premium))

    def calc_income_social_security(self):
        self.w2_income = self.work_income

        if self.age >= self.SS_age:
            self.SS_income = self.SS_benefit
        elif self.w2_income == 0:
            self.SS_income = calc_survivor_SS_benefit(self.SS_survivor_benefit, 67, self.age)
        self.year_total_income += self.w2_income + self.pension_income + self.fixed_income + self.SS_income

        if self.verbose:
            if self.work_income > 0:
                print('Work income: ${:,.2f}'.format(self.work_income))
            if self.pension_income > 0:
                print('Pension income: ${:,.2f}'.format(self.pension_income))
            if self.fixed_income > 0:
                print('Other fixed income: ${:,.2f}'.format(self.fixed_income))
            if self.SS_income > 0:
                print('Social Security: ${:,.2f}'.format(self.SS_income))

    def calc_RMDs(self):
        if self.age >= self.RMD_age:
            self.RMDs = round(self.pretax_funds/RMD.RMD_factor[self.age], 2)
            self.take_pretax_distributions(self.RMDs, RMD=True)
        else:
            self.RMDs = 0

        if self.inherit_pretax_funds > 0:
            if self.inherit_timeline == 'lifetime':
                self.inherit_RMDs = round(self.inherit_pretax_funds/self.inherit_RMD_factor, 2)
                self.take_inherit_pretax_distributions(self.inherit_RMDs, RMD=True)
            elif self.inherit_timeline == '10year':
                if (self.age - self.inherit_age) == 10:
                    self.inherit_RMDs = self.inherit_pretax_funds
                    self.take_inherit_pretax_distributions(self.inherit_RMDs, RMD=True)
                else:
                    self.inherit_RMDs = 0
        else:
            self.inherit_RMDs = None

    def calc_interest_dividends(self, year_int_income=None, year_div_income=None, state_exempt_int=0, foreign_taxable_income=0, foreign_tax_paid=0):
        if year_int_income is None:
            self.year_interest_income = self.eff_savings_rate * self.savings
        else:
            self.year_interest_income = year_int_income
        self.savings += self.year_interest_income

        if year_div_income is None:
            self.year_dividend_income = self.dividend_rate * self.brokerage_funds
        else:
            self.year_dividend_income = year_div_income

        if self.reinvest_div:
            self.make_contribution(self.year_dividend_income, acct='brokerage')
        else:
            self.year_total_income += self.year_dividend_income
        
        self.state_nontaxable_int = state_exempt_int
        self.foreign_taxable_income = foreign_taxable_income
        self.foreign_tax_paid = foreign_tax_paid

        if self.verbose:
            print('Interest: ${:,.2f}'.format(self.year_interest_income))
            print('Dividends: ${:,.2f}'.format(self.year_dividend_income))

    def calc_marginal_brackets(self, quiet=False):
        # pretax 401k contributions do not appear here -- already subtracted from w2_income
        ordinary_income = self.w2_income + self.pension_income + self.fixed_income + self.year_pretax_distributions +\
                          self.year_interest_income
        LTCG = self.year_realized_gains

        if self.qual_div:
            LTCG += self.year_dividend_income
        else:
            ordinary_income += self.year_dividend_income

        # federal
        fed_adjustments = self.pretax_contribution # IRA

        self.gross_income = ordinary_income + LTCG
        incomplete_AGI = self.gross_income - fed_adjustments
        taxable_SS = self.calc_taxable_SS(incomplete_AGI)
        self.AGI = incomplete_AGI + taxable_SS
        self.MAGI = self.AGI + self.pretax_contribution
        self.calc_OBBB_senior_deduction(quiet=quiet)

        adj_ordinary_income = self.AGI - LTCG
        self.taxable_income = max(adj_ordinary_income - self.final_deduction, 0)
        self.taxable_LTCG = min(LTCG, max(self.AGI - self.final_deduction, 0))

        # state
        state_subtraction = (taxable_SS + self.state_nontaxable_int) if self.state_SS_exempt else self.state_nontaxable_int
        state_exemption_deduction = self.state_deduction

        if self.state == 'MD':
            state_subtraction += self.calc_pension_excl_MD(quiet=quiet)
            state_exemption_deduction += self.calc_exemptions_MD(quiet=quiet)

        self.state_AGI = self.AGI - state_subtraction
        self.state_MAGI = self.state_AGI + self.pretax_contribution # true for state credit eligibility, but not for medical eligibility

        self.state_taxable_income = max(self.state_AGI - state_exemption_deduction, 0)

        for i, amt in enumerate(self.ord_income_brackets):
            if self.taxable_income >= amt: # was >
                continue
            rate_ind = i-1
            lim = amt
            if i == 0:
                rate_ind = 0
                lim = self.ord_income_brackets[1]
            self.fed_marginal_bracket = self.ord_income_rates[rate_ind]
            self.income_bracket_lim = lim
            self.income_bracket_room = lim - self.taxable_income
            break
        else:
            self.fed_marginal_bracket = self.ord_income_rates[-1]
            self.income_bracket_lim = float('inf')

        stacked_LTCG_income = self.taxable_income + self.taxable_LTCG
        for i, amt in enumerate(self.LTCG_brackets):
            if stacked_LTCG_income >= amt: # was >
                continue
            rate_ind = i-1
            lim = amt
            if i == 0:
                rate_ind = 0
                lim = self.LTCG_brackets[1]
            self.LTCG_marginal_bracket = self.LTCG_rates[rate_ind]
            self.LTCG_bracket_lim = lim
            self.LTCG_bracket_room = lim - stacked_LTCG_income
            break
        else:
            self.LTCG_marginal_bracket = self.LTCG_rates[-1]
            self.LTCG_bracket_lim = float('inf')

        for i, amt in enumerate(self.state_income_brackets):
            if self.state_taxable_income >= amt: # was >
                continue
            rate_ind = i-1
            lim = amt
            if i == 0:
                rate_ind = 0
                lim = self.state_income_brackets[1]
            self.state_marginal_bracket = self.state_income_rates[rate_ind]
            self.state_income_bracket_lim = lim
            self.state_income_bracket_room = lim - self.state_taxable_income
            break
        else:
            self.state_marginal_bracket = self.state_income_rates[-1]
            self.state_income_bracket_lim = float('inf')

        if np.logical_and(self.verbose, quiet is False):
            print('Fed ord. income bracket: {:,.2f}%'.format(self.fed_marginal_bracket*100))
            print('Fed LTCG bracket: {:,.2f}%'.format(self.LTCG_marginal_bracket*100))
            print('{} income bracket: {:,.2f}%'.format(self.state, self.state_marginal_bracket*100))
            print('Local rate: {:,.2f}%'.format(self.state_local_rate*100))

    def make_contribution(self, amt, acct='savings'):
        if acct=='savings':
            self.savings += amt
        elif acct=='brokerage':
            self.brokerage_funds += amt
            self.brokerage_cost_basis += amt
        elif acct=='pretax':
            contr = min(amt, self.cont_lim_ira - self.pretax_contribution - self.roth_contribution)
            if contr < amt:
                print('Only contributed ${:,.2f} to respect IRA limit'.format(contr))
            self.pretax_funds += contr
            self.pretax_contribution += contr
        else:
            contr = min(amt, self.cont_lim_ira - self.pretax_contribution - self.roth_contribution)
            if contr < amt:
                print('Only contributed ${:,.2f} to respect IRA limit'.format(contr))
            self.roth_funds += contr
            self.roth_contribution += contr

        self.update_net_worth(quiet=True)

    def max_out_IRA(self, acct='roth', source_acct='cash'):
        amt = self.cont_lim_ira - self.pretax_contribution - self.roth_contribution

        if source_acct == 'savings':
            self.savings -= amt
            self.update_net_worth(quiet=True)
        elif source_acct == 'cash':
            pass
        else:
            raise ValueError('Fund IRA from savings or cash.')

        self.make_contribution(amt, acct=acct)

        if self.verbose:
            print('Maxed out {} IRA from {}.'.format(acct, source_acct))

    def make_401k_contribution(self, cont_pcnt=None, cont_amt=None, acct='pretax', match_pcnt=0):

        if self.work_income == 0:
            print('No work income, can\'t contribute to 401k.')
            return
        
        if cont_amt is None:
            cont_amt = cont_pcnt * self.work_income
        elif cont_pcnt is None:
            cont_pcnt = cont_amt/self.work_income
        else:
            raise ValueError('Both contribution amount and percentage were supplied.')

        contr = min(cont_amt, self.cont_lim_401k - self.contribution_401k)
        if contr < cont_amt:
            print('Only contributed ${:,.2f} to respect 401k limit'.format(contr))

        employer_contr = min(match_pcnt, cont_pcnt) * self.work_income

        if acct =='pretax':
            self.pretax_funds += contr + employer_contr
            self.w2_income -= contr # this is a federal exclusion -- doesn't even make its way onto a W2, or a tax return
        else:
            self.roth_funds += contr + employer_contr

        self.year_total_income -= contr
        self.contribution_401k += contr

        self.update_net_worth(quiet=True)
        self.calc_marginal_brackets(quiet=True)

    def take_pretax_distributions(self, amt, RMD=False):
        if self.pretax_funds < amt:
            backup_fn = self.withdrawal_sequence['pretax']
            if backup_fn is None:
                raise ValueError('Out of money at age {}!'.format(self.age))
            backup_fn(amt-self.pretax_funds)
            self.pretax_funds = 0
            return
        self.pretax_funds -= amt
        self.year_pretax_distributions += amt
        self.year_pretax_income += amt
        self.year_total_income += amt
        self.update_net_worth(quiet=True)

        if self.verbose:
            if RMD:
                print('RMDs: ${:,.2f}'.format(amt))
            else:
                print('Pretax distributions: ${:,.2f}'.format(amt))

        self.calc_marginal_brackets(quiet=True)

    def take_inherit_pretax_distributions(self, amt, RMD=False):
        if self.inherit_pretax_funds < amt:
            backup_fn = self.withdrawal_sequence['inherit_pretax']
            if backup_fn is None:
                raise ValueError('Out of money at age {}!'.format(self.age))
            backup_fn(amt-self.inherit_pretax_funds)
            self.inherit_pretax_funds = 0
            return
        self.inherit_pretax_funds -= amt
        self.year_pretax_distributions += amt
        self.year_pretax_income += amt
        self.year_total_income += amt
        self.update_net_worth(quiet=True)

        if self.verbose:
            if RMD:
                print('Inherited RMDs: ${:,.2f}'.format(amt))
            else:
                print('Inherited pretax distributions: ${:,.2f}'.format(amt))

        self.calc_marginal_brackets(quiet=True)

    def take_roth_distributions(self, amt):
        if self.roth_funds < amt:
            backup_fn = self.withdrawal_sequence['roth']
            if backup_fn is None:
                raise ValueError('Out of money at age {}!'.format(self.age))
            backup_fn(amt-self.roth_funds)
            self.roth_funds = 0
            # raise ValueError('Out of money at age {}!'.format(self.age))
        self.roth_funds -= amt
        self.year_roth_distributions += amt
        self.year_total_income += amt
        self.update_net_worth(quiet=True)

        if self.verbose:
            print('Roth distributions: ${:,.2f}'.format(amt))

    def withdraw_savings(self, amt):
        if self.savings < amt:
            backup_fn = self.withdrawal_sequence['savings']
            if backup_fn is None:
                raise ValueError('Out of money at age {}!'.format(self.age))
            backup_fn(amt-self.savings)
            # self.take_roth_distributions(amt-self.savings)
            # self.make_brokerage_sales(amt-self.savings)
            self.savings = 0
            return
        self.savings -= amt
        self.year_savings_withdrawal += amt
        self.year_total_income += amt
        self.update_net_worth(quiet=True)

        if self.verbose:
            print('Savings withdrawal: ${:,.2f}'.format(amt))

    def make_brokerage_sales(self, amt, cost_basis_ratio=None):
        if self.brokerage_funds < amt:
            backup_fn = self.withdrawal_sequence['brokerage']
            if backup_fn is None:
                self.print_balances()
                raise ValueError('Out of money at age {}!'.format(self.age))
            backup_fn(amt-self.brokerage_funds)
            # self.withdraw_savings(amt-self.brokerage_funds)
            # self.take_pretax_distributions(amt-self.brokerage_funds)
            self.brokerage_funds = 0
            return
        if cost_basis_ratio is None:
            cost_basis_ratio = self.brokerage_cost_basis/self.brokerage_funds

        principal_sales = cost_basis_ratio * amt

        self.brokerage_cost_basis -= principal_sales
        self.brokerage_funds -= amt
        self.year_realized_gains += (amt - principal_sales)
        self.year_brokerage_sales += amt
        ### Maybe make sales/income separate -- differentiate rebalancing from living off portfolio
        self.year_total_income += amt
        self.update_net_worth(quiet=True)

        if self.verbose:
            print('Brokerage sales: ${:,.2f}'.format(amt))
            print('Realized gains: ${:,.2f}'.format(amt - principal_sales))

        self.calc_marginal_brackets(quiet=True)

    def sell_house(self, purchase_price, sale_price, closing_cost_fact, loan_balance, primary=True, acct='brokerage'):
        adj_sale_price = (1-closing_cost_fact)*sale_price
        realized_gain = max(0.0, adj_sale_price - purchase_price)

        # taxable LTCG
        taxable_realized_gain = realized_gain
        if primary:
            taxable_realized_gain = min(self.home_gain_exclusion, realized_gain)
        self.year_realized_gains += taxable_realized_gain

        # add profit to acct
        profit = adj_sale_price - loan_balance
        self.make_contribution(profit, acct=acct)

        if self.verbose:
            print('Sale profit: ${:,.2f}'.format(profit))
            print('Realized gains: ${:,.2f}'.format(taxable_realized_gain))

        self.calc_marginal_brackets(quiet=True)

    def meet_income_need(self, desired_income, acct='pretax'):
        portfolio_need = desired_income - self.year_total_income

        if portfolio_need <= 0:
            surplus = -portfolio_need
            self.year_surplus = surplus
            if self.verbose:
                print('Surplus: ${:,.2f}'.format(surplus))
            return

        if acct == 'pretax':
            self.take_pretax_distributions(portfolio_need)
        elif acct == 'inherit_pretax':
            self.take_inherit_pretax_distributions(portfolio_need)
        elif acct == 'brokerage':
            self.make_brokerage_sales(portfolio_need)
        elif acct == 'roth':
            self.take_roth_distributions(portfolio_need)
        else:
            self.withdraw_savings(portfolio_need)

    def pay_healthcare_premium(self, acct='savings'):

        if self.healthcare is None:
            return 0
        
        if self.healthcare == 'medicare':
            if self.check_medicare_age:
                if self.age < 65:
                    self.calc_ACA_premium()

            self.calc_medicare_premium(lookback_yrs=2)
            
        elif self.healthcare == 'ACA':
            self.calc_ACA_premium()

        premium_to_pay = self.healthcare_premium

        if self.year_surplus >= premium_to_pay:
            self.year_surplus -= premium_to_pay
            premium_to_pay = 0
        else:
            premium_to_pay -= self.year_surplus
            self.year_surplus = 0
        
        if acct=='pretax':
            self.take_pretax_distributions(premium_to_pay)
        elif acct=='inherit_pretax':
            self.take_inherit_pretax_distributions(premium_to_pay)
        elif acct=='brokerage':
            self.make_brokerage_sales(premium_to_pay)
        elif acct=='roth':
            self.take_roth_distributions(premium_to_pay)
        else:
            self.withdraw_savings(premium_to_pay)

        return self.healthcare_premium

    def make_roth_conversion(self, amt, quiet=False):
        if self.pretax_funds < amt:
            amt = self.pretax_funds
        self.pretax_funds -= amt
        self.roth_funds += amt
        self.year_pretax_distributions += amt

        if np.logical_and(self.verbose, quiet is False):
            print('Roth conversion: ${:,.2f}'.format(amt))

        self.calc_marginal_brackets(quiet=True)

    def roth_convert_up_to(self, marginal_rate):

        if self.fed_marginal_bracket > marginal_rate:
            self.make_roth_conversion(0)
            return

        # Binary search on conversion amount. lo is always safe (bracket <= target),
        # hi always overshoots. Each probe restores state so only the final commit is permanent.
        lo, hi = 0.0, self.pretax_funds
        init_pretax = self.pretax_funds
        init_roth   = self.roth_funds
        init_dist   = self.year_pretax_distributions

        while hi - lo > 1:
            mid = (lo + hi) / 2
            self.make_roth_conversion(mid, quiet=True)
            if self.fed_marginal_bracket <= marginal_rate:
                lo = mid
            else:
                hi = mid
            # Restore state for next probe
            self.pretax_funds              = init_pretax
            self.roth_funds                = init_roth
            self.year_pretax_distributions = init_dist
            self.calc_marginal_brackets(quiet=True)

        self.make_roth_conversion(lo)

    def add_tax_credit(self, credit, level, type='nonrefundable', quiet=False):
        if level == 'fed':
            if type == 'nonrefundable':
                self.year_fed_nref_credit += credit
            elif type == 'refundable':
                self.year_fed_ref_credit += credit
        elif level == 'state':
            if type == 'nonrefundable':
                self.year_state_nref_credit += credit
            elif type == 'refundable':
                self.year_state_ref_credit += credit
        else:
            raise ValueError('Level must be fed or state.')
        
        if np.logical_and(self.verbose, quiet is False):
            print(f'Added {level} {type} credit of ${credit:,.2f}')

    def add_tax_withheld(self, amt, level):
        if level == 'fed':
            self.fed_tax_withheld = amt
        elif level =='state':
            self.state_tax_withheld = amt
        else:
            raise ValueError('Level must be fed or state.')

    def calc_taxable_SS(self, AGI):

        prov_income = AGI + self.SS_income/2
        prov_income_to_tax = prov_income
        SS_taxable = 0

        for i, amt in enumerate(self.SS_brackets[::-1]):
            if prov_income_to_tax <= amt:
                continue
            
            SS_taxable += self.SS_rates[::-1][i] * (prov_income_to_tax - amt)
            prov_income_to_tax = amt

        return min(SS_taxable, 0.85*self.SS_income)
    
    def calc_income_tax(self, state=False):
        
        if state:
            rates = self.state_income_rates
            brackets = self.state_income_brackets
            income_to_tax = self.state_taxable_income
            total_tax = income_to_tax*self.state_local_rate
        else:
            rates = self.ord_income_rates
            brackets = self.ord_income_brackets
            if self.taxable_income == 0:
                income_to_tax = 0
            elif self.taxable_income + self.taxable_LTCG < 100000:
                income_to_tax = np.floor(self.taxable_income / 50) * 50 + 25 # halfway in bracket separated by $50
            else:
                income_to_tax = self.taxable_income
            total_tax = 0

        for i, amt in enumerate(brackets[::-1]):
            if income_to_tax <= amt:
                continue

            total_tax += rates[::-1][i] * (income_to_tax - amt)
            income_to_tax = amt

        return total_tax

    def calc_LTCG_tax(self):

        gains_to_tax = self.taxable_LTCG
        income_gains_to_tax = self.taxable_income + gains_to_tax

        total_tax = 0
        for i, amt in enumerate(self.LTCG_brackets[::-1]):
            if income_gains_to_tax <= amt:
                continue

            marginal_gains = min((income_gains_to_tax - amt), gains_to_tax)
            total_tax += self.LTCG_rates[::-1][i] * marginal_gains
            gains_to_tax -= marginal_gains
            income_gains_to_tax = self.taxable_income + gains_to_tax

        return total_tax

    def calculate_taxes(self, quiet=False):

        self.calc_marginal_brackets(quiet=quiet)
        self.year_income_tax = self.calc_income_tax()
        self.year_LTCG_tax = self.calc_LTCG_tax()
        year_fed_tax = self.year_income_tax + self.year_LTCG_tax
        year_state_tax = self.calc_income_tax(state=True)

        if self.state == 'MD':
            state_personal_credit = self.calc_credits_MD(quiet=quiet)
        elif self.state == 'CA':
            state_personal_credit = self.calc_credits_CA(quiet=quiet)
        state_nref_credit = state_personal_credit + self.year_state_nref_credit

        fed_nref_credit = self.year_fed_nref_credit
        if self.foreign_tax_paid > 0:
            fed_nref_credit += self.calc_credits_fed(year_fed_tax, quiet=quiet)

        self.year_fed_tax = max(year_fed_tax-fed_nref_credit, 0) - self.year_fed_ref_credit
        self.year_state_tax = max(year_state_tax-state_nref_credit, 0) - self.year_state_ref_credit
        self.year_fed_tax_owed = self.year_fed_tax - self.fed_tax_withheld
        self.year_state_tax_owed = self.year_state_tax - self.state_tax_withheld
        self.year_total_tax = self.year_fed_tax + self.year_state_tax
        self.year_tax_owed = self.year_fed_tax_owed + self.year_state_tax_owed

        if np.logical_and(self.verbose, quiet is False):
            print('')
            print('AGI: ${:,.2f}'.format(self.AGI))
            # print('MAGI: ${:,.2f}'.format(self.MAGI))
            print('{} AGI: ${:,.2f}'.format(self.state, self.state_AGI))
            print('Fed. taxable income: ${:,.2f}'.format(self.taxable_income))
            print('Fed. taxable LTCG: ${:,.2f}'.format(self.taxable_LTCG))
            # print('Fed. taxable income: ${:,.2f}'.format(self.taxable_income+self.taxable_LTCG))
            print('{} taxable income: ${:,.2f}'.format(self.state, self.state_taxable_income))
            print('Ordinary income tax: ${:,.2f}'.format(self.year_income_tax))
            print('LTCG tax: ${:,.2f}'.format(self.year_LTCG_tax))
            # print('Fed. tax: ${:,.2f}'.format(year_fed_tax))
            print('{} state tax: ${:,.2f}'.format(self.state, year_state_tax))
            print('Fed. tax after credits: ${:,.2f}'.format(self.year_fed_tax))
            print('{} tax after credits: ${:,.2f}'.format(self.state, self.year_state_tax))
            if self.year_fed_tax_owed >= 0:
                print('Final fed. tax payment: ${:,.2f}'.format(self.year_fed_tax_owed))
            else:
                print('Final fed. tax refund: ${:,.2f}'.format(-self.year_fed_tax_owed))
            if self.year_state_tax_owed >= 0:
                print('Final {} tax payment: ${:,.2f}'.format(self.state, self.year_state_tax_owed))
            else:
                print('Final {} tax refund: ${:,.2f}'.format(self.state, -self.year_state_tax_owed))
            print('')

    def settle_taxes(self, acct='savings'):
        self.calculate_taxes(quiet=True)
        tax_to_pay = self.year_tax_owed - self.year_tax_withdrawn

        if self.year_surplus >= tax_to_pay:
            self.year_surplus -= tax_to_pay
            self.year_tax_withdrawn += tax_to_pay
            tax_to_pay = 0
        else:
            tax_to_pay -= self.year_surplus
            self.year_tax_withdrawn =+ self.year_surplus
            self.year_surplus = 0

        while tax_to_pay > 1:
            # withdraw amount for tax
            if acct=='pretax':
                self.take_pretax_distributions(tax_to_pay)
            elif acct=='inherit_pretax':
                self.take_inherit_pretax_distributions(tax_to_pay)
            elif acct=='brokerage':
                self.make_brokerage_sales(tax_to_pay)
            elif acct=='roth':
                self.take_roth_distributions(tax_to_pay)
            else:
                self.withdraw_savings(tax_to_pay)

            self.year_tax_withdrawn += tax_to_pay
            self.calculate_taxes(quiet=True)
            tax_to_pay = self.year_tax_owed - self.year_tax_withdrawn

        self.calculate_taxes()

    def balance_year(self, acct='brokerage'):
        assert acct in ['brokerage', 'savings']

        if self.verbose:
            print('End-of-year surplus: ${:,.2f}'.format(self.year_surplus))
        self.make_contribution(self.year_surplus, acct=acct)
        self.year_surplus = 0

        self.MAGI_arr = np.insert(self.MAGI_arr, 0, self.MAGI)


if __name__=='__main__':

    RB = TaxPlanning(filing='single', age=63, taxyear=2025, verbose=True, fixed_income=105000, healthcare='ACA')

    for i in range(4):
        RB.meet_income_need(0)
        RB.pay_healthcare_premium()
        RB.settle_taxes()
        RB.balance_year()
        if RB.age==64:
            RB.advance_year(healthcare='medicare')
        else:
            RB.advance_year()