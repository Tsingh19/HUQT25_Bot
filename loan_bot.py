import socketio
import threading
import time
import requests

# API Credentials
API_KEY = "d5767133-59df-4030-b6fb-4b1ae6eb97c3"
ACCOUNT_ID = "NAF"
WS_URL = "wss://huqt-oracle-exchange.fly.dev"
CANCEL_API_URL = "https://huqt-oracle-exchange.fly.dev/exchanges/cancel_order"
# API URL for order placement and cancellation
ORDER_API_URL = "https://huqt-oracle-exchange.fly.dev/exchanges/add_order"

# Create a single global Socket.IO client
sio = socketio.Client()

# Global Data Stores
latest_position = {}
latest_orders = {}
latest_order_book = {}
latest_trades = []

# Flags to track data updates
data_received = {"position": False, "orders": False, "order_book": False, "trades": False}

# Asset to listen for
WATCHED_ASSET = "LOAN"

@sio.event
def connect():
    """Authenticate after connecting and request data only for the specified asset."""
    print("Connected to WebSocket.")
    sio.emit("authenticate_socket", {"apiKey": API_KEY, "account": ACCOUNT_ID})
    sio.emit("position_update", {})  # Request positions
    sio.emit("open_orders_update", {})  # Request open orders
    sio.emit("md_update", {"symbol": WATCHED_ASSET})  # Request market data only for the specified asset

@sio.event
def position_update(data):
    """Handles position updates and updates global variable only for the specified asset."""
    global latest_position
    if isinstance(data, list):
        latest_position = {pos["symbol"]: pos for pos in data if pos["symbol"] == WATCHED_ASSET}
        data_received["position"] = True

@sio.event
def open_orders_update(data):
    """Handles open order updates and updates global variable only for the specified asset."""
    global latest_orders
    if isinstance(data, dict):
        latest_orders = {symbol: orders for symbol, orders in data.items() if symbol == WATCHED_ASSET}
        data_received["orders"] = True

@sio.event
def md_update(data):
    """Handles market data updates only for the specified asset."""
    global latest_order_book, latest_trades
    if isinstance(data, dict) and data.get("symbol") == WATCHED_ASSET:
        if "book" in data:
            latest_order_book = data["book"]
            data_received["order_book"] = True
        if "tape" in data:
            latest_trades = data["tape"]
            data_received["trades"] = True

@sio.event
def disconnect():
    """Handles disconnection."""
    print("Disconnected from WebSocket.")

def start_websocket_listener():
    """Runs the WebSocket listener in a separate thread."""
    while True:
        try:
            sio.connect(WS_URL)
            sio.wait()
        except Exception as e:
            print("WebSocket error:", e)
        finally:
            sio.sleep(5)

# Start WebSocket listener in a background thread
listener_thread = threading.Thread(target=start_websocket_listener, daemon=True)
listener_thread.start()

# Utility function to wait for data
def wait_for_data(key):
    """Waits until the specified data type is received."""
    while not data_received[key]:
        time.sleep(0.1)

# Function to filter non-user orders using open orders
def filter_non_user_orders(order_book):
    """Filters out orders in the order book that belong to the user using open orders."""
    wait_for_data("orders")
    user_orders = {(order["price"], order["size"]) for order in latest_orders.get(WATCHED_ASSET, [])}
    
    bids, asks = order_book if isinstance(order_book, list) and len(order_book) == 2 else ([], [])
    
    non_user_bids = [order for order in bids if (order.get("price"), order.get("size")) not in user_orders]
    non_user_asks = [order for order in asks if (order.get("price"), order.get("size")) not in user_orders]
    
    return non_user_bids, non_user_asks

# Functions to Access Stored Data
def get_position_for_asset(asset):
    if asset != WATCHED_ASSET:
        return None
    wait_for_data("position")
    return latest_position.get(asset, None)

def get_open_orders_for_asset(asset):
    if asset != WATCHED_ASSET:
        return []
    wait_for_data("orders")
    return latest_orders.get(asset, [])

def get_most_competitive_orders(asset):
    """Finds the highest bid and lowest ask for a given asset using non-user orders."""
    if asset != WATCHED_ASSET:
        return {"best_bid": None, "best_ask": None}
    wait_for_data("order_book")
    
    non_user_bids, non_user_asks = filter_non_user_orders(latest_order_book)
    
    best_bid = max(non_user_bids, key=lambda x: x.get("price", float("-inf")), default=None)
    best_ask = min(non_user_asks, key=lambda x: x.get("price", float("inf")), default=None)
    
    return {"best_bid": best_bid, "best_ask": best_ask}

def get_recent_trades(asset):
    if asset != WATCHED_ASSET:
        return []
    wait_for_data("trades")
    return [trade for trade in latest_trades if trade["symbol"] == asset]

def get_total_order_size_for_asset(asset, side):
    if asset != WATCHED_ASSET:
        return 0
    wait_for_data("orders")
    side = side.lower()
    open_orders = get_open_orders_for_asset(asset)
    return sum(order.get("size", 0) for order in open_orders if order.get("side", "").lower() == side)

def cancel_orders_for_asset_side(asset, side):
    if asset != WATCHED_ASSET:
        return
    wait_for_data("orders")
    side = side.lower()
    while True:
        open_orders = get_open_orders_for_asset(asset)
        matching_orders = [order for order in open_orders if order["side"].lower() == side]
        if not matching_orders:
            break
        for order in matching_orders:
            order_id = order["id"]
            if order_id:
                requests.post(CANCEL_API_URL, json={"apiKey": API_KEY, "account": ACCOUNT_ID, "orderId": order_id})
        time.sleep(0.01)

def cancel_half_orders(asset, side):
    if asset != WATCHED_ASSET:
        return
    wait_for_data("orders")
    side = side.lower()
    open_orders = get_open_orders_for_asset(asset)
    
    matching_orders = sorted(
        [order for order in open_orders if order["side"].lower() == side],
        key=lambda x: x["price"],
        reverse=(side == "sell")  # Higher price first for sells, lower price first for buys
    )
    
    total_size = sum(order["size"] for order in matching_orders)
    target_cancel_size = total_size / 2  # Cancel half of the total order size
    canceled_size = 0
    
    for order in matching_orders:
        if canceled_size >= target_cancel_size:
            break
        order_id = order["id"]
        if order_id:
            requests.post(CANCEL_API_URL, json={"apiKey": API_KEY, "account": ACCOUNT_ID, "orderId": order_id})
            canceled_size += order["size"]
            time.sleep(0.01)

def get_weighted_avg_trade_price(asset):
    if asset != WATCHED_ASSET:
        return None
    wait_for_data("trades")
    trades = get_recent_trades(asset)
    total_value = sum(trade["price"] * trade["size"] for trade in trades if "price" in trade and "size" in trade)
    total_size = sum(trade["size"] for trade in trades if "size" in trade)
    return total_value / total_size if total_size > 0 else None

def place_order(asset, price, size, side, tif="Day"):
    payload = {
        "apiKey": API_KEY,
        "account": ACCOUNT_ID,
        "symbol": asset,
        "price": price,
        "size": size,
        "side": side.capitalize(),  # Ensure correct casing
        "tif": tif  # "Day" or "IOC"
    }
    response = requests.post(ORDER_API_URL, json=payload)
    
    try:
        response_data = response.json()
        print(f"[ORDER RESPONSE] {response_data}")
        return response_data
    except Exception as e:
        print(f"[ERROR] Failed to parse response: {e}")
        return {"status": "error", "msg": "Invalid response format"}

import time
import requests
import random

# Replace with your actual API key and account name
API_KEY = "d5767133-59df-4030-b6fb-4b1ae6eb97c3"
ACCOUNT_ID = "NAF"

# Trading Parameters
BUY_POSITION_THRESHOLD = 100000  # Maximum allowed buy position
SELL_POSITION_THRESHOLD = 100000  # Maximum allowed sell position
BUY_OPEN_ORDERS_THRESHOLD = 100000  # Maximum allowed buy open orders
SELL_OPEN_ORDERS_THRESHOLD = 100000  # Maximum allowed sell open orders
BUY_REENTRY_THRESHOLD = 100000  # Threshold at which we can start buying again after stopping
SELL_REENTRY_THRESHOLD = 100000  # Threshold at which we can start selling again after stopping
ORDER_SIZE = 100000  # Default order size
DEFAULT_BID_PRICE = 99  # Default bid price if no bids are present
DEFAULT_ASK_PRICE = 105  # Default ask price if no asks are present
collaboration_deviate_rate = 0
defection_deviate_rate = 0.01


# Market state flags
buy_halted = False
sell_halted = False
buy_collaboration = False
sell_collaboration = False

# Market Maker Function
def market_maker(asset):
    """Market-making bot that undercuts the most competitive price and manages risk."""
    global buy_halted, sell_halted
    global buy_collaboration, sell_collaboration
    
    my_prev_buy_price = None
    my_prev_sell_price = None
    
    cancel_orders_for_asset_side(asset, "buy")
    cancel_orders_for_asset_side(asset, "sell")
    
    while True:
        print("\n[INFO] Fetching market data...")

        competitive_orders = get_most_competitive_orders(asset)
        best_bid = competitive_orders.get("best_bid")
        best_ask = competitive_orders.get("best_ask")
        
        if not best_bid:
            best_bid = {"price": DEFAULT_BID_PRICE}  # Set default bid price if order book is empty
        if not best_ask:
            best_ask = {"price": DEFAULT_ASK_PRICE}  # Set default ask price if order book is empty
        
        print(f"[MARKET] Best Bid: {best_bid}, Best Ask: {best_ask}")
        
        curr_market_buy_price = best_bid["price"]
        curr_market_sell_price = best_ask["price"]
        
        my_best_bid = max([order["price"] for order in get_open_orders_for_asset(asset) if order["side"] == "buy"], default=None)
        my_best_ask = min([order["price"] for order in get_open_orders_for_asset(asset) if order["side"] == "sell"], default=None)

        if my_best_bid == None:
            if buy_collaboration == True:
                my_best_bid = curr_market_buy_price
                buy_collaboration = True
            else:
                my_best_bid = curr_market_buy_price + 1
                buy_collaboration = False

        if my_best_ask == None:
            if sell_collaboration == True:
                my_best_ask = curr_market_buy_price
                sell_collaboration = True
            else:
                my_best_ask = curr_market_sell_price - 1
                sell_collaboration = False
        
        if my_prev_buy_price != None:
            if my_prev_buy_price == curr_market_buy_price:
                random_number = random.uniform(0, 1)
                if random_number < defection_deviate_rate:
                    my_best_bid = curr_market_buy_price + 1
                    buy_collaboration = False
                else:
                    my_best_bid = curr_market_buy_price
                    buy_collaboration = True
            else:
                random_number = random.uniform(0, 1)
                if random_number < collaboration_deviate_rate:
                    my_best_bid = curr_market_buy_price
                else:
                    my_best_bid = curr_market_buy_price + 1
                buy_collaboration = False
        
        if my_prev_sell_price != None:
            if my_prev_sell_price == curr_market_sell_price:
                random_number = random.uniform(0, 1)
                if random_number < defection_deviate_rate:
                    my_best_ask = curr_market_sell_price - 1
                    sell_collaboration = False
                else:
                    my_best_ask = curr_market_sell_price
                    sell_collaboration = True
            else:
                random_number = random.uniform(0, 1)
                if random_number < collaboration_deviate_rate:
                    my_best_ask = curr_market_sell_price
                else:
                    my_best_ask = curr_market_sell_price - 1
                sell_collaboration = False
        
        if my_best_bid >= my_best_ask:
            my_best_bid = curr_market_buy_price
            my_best_ask = curr_market_sell_price
        
        if my_best_bid <= DEFAULT_BID_PRICE:
            my_best_bid = DEFAULT_BID_PRICE + 1
        if my_best_ask >= DEFAULT_ASK_PRICE:
            my_best_ask = DEFAULT_ASK_PRICE - 1
            
            
        print(f"[TRADING] Collaboration for Buying: {buy_collaboration}, Collaboration for Selling: {sell_collaboration}")
        
        print(f"[TRADING] Adjusted Buy Price: {my_best_bid}, Adjusted Sell Price: {my_best_ask}")
        
        weighted_price = get_weighted_avg_trade_price(asset)
        print(f"[TRADING] Weighted Price: {weighted_price}")
        
        position_data = get_position_for_asset(asset)
        current_position = position_data["position"] if position_data else 0
        print(f"[POSITION] Current Position: {current_position}")

        total_buy_open_orders = get_total_order_size_for_asset(asset, "buy")
        total_sell_open_orders = get_total_order_size_for_asset(asset, "sell")
        print(f"[ORDERS] Open Buy Orders: {total_buy_open_orders}, Open Sell Orders: {total_sell_open_orders}")
        
        open_orders = get_open_orders_for_asset(asset)

        # Get highest buy price and lowest sell price
        my_prev_buy_price = max(
            [order["price"] for order in open_orders if order["side"] == "buy"], 
            default=None
        )
        my_prev_sell_price = min(
            [order["price"] for order in open_orders if order["side"] == "sell"], 
            default=None
        )
        
        # Check if buy threshold has been hit
        if current_position >= BUY_POSITION_THRESHOLD:
            buy_halted = True
        if current_position <= BUY_REENTRY_THRESHOLD:
            buy_halted = False
        
        # Check if sell threshold has been hit
        if current_position <= -SELL_POSITION_THRESHOLD:
            sell_halted = True
        if current_position >= SELL_REENTRY_THRESHOLD:
            sell_halted = False
        
        time.sleep(0.1)
        
        if (
            not buy_halted and
            current_position < BUY_POSITION_THRESHOLD and
            my_best_bid < weighted_price
        ):
            if my_best_bid == my_prev_buy_price:
                if total_buy_open_orders != ORDER_SIZE and (current_position + total_buy_open_orders != BUY_POSITION_THRESHOLD):
                    print("[ACTION] Refilling BUY order...")
                    place_order(asset, my_best_bid, min(ORDER_SIZE - total_buy_open_orders, BUY_POSITION_THRESHOLD - current_position - total_buy_open_orders), "buy")
            else:
                my_prev_buy_price = my_best_bid
                print("[ACTION] Placing new BUY order...")
                cancel_orders_for_asset_side(asset, "buy")
                place_order(asset, my_best_bid, min(ORDER_SIZE, BUY_POSITION_THRESHOLD - current_position), "buy")
        else:
            my_prev_buy_price = None
            cancel_orders_for_asset_side(asset, "buy")
            print("[SKIP] Buy order not placed due to position, open order limits, or halted state.")
        
        time.sleep(0.1)
        
        if (
            not sell_halted and
            current_position > -SELL_POSITION_THRESHOLD and
            my_best_ask > weighted_price
        ):
            if my_best_ask == my_prev_sell_price:
                if total_sell_open_orders != ORDER_SIZE and (-current_position + total_sell_open_orders != SELL_POSITION_THRESHOLD):
                    print("[ACTION] Refilling SELL order...")
                    place_order(asset, my_best_ask, min(ORDER_SIZE - total_sell_open_orders, SELL_POSITION_THRESHOLD + current_position - total_sell_open_orders), "sell")
            else:
                my_prev_sell_price = my_best_ask
                print("[ACTION] Placing new SELL order...")
                cancel_orders_for_asset_side(asset, "sell")
                place_order(asset, my_best_ask, min(ORDER_SIZE, SELL_POSITION_THRESHOLD + current_position), "sell")
        else:
            my_prev_sell_price = None
            cancel_orders_for_asset_side(asset, "sell")
            print("[SKIP] Sell order not placed due to position, open order limits, or halted state.")
        
        time.sleep(0.1)
        
# Example usage:
market_maker("LOAN")