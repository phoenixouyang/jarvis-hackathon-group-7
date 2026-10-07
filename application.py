import csv
from decimal import Decimal, InvalidOperation


FLAG_THRESHOLD = Decimal("10000")

# This function reads a csv file and return a list of lists
# each element of the returned list is a row in the csv file
# The first row is the header row
def read_csv_file(file_name):
    data_set = []
    with open(file_name, mode='r', encoding="utf-8-sig") as file:
        csv_reader = csv.reader(file)
        for row in csv_reader:
            data_set.append(row)
    return data_set

# This function writes out a list of lists to a csv file.
# each element of the list is a row in the csv file
# The first row is the header row
def write_csv_file(file_name, data_set):
    with open(file_name, mode='w', newline='', encoding="utf-8-sig") as file:
        csv_writer = csv.writer(file)
        for row in data_set:
            csv_writer.writerow(row)

# This function reads the raw CSV files, and converts the accounts.csv into a dict, using Account Id as a key.
# It converts transactions into a list, and returns both objects.
def load_data():
    accounts_raw = read_csv_file("accounts.csv")
    transactions_raw = read_csv_file("transactions.csv")

    accounts_headers = accounts_raw[0]
    transactions_headers = transactions_raw[0]

    accounts_dict = {}
    for row in accounts_raw[1:]:
        d = dict(zip(accounts_headers, row))
        key = (d["accountId"])
        accounts_dict[key] = d

    transactions_list = []
    for row in transactions_raw[1:]:
        d = dict(zip(transactions_headers, row))
        transactions_list.append(d)

    return accounts_dict, transactions_list


# This function parses an amount string into a Decimal, or returns None if it is not a number
def parse_amount(value):
    try:
        return Decimal(value.strip())
    except (InvalidOperation, AttributeError):
        return None

# This function checks a single transaction against the accounts to validate for:
# existing accounts, valid amounts, closed accounts, and daily limits
# Returns (approved, reason). reason is None when approved.
def validate_transaction(transaction, accounts):
    tx_type = transaction["type"].strip().upper()
    from_id = transaction["fromAccount"].strip()
    to_id = transaction["toAccount"].strip()
    amount = parse_amount(transaction["amount"])

    if amount is None:
        return False, "INVALID AMOUNT"
    if amount < 0:
        return False, "NEGATIVE AMOUNT"
    if amount == 0:
        return False, "INVALID AMOUNT"

    # Which accounts each transaction type needs
    if tx_type in ("PURCHASE", "WITHDRAWAL"):
        needs_from, needs_to = True, False
    elif tx_type == "DEPOSIT":
        needs_from, needs_to = False, True
    elif tx_type == "TRANSFER":
        needs_from, needs_to = True, True
    elif tx_type == "REVERSAL":
        needs_from, needs_to = True, False
    else:
        return False, "UNSUPPORTED TRANSACTION TYPE"

    if (needs_from and from_id not in accounts) or (needs_to and to_id not in accounts):
        return False, "INVALID ACCOUNT"

    from_account = accounts[from_id] if needs_from else None
    to_account = accounts[to_id] if needs_to else None

    for account in (from_account, to_account):
        if account is not None and account["status"].strip().upper() == "CLOSED":
            return False, "CLOSED ACCOUNT"

    # A reversal credits the fromAccount, so the spending checks don't apply
    if from_account is not None and tx_type != "REVERSAL":
        if amount > Decimal(from_account["dailyLimit"]):
            return False, "EXCEEDS DAILY LIMIT"
        if amount > Decimal(from_account["balance"]):
            return False, "INSUFFICIENT FUNDS"

    return True, None

# This function applies an approved transaction to the account balances
def apply_transaction(transaction, accounts):
    amount = parse_amount(transaction["amount"])
    from_id = transaction["fromAccount"].strip()
    to_id = transaction["toAccount"].strip()

    if transaction["type"].strip().upper() == "REVERSAL":
        account = accounts[from_id]
        account["balance"] = str(Decimal(account["balance"]) + amount)
        return

    if from_id:
        account = accounts[from_id]
        account["balance"] = str(Decimal(account["balance"]) - amount)
    if to_id:
        account = accounts[to_id]
        account["balance"] = str(Decimal(account["balance"]) + amount)

# This function returns why a transaction should be flagged for review,
# or None if it doesn't need review
# flagged transactions: Reversals and amounts over $10,000
def review_reason(transaction):
    if transaction["type"].strip().upper() == "REVERSAL":
        return "REVERSAL"
    amount = parse_amount(transaction["amount"])
    if amount is not None and amount > FLAG_THRESHOLD:
        return "AMOUNT OVER 10000"
    return None

# This function validates every transaction in order, updates the accounts for
# approved ones, prints each result, and returns the summary counts along with
# the flagged transactions
def process_transactions(transactions, accounts):
    summary = {"processed": 0, "approved": 0, "rejected": 0, "flagged": 0}
    flagged_transactions = []
    # IDs of transactions that were applied to the accounts (approved or flagged) to track duplication
    applied_ids = set()

    for transaction in transactions:
        # validate if transaction is duplicated, and already processed
        tx_id = transaction["transactionId"].strip()
        if tx_id in applied_ids:
            approved, reason = False, "DUPLICATE TRANSACTION"
        else:
            approved, reason = validate_transaction(transaction, accounts)
        flag_reason = review_reason(transaction)

        if approved:
            applied_ids.add(tx_id)

        if not approved:
            result = "REJECTED - " + reason
            summary["rejected"] += 1
        elif flag_reason:
            apply_transaction(transaction, accounts)
            result = "FLAGGED - " + flag_reason
            summary["flagged"] += 1
            flagged = dict(transaction)
            flagged["status"] = "FLAGGED"
            flagged["rejectReason"] = ""
            flagged["flagReason"] = flag_reason
            flagged_transactions.append(flagged)
        else:
            apply_transaction(transaction, accounts)
            result = "APPROVED"
            summary["approved"] += 1

        summary["processed"] += 1
        print(transaction["transactionId"], result)

    return summary, flagged_transactions

# This function writes the flagged transactions out to a csv file
def write_flagged_transactions(file_name, flagged_transactions, transaction_headers):
    headers = transaction_headers + ["status", "rejectReason", "flagReason"]
    rows = [headers]
    for transaction in flagged_transactions:
        rows.append([transaction[h] for h in headers])
    write_csv_file(file_name, rows)

# This function writes the accounts (with updated balances) back out to a csv file
def write_accounts(file_name, accounts):
    headers = list(next(iter(accounts.values())).keys())
    rows = [headers]
    for account in accounts.values():
        row = [account[h] for h in headers]
        row[headers.index("balance")] = f"{Decimal(account['balance']):.2f}"
        rows.append(row)
    write_csv_file(file_name, rows)


def main():
    accounts, transactions = load_data()
    summary, flagged_transactions = process_transactions(transactions, accounts)

    # Processing summary
    print()
    print("Transactions Processed:", summary["processed"])
    print("Approved:", summary["approved"])
    print("Rejected:", summary["rejected"])
    print("Flagged:", summary["flagged"])

    # Report outputs for account balances, and flagged transactions for review
    write_accounts("updated_accounts.csv", accounts)
    write_flagged_transactions("flagged_transactions.csv", flagged_transactions,
                               list(transactions[0].keys()))

if __name__ == "__main__":
    main()

