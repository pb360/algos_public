#!/home/paul/miniconda3/envs/crypto_data_scrape/bin/python3
# -*- coding: utf-8 -*-
# imports
#
#

"""
This script creates a websocket connection to binance and listens and records all trades for relevant pairs
"""

# ### imports
#
#
import os
import time
# ### time zone change... this must happen first and utils must be imported first
os.environ['TZ'] = 'UTC'
time.tzset()

import pandas as pd
import sys  # ###PAUL_del_later_if_not_needed
import threading
import traceback
from twisted.internet import task, reactor

# ### local imports
#
#
import config
from utils import send_email, get_data_file_path, convert_date_format, convert_symbol

# needed to let the package to see itself for interior self imports
sys.path.append('/mnt/algos/ext_packages/sams_binance_api')
from binance.client import Client
from binance.websockets import BinanceSocketManager

# ### variable definitions

#
START_TIME = time.time()
params = config.params

exchange = 'binance'  # exchange we are collecting data for
script = 'data_scrape_binance.py'
params['exchange'] = exchange

lock = threading.Lock()  # locks other threads from writing to daily trade file

# global variables used in various functions
this_scripts_process_ID = os.getpid()
conn_key = 0  ### used to close binance connections... is int, need one to start so zero
last_msg_time = time.time() + 1.5
consecutive_error_messages = 0
message_counter = 0  # for debug only

# api keys
api_key = params['keys']['binance_data_key_1']
secret_key = params['keys']['binance_data_key_secret_1']

# parameters about investment universe
tracked_symbols_exchange_format = list(params['universe'][exchange]['convert_dict']['universal'].keys())
pair_collection_list = params['universe'][exchange]['pair_collection_list']


if exchange == 'binanceus':
    tld = 'us'
else:
    tld = 'com'

# binance client
client = Client(
    api_key=api_key,
    api_secret=secret_key,
    requests_params=None,
    tld=tld  # ###PAUL this is for the country... need to set that for sure.... careful on other exchanges
)

# initiate client instance
bm = BinanceSocketManager(client)


def lock_thread_append_to_file(file_path, new_line):
    """locks file so no other thread from this script may write to it

    ###PAUL TODO: make a decorator so that BTC_USDT isnt fighting ETH_BTC for a lock

    inputs:
        file_path (str): string from root directory to file
        new_line (str): to append to file

    out:
        none
    """
    lock.acquire()  # thread must aquire lock to write to file
    # in this section, only one thread can be present at a time.
    with open(file_path, "a") as f:
        f.write(new_line)
    os.chmod(file_path, 0o777)
    lock.release()


def rename_temp_to_live_file(temp_file_path, live_file_path):
    """lock thread so live file may be deleted, and temp file renamed to live file
    ###PAUL this is an idea if speed becomes a problem, NOT USED CURRENTLY
    """
    lock.acquire()
    os.remove(live_file_path)
    os.rename(temp_file_path, live_file_path)
    lock.release()


def make_new_trade_observation_for_trade_file(trade_info, pair):
    new_line = str(trade_info['E'] / 1000) + ',' \
               + pair + ',' \
               + str(trade_info['t']) + ',' \
               + str(trade_info['p']) + ',' \
               + str(trade_info['q']) + ',' \
               + str(trade_info['b']) + ',' \
               + str(trade_info['a']) + ',' \
               + str(trade_info['T'] / 1000) + ',' \
               + str(trade_info['m']) + '\n'
    return new_line


def check_if_file_make_dirs_then_write(file_path, new_line, header=None, thread_lock=False):
    # check that the file exists for the correct time period
    if os.path.isfile(file_path):
        if thread_lock == True:
            lock_thread_append_to_file(file_path, new_line)
        if thread_lock == False:
            # write trade to historical file... no lock as this script only appends to these files
            with open(file_path, "a") as f:
                f.write(new_line)
            os.chmod(file_path, 0o777)

    else:  # file does not exist
        # check if directory heading to file exists, if not make all required on the way
        fp_dirname = os.path.dirname(file_path)
        if os.path.isdir(fp_dirname) == False:
            os.makedirs(fp_dirname)

        # write the new line, and header if requestd
        with open(file_path, "a") as f:
            if header is not None:
                f.write(header)
            f.write(new_line)
        os.chmod(file_path, 0o777)


def process_message(msg):
    # # #######   ---------------------------------------------------------------- START: debug
    # # #######   ---------------------------------------------------------------- START: debug
    # global message_counter
    # message_counter += 1
    #
    # if message_counter > 10:       # once enough messages force an error
    #     msg['data']['e'] = 'error'
    # # #######   ---------------------------------------------------------------- END: debug
    # # #######   ---------------------------------------------------------------- END: debug

    global conn_key
    global exchange
    global last_msg_time
    global this_scripts_process_ID
    global consecutive_error_messages

    # reset last message time for heartbeat check... if too long script assumes problem and restarts
    last_msg_time = time.time()

    stream = msg['stream']
    trade_info = msg['data']

    # print the current message
    print(stream + '  process ID: ' + str(this_scripts_process_ID), flush=True)

    # ###PAUL TODO add to non-existant logger
    if trade_info['e'] != 'trade':
        if consecutive_error_messages > 10:
            consecutive_error_messages += 1
        else:
            message = "just a notification, no action needed"
            send_email(subject='ALGOS UPDATE: ' + exchange + ' trades scrape ---- Consecutive Error from Websocket',
                       message=message,
                       script=script)

    # if normal trade message received process it
    else:
        consecutive_error_messages = 0  # since its a good message, reset the error counter

        # get trade info from message
        pair = trade_info['s']
        pair = convert_symbol(pair, in_exchange=exchange, out_exchange='universal')

        new_line = make_new_trade_observation_for_trade_file(trade_info, pair)

        # ### write to live data file
        live_data_file_path = get_data_file_path(data_type='trade', pair=pair, date='live', exchange=exchange)
        check_if_file_make_dirs_then_write(file_path=live_data_file_path, new_line=new_line, thread_lock=True)

        # ### WRITE TO HISTORICAL DATA FILES
        trade_info_epoch_time = trade_info['E'] / 1000
        date_tuple = convert_date_format(trade_info_epoch_time, 'tuple_to_day')

        daily_trade_fp = get_data_file_path('trade', pair, date=date_tuple, exchange=exchange)
        header = 'msg_time,ticker,trade_id,price,quantity,buy_order_id,sell_order_id,trade_time,buyer_is_maker\n'

        check_if_file_make_dirs_then_write(file_path=daily_trade_fp, new_line=new_line, header=header)

    return None


# iter_count_live_file_trim = 0   # ###DEBUG used to be sure function spits an error at some point
def trim_live_files(params=params):
    """removes data older than param from active_services from live data files

    ###PAUL TODO make so one thread locks and handles ONE file... low priority
    """
    # # #######   ---------------------------------------------------------------- START: debug
    # # #######   ---------------------------------------------------------------- START: debug
    # global iter_count_live_file_trim
    # iter_count_live_file_trim += 1
    # print('iter #: ',  str(iter_count_live_file_trim), ' of live data purge', flush=True)
    #
    # if iter_count_live_file_trim > 10:
    #     print('hur-dee-dur... i stopped \n'*10, flush=True)
    #     raise ValueError
    # # #######   ---------------------------------------------------------------- END: debug
    # # #######   ---------------------------------------------------------------- END: debug

    # variable definitions
    global exchange
    global tracked_symbols_exchange_format

    trade_col_names = params['data_format'][exchange]['trade_col_name_list']

    for pair in tracked_symbols_exchange_format:
        pair = convert_symbol(pair, in_exchange=exchange, out_exchange='universal')

        lock.acquire()
        live_fp = get_data_file_path(data_type='trade', pair=pair, date='live', exchange=exchange)

        try:
            recent_trades = pd.read_csv(live_fp, names=trade_col_names, index_col=False)

            # only keep recent trades within cutoff time threshold
            subtract_time = params['active_services']['trades'][exchange]['secs_of_live_trades']
            live_trade_cutoff_time = time.time() - subtract_time
            recent_trades = recent_trades[recent_trades['msg_time'] > live_trade_cutoff_time]

            # re-write live trade file
            recent_trades.to_csv(live_fp, header=False, index=False)

        # happens auto for new pairs
        except FileNotFoundError:
            print('debug 1: FileNotFoundError: ' + str(live_fp), flush=True)
            pass
        except TypeError:
            send_email(subject='ALGOS UPDATE: ' + exchange + 'collection error',
                       message=(('we have a problem \n' * 10) + '\n'
                                + 'msg_time type:  ', str(type(recent_trades['msg_time']))
                                + 'NEEDS DEBUGGING \n \n \n error in trim_live_files \n \n error below \n \n' \
                                + str(e)),
                       script=script
                       )
        lock.release()

    pass


###PAUL may need a new function as shown below
def kill_scraper_for_sysd_autostart(conn_key, reason=""):
    global this_scripts_process_ID
    global bm

    # send email notification
    now = str(time.gmtime(time.time()))
    subject = 'ALGOS UPDATE:' + exchange + ' collection ---- ended by sysd autorestart'
    message = 'The data scraper for binance failed at ' + now + '\n' \
              + ' there will be a follow up email when a new instance is successfully started' + '\n' \
              + 'process ID of the script that failed: ' + str(this_scripts_process_ID) + '\n' + '\n' \
              + 'Reason: ' + reason

    send_email(subject, message, script=script)

    # stop the socket. close the client
    bm.stop_socket(conn_key)
    bm.close()

    # stop reactor ###PAUL TODO i don' think this should ever throw an error by no time for testing right now...
    try:
        reactor.stop()
    except:
        pass

    # sys.exit() ### this is providing problems because it is held in a try/catch statement use line below
    raise TimeoutError


# be sure we are still recieving messages
def heartbeat_check(params=params):
    # # DEBUG conditional... stop the script after 1 min 20 seconds
    # if now > START_TIME + 40:
    #     print('DEBUG: Starting new script', flush=True)
    #     start_backup_scraper(conn_key)

    global conn_key
    global last_msg_time
    now = time.time()

    # wait 2 seconds... ###PAUL
    # time.sleep(2)
    # if no msg in last 30 seconds
    no_message_timeout = params['active_services']['trades'][exchange]['no_message_timeout']
    if now > last_msg_time + no_message_timeout:  # ###PAUL consider using global var heartbeat_check_interval
        print('NO MESSAGE FOR TOO LONG: killing process for auto-restart by systemd', flush=True)
        kill_scraper_for_sysd_autostart(conn_key, reason='   heartbeat_check() time out v4')


def notify_of_process_start():
    global this_scripts_process_ID
    now_time_string = str(time.gmtime(time.time()))

    message = 'Process ID: ' + str(this_scripts_process_ID) + '\n' + \
              'Start Time: ' + now_time_string

    send_email(subject='ALGOS UPDATE: ' + exchange + ' ---- collection started',
               message=message,
               script=script)


# run everything
def main(params=params):
    """run all the functions defined in scraper above
    """
    global conn_key

    notify_of_process_start()

    # start websocket
    conn_key = bm.start_multiplex_socket(pair_collection_list, process_message)

    # live file trim task
    secs_between_trims = params['active_services']['trades'][exchange]['secs_between_trims']
    file_trim_task = task.LoopingCall(f=trim_live_files)
    file_trim_task.start(secs_between_trims)  # call every sixty seconds

    # heartbeat check task... make sure still recieving messages
    heartbeat_interval = params['active_services']['trades'][exchange]['message_heartbeat_check']
    heartbeat_check_task = task.LoopingCall(f=heartbeat_check)
    heartbeat_check_task.start(heartbeat_interval)

    # then start the socket manager
    bm.start()


try:
    main()
    print('----------------------   data_scrape.py ran fully  ------------------\n'*10, flush=True)
except Exception as e:
    exc_type, exc_value, exc_traceback = sys.exc_info()
    issues = traceback.format_exception(exc_type, exc_value, exc_traceback)

    reason = ""
    for issue in issues:
        reason += issue

    while True:
        kill_scraper_for_sysd_autostart(conn_key, reason=reason)

        # this above should work once

    # final layer of quitting, incase all else fails
    raise TimeoutError
    sys.exit()
