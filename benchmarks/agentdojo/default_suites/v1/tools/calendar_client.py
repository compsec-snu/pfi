import datetime
from typing import Annotated

from pydantic import BaseModel, EmailStr, model_validator
from typing_extensions import Self

from default_suites.v1.tools.email_client import Inbox, env as email_env
from default_suites.v1.tools.types import CalendarEvent, CalendarEventID, EvenStatus
from functions_runtime import Depends
from langchain_core.tools import tool
from pfi_agent import pfi_tool, PFIData, PFIDataList, PFIDataDict, PFIPluginResult

class Calendar(BaseModel):
    current_day: datetime.date
    account_email: EmailStr
    initial_events: list[CalendarEvent]
    events: dict[CalendarEventID, CalendarEvent] = {}

    @model_validator(mode="after")
    def _create_events(self) -> Self:
        all_ids = [event.id_ for event in self.initial_events]
        if len(all_ids) != len(set(all_ids)):
            duplicate_ids = [id_ for id_ in all_ids if all_ids.count(id_) > 1]
            raise ValueError(f"Event IDs must be unique.")
        self.events = {event.id_: event for event in self.initial_events}
        return self

    def _get_next_id(self) -> CalendarEventID:
        largest_id = max((int(key) for key in self.events.keys()), default=0)
        return CalendarEventID(largest_id + 1)

    def get_by_day(self, day: datetime.date) -> list[CalendarEvent]:
        return [event for event in self.events.values() if event.start_time.date() == day]

    def create_event(
        self,
        title: str,
        description: str,
        start_time: datetime.datetime,
        end_time: datetime.datetime,
        location: str | None,
        participants: list[EmailStr],
    ) -> CalendarEvent:
        id_ = self._get_next_id()
        participants.append(self.account_email)
        participants = list(set(participants))
        event = CalendarEvent(
            title=title,
            description=description,
            start_time=start_time,
            end_time=end_time,
            location=location,
            participants=participants,
            id_=id_,
            creator="emma.johnson@bluesparrowtech.com"
        )
        self.events[id_] = event
        return event

    def cancel_event(self, event_id: CalendarEventID) -> None:
        if event_id not in self.events:
            raise ValueError(f"Event with given ID not found.")
        self.events[event_id].status = EvenStatus.canceled
        email_env.inbox.send_email(
            self.events[event_id].participants,
            f"Canceled: '{self.events[event_id].title}'",
            "The event has been canceled.",
            attachments=[self.events[event_id]],
        )

    def search_events(self, query: str, date: datetime.date | None = None) -> list[CalendarEvent]:
        if date is not None:
            events = self.get_by_day(date)
        else:
            events = self.events.values()
        return [
            event
            for event in events
            if query.lower() in event.title.lower() or query.lower() in event.description.lower()
        ]

    def day_has_conflicts(self, day: datetime.date) -> bool:
        events = self.get_by_day(day)
        for i, event in enumerate(events):
            for other_event in events[i + 1 :]:
                if (
                    event.start_time <= other_event.start_time < event.end_time
                    or event.start_time < other_event.end_time <= event.end_time
                ):
                    return True
        return False

    def reschedule_event(
        self,
        event_id: CalendarEventID,
        new_start_time: datetime.datetime,
        new_end_time: datetime.datetime | None = None,
    ) -> CalendarEvent:
        if event_id not in self.events:
            raise ValueError(f"Event with given ID not found.")
        event = self.events[event_id]
        event.start_time = new_start_time
        if new_end_time is not None:
            event.end_time = new_end_time
        else:
            event.end_time = new_start_time + (event.end_time - event.start_time)
        start_date = event.start_time.date().isoformat()
        start_time = event.start_time.time().isoformat()
        end_date = event.end_time.date().isoformat()
        end_time = event.end_time.time().isoformat()
        body = f"The event has been rescheduled. It will start on  {start_date} at {start_time} and end on {end_date} at {end_time}."
        email_env.inbox.send_email(
            event.participants,
            subject="Rescheduled: '{event.title}'",
            body=body,
            attachments=[event],
        )
        return event

    def add_participants(self, event_id: CalendarEventID, participants: list[EmailStr]) -> CalendarEvent:
        if event_id not in self.events:
            raise ValueError(f"Event with given ID not found.")
        event = self.events[event_id]
        event.participants.extend(participants)
        return event

class CalendarEnvironment(BaseModel):
    calendar: Calendar

calendar = Calendar(
    current_day=datetime.date.today(),
    account_email="test@gmail.com",
    initial_events=[],
)

env = CalendarEnvironment(calendar=calendar)

@pfi_tool
def get_day_calendar_events(day: str) -> PFIPluginResult:
    """Returns the appointments for the given `day`. Returns a list of dictionaries with informations about each meeting.

    :param day: The day for which to return the appointments. Must be in format YYYY-MM-DD.
    """
    date = datetime.datetime.strptime(day, "%Y-%m-%d")
    res = [PFIData(data=event, attr="email:"+event.creator) for event in env.calendar.get_by_day(date.date())]
    return PFIDataList(data=res)

@pfi_tool
def create_calendar_event(
    title: str,
    start_time: str,
    end_time: str,
    description: str = "",
    participants: list[str] = None,
    location: str = None,
) -> PFIPluginResult:
    """Creates a new calendar event with the given details and adds it to the calendar.
    It also sends an email to the participants with the event details.

    :param title: The title of the event.
    :param start_time: The start time of the event. Must be in format YYYY-MM-DD HH:MM.
    :param end_time: The end time of the event. Must be in format YYYY-MM-DD HH:MM.
    :param description: The description of the event.
    :param participants: The list of participants' email addresses. If `None`, no participants are set. The calendar owner's email address is always included..
    :param location: The location of the event. If `None`, no location is set.
    """
    parsed_start_time = datetime.datetime.strptime(start_time, "%Y-%m-%d %H:%M")
    parsed_end_time = datetime.datetime.strptime(end_time, "%Y-%m-%d %H:%M")
    if participants is None:
        participants = []
    new_event = env.calendar.create_event(title, description, parsed_start_time, parsed_end_time, location, participants)
    email_env.inbox.send_email(
        recipients=participants,
        subject=f"Invitation: {title}",
        body=description,
        attachments=[new_event],
    )
    return PFIData(data=new_event, attr="email:"+new_event.creator)

@pfi_tool
def search_calendar_events(
    query: str,
    date: str | None = None,
) -> PFIPluginResult:
    """Searches calendar events that match the given query in the tile or the description.
    If provided, filters events by date.
    Returns a list of event dictionaries with the title, description, start time, end time, location, participants, and id.

    :param query: The query string to search for in event titles and descriptions.
    :param date: The date for which to search events. Must be in format YYYY-MM-DD. If `null`, searches all events.
    """
    if date is not None:
        date_ = datetime.datetime.strptime(date, "%Y-%m-%d").date()
    else:
        date_ = None
    matches = env.calendar.search_events(query, date_)
    if len(matches) == 0:
        raise ValueError("No events found. Try with a different query.")
    matches = [PFIData(data=match, attr="email:"+match.creator) for match in matches]
    return PFIDataList(data=matches)

@pfi_tool
def get_current_day() -> PFIPluginResult:
    """Returns the current day in ISO format, e.g. '2024-01-01'.
    It is useful to know what the current day, year, or month is, as the assistant
    should not assume what the current date is."""
    return PFIData(data=env.calendar.current_day.isoformat(), attr="tool:calendar")

@pfi_tool
def cancel_calendar_event(event_id: str) -> PFIPluginResult:
    """Cancels the event with the given `event_id`. The event will be marked as canceled and no longer appear in the calendar.
    It will also send an email to the participants notifying them of the cancellation.

    :param event_id: The ID of the event to cancel.
    """
    env.calendar.cancel_event(CalendarEventID(event_id))
    return PFIData(data=f"Event {event_id} has been canceled and participants have been notified.", attr="tool:calendar")

@pfi_tool
def reschedule_calendar_event(
    event_id: str,
    new_start_time: str,
    new_end_time: str | None = None,
) -> PFIPluginResult:
    """Reschedules the event with the given `event_id` to the new start and end times.
    It will also send an email to the participants notifying them of the rescheduling.

    :param event_id: The ID of the event to reschedule.
    :param new_start_time: The new start time of the event. Must be in format YYYY-MM-DD HH:MM.
    :param new_end_time: The new end time of the event. Must be in format YYYY-MM-DD HH:MM.
    If `null`, the end time will be computed based on the new start time to keep the event duration the same.
    """
    original_event = env.calendar.events[CalendarEventID(event_id)]
    
    if new_end_time is not None:
        parsed_new_end_time = datetime.datetime.strptime(new_end_time, "%Y-%m-%d %H:%M")
    else:
        original_duration = original_event.end_time - original_event.start_time
        parsed_new_end_time = datetime.datetime.strptime(new_start_time, "%Y-%m-%d %H:%M") + original_duration
    calendar_event = env.calendar.reschedule_event(
        CalendarEventID(event_id),
        datetime.datetime.strptime(new_start_time, "%Y-%m-%d %H:%M"),
        parsed_new_end_time,
    )
    res = f"Event {event_id} has been rescheduled and participants have been notified."
    return PFIData(data=res, attr="tool:calendar")
    # return PFIData(data=calendar_event, attr=calendar_event.creator)

@pfi_tool
def add_calendar_event_participants(
    event_id: str,
    participants: list[str],
) -> PFIPluginResult:
    """Adds the given `participants` to the event with the given `event_id`.
    It will also email the new participants notifying them of the event.

    :param event_id: The ID of the event to add participants to.
    :param participants: The list of participants' email addresses to add to the event.
    """
    calendar_event = env.calendar.add_participants(CalendarEventID(event_id), participants)
    res = f"Participants have been added to event {event_id}."
    return PFIData(data=res, attr="tool:calendar")
    # return PFIData(data=calendar_event, attr=calendar_event.creator)
