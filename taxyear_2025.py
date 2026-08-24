import numpy as np

# Federal tax
ord_income_rates               = np.array([0.1,0.12,0.22,0.24,0.32,0.35,0.37])
ord_income_brackets = {'single': np.array([0,11925,48475,103350,197300,250525,626350]),
                       'MFJ'   : np.array([0,23850,96950,206700,394600,501050,751600])}

LTCG_rates               = np.array([0, 0.15, 0.2])
LTCG_brackets = {'single': np.array([0, 48350, 533400]),
                 'MFJ'   : np.array([0, 96700, 600050])}

SS_rates              = np.array([0, 0.5, 0.85])
SS_brackets = {'single':np.array([0, 25000, 34000]),
               'MFJ'   :np.array([0, 32000, 44000])}

standard_deduction = {'single':15750, 'MFJ':31500} # was 15000/30000 before OBBB
deduction_bonus    = {'single':2000, 'MFJ':1600*2}
OBBB_senior_deduction = {'single':6000, 'MFJ':12000}
OBBB_thresh_phaseout  = {'single':np.array([75000, 175000]),
                         'MFJ'   :np.array([150000, 250000])}

SALT_deduction_cap = 40000

#### CA ####
ca_income_rates               = np.array([0.01,0.02,0.04,0.06,0.08,0.093,0.103,0.113,0.123])
ca_income_brackets = {'single': np.array([0,11079,26264,41452,57542,72724,371479,445771,742953]),
                       'MFJ'  : np.array([0,22158,52528,82904,115084,145448,742958,891542,1485906])}
ca_local_rate = 0.0

ca_standard_deduction = {'single':5706, 'MFJ':11412}
ca_ss_exempt = True

ca_exemption_agi_increment  = 2500
ca_exemption_agi_thresholds = {'single': 252203, 'MFJ': 504411}
ca_exemption_credits = {'personal' : {'amt':153, 'step':6, 'type':'nonrefundable'},
                        'senior'   : {'amt':153, 'step':6, 'type':'nonrefundable'},
                        'dependent': {'amt':475, 'step':18, 'type':'nonrefundable'}}

ca_renter_credit  = {'amt':60,'type':'nonrefundable'}
ca_renter_ca_agi_lim = {'single': 53994, 'MFJ': 107987}
############

#### MD ####
md_income_rates               = np.array([0.02, 0.03, 0.04, 0.0475, 0.05, 0.0525, 0.055, 0.0575, 0.0625, 0.065])
md_income_brackets = {'single': np.array([0, 1000, 2000, 3000, 100000, 125000, 150000, 250000,  500000, 1000000]),
                      'MFJ'   : np.array([0, 1000, 2000, 3000, 150000, 175000, 225000, 300000,  600000, 1200000])}
md_local_rate = 0.0320 # flat percentage set by each county

md_standard_deduction = {'single': 3350, 'MFJ': 6700}
md_ss_exempt = True

md_personal_exemption                   = np.array([3200, 1600, 800, 0])   # per person
md_exemption_agi_thresholds = {'single' : np.array([0, 100000, 125000, 150000]),
                               'MFJ'    : np.array([0, 150000, 175000, 200000])}
md_senior_exemption = 1000  # additional per person age 65+

md_senior_credit         = {'amt': {'single':1000, 'MFJ':1750}, 'type':'nonrefundable'}   # credit amount (one/both 65+)
md_senior_credit_agi_lim = {'single': 100000, 'MFJ': 150000}

# Qualifying income: pensions and income from employer plans (401k)
md_pension_exclusion_max = {'single':41200, 'MFJ':82400}  ## in reality, this is a per-pension exclusion, so the pooling isn't right
md_ira_dist_included = False

# Maryland capital gains surtax (new TY 2025): 2% on net capital gains when federal AGI
# exceeds $350,000 (threshold applies to ALL filing statuses — no MFJ doubling).
# Exceptions: primary residence sales where proceeds ≤ $1.5M, certain qualifying business assets.
############

# other
ira_cont_lim = {'single': 7000, 'MFJ': 14000}
ira_cont_bonus = {'single':1000, 'MFJ': 2000}
ret_cont_lim = {'single': 23500, 'MFJ': 47000}
ret_cont_bonus = {'single': 7500, 'MFJ': 15000}

# Medicare
IRMAA_B_charges_mo            = np.array([185.00, 259.00, 370.00, 480.90, 591.90, 628.90])
IRMAA_D_charges_mo            = np.array([0, 13.70, 35.30, 57.00, 78.60, 85.80])
IRMAA_thresholds   = {'single': np.array([0, 106000, 133000, 167000, 200000, 499999]),
                      'MFJ'   : np.array([0, 212000, 266000, 334000, 400000, 749999])}
IRMAA_charges_ann  = {'single': 12*(IRMAA_B_charges_mo + IRMAA_D_charges_mo),
                      'MFJ'   : 12*2*(IRMAA_B_charges_mo + IRMAA_D_charges_mo)}

# ACA Marketplace
FPL_1 = {'48':15060,'AK':18810,'HI':17310}
FPL_2 = {'48':20440,'AK':25540,'HI':23500}
unsub_premium = None # expected contribution capped

# non-expansion states: no coverage gap; assumes 0% contr rate can be maintained through immigration status
ACA_income_tier       = np.array([1, 1.01, 1.32, 1.33, 1.38, 1.5, 2,  2.5, 3,   4]) 
ACA_contr_rate_nonexp = np.array([0, 0,    0,    0,    0,    0,  .02, .04, .06, .085])
ACA_contr_rates = {'expansion':np.concatenate((np.zeros(4), ACA_contr_rate_nonexp[4:])),
                   'non-expansion':ACA_contr_rate_nonexp,
                   'WI/GA' : np.concatenate((np.zeros(1),ACA_contr_rate_nonexp[1:]))}
ACA_thresholds = {'single': np.round(ACA_income_tier*FPL_1['48'], decimals=2), 
                  'MFJ'   : np.round(ACA_income_tier*FPL_2['48'], decimals=2)}
for filing, thresh_arr in ACA_thresholds.items():
    # flat rate from 100%-133% FPL - get edges 1 cent away
    thresh_arr[1] = thresh_arr[0] + 0.01
    thresh_arr[2] = thresh_arr[3] - 0.01

# home sale realized gain exclusion. static since 1997
home_sale_exclusion = {'single': 250000, 'MFJ':500000}