import datetime
from typing import Annotated

from pydantic import BaseModel

from functions_runtime import Depends
from strenum import StrEnum
from langchain_core.tools import tool
from pfi_agent import pfi_tool, PFIData, PFIDataList, PFIDataDict, PFIPluginResult


class ReservationType(StrEnum):
    HOTEL = "hotel"
    CAR = "car"
    RESTAURANT = "restaurant"

# Attr: user
class User(BaseModel):
    first_name: str
    last_name: str
    ID_number: str
    email: str
    phone_number: str
    address: str
    passport_number: str
    bank_account_number: str
    credit_card_number: str

# Attr: reviews: unknown, others: tool:travel
class Hotel(BaseModel):
    name: str
    city: str
    rating: float
    price_min: float
    price_max: float
    address: str
    reviews: list


class Hotels(BaseModel):
    hotel_list: list[Hotel]

    def get_all_hotels_in_city(self, city: str) -> list[Hotel]:
        return [hotel for hotel in self.hotel_list if hotel.city == city]

# Attr: tool:travel
class Flight(BaseModel):
    airline: str
    flight_number: str
    departure_city: str
    arrival_city: str
    departure_time: datetime.datetime
    arrival_time: datetime.datetime
    price: float
    contact_information: str


class Flights(BaseModel):
    flight_list: list[Flight]

# Attr: tool:travel
class Reservation(BaseModel):
    reservation_type: ReservationType | None
    title: str
    start_time: datetime.datetime
    end_time: datetime.datetime
    contact_information: str

# Attr: reviews: unknown, others: tool:travel
class Restaurant(BaseModel):
    name: str
    city: str
    address: str
    rating: float
    price_per_person: float
    operating_hours: str
    reviews: list
    contact_information: str
    cuisine_type: str  # could be: Italian, Chinese, Indian, Japanese
    dietary_restrictions: str  # could be: Vegetarian, Vegan, Gluten-free, Dairy-free


class Restaurants(BaseModel):
    restaurant_list: list[Restaurant]

# Attr: reviews: unknown, others: tool:travel
class CarRentalCompany(BaseModel):
    name: str
    city: str
    address: str
    rating: float
    price_per_day: float
    reviews: list
    contact_information: str
    car_types_available: list  # could be: Sedan, SUV, Convertible, Truck
    fuel_options: list  # could be: Regular, Premium, Electric


class CarRental(BaseModel):
    company_list: list[CarRentalCompany]

class Travel(BaseModel):
    hotels: Hotels
    flights: Flights
    restaurants: Restaurants
    car_rental: CarRental
    reservation: Reservation
    user: User

class TravelEnvironment(BaseModel):
    hotels: Hotels
    flights: Flights
    restaurants: Restaurants
    car_rental: CarRental
    reservation: Reservation
    user: User


env = TravelEnvironment(
    hotels=Hotels(hotel_list=[]),
    flights=Flights(flight_list=[]),
    restaurants=Restaurants(restaurant_list=[]),
    car_rental=CarRental(company_list=[]),
    reservation=Reservation(reservation_type=None, title="", start_time=datetime.datetime.now(), end_time=datetime.datetime.now(), contact_information=""),
    user=User(first_name="", last_name="", ID_number="", email="", phone_number="", address="", passport_number="", bank_account_number="", credit_card_number="")
)

# env = TravelEnvironment(travel=travel)

# note: for user

@pfi_tool
def get_user_information() -> PFIPluginResult:
    """Get the user information, could be: first name, last name, ID number, email, phone number, address, passport number, bank account number, credit card number. These information are used for booking hotels, restaurants, car rentals, and flights."""
    res = {
        "First Name": env.user.first_name,
        "Last Name": env.user.last_name,
        "ID Number": env.user.ID_number,
        "Email": env.user.email,
        "Phone Number": env.user.phone_number,
        "Address": env.user.address,
        "Passport Number": env.user.passport_number,
        "Bank Account Number": env.user.bank_account_number,
        "Credit Card Number": env.user.credit_card_number,
    }
    return PFIData(data=res, attr="user")



# note: for hotel

@pfi_tool
def get_all_hotels_in_city(city: str) -> PFIPluginResult:
    """Get all hotels in the given city.
    :param city: The city to get hotels from.
    """
    hotel_names = [hotel.name for hotel in env.hotels.hotel_list if hotel.city == city]
    hotel_names = "Hotel Names: " + "\n".join(hotel_names) + "\n"
    return PFIData(data=hotel_names, attr="tool:travel")

@pfi_tool
def get_hotels_prices(hotel_names: list[str]) -> PFIPluginResult:
    """Get all hotels within the given budget, should be within the price range.
    :param hotel_names: The name of the hotel to get the price range for.
    """
    res = {
        hotel.name: f"Price range: {hotel.price_min} - {hotel.price_max}"
        for hotel in env.hotels.hotel_list
        if hotel.name in hotel_names
    }
    return PFIData(data=res, attr="tool:travel")

@pfi_tool
def get_hotels_address(hotel_name: str) -> PFIPluginResult:
    """Get the address of the given hotel.
    :param hotel_name: The name of the hotel to get the address for.
    """
    res = {hotel.name: hotel.address for hotel in env.hotels.hotel_list if hotel.name == hotel_name}
    return PFIData(data=res, attr="tool:travel")

# @pfi_tool
# def get_rating_reviews_for_hotels(hotel_names: list[str]) -> PFIPluginResult:
#     """Get the rating and reviews for the given hotels.
#     :param hotel_names: The names of the hotels to get reviews for.
#     """
#     res = {
#         hotel.name: PFIData(data="Rating: " + str(hotel.rating) + "\n" + "Reviews: " + "\n".join(hotel.reviews), attr = "unknown")
#         for hotel in env.hotels.hotel_list
#         if hotel.name in hotel_names
#     }
#     return PFIDataDict(data=res)

@pfi_tool
def get_rating_for_hotels(hotel_names: list[str]) -> PFIPluginResult:
    """Get the rating for the given hotels.
    :param hotel_names: The names of the hotels to get ratings for.
    """
    res = {
        hotel.name: "Rating: " + str(hotel.rating)
        for hotel in env.hotels.hotel_list
        if hotel.name in hotel_names
    }
    return PFIData(data=res, attr="tool:travel")

@pfi_tool
def get_reviews_for_hotels(hotel_names: list[str]) -> PFIPluginResult:
    """Get the reviews for the given hotels.
    :param hotel_names: The names of the hotels to get reviews for.
    """
    res = {
        hotel.name: PFIData(data="Reviews: " + "\n".join(hotel.reviews), attr="unknown")
        for hotel in env.hotels.hotel_list
        if hotel.name in hotel_names
    }
    return PFIDataDict(data=res)

# note: for restaurant

@pfi_tool
def get_all_restaurants_in_city(city: str) -> PFIPluginResult:
    """Get all restaurants in the given city.
    :param city: The city to get restaurants from.
    """
    restaurant_names = [restaurant.name for restaurant in env.restaurants.restaurant_list if restaurant.city == city]
    restaurant_names = "Restaurant in " + city + ": " + "\n".join(restaurant_names) + "\n"
    return PFIData(data=restaurant_names, attr="tool:travel")

@pfi_tool
def get_restaurants_address(
    restaurant_names: list[str],
) -> PFIPluginResult:
    """Get the address of the given restaurants.
    :param restaurant_names: The name of the restaurant to get the address for.
    """
    address = {
        restaurant.name: restaurant.address
        for restaurant in env.restaurants.restaurant_list
        if restaurant.name in restaurant_names
    }

    return PFIData(data=address, attr="tool:travel")

# @pfi_tool
# def get_rating_reviews_for_restaurants(
#     restaurant_names: list[str],
# ) -> PFIPluginResult:
#     """Get the rating and reviews for the given restaurants.
#     :param restaurant_names: The names of the restaurants to get reviews for.
#     """
#     res = {
#         restaurant.name: PFIData(data="Rating: " + str(restaurant.rating) + "\n" + "Reviews: " + "\n".join(restaurant.reviews), attr="unknown")
#         for restaurant in env.restaurants.restaurant_list
#         if restaurant.name in restaurant_names
#     }
#     return PFIDataDict(data=res)

@pfi_tool
def get_rating_for_restaurants(
    restaurant_names: list[str],
) -> PFIPluginResult:
    """Get the rating for the given restaurants.
    :param restaurant_names: The names of the restaurants to get rating for.
    """
    res = {
        restaurant.name: "Rating: " + str(restaurant.rating)
        for restaurant in env.restaurants.restaurant_list
        if restaurant.name in restaurant_names
    }
    return PFIData(data=res, attr="tool:travel")
@pfi_tool
def get_reviews_for_restaurants(
    restaurant_names: list[str],
) -> PFIPluginResult:
    """Get the reviews for the given restaurants.
    :param restaurant_names: The names of the restaurants to get reviews for.
    """
    res = {
        restaurant.name: PFIData(data="\n".join(restaurant.reviews), attr="unknown")
        for restaurant in env.restaurants.restaurant_list
        if restaurant.name in restaurant_names
    }
    return PFIDataDict(data=res)

@pfi_tool
def get_cuisine_type_for_restaurants(
    restaurant_names: list[str],
) -> PFIPluginResult:
    """Get the cuisine type of the given restaurants, could be: Italian, Chinese, Indian, Japanese.
    :param restaurant_names: The name of restaurants to get the cuisine type for.
    """
    res = {
        restaurant.name: restaurant.cuisine_type
        for restaurant in env.restaurants.restaurant_list
        if restaurant.name in restaurant_names
    }
    return PFIData(data=res, attr="tool:travel")

@pfi_tool
def get_dietary_restrictions_for_all_restaurants(
    restaurant_names: list[str],
) -> PFIPluginResult:
    """Get the dietary restrictions of the given restaurants, could be: Vegetarian, Vegan, Gluten-free, Dairy-free.
    :param restaurant_names: The name of the restaurant to get the dietary restrictions for.
    """
    restaurant_names_ = ", ".join(restaurant_names)
    res = {
        restaurant.name: restaurant.dietary_restrictions
        for restaurant in env.restaurants.restaurant_list
        if restaurant.name in restaurant_names_
    }
    return PFIData(data=res, attr="tool:travel")

@pfi_tool
def get_contact_information_for_restaurants(
    restaurant_names: list[str],
) -> PFIPluginResult:
    """Get the contact information of the given restaurants.
    :param restaurant_names: The name of the restaurant to get the contact information for.
    """
    res = {
        restaurant.name: restaurant.contact_information
        for restaurant in env.restaurants.restaurant_list
        if restaurant.name in restaurant_names
    }
    return PFIData(data=res, attr="tool:travel")

@pfi_tool
def get_price_for_restaurants(
    restaurant_names: list[str],
) -> PFIPluginResult:
    """Get the price per person of the given restaurants.
    :param restaurant_names: The name of the restaurant to get the price per person for.
    """
    res = {
        restaurant.name: restaurant.price_per_person
        for restaurant in env.restaurants.restaurant_list
        if restaurant.name in restaurant_names
    }
    return PFIData(data=res, attr="tool:travel")

@pfi_tool
def check_restaurant_opening_hours(
    restaurant_names: list[str],
) -> PFIPluginResult:
    """Get the openning hours of the given restaurants, check if the restaurant is open.
    :param restaurant_names: The name of the restaurant to get the operating hours for.
    """
    res = {
        restaurant.name: restaurant.operating_hours
        for restaurant in env.restaurants.restaurant_list
        if restaurant.name in restaurant_names
    }
    return PFIData(data=res, attr="tool:travel")


# note: for car rental

@pfi_tool
def get_all_car_rental_companies_in_city(city: str) -> PFIPluginResult:
    """Get all car rental companies in the given city.
    :param city: The city to get car rental companies from.
    """
    company_names = [company.name for company in env.car_rental.company_list if company.city == city]
    company_names = "Car Rental Companies in " + city + ": " + "\n".join(company_names) + "\n"
    return PFIData(data=company_names, attr="tool:travel")

@pfi_tool
def get_car_types_available(company_name: list[str]) -> PFIPluginResult:
    """Get the car types available for the given car rental companies.
    :param company_name: The name of the car rental company to get the car types available for.
    """
    res = {
        company.name: company.car_types_available for company in env.car_rental.company_list if company.name in company_name
    }
    return PFIData(data=res, attr="tool:travel")

# @pfi_tool
# def get_rating_reviews_for_car_rental(company_name: list[str]) -> PFIPluginResult:
#     """Get the rating and reviews for the given car rental companies.
#     :param company_name: The name of the car rental company to get reviews for.
#     """
#     res = {
#         company.name: PFIData(data = "Rating: " + str(company.rating) + "\n" + "Reviews: " + "\n".join(company.reviews), attr="unknown")
#         for company in env.car_rental.company_list
#         if company.name in company_name
#     }
#     return PFIDataDict(data=res)

@pfi_tool
def get_rating_for_car_rental(company_name: list[str]) -> PFIPluginResult:
    """Get the rating for the given car rental companies.
    :param company_name: The name of the car rental company to get rating for.
    """
    res = {
        company.name: "Rating: " + str(company.rating)
        for company in env.car_rental.company_list
        if company.name in company_name
    }
    return PFIData(data=res, attr="tool:travel")

@pfi_tool
def get_reviews_for_car_rental(company_name: list[str]) -> PFIPluginResult:
    """Get the reviews for the given car rental companies.
    :param company_name: The name of the car rental company to get reviews for.
    """
    res = {
        company.name: PFIData(data="\n".join(company.reviews), attr="unknown")
        for company in env.car_rental.company_list
        if company.name in company_name
    }
    return PFIDataDict(data=res)

@pfi_tool
def get_car_rental_address(company_name: list[str]) -> PFIPluginResult:
    """Get the address of the given car rental companies.
    :param company_name: The name of the car rental company to get the address for.
    """
    res = {company.name: company.address for company in env.car_rental.company_list if company.name in company_name}
    return PFIData(data=res, attr="tool:travel")

@pfi_tool
def get_car_fuel_options(company_name: list[str]) -> PFIPluginResult:
    """Get the fuel options of the given car rental companies.
    :param company_name: The name of the car rental company to get the fuel options for.
    """
    res = {company.name: company.fuel_options for company in env.car_rental.company_list if company.name in company_name}
    return PFIData(data=res, attr="tool:travel")

@pfi_tool
def get_car_price_per_day(company_name: list[str]) -> PFIPluginResult:
    """Get the price per day of the given car rental companies.
    :param company_name: The name of the car rental company to get the price per day for.
    """
    res = {company.name: company.price_per_day for company in env.car_rental.company_list if company.name in company_name}
    return PFIData(data=res, attr="tool:travel")

@pfi_tool
def reserve_hotel(
    hotel: str,
    start_day: str,
    end_day: str,
) -> PFIPluginResult:
    """Makes a reservation for a hotel with the provided details..
    :param hotel: Where the reservation is made. It must only be the name of the hotel.
    :param start_day: The check-in day for the hotel. Should be in ISO format 'YYYY-MM-DD'.
    :param end_day: The check-out day for the hotel. Should be in ISO format 'YYYY-MM-DD'.
    """
    env.reservation.contact_information = env.user.phone_number
    env.reservation.reservation_type = ReservationType.HOTEL
    env.reservation.title = hotel
    env.reservation.start_time = datetime.datetime.fromisoformat(start_day)
    env.reservation.end_time = datetime.datetime.fromisoformat(end_day)
    res = f"Reservation for {hotel} from {start_day} to {end_day} has been made successfully."
    return PFIData(data=res, attr="tool:travel")

@pfi_tool
def reserve_restaurant(
    restaurant: str,
    start_time: str,
) -> PFIPluginResult:
    """Makes a reservation for a restaurant with the provided details.

    :param restaurant: Where the reservation is made. It must only be the name of the restaurant.
    :param start_time: The reservation time. Should be in ISO format 'YYYY-MM-DD HH:MM'.
    The end time is automatically set to be two hours after the start of the env.reservation.
    """
    env.reservation.contact_information = env.user.phone_number
    env.reservation.reservation_type = ReservationType.RESTAURANT
    env.reservation.title = restaurant
    env.reservation.start_time = datetime.datetime.fromisoformat(start_time)
    env.reservation.end_time = datetime.datetime.fromisoformat(start_time) + datetime.timedelta(hours=2)
    reservation_date = env.reservation.start_time.date().isoformat()
    start_time = env.reservation.start_time.strftime("%H:%M")
    end_time = env.reservation.end_time.strftime("%H:%M")
    res = f"Reservation for {restaurant} from {start_time} to {end_time} on {reservation_date} has been made successfully."
    return PFIData(data=res, attr="tool:travel")

@pfi_tool
def reserve_car_rental(
    company: str,
    start_time: str,
    end_time: str | None,
) -> PFIPluginResult:
    """Makes a reservation for a car rental with the provided details.

    :param company: Where the reservation is made. It must only be the name of the car rental company.
    :param start_time: The reservation starting time. Should be in ISO format 'YYYY-MM-DD HH:MM'.
    :param end_time: The reservation end time. Should be in ISO format 'YYYY-MM-DD HH:MM'.
    """
    env.reservation.contact_information = env.user.phone_number
    env.reservation.reservation_type = ReservationType.CAR
    env.reservation.title = company
    env.reservation.start_time = datetime.datetime.fromisoformat(start_time)
    env.reservation.end_time = datetime.datetime.fromisoformat(start_time)
    res = f"Reservation for a car at {company} from {start_time} to {end_time} has been made successfully."
    return PFIData(data=res, attr="tool:travel")

@pfi_tool
def get_flight_information(
    departure_city: str,
    arrival_city: str,
) -> PFIPluginResult:
    """Get the flight information from the departure city to the arrival city.
    :param departure_city: The city to depart from.
    :param arrival_city: The city to arrive at.
    """
    flight_info = [
        f"Airline: {flight.airline}, Flight Number: {flight.flight_number}, Departure Time: {flight.departure_time}, Arrival Time: {flight.arrival_time}, Price: {flight.price}, Contact Information: {flight.contact_information}"
        for flight in env.flights.flight_list
        if flight.departure_city == departure_city and flight.arrival_city == arrival_city
    ]
    res = "\n".join(flight_info)
    return PFIData(data=res, attr="tool:travel")