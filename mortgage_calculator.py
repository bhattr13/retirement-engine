import numpy as np
import numpy_financial as npf
import matplotlib.pyplot as plt

def calc_interest(principal, mo_rate, n_payments, fixed_payment):

    interest_arr = np.zeros(n_payments)
    balance = principal

    for i in range(n_payments):

        interest_paid = balance * mo_rate
        principal_paid = fixed_payment - interest_paid
        balance -= principal_paid
        interest_arr[i] = interest_paid

    return interest_arr


def calc_annual_interest(annual_payment, ann_rate, principal):
    """Calculate the interest paid during one year of a mortgage.
    
    Parameters:
    -----------
    annual_payment : float
        Fixed annual payment amount
    ann_rate : float
        Annual interest rate (decimal, e.g., 0.03 for 3%)
    principal : float
        Current loan balance at the start of the year
    
    Returns:
    --------
    float : Total interest paid during the year
    """

    mo_rate = ann_rate / 12
    monthly_payment = annual_payment / 12
    
    # Calculate interest for 12 months
    interest_arr = calc_interest(principal, mo_rate, 12, monthly_payment)
    return np.sum(interest_arr)



def calc_annual_mortgage(principal, loan_term, ann_rate, plot=False):
    """Calculate annual mortgage payment and interest paid that year.
    
    Parameters:
    -----------
    principal : float
        Current loan balance
    loan_term : int
        Remaining loan term in years
    ann_rate : float
        Annual interest rate (decimal, e.g., 0.03 for 3%)
    plot : bool
        If True, displays full amortization schedule plot. Default is False.
    
    Returns:
    --------
    annual_payment : Total mortgage payment for the year
    """

    mo_rate = ann_rate/12
    
    # Calculate fixed payment
    n_payments = loan_term * 12
    annual_payment = npf.pmt(mo_rate, n_payments, -principal) * 12

    return annual_payment


def amortize(principal, ann_rate, n):
    """Return annual payment and annual interest arrays over the full loan term.

    Parameters
    ----------
    principal : float
        Starting loan balance.
    ann_rate : float
        Annual interest rate (decimal, e.g. 0.03 for 3%).
    n : int
        Loan term in years.

    Returns
    -------
    payments : np.ndarray, shape (n,)
        Fixed annual payment (same every year).
    interest : np.ndarray, shape (n,)
        Interest portion of payments each year (decreasing over time).
    """
    mo_rate = ann_rate / 12
    n_months = n * 12
    monthly_payment = npf.pmt(mo_rate, n_months, -principal)

    periods = np.arange(1, n_months + 1)
    monthly_interest = npf.ipmt(mo_rate, periods, n_months, -principal)

    interest = monthly_interest.reshape(n, 12).sum(axis=1)
    payments = np.full(n, monthly_payment * 12)

    principal_paid = np.cumsum(payments - interest)
    balance_start = np.concatenate([[principal], principal - principal_paid[:-1]])
    balance_end = principal - principal_paid
    avg_principal = (balance_start + balance_end) / 2

    return payments, interest, avg_principal


if __name__ == '__main__':
    principal = 9.1e5
    loan_term = 20 # yrs
    ann_rate = 0.03

    ann_mortgage, ann_interest = amortize(principal, ann_rate, loan_term)

    # total_payment = calc_annual_mortgage(principal, loan_term, ann_rate)
    # print('Mo. mortgage payment: ${:,.2f}'.format(total_payment/12))
    # print('')

    # for n in range(10):
    #     total_interest_paid = calc_annual_interest(total_payment, ann_rate, principal)
    #     print('Annual interest payment: ${:,.2f}'.format(total_interest_paid))

    #     total_principal_paid = total_payment - total_interest_paid
    #     principal -= total_principal_paid

    

