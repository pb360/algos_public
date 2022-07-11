#!/home/paul/miniconda3/envs/algos/bin/python3 -u
# ### imports
#
#
print(20*'----starting script ----\n')
# ### time zone change... this must happen first and utils must be imported first
import os
import time

os.environ['TZ'] = 'UTC'
time.tzset()

# standard imports
import ccxt
import pandas as pd
from twisted.internet import task, reactor  # always keep, swich back and forth between using this
import sys

# local imports
#
#
sys.path.append('/mnt/algos/')
import config

params = config.params
from utils import *

# time the script from start to first trade
START_TIME = time.time()
this_scripts_process_ID = os.getpid()


# ### user input variables
#
#

# ### some are hard set in the script (for now, these are up top)
diff_thresh = 11  # min volume in $ (should be liq...) for order to be placed
mins_short_term_price = 25  # how much of short term prices to keep

# ### most of these should come through machine specific parameters via the portfolio name the systemd file provides
port_name = sys.argv[1]
exchange = params['active_services']['ports'][port_name]['exchange']
data_exchange = params['active_services']['ports'][port_name]['data_exchange']
pairs_traded = params['active_services']['ports'][port_name]['pairs_traded']
account_name = params['active_services']['ports'][port_name]['account_name']
window_sma_short = params['active_services']['ports'][port_name]['window_sma_short']
window_sma_long = params['active_services']['ports'][port_name]['window_sma_long']


#
#
# ### END user input
# ###
# ### API things

# handling various api key formats for different exchanges
if exchange in ['kucoin']:
    passphrase_needed = True 
else:
    passphrase_needed = False

api_key = params['keys'][exchange][account_name]['trade_1']['key']
secret_key = params['keys'][exchange][account_name]['trade_1']['secret']

if passphrase_needed:
    passphrase = params['keys'][exchange][account_name]['trade_1']['passphrase']

# ### create connection client
#
#
if exchange == 'kucoin':
    client = ccxt.kucoin({'apiKey': api_key,
                          'secret': secret_key,
                          'password': passphrase})

elif exchange == 'binance':
    client = ccxt.binance({'apiKey': api_key, 'secret': secret_key})

elif exchange == 'binanceus':
    client = ccxt.binanceus({'apiKey': api_key, 'secret': secret_key})

else:
    print('exchange not supported')
    raise ValueError

# ### Global Variables
#
#
# # constants
#
iter_count = 0  # counter for decision cycles  i.e.   place_order_on_signals()

# params['port_name'] = port_name  # ###PAUL no need to put this here... for now leave out and remove if can
op_sys = params['constants']['os']

# ### utility constants... these should be constant on an exchange basis (for crypto)
prices_dtype_dict = params['data_format'][exchange]['price_name_and_type']
order_filters_names_type_dict = params['data_format'][exchange]['order_filters_name_type']

# ### globals
#
#
prices_dfs_dict = dict()  # {pair: price_df}
short_term_prices_dict = dict()  # {pair: price_df}
last_prices_dict = dict()  # {pair: most_recent_price}

# in order of how derived from prices each is
signal_dfs_dict = dict()  # {pair: signal}  # ###PAUL all vari's standard except this one
actions_dict = dict()  # {pair: one_of --> ['buy_again', 'buy', 'neutural', 'sell', 'sell_again']}

# state of holdings / portfolio
port_value = 0  # total port value (in USD denomination)
port_usd = 0  # USD currently in the portfolio (available for purchasing stuff)
port_allocation_dict = dict()  # prortion value each pair gets - ex: {'BTCUSDT':0.75, 'ETHUSDT':0.25}

# value held (in base asset) ----  formatted:  {'free':free, 'locked':locked, 'total':total}
port_holdings_dict = dict()

# each is structured bag_dict[pair][base, base_in_quote, AND quote]
bag_max_dict = dict()  # max value of port for pair if all in the quote or itself - uses allocation_dict
bag_actual_dict = dict()  # what we really got
bag_desired_dict = dict()  # what we want

order_open_dict = {}  # contains all open orders, backed up live in  ./data/<port_name>/open_orders.csv


# ######### CELL_SPLIT
# ######### CELL_SPLIT CELL_SPLIT CELL_SPLIT ######################################################
# ######### CELL_SPLIT CELL_SPLIT CELL_SPLIT CELL_SPLIT CELL_SPLIT CELL_SPLIT #####################
# ######### CELL_SPLIT CELL_SPLIT CELL_SPLIT CELL_SPLIT CELL_SPLIT CELL_SPLIT #####################
# ######### CELL_SPLIT CELL_SPLIT CELL_SPLIT ######################################################
# ######### CELL_SPLIT


def directory_check_for_portfolio_data(params):
    """ checks that the directory setup for the current portfolio is correct
    if needed it will create a directory in ./data/<port_name> with other necessary thing in it.
    """

    # create portfolio orders dir:         ./data/<exchange>/<port_name>   ...if its not there yet
    port_path = get_data_file_path(data_type='port_folder',
                                   pair=None,
                                   date='live',
                                   port=port_name,
                                   exchange=exchange,
                                   )

    dirs_needed_for_order_data = [port_path, port_path + 'closed/', ]
    for pair in pairs_traded:
        dirs_needed_for_order_data.append(port_path + 'closed/' + pair + '/')

    for dir_path in dirs_needed_for_order_data:
        check_if_dir_exists_and_make(dir_path)

    fps_needed = [port_path + 'last_check.txt',
                  port_path + 'open_orders.csv',
                  ]
    for fp in fps_needed:
        if not os.path.isfile(fp):
            with open(fp, 'x'):
                pass

    return None


# initialize actions dict --> {'pair': 'neutural'}
def initialize_actions_dicts():
    global actions_dict

    for pair in pairs_traded:
        actions_dict[pair] = 'neutural'

    return None


# initialize allocation dict
def initialize_port_allocation_dict(method='default'):
    """ initialized the proportion of assets in the trading account that go to each pair """
    global port_allocation_dict
    global pairs_traded

    if method == 'default':
        port_allocation_dict['ADA-USDT'] = 0.0
        port_allocation_dict['BNB-USDT'] = 0.0
        port_allocation_dict['BTC-USDT'] = 0.25
        port_allocation_dict['DOGE-USDT'] = 0.25
        port_allocation_dict['ETH-USDT'] = 0.25
        port_allocation_dict['LINK-USDT'] = 0.25
        port_allocation_dict['LTC-USDT'] = 0.0
        port_allocation_dict['XLM-USDT'] = 0.0

    if method == 'all BTC':
        for pair in pairs_traded:
            if pair == 'BTC-USDT':
                port_allocation_dict[pair] = 1
            else:
                port_allocation_dict[pair] = 0

    if method == 'uniform':
        num_pairs = len(pairs_traded)

        for pair in pairs_traded:
            port_allocation_dict[pair] = 1 / num_pairs

    if method == 'markowitz':
        raise RuntimeError

    return None


# initial get for prices
def get_initial_prices_batch():
    """get prices from historical files.. calculate metrics, populate signal_df_dict

    output
        None: edits prices_dfs_dict as a global variable

    ###PAUL there is a huge problem with this function... its prices are not coming in up to date.
    ###PAUL its super weird and i have no clue what is going on with it... looking into now because kindof
    ###PAUL crucial error
    """

    global pairs_traded
    global prices_dfs_dict
    global short_term_prices_dict

    for pair in pairs_traded:
        # get_data will retrieve the last 24 hours of prices from written price files
        prices = get_data(data_type='price', pair=pair, date='live', exchange=data_exchange)  # gets 24 hours

        # fill in annoying missing data
        prices.fillna(method='ffill', inplace=True)
        prices.fillna(method='bfill', inplace=True)
        prices.fillna(method='ffill', inplace=True)
        prices_dfs_dict[pair] = prices

        # fill the short term prices dict (used for secondary orders)
        # clean prices_older than 10 mins... (for now)
        cutoff_time = datetime.datetime.now() + datetime.timedelta(minutes=-mins_short_term_price)
        keep_mask = prices.index > cutoff_time
        short_term_prices_dict[pair] = prices_dfs_dict[pair][keep_mask].copy(deep=True)

        # get vwap and mid_ewm prices... used to place orders for scam wicks
        short_term_prices_dict[pair]['mid_vwap'] = (short_term_prices_dict[pair]['buy_vwap'] +
                                                    short_term_prices_dict[pair]['sell_vwap']) / 2
        short_term_prices_dict[pair]['mid_ewm'] = short_term_prices_dict[pair]['mid_vwap'].ewm(alpha=0.6).mean()

    return None


def make_symbol_filters_dict(universal_symbol, market_info_dicts, exchange):
    """
    universal_symbol (str): Ex: BTC-USDT
    info (dict): result of ccxt_client.fetch_markets()
    exchange (str):  exchange (being traded, not data)   Ex: binanceus
    """

    filters_dict = {}

    exchange_symbol = convert_symbol(universal_symbol, in_exchange='universal', out_exchange=exchange)

    for d in market_info_dicts:
        if d['id'] == exchange_symbol:
            symbol_dict = d

    filters_dict['universal_symbol'] = universal_symbol
    filters_dict['id'] = symbol_dict['id']
    filters_dict['base'] = symbol_dict['base']
    filters_dict['precision_amount'] = symbol_dict['precision']['amount']
    filters_dict['quote'] = symbol_dict['quote']
    filters_dict['precision_price'] = symbol_dict['precision']['price']

    limits_price_min = symbol_dict['limits']['price']['min']
    if limits_price_min is None:
        limits_price_min = 0
    filters_dict['limits_price_min'] = limits_price_min

    limits_price_max = symbol_dict['limits']['price']['max']
    if limits_price_max is None:
        limits_price_max = 10e6
    filters_dict['limits_price_max'] = limits_price_max

    filters_dict['limits_amount_min'] = symbol_dict['limits']['amount']['min']
    filters_dict['limits_amount_max'] = symbol_dict['limits']['amount']['max']
    filters_dict['limits_cost_min'] = symbol_dict['limits']['cost']['min']
    filters_dict['limits_cost_max'] = symbol_dict['limits']['cost']['max']

    # precision numbers for these exchanges given in terms of # of decimals must --> tick size
    if exchange in ['binance', 'binanceus']:
        # swap_from_int_to_ticksize = True
        filters_dict['precision_amount'] = 1/10**filters_dict['precision_amount']
        filters_dict['precision_price'] = 1/10**filters_dict['precision_price']

    return filters_dict


def make_pair_info_df():
    """makes DataFrame, indexed by column "universal_symbol" with columns:
        'exchange_symbol', 'baseAsset', 'baseAssetPrecision', 'quoteAsset', 'quoteAssetPrecision',
        'minPrice', 'maxPrice', 'tickSize', 'minQty', 'maxQty', 'stepSize', 'minNotional',
        'marketMinQty', 'marketMaxQty', 'marketStepSize'
    """

    global pair_info_df
    global client

    pair_entry_list = []

    markets = client.fetch_markets()

    for symbol in pairs_traded:
        filters_dict = make_symbol_filters_dict(universal_symbol=symbol,
                                                market_info_dicts=markets,
                                                exchange=exchange)
        pair_entry_list.append(filters_dict)

    pair_info_df = pd.DataFrame.from_records(pair_entry_list, index='universal_symbol')
    pair_info_df = pair_info_df.astype(dtype=order_filters_names_type_dict)


def update_prices(pair, params=params):
    """ ###PAUL TODO: make new version... update it from price file, then trades
    this function ran into issues when place_order_on_signals is not being constantly called. while it will
    be constantly called in live usage, still it would be good to get from the price file just in case
    further, the price file does not f(orward)fill to the current second with past prices and no volume as
    it should. this is an adujustment which realistically should be made in the pipe_trades_to_prices_script
    as once a second fully occurs with no trades it is appropiate to put the prior prices in for that
    observation period
    """

    global exchange
    global data_exchange
    global prices_dfs_dict

    latest_price_written = max(prices_dfs_dict[pair].index)

    # get all the new trades
    # ###PAUL_refractor... wrong exchange cause dealing with binance prices.. dont know how to handle rn
    live_trades = get_live_trades_data(pair, exchange=data_exchange)  # ###PAUL_refractor
    live_prices = convert_trades_df_to_prices(live_trades, exchange=data_exchange)  # ###PAUL_refractor
    live_prices = live_prices[live_prices.index > latest_price_written]

    # merge the new prices with the old prices.
    prices_dfs_dict[pair] = pd.concat([prices_dfs_dict[pair], live_prices])

    # clean prices_older than 24 hr... probably wont need more for informed decision making (for now)
    cutoff_time = datetime.datetime.now() + datetime.timedelta(hours=-24)
    keep_mask = prices_dfs_dict[pair].index > cutoff_time
    prices_dfs_dict[pair] = prices_dfs_dict[pair][keep_mask]

    # fill NaNs (only happens when is missing information so this is needed at this step each update)
    prices_dfs_dict[pair].fillna(method='ffill', inplace=True)
    prices_dfs_dict[pair].fillna(method='bfill', inplace=True)


def update_all_prices(params=params):
    global pairs_traded

    for pair in pairs_traded:
        update_prices(pair)

    return None


def update_short_term_prices(pair, params=params):
    """updates the short term prices... the file reading in this may take a bit extra timme, for stability
    for now this is seperate from update prices... eventually should be combined with update prices as to
    not need to generate prices from live trades twice
    """

    global exchange
    global short_term_prices_dict

    latest_price_written = max(short_term_prices_dict[pair].index)

    # get all the new trades
    # ###PAUL this is a dirty fix... after initializing the short term prices on the data exchange
    # ###PAUL i switch them to "exchange" the trading exchange...
    live_trades = get_live_trades_data(pair, exchange=exchange)  # ###PAUL_refractor
    live_prices = convert_trades_df_to_prices(live_trades, exchange=exchange)  # ###PAUL_refractor
    live_prices = live_prices[live_prices.index > latest_price_written]

    # merge the new prices with the old prices.
    short_term_prices_dict[pair] = pd.concat([prices_dfs_dict[pair], live_prices])

    # clean prices older than   mins_short_term_price
    cutoff_time = datetime.datetime.now() + datetime.timedelta(minutes=-mins_short_term_price)
    keep_mask = short_term_prices_dict[pair].index > cutoff_time
    short_term_prices_dict[pair] = short_term_prices_dict[pair][keep_mask]

    # fill NaNs (only happens when is missing information so this is needed at this step each update)
    short_term_prices_dict[pair].fillna(method='ffill', inplace=True)
    short_term_prices_dict[pair].fillna(method='bfill', inplace=True)

    # recently added
    short_term_prices_dict[pair]['mid_vwap'] = (short_term_prices_dict[pair]['buy_vwap'] +
                                                short_term_prices_dict[pair]['sell_vwap']) / 2
    short_term_prices_dict[pair]['mid_ewm'] = short_term_prices_dict[pair]['mid_vwap'].ewm(alpha=0.6).mean()

    return None


def update_all_short_term_prices(params=params):
    global pairs_traded

    for pair in pairs_traded:
        update_short_term_prices(pair)

    return None


def update_signals(params=params):
    """also handles initialization of the signals dictionary
    """

    # first update the prices
    update_all_prices()
    update_all_short_term_prices()

    # declare globals for this scope
    global pairs_traded
    global prices_dfs_dict
    global signal_dfs_dict
    global sma_short
    global sma_long

    for pair in pairs_traded:
        prices = prices_dfs_dict[pair]

        sma_short = prices['buy_vwap'].rolling(window=window_sma_short).mean().fillna(method='bfill')[-1]
        sma_long = prices['buy_vwap'].rolling(window=window_sma_long).mean().fillna(method='bfill')[-1]
        print('sma_short = ' + str(sma_short) + '  --VS--  '  + str(sma_long) + ' = sma_long')

        # buy if shorter SMA is bigger than longer SMA
        if sma_short > sma_long:
            signal_dfs_dict[pair] = -1

        # sell if shorter SMA smaller than longer SMA
        if sma_short < sma_long:
            signal_dfs_dict[pair] = 1

    return None


def initialize_bag_dicts():
    global pairs_traded
    global bag_max_dict
    global bag_actual_dict
    global bag_desired_dict

    for pair in pairs_traded:
        bag_max_dict[pair] = {'base': 0, 'base_in_quote': 0, 'quote': 0}
        bag_actual_dict[pair] = {'base': 0, 'base_in_quote': 0, 'quote': 0}
        bag_desired_dict[pair] = {'base': 0, 'base_in_quote': 0, 'quote': 0}


def update_port_holdings_and_value():
    '''updates the global variables listed at the top of the function
    note the differientation between holdings and bags
        - holdings is EVERYTHING in the account
        - bags are things that are tradable according to pairs tracked
        - value is determined from bags, holdings are not included and must be manually traded

    TODO: this function gets holdings of ALL pairs, not all pairs are tracked right now some
     optimization needs to be done its not worth adding all pairs to track.. will take longer and more compute
    '''

    global pairs_traded
    global pair_info_df

    global short_term_prices_dict
    global last_prices_dict

    global port_value
    global port_usd
    global port_holdings_dict
    global port_allocation_dict

    global bag_max_dict
    global bag_actual_dict

    # update port holdings    ---- note: it gets all holdable assets on some exchanges....
    bag_dict = client.fetch_balance()  # ccxt returns dict of dicts:  'XRP': {'free': 0.0, 'used': 0.0, 'total': 0.0}
    del bag_dict['info']
    bag_dict_assets = bag_dict.keys()

    # loop adds pairs outside of portfolio's control to bag list... these don't contribute value to the port value
    for symbol in pairs_traded:
        base = pair_info_df.loc[symbol]['base']  # gets the base asset of a pair

        # ###PAUL this is a change in the port holdings dict... 'used', used to be keyed via 'locked' or another term
        if base not in bag_dict_assets:  # we dont have any of this asset in holdings
            port_holdings_dict[base] = {'free': 0.0, 'used': 0.0, 'total': 0.0}
        else:
            port_holdings_dict[base] = bag_dict[base]  # gets holdings for that base asset / ticker

    # add dollars to port holdings
    if exchange == 'binanceus':
        port_holdings_dict['USD'] = bag_dict['USD']
    else:
        port_holdings_dict['USDT'] = bag_dict['USDT']

    # update port_value   ---- note: only considers the pair's traded in the portfolio value
    port_value_t = 0

    for symbol in pairs_traded:
        # get the base asset of each symbol
        base_asset = pair_info_df.loc[symbol]['base']

        # get qty and value of base asset held for each pair
        last_price = float(short_term_prices_dict[symbol].iloc[-1:]['mid_ewm'])
        last_prices_dict[symbol] = last_price
        base_asset_qty = port_holdings_dict[base_asset]['total']
        asset_value = last_price * base_asset_qty

        # update actual bags dict
        bag_actual_dict[symbol]['base'] = base_asset_qty
        bag_actual_dict[symbol]['base_in_quote'] = asset_value

        port_value_t += asset_value

    ###PAUL there will be a problem trading on exchanges with tether vs USD (mainly all vs binance-us)

    # calculating the portfolio's value.... first take dollars into account
    if exchange == 'binanceus':
        port_value_t += bag_dict['USD']['total']  # tack on the USD value... not a pair tracked
    else:
        port_value_t += bag_dict['USDT']['total']

    port_value = port_value_t

    # UPDATE: bag_max_dict ---- must do this after the new total value is assessed
    for pair in pairs_traded:
        # get dollars for actual bags dict by subtracting value held from proportion of portfolio for pair
        total_value_for_pair = port_allocation_dict[pair] * port_value

        last_price = last_prices_dict[pair]
        quote_value_of_pair_bag = last_price * bag_actual_dict[pair]['base']
        bag_actual_dict[pair]['quote'] = total_value_for_pair - quote_value_of_pair_bag

        # update all of max bag dict
        #
        # ###PAUL_refractor... generalize the base_asset as a variable ??? not sure what I meant here del_later
        #
        bag_max_dict[pair]['base'] = total_value_for_pair / last_price
        bag_max_dict[pair]['base_in_quote'] = total_value_for_pair
        bag_max_dict[pair]['quote'] = total_value_for_pair


def update_actions_dict():
    """ the primary benefit of this function is to see whether we have a buy or sell that has been determined
    and then to up the priority of that order if it needs it.

    output:
        actions_dict (dict): {'BTCUSDT':'buy',  'XRPUSDT':'sell'}
    """
    global actions_dict
    global pairs_traded
    global signals_dfs_dict

    for pair in pairs_traded:
        action = actions_dict[pair]
        signal_int = signal_dfs_dict[pair]  # -1 = sell    1 = buy

        # BUY condition met
        if signal_int == -1:
            if action == 'buy':
                actions_dict[pair] = 'buy_again'
            else:
                actions_dict[pair] = 'buy'

        # SELL condition met
        elif signal_int == 1:
            if action == 'sell':
                actions_dict[pair] = 'sell_again'
            else:
                actions_dict[pair] = 'sell'

                # NEITHER buy or sell condition met
        else:
            actions_dict[pair] = 'neutural'


def update_desired_bags(pair):
    """called in place_orders_on_signal()
    ###PAUL_refractor... maybe needed for place_secondary orders?
    ###PAUL_tag1 ---- longer term consideration... desired_bags more complex than in or out
    ###PAUL_tag1 ---- also considering using funds that aren't being utilized for a more bullish asset.
    ###PAUL_tag1 ---- after further thought, keep as is, these strats (like markowitz) will adjust portfolio_allocation
    """

    global actions_dict
    global bag_max_dict
    global bag_desired_dict

    action = actions_dict[pair]

    if action == 'buy' or action == 'buy_again':
        bag_desired_dict[pair]['base'] = bag_max_dict[pair]['base']
        bag_desired_dict[pair]['base_in_quote'] = bag_max_dict[pair]['base_in_quote']
        bag_desired_dict[pair]['quote'] = 0

    if action == 'sell' or action == 'sell_again':
        bag_desired_dict[pair]['base'] = 0
        bag_desired_dict[pair]['base_in_quote'] = 0
        bag_desired_dict[pair]['quote'] = bag_max_dict[pair]['quote']

    return None


# make stuff thats gotta be made
directory_check_for_portfolio_data(params)
make_pair_info_df()
initialize_bag_dicts()

initialize_port_allocation_dict(method='uniform')
initialize_actions_dicts()
get_initial_prices_batch()
update_all_prices()
update_all_short_term_prices()
update_signals()
update_port_holdings_and_value()
update_actions_dict()

for pair in pairs_traded:
    update_desired_bags(pair)

print('created global variables and ran one iteration of updates ')


# ######### CELL_SPLIT
# ######### CELL_SPLIT CELL_SPLIT CELL_SPLIT ######################################################
# ######### CELL_SPLIT CELL_SPLIT CELL_SPLIT CELL_SPLIT CELL_SPLIT CELL_SPLIT #####################
# ######### CELL_SPLIT CELL_SPLIT CELL_SPLIT CELL_SPLIT CELL_SPLIT CELL_SPLIT #####################
# ######### CELL_SPLIT CELL_SPLIT CELL_SPLIT ######################################################
# ######### CELL_SPLIT


def make_ccxt_order_info_dict(response):
    """takes a CCXT style placed OR fetch order response and makes it into an order info dict
    """

    # things that gotta be done first
    order_info_dict = dict()

    order_info_dict['id'] = response['id']
    order_info_dict['symbol'] = response['symbol'].replace('/', '-')  # fetch order may come with '/'...
    order_info_dict['clientOrderId'] = response['clientOrderId']
    order_info_dict['timestamp'] = response['timestamp']
    order_info_dict['price'] = response['price']
    order_info_dict['amount'] = response['amount']
    order_info_dict['filled'] = response['filled']
    order_info_dict['cost'] = response['cost']
    order_info_dict['side'] = response['side']
    order_info_dict['status'] = response['status']
    order_info_dict['type'] = response['type']

    return order_info_dict


def make_order_observation_csv_line(order_info_dict):
    """returns a string to go in live order tracking file
    only to be used on a fetched order status using ccxt_client.fetch_order()

    # ###PAUL TODO... switch this to a loop through a list... makes the code nicer

    """

    try:
        remaining = order_info_dict['remaining']
    except KeyError:
        remaining = 0

    new_live_order_line = order_info_dict['id'] + ',' \
                          + str(order_info_dict['symbol']) + ',' \
                          + str(order_info_dict['side']) + ',' \
                          + str(order_info_dict['price']) + ',' \
                          + str(order_info_dict['amount']) + ',' \
                          + str(order_info_dict['filled']) + ',' \
                          + str(order_info_dict['cost']) + ',' \
                          + str(remaining) + ',' \
                          + str(order_info_dict['status']) + ',' \
                          + str(order_info_dict['timestamp']) + ',' \
                          + str(order_info_dict['type']) \
                          + str(order_info_dict['clientOrderId']) + ',' \
                          + '\n'

    return new_live_order_line


def process_placed_order(placed_order_res):
    """makes live order observation from placed order response.. note there are subtle differences between
    a placed order response and a get_or der response which is an update on an already placed orders.py
    for more see the update from
    """
    global exchange
    global port_name
    global order_open_dict

    # ### the below should not be needed and can be deleted after this whole ish runs clean
    #     # used as primary key among orders (not sure if this or clientOrderId best practice...)
    #     pair = placed_order_res['symbol']
    #     pair = pair.replace('/', '-')  # symbols sometimes come in standard CCXT format of BASE/QUOTE

    #     # shouldn't be needed any more as we use ccxt formats
    # #     universal_symbol = convert_symbol(pair, in_exchange=exchange, out_exchange='universal')

    # parse the placed order response
    order_info_dict = make_ccxt_order_info_dict(response=placed_order_res)
    orderId = placed_order_res['id']
    symbol = placed_order_res['symbol'].replace('/', '-')  # some exchanges ccxt returns a '/' instead of '-'

    # add the new order to the dictionary tracking open orders
    order_open_dict[(orderId, symbol)] = order_info_dict

    # ### write the order to the live files
    #
    open_order_fp = get_data_file_path(data_type='order',
                                       pair='None',
                                       date='live',
                                       port=port_name,
                                       exchange=exchange)

    new_live_order_line = make_order_observation_csv_line(order_info_dict)

    with open(open_order_fp, "a") as f:
        f.write(new_live_order_line)
    os.chmod(open_order_fp, 0o777)  # '0o777' needed for when running on systemd


def place_order(B_or_S, pair, o_type, base_qty, price=None, order_id=None):
    """places an orders.py

    input:
        pair (str): 'BTCUSDT'... use universal_symbol tracked NOT the USA universal_symbol, it will convert it
        o_type (str): 'limit' only supported now, in future maybe, market and more...
        B_or_S (str): 'buy' or 'sell'
        base_qty (float): amount of base asset to buy (i.e. BTC in BTCUSDT )
        quote_qty (float): same functionality as base_qty, but for quote... NOT YET SUPPORTED
        price (float): price of base asset in quote asset terms

    returns:
        ???? not sure need:
        order ID to track the order status, maybe more
    """




    if pair not in pairs_traded:  # ###PAUL  not sure what I wanted to be doing here
        raise KeyError

    # ### verify constraints met for order... precision_amount and precision_price should be only ones affected
    #
    #


    info = pair_info_df.loc[pair]

    # most important / relevant checks



    # ###PAUL_start_here the line below is rounding wrong, however this has not been a problem for kucoin... pls fix
    # ###PAUL_start_here the line below is rounding wrong, however this has not been a problem for kucoin... pls fix
    # ###PAUL_start_here the line below is rounding wrong, however this has not been a problem for kucoin... pls fix
    # ###PAUL_start_here the line below is rounding wrong, however this has not been a problem for kucoin... pls fix
    # ###PAUL_start_here the line below is rounding wrong, however this has not been a problem for kucoin... pls fix
    base_qty = round_step_size(quantity=base_qty, step_size=info['precision_amount'])




    price = round_step_size(quantity=price, step_size=info['precision_price'])

    # exchange rules
    if base_qty < info['limits_amount_min'] or base_qty > info['limits_amount_max']:
        print('base_qty: ' + str(base_qty) + 3 * ('\n LIMIT_HIT LIMIT_HIT LIMIT_HIT'))
        raise ValueError

    if price < info['limits_price_min'] or price > info['limits_price_max']:
        print('price: ' + str(price) + 3 * ('\n P_LIMIT_HIT P_LIMIT_HIT P_LIMIT_HIT'))
        raise ValueError

    # ###PAUL would like to get rid of the below and raise a ValueError also
    # notional requirements (makes sure that the order is large enough in terms of quote asset)
    if price * base_qty < info['limits_cost_min']:
        print('    Price: ' + str(price) + '\n')
        print('    base_qty: ' + str(base_qty) + '\n')
        print("    info['limits_cost_min']: " + str(info['limits_cost_min']) + '\n')

        return 'order not placed MIN_NOTIONAL issue '

    # ### place order
    #
    #
    # string used to place order on pair on the exchange
    symbol = info['id']  # formerly 'exchange_symbol'... now labled id because CCXT unified structure

    if o_type == 'limit':
        print('placing order')
        print('Limit Order:  ' + B_or_S + ' ' + str(base_qty) + ' ' + symbol + ' for $' + str(price))

        order_res = client.create_limit_order(symbol=symbol,
                                              side=B_or_S,
                                              amount=base_qty,
                                              price=price)

    else:
        print('Error: order type not supported')
        raise TypeError

    process_placed_order(order_res)

    return order_res


def write_closed_order(orderId, pair, response):
    """writes order that has closed to a file of orders for that pair
    """

    # global order_open_dict
    global params

    # response = client.fetch_order(id=orderId, symbol=pair)
    order_info_dict = make_ccxt_order_info_dict(response)

    header = 'orderId,ticker,clientOrderId,placedTime,price,origQty,executedQty,cummulativeQuoteQty,side,status,ord_type,updateTime\n'
    new_line = make_order_observation_csv_line(order_info_dict)

    daily_trade_fp = get_data_file_path('closed_order', pair, date='live', port=port_name, exchange=exchange)

    # check that the file exists for the correct time period
    file_existed = os.path.isfile(daily_trade_fp)
    with open(daily_trade_fp, "a") as f:
        if file_existed == False:  # then new file, write header
            f.write(header)
        f.write(new_line)
    os.chmod(daily_trade_fp, 0o777)

    return None


def remove_order_from_open_tracking(tuple_key, response):
    """serves 3 primary purposes:  1.) removes order from ./data/orders/open/open_orders.csv
                                   2.) writes the order to the pair's / day's closed order file
                                   3.) removes order from global tracking dictionary
    """

    global order_open_dict

    orderId, universal_symbol = tuple_key

    # ### remove order from open order tracking file
    #
    open_order_fp = get_data_file_path(data_type='order', pair=None, date='live', port=port_name, exchange=exchange)

    with open(open_order_fp, 'r') as f:
        lines = f.readlines()

    # rewrite file without the orderId in it
    with open(open_order_fp, "w") as f:
        for line in lines:
            if str(orderId) not in line[:15]:
                f.write(line)

    # ### write to closed order files
    write_closed_order(orderId, universal_symbol, response)

    # ### remove order from dictionary... must do last, info here used to write to closed order file
    #
    del order_open_dict[(orderId, universal_symbol)]

    return None


def close_order(order_id_tuple):
    orderId, universal_symbol = order_id_tuple
    exchange_symbol = convert_symbol(universal_symbol, in_exchange='universal', out_exchange=exchange)

    tuple_key = (orderId, universal_symbol)

    # cancel the order
    try: # ###PAUL would like to handle closed orders with out a try except if possible. test out what the response is
        order_res = client.cancel_order(id=orderId, symbol=exchange_symbol)
        remove_order_from_open_tracking(tuple_key, response=order_res)

        print('closed order: ')
        print(order_res)

    except Exception as e: # for now if this errors then check_for_closed_orders should handle it
        print('order cancel attempted, it seems order was filled: ')
        print('    symbol: ' + exchange_symbol + '  orderId: ' + str(orderId) + '/n /n /n')
        print(e)
        print('/n /n /n ')

    return None


def check_opens_and_close_lower_priority_orders(B_or_S, price, pair):
    """goes over all the open orders for the set of API keys and if the new order
    """

    global order_open_dict

    order_higher_priority = False
    order_open_for_pair = False
    keys_to_close = []

    # ###PAUL_refractor... this could (should?) be built more DRY
    #
    # for order in open_orders check...
    for key in order_open_dict.keys():
        _, order_pair = key

        # if there is an open order
        if pair == order_pair:
            print('already an order open for pair  --->  ' + pair)
            order_open_for_pair = True
            old_price = float(order_open_dict[key]['price'])

            if B_or_S == 'buy' and price > old_price or B_or_S == 'sell' and price < old_price:
                print("higher priority order ---- " + pair + B_or_S + '  ask was  ' + str(old_price)
                      + '  updated to:   ' + str(price))
                order_higher_priority = True
                keys_to_close.append(key)

                # there should only be one key to close for but we'll make it possible for multiple
    for key in keys_to_close:
        close_order(key)

    return order_higher_priority, order_open_for_pair


def process_fetch_order_response(response):
    '''not sure if will be needed but we will keep bumping this down the line till we figure it out
    expecting it to me similar to placed order response and barely needed....
    '''

    return


def update_most_recent_order_check_file():
    fp = get_data_file_path(data_type='last_order_check',
                            pair=None,
                            date='live',
                            port=port_name,
                            exchange=exchange)

    now = str(time.time())

    with open(fp, 'w') as f:
        f.write(now)
    os.chmod(fp, 0o777)

    return None


# ######### CELL_SPLIT
# ######### CELL_SPLIT CELL_SPLIT CELL_SPLIT ######################################################
# ######### CELL_SPLIT CELL_SPLIT CELL_SPLIT CELL_SPLIT CELL_SPLIT CELL_SPLIT #####################
# ######### CELL_SPLIT CELL_SPLIT CELL_SPLIT CELL_SPLIT CELL_SPLIT CELL_SPLIT #####################
# ######### CELL_SPLIT CELL_SPLIT CELL_SPLIT ######################################################
# ######### CELL_SPLIT


def print_update_on_bot():
    global iter_count

    print('ALGOS - LIVE BOT - iter: ' + str(iter_count) \
          + ' ---- port: ' + port_name \
          + ' ---- exchange: ' + exchange)

    print('SIGNAL')
    print('    ' + str(signal_dfs_dict))

    print('ACTUAL BAGS')
    for key, value in bag_actual_dict.items():
        print('    ' + key + ':  ' + str(value))

    print('DESIRED BAGS')
    for key, value in bag_desired_dict.items():
        print('    ' + key + ':  ' + str(value))


def figure_price_qty_for_order(pair, diff, action):
    global port_holdings_dict
    global short_term_prices_dict
    global pair_info_df

    # info needed whether buying or selling
    last_price_df_t = short_term_prices_dict[pair].iloc[-1:]
    mid_vwap = float(last_price_df_t['mid_vwap'])
    mid_ewm = float(last_price_df_t['mid_ewm'])

    if diff >= diff_thresh:  # we are buying
        if exchange == 'binanceus':
            current_dollar_holdings = port_holdings_dict['USD']['free']
        else:
            current_dollar_holdings = port_holdings_dict['USDT']['free']

        buy_dollars = min(diff, current_dollar_holdings)  # cant buy more than i have

        if action == 'buy':
            B_or_S = 'buy'
            price = min(mid_vwap, mid_ewm)  # want to buy for cheaper since not high priority
            qty = buy_dollars / price * 0.98

        else:  # more urgent option... or for some reason have too little (crash and re-boot)
            B_or_S = 'buy'
            price = max(mid_vwap, mid_ewm)  # max cause on buy again we really want the asset
            qty = buy_dollars / price * 0.98

    if diff <= -diff_thresh:  # we are selling
        baseAsset = pair_info_df.loc[pair]['base']
        baseAsset_holdings = port_holdings_dict[baseAsset]['free']
        sell_dollars = min(-diff, min(mid_vwap, mid_ewm) * baseAsset_holdings)

        if action == 'sell':
            B_or_S = 'sell'
            price = max(mid_vwap, mid_ewm)  # max cause want the highest price on non-urgent sell
            qty = 0.98 * (sell_dollars / price)

        else:  # more urgent (sell again or if we have too much unintentionally - a reboot for example)
            B_or_S = 'sell'
            price = min(mid_vwap, mid_ewm)  # min... want to get rid of it on urgent sells
            qty = 0.98 * (sell_dollars / price)

    return price, qty, B_or_S


def check_for_orders_and_close_unrelated():
    """checks all orders open on exchange (for the account's client) and closes any outside of pairs_traded
    NOTE: this isnt used yet, it is the old version of check_for_closed_orders, but fetch_markets has an api limit
    on binance so this will be added back in as mentioned

    # ###PAUL_todo get this into the rotation with a twisted reactor task (every 5 minutes...)
    """

    global order_open_dict

    # get open orders from exchange

    # ###PAUL_debug cant do this on binance, going to have to check each order listed
    # ###PAUL_plsfix add a sub routine later that checks for any open orders on exchanges in general and closes
    # ###PAUL_plsfix if they are not aready in the tracking
    # ###PAUL debug

    # we only wanna be calling this rarely
    open_orders_res_list = client.fetch_open_orders()

    order_res = 'needed now for remove order from tracking, handle when this function goes live '

    # put list of keys: tuples (orderId, universal_symbol) from exchange collected
    open_orders_on_exchange = []
    for res in open_orders_res_list:
        exchange_symbol = res['symbol'].replace('/', '-')
        universal_symbol = convert_symbol(exchange_symbol, in_exchange=exchange, out_exchange='universal')

        orderId = res['id']
        tup = (orderId, universal_symbol)

        open_orders_on_exchange.append(tup)

    # loop through the open_order_dict, remove entry if the order is not in the orders on the exchange
    keys_to_delete = []
    for key in order_open_dict:
        if key not in open_orders_on_exchange:
            keys_to_delete.append(key)

    for key in keys_to_delete:
        remove_order_from_open_tracking(key, response=order_res)

    return None


def check_for_closed_orders():
    """checks if any of the open orders being tracked are now closed and removes them from tracking
    TODO: need to add order fills to tracking consider ./data/orders/filled/  (filled being a new dir)
    """

    global order_open_dict

    # ###PAUL_dev notes
    #
    # ###
    # |    status    |  kucoin   |   binance(us)  |  ### ccxt converts varying format status to open or closed...
    # |     open     |  'open'   |   'open'       |  ### where as binance uses FILLED, PARTIALLY_FILLED, etc...
    # |    closed    | 'closed'  |   'closed'     |  ### kucoin uses isActive: [True, False]

    for key, value in order_open_dict.items():
        order_id, universal_symbol = key

        exchange_symbol = convert_symbol(universal_symbol, in_exchange='universal', out_exchange=exchange)

        order_res = client.fetch_order(id=order_id, symbol=exchange_symbol)

        if order_res['status'] == 'closed':
            remove_order_from_open_tracking(key, response=order_res)

    return None


def reassess_bags_and_orders(params):
    """
    """
    global iter_count

    global actions_dict

    global port_value
    global port_holdings_dict
    global port_allocation_dict

    global pair_info_df

    global bag_max_dict
    global bag_actual_dict
    global bag_desired_dict



    update_signals()  # also includes update to long and short term prices

    # get desired action for pair
    update_actions_dict()

    # want update holdings and value as near as placing new orders as possible... this cancels open orders
    update_port_holdings_and_value()

    for pair in pairs_traded:

        exchange_symbol = convert_symbol(pair, in_exchange='universal', out_exchange=exchange)

        # place buy/sell order
        action = actions_dict[pair]

        if iter_count % 10 == 0:
            print_update_on_bot()

        # most actions should be neutral... save time by passing on other actions if neutral
        if action == 'neutural':
            continue

        update_desired_bags(pair)  # bag for pair to  {0, max_bag_for_pair} based on allocation

        actual_base_in_quote_value = bag_actual_dict[pair]['base_in_quote']
        desired_base_in_quote_value = bag_desired_dict[pair]['base_in_quote']

        diff = desired_base_in_quote_value - actual_base_in_quote_value

        # if diff to small, we dont do anything
        ###PAUL this only works IF QUOTE IS IN DOLLARS..
        ###PAUL once trading in other quotes need to figure out another way to go about this
        if -diff_thresh < diff and diff < diff_thresh:
            continue  # skips to next iteration of for loop

        print('debug_1 ---- pair: ' + str(pair))
        print('debug_1 ---- diff: ' + str(diff))

        ###PAUL TODO: should add order book info on prices to this to take advantage of scan wicks
        # this means buying at the scam price if lower than the above, vise versa selling
        price, qty, B_or_S = figure_price_qty_for_order(pair, diff, action)
        total_order_value = qty * price

        print('debug_1 ---- price: ' + str(price))
        print('debug_1 ---- qty: ' + str(qty))
        print('debug_1 ---- total_order_value: ' + str(total_order_value))

        if total_order_value < 9:
            continue

        print('debug_2 ---- pair: ' + pair)
        order_higher_priority, order_open_for_pair = check_opens_and_close_lower_priority_orders(B_or_S,
                                                                                                 price,
                                                                                                 pair)

        print('debug_2 ---- order_higher_priority: ' + str(order_higher_priority))
        print('debug_2 ---- order_open_for_pair: ' + str(order_open_for_pair))

        ###PAUL eventually expecting error... if order filled between the line above + below (due to latency)
        if order_higher_priority == True or order_open_for_pair == False:
            print('PLACING LIMIT ORDER ---- ' + B_or_S + ' - ' + str(qty) + ' - ' + pair
                  + ' for $' + str(price) + ' ---- in port_name: ' + port_name)


            order_res = place_order(B_or_S=B_or_S,
                                    pair=pair,
                                    o_type='limit',
                                    base_qty=qty,
                                    price=price
                                    )
            process_placed_order(order_res)

    time.sleep(0.1)  # gives small time for highly likely orders to fill before checking
    check_for_closed_orders()  # stops tracking orders that were closed any way (filled, bot, or manual)

    # only update the portfolios most recent update time if this function runs to fruition
    update_most_recent_order_check_file()

    iter_count += 1

    return None


# signal_based_order_interval = params['constants']['signal_based_order_interval']
# place_orders_on_signal_task = task.LoopingCall(f=place_signal_on_orders_exception_catch)
# place_orders_on_signal_task.start(signal_based_order_interval)

i = 0

while i < 100000:
    reassess_bags_and_orders(params)
    time.sleep(10)
