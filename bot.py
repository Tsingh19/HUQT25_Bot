import requests
import json
import time

# API Configuration
API_KEY = "d5780721-c5f4-41f9-9bad-fa775d82c090"
ACCOUNT = "NAF"
SYMBOL = "LOAN"
API_URL = "https://huqt-oracle-exchange.fly.dev"

BUY_PRICE = 101  # 0.98 USD in cents
SELL_PRICE = 102  # 1.02 USD in cents
ORDER_SIZE = 10000  # 75,000 shares
ORDER_THRESHOLD = 5000  # Minimum order amount before placing new ones


# Function to get open orders
def get_open_orders():
    """Fetches open orders for the account."""
    url = f"{API_URL}/exchanges/open_orders"
    params = {"apiKey": API_KEY, "account": ACCOUNT, "symbol": SYMBOL}
    response = requests.get(url, params=params)

    if response.status_code == 200:
        return response.json()  # Returns list of open orders
    else:
        print(f"Error fetching open orders: {response.text}")
        return []


# Function to place an order
def place_order(side, price, size):
    """Places a buy or sell order."""
    url = f"{API_URL}/exchanges/add_order"
    data = {
        "apiKey": API_KEY,
        "symbol": SYMBOL,
        "price": price,
        "size": size,
        "side": side,
        "account": ACCOUNT,
        "tif": "Day",
    }

    response = requests.post(url, json=data)
    result = response.json()

    if result.get("status") == "Ack":
        print(f"{side} Order Placed: {size} @ {price/100:.2f}")
    else:
        print(f"Order Error ({side}): {result.get('msg')}")


# Function to check and refresh orders
def manage_orders():
    while True:
        open_orders = get_open_orders()

        buy_orders = sum(o["size"] for o in open_orders if o["side"] == "Buy")
        sell_orders = sum(o["size"] for o in open_orders if o["side"] == "Sell")

        print(f"Current Buy Orders: {buy_orders}, Current Sell Orders: {sell_orders}")

        # If total buy orders are less than threshold, place a buy order
        if buy_orders < ORDER_THRESHOLD:
            place_order("Buy", BUY_PRICE, ORDER_SIZE)

        # If total sell orders are less than threshold, place a sell order
        if sell_orders < ORDER_THRESHOLD:
            place_order("Sell", SELL_PRICE, ORDER_SIZE)

        # Wait 5 seconds before checking again
        time.sleep(3)


# Run the order management loop
if __name__ == "__main__":
    manage_orders()
