from typing import Annotated

from pydantic import BaseModel, Field

from functions_runtime import Depends
from langchain_core.tools import tool
from pfi_agent import pfi_tool, PFIData, PFIDataList, PFIDataDict, PFIPluginResult

class Message(BaseModel):
    sender: str = Field(..., title="Sender of the message")
    recipient: str = Field(..., title="Recipient of the message (either user or a channel)")
    body: str = Field(..., title="Body of the message")

class Channel(BaseModel):
    name: str = Field(..., title="Name of the channel")
    creator: str = Field(default="Unknown", title="Creator of the channel")

class Slack(BaseModel):
    users: list[str] = Field(..., title="List of users in the slack")
    user_email: dict[str, str] = Field(..., title="Email of each user")
    channels: list[Channel] = Field(..., title="List of channels in the slack")
    user_channels: dict[str, list[str]] = Field(..., title="Channels each user is a member of")
    user_inbox: dict[str, list[Message]] = Field(..., title="Inbox of each user")
    channel_inbox: dict[str, list[Message]] = Field(..., title="Inbox of each channel")

class SlackEnvironment(BaseModel):
    slack: Slack

slack = Slack(users=[], user_email={}, channels=[], user_channels={}, user_inbox={}, channel_inbox={})

# env
env = SlackEnvironment(slack=slack)

@pfi_tool
def get_channels() -> PFIPluginResult:
    """Get the list of channel names in the slack. """
    res: list[PFIData] = []
    for ch in env.slack.channels:
        res.append(PFIData(data=ch.name, attr="slack:user:"+ch.creator))
    return PFIDataList(data=res)

@pfi_tool
def add_user_to_channel(user: str, channel: str) -> PFIPluginResult:
    """Add a user to a given channel.

    :param user: The user to add to the channel.
    :param channel: The channel to add the user to.
    """
    res = ""
    attr = "tool:slack"
    if user not in env.slack.users:
        res = "ValueError("+f"User not found in the users list"+")"
    else:
        channel_found = False
        for ch in env.slack.channels:
            if ch.name == channel:
                channel_found = True
        if channel_found:
                env.slack.user_channels[user].append(channel)
                res = f"User added to channel."
        else:
            res = "ValueError("+f"Channel not found in the channels list"+")"
    return PFIData(data=res, attr=attr)

@pfi_tool
def read_channel_messages(channel: str) -> PFIPluginResult:
    """Read the messages from the given channel.

    :param channel: The channel to read the messages from.
    """
    for ch in env.slack.channels:
        if ch.name == channel:
            messages = env.slack.channel_inbox.get(channel, [])
            res: list[PFIData] = []
            for msg in messages:
                res.append(PFIData(data=str(msg), attr=f"slack:channel:{channel}"))
            return PFIDataList(data=res)
    return PFIData(data="ValueError("+f"Channel does not exist!"+")", attr="tool:slack")

@pfi_tool
def read_inbox(user: str) -> PFIPluginResult:
    """Read the direct messages from the given user inbox.

    :param user: The user whose inbox to read.
    """
    if user not in env.slack.users:
        return PFIData(data="ValueError("+f"User not found in the users list"+")", attr="tool:slack")
    messages = env.slack.user_inbox.get(user, [])
    res: list[PFIData] = []
    for msg in messages:
        res.append(PFIData(data=str(msg), attr=f"slack:user:{msg.sender}"))
    return PFIDataList(data=res)

@pfi_tool
def send_direct_message(recipient: str, body: str) -> PFIPluginResult:
    """Send a direct message from `author` to `recipient` with the given `content`.

    :param recipient: The recipient of the message.
    :param body: The body of the message.
    """
    sender = "bot"
    if recipient not in env.slack.users:
        return PFIData(data="ValueError("+f"Recipient not found in the users list"+")", attr="tool:slack")

    msg = Message(sender=sender, recipient=recipient, body=body)
    if recipient not in env.slack.user_inbox:
        env.slack.user_inbox[recipient] = []
    env.slack.user_inbox[recipient].append(msg)
    return PFIData(data="Message sent", attr="tool:slack")

@pfi_tool
def send_channel_message(channel: str, body: str) -> PFIPluginResult:
    """Send a channel message from `author` to `channel` with the given `content`.

    :param channel: The channel to send the message to.
    :param body: The body of the message.
    """
    res = ""
    attr = "tool:slack"
    
    sender = "bot"
    channel_found = False
    for ch in env.slack.channels:
        if ch.name == channel:
            channel_found = True
            break
    if not channel_found:
        res = "ValueError("+f"Channel not found in the channels list"+")"
    else:
        msg = Message(sender=sender, recipient=channel, body=body)
        if channel not in env.slack.channel_inbox:
            env.slack.channel_inbox[channel] = []
        env.slack.channel_inbox[channel].append(msg)
        res = "Message sent"
    return PFIData(data=res, attr=attr)

@pfi_tool
def invite_user_to_slack(user: str, user_email: str) -> PFIPluginResult:
    """Invites a user to the Slack workspace.

    :param user: The user to invite.
    :param user_email: The user email where invite should be sent.
    """
    res = ""
    attr = "tool:slack"
    if user in env.slack.users:
        res = "ValueError("+f"User already in the users list"+")"
    else:
        env.slack.users.append(user)
        env.slack.user_inbox[user] = []
        env.slack.user_channels[user] = []
        env.slack.user_email[user] = user_email
        res = f"User {user} invited to Slack"
    return PFIData(data=res, attr=attr)
@pfi_tool
def remove_user_from_slack(user: str) -> PFIPluginResult:
    """Remove a user from the Slack workspace.

    :param user: The user to remove.
    """
    res = ""
    attr = "tool:slack"
    if user not in env.slack.users:
        res = "ValueError("+f"User not found in the users list"+")"
    else:
        env.slack.users.remove(user)
        del env.slack.user_inbox[user]
        del env.slack.user_channels[user]
        res = f"User {user} removed from Slack"
    return PFIData(data=res, attr=attr)

def _get_users_in_channel(channel: str) -> list[str]:
    users = []
    for user, channels in env.slack.user_channels.items():
        if channel in channels:
            users.append(user)
    return users
@pfi_tool
def get_users_in_channel(channel: str) -> PFIPluginResult:
    """Get the list of users in the given channel.

    :param channel: The channel to get the users from.
    """
    channel_found = False
    for ch in env.slack.channels:
        if ch.name == channel:
            channel_found = True
            break
    if not channel_found:
        res = "ValueError("+f"Channel not found in the channels list"+")"
        return PFIData(data=res, attr="tool:slack")
    
    users = _get_users_in_channel(channel)
    return PFIData(data=users, attr="tool:slack")

@pfi_tool
def get_user_count_in_channel(channel: str) -> PFIPluginResult:
    """
    Get the number of users in the given channel.
    
    :param channel: The channel to get the user count from.
    """
    channel_found = False
    for ch in env.slack.channels:
        if ch.name == channel:
            channel_found = True
            break
    if not channel_found:
        res = "ValueError("+f"Channel not found in the channels list"+")"
        return PFIData(data=res, attr="tool:slack")
    return PFIData(data=len(_get_users_in_channel(channel)), attr="tool:slack")

@pfi_tool
def get_users() -> PFIPluginResult:
    """Get the list of users in the slack. """
    return PFIData(data=env.slack.users, attr="tool:slack")
