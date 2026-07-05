def simplify_debts(balances: dict) -> list:
    """Simplifies the debts within a group using a greedy algorithm.

    Given the net balances of all users in a group, it calculates the
    minimum necessary transfers to settle all debts.

    Args:
        balances: A dictionary mapping user names to their net balances (e.g. {'Alice': -50.0, 'Bob': 20.0}).

    Returns:
        A list of transfer instructions (e.g. ['Alice pays Bob $20.00']).
    """
    # Separate into debtors and creditors
    debtors = []  # List of [name, absolute_debt_amount]
    creditors = []  # List of [name, credit_amount]

    for name, bal in balances.items():
        if bal < -0.01:
            debtors.append([name, -bal])
        elif bal > 0.01:
            creditors.append([name, bal])

    # Sort descending by amount to apply greedy approach
    debtors.sort(key=lambda x: x[1], reverse=True)
    creditors.sort(key=lambda x: x[1], reverse=True)

    transfers = []
    i = 0
    j = 0

    while i < len(debtors) and j < len(creditors):
        debtor_name, debtor_amt = debtors[i]
        creditor_name, creditor_amt = creditors[j]

        # Calculate transfer amount
        transfer_amt = min(debtor_amt, creditor_amt)
        transfers.append(f"{debtor_name} pays {creditor_name} ${transfer_amt:.2f}")

        # Deduct the transferred amount
        debtors[i][1] -= transfer_amt
        creditors[j][1] -= transfer_amt

        # Move pointers if settled
        if debtors[i][1] < 0.01:
            i += 1
        if creditors[j][1] < 0.01:
            j += 1

    return transfers


# Wrap for registering as an ADK tool
def simplify_debts_tool(balances: dict[str, float]) -> list[str]:
    """Simplifies group debts using a greedy algorithm to settle balances with minimum transfers.

    Args:
        balances: A dictionary of net balances where keys are user names and values are their net amounts.
                  A positive amount means they are owed money, and a negative amount means they owe money.
                  Example: {"Alice": -50.0, "Bob": 20.0, "Charlie": 30.0}

    Returns:
        A list of strings representing the simplified transfers.
    """
    return simplify_debts(balances)
