from typing import Annotated

from pydantic import BaseModel, Field

from functions_runtime import Depends
from langchain_core.tools import tool
from pfi_agent import pfi_tool, PFIData, PFIDataList, PFIDataDict, PFIPluginResult

class UserAccount(BaseModel):
    """
    Represents a simple user account.
    """

    first_name: str = Field(..., title="First name of the user")
    last_name: str = Field(..., title="Last name of the user")
    street: str = Field(..., title="Street of the user")
    city: str = Field(..., title="City of the user")
    password: str = Field(..., title="Password of the user")

class UserAccountEnvironment(BaseModel):
    user_account: UserAccount

account = UserAccount(first_name="John", last_name="Doe", street="123 Main St", city="Springfield", password="password")
env = UserAccountEnvironment(user_account=account)

@pfi_tool
def get_user_info() -> PFIPluginResult:
    """
    Get the user information.
    """
    res = {
        "first_name": env.user_account.first_name,
        "last_name": env.user_account.last_name,
        "street": env.user_account.street,
        "city": env.user_account.city,
    }
    return PFIData(data=res, attr="user")

@pfi_tool
def update_password(password: str) -> PFIPluginResult:
    """
    Update the user password.

    :param password: New password for the user
    """
    env.user_account.password = password
    return PFIData(data="Password updated", attr="tool:user_account")

@pfi_tool
def update_user_info(
    first_name: str | None = None,
    last_name: str | None = None,
    street: str | None = None,
    city: str | None = None,
) -> PFIPluginResult:
    """
    Update the user information.

    :param first_name: First name of the user (optional)
    :param last_name: Last name of the user (optional)
    :param street: Street of the user (optional)
    :param city: City of the user (optional)
    """
    if first_name:
        env.user_account.first_name = first_name
    if last_name:
        env.user_account.last_name = last_name
    if street:
        env.user_account.street = street
    if city:
        env.user_account.city = city

    res = {
        "first_name": env.user_account.first_name,
        "last_name": env.user_account.last_name,
        "street": env.user_account.street,
        "city": env.user_account.city,
    }
    return PFIData(data=res, attr="user")