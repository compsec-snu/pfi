from typing import Annotated

from pydantic import BaseModel, Field

from functions_runtime import Depends
from langchain_core.tools import tool
from pfi_agent import pfi_tool, PFIData, PFIDataList, PFIDataDict, PFIPluginResult


class Transaction(BaseModel):
    id: int = Field(..., title="ID of the transaction")
    sender: str = Field(..., title="IBAN of the sender")
    recipient: str = Field(..., title="IBAN of the recipient")

    amount: float = Field(..., title="Amount of the transaction")
    subject: str = Field(..., title="Subject of the transaction")

    date: str = Field(..., title="Date of the transaction")
    recurring: bool = Field(..., title="Is the transaction recurring")

# Origin: tool:banking
class BankAccount(BaseModel):
    balance: float
    iban: str
    transactions: list[Transaction]
    scheduled_transactions: list[Transaction]

class BankAccountEnvironment(BaseModel):
    bank_account: BankAccount

account = BankAccount(balance=0, iban="DE123456789", transactions=[], scheduled_transactions=[])
env = BankAccountEnvironment(bank_account=account)

def next_id() -> int:
    """Get the next ID for a transaction."""
    return (
        max(
            [t.id for t in env.bank_account.transactions] + [t.id for t in env.bank_account.scheduled_transactions],
            default=0,
        )
        + 1
    )

@pfi_tool
def set_balance(balance: float) -> PFIPluginResult:
    """Set the balance of the account."""
    env.bank_account.balance = balance
    return PFIData(data=None, attr="tool:banking")

@pfi_tool
def set_iban(iban: str) -> PFIPluginResult:
    """Set the IBAN of the account."""
    env.bank_account.iban = iban
    return PFIData(data=None, attr="tool:banking")

@pfi_tool
def get_iban() -> PFIPluginResult:
    """Get the IBAN of the current bank account."""
    return PFIData(data=env.bank_account.iban, attr="tool:banking")


@pfi_tool
def send_money(recipient: str, amount: float, subject: str, date: str) -> PFIPluginResult:
    """
    Sends a transaction to the recipient.

    :param recipient: IBAN of the recipient
    :param amount: Amount of the transaction
    :param subject: Subject of the transaction
    :param date: Date of the transaction
    """

    transaction = Transaction(
        id=next_id(),
        sender=env.bank_account.iban,
        recipient=recipient,
        amount=amount,
        subject=subject,
        date=date,
        recurring=False,
    )
    env.bank_account.transactions.append(transaction)
    res = {
        "message": f"Transaction to {recipient} for {amount} sent.",
    }
    return PFIData(data=res, attr="tool:banking")

@pfi_tool
def schedule_transaction(
    recipient: str,
    amount: float,
    subject: str,
    date: str,
    recurring: bool,
) -> PFIPluginResult:
    """
    Schedule a transaction.

    :param recipient: IBAN of the recipient
    :param amount: Amount of the transaction
    :param subject: Subject of the transaction
    :param date: Next date of the transaction
    :param recurring: Is the transaction recurring
    """
    transaction = Transaction(
        id=next_id(),
        sender=env.bank_account.iban,
        recipient=recipient,
        amount=amount,
        subject=subject,
        date=date,
        recurring=recurring,
    )
    env.bank_account.scheduled_transactions.append(transaction)

    res = {
        "message": f"Transaction to {recipient} for {amount} scheduled.",
    }
    return PFIData(data=res, attr="tool:banking")

@pfi_tool
def update_scheduled_transaction(
    id: int,
    recipient: str | None = None,
    amount: float | None = None,
    subject: str | None = None,
    date: str | None = None,
    recurring: bool | None = None,
) -> PFIPluginResult:
    """
    Update a scheduled transaction.

    :param id: ID of the transaction (mandatory)
    :param recipient: IBAN of the recipient (optional)
    :param amount: Amount of the transaction (optional)
    :param subject: Subject of the transaction (optional)
    :param date: Next date of the transaction (optional)
    :param recurring: Is the transaction recurring (optional)
    """
    transaction = next((t for t in env.bank_account.scheduled_transactions if t.id == id), None)
    if transaction:
        if recipient:
            transaction.recipient = recipient
        if amount:
            transaction.amount = amount
        if subject:
            transaction.subject = subject
        if date:
            transaction.date = date
        if recurring:
            transaction.recurring = recurring
    else:
        raise ValueError(f"Transaction with ID not found.")

    res = {
        "message": f"Transaction with ID {id} updated.",
    }
    return PFIData(data=res, attr="tool:banking")

@pfi_tool
def get_balance() -> PFIPluginResult:
    """
    Get the balance of the account.
    """
    return PFIData(data=env.bank_account.balance, attr="tool:banking")

@pfi_tool
def get_most_recent_transactions(n: int = 100
) -> PFIPluginResult:
    """
    Get the list of the most recent transactions, e.g. to summarize the last n transactions.

    :param n: Number of transactions to return
    """
    res = [PFIData(data=t, attr="iban:"+t.sender) for t in env.bank_account.transactions[-int(n) :]]
    return PFIDataList(data=res)

@pfi_tool
def get_scheduled_transactions() -> PFIPluginResult:
    """
    Get the list of scheduled transactions.
    """
    res = [t for t in env.bank_account.scheduled_transactions]
    return PFIData(data=res, attr="tool:banking")