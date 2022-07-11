#!/home/paul/miniconda3/envs/crypto_data_scrape/bin/python3 -u
# -*- coding: utf-8 -*-

# ### imports
#
#
import os
import time
os.environ['TZ'] = 'UTC'
time.tzset()

from twisted.internet import task, reactor

# ### local imports
#
#
from utils import *
# from bot_utils import make_and_start_systemd_bot_service

params = config.params

add_constant = params['keys']['add_constant']
add_position = params['keys']['add_position']
word = params['keys']['comp_p_word']
word = word + str(int(word[add_position]) + add_constant)

device_name = params['device_info']['device_name']


# ###PAUL this function should be in utils... dont want to move it now cause both servers running
# used a few times to restart services, good because it allows for mode switching easily for manual updates
def restart_service(service_type, params_t, exchange=None, port=None, pword=word, mode='hard_restart'):
    """takes given parameters and will restart (if cooldown doesn't override the restart)

    output:
        params (dict): NOTE, this fn takes params in its own space, modifies it in functions that treat it globally
    """
    # can only receive an exchange OR a portfolio...
    if exchange is not None and port is not None:
        print('can only take a port OR an exchange')
        raise IOError
    if exchange is not None:  # we are restarting a trade collector or price maker
        _ = exchange
        service_dict = params_t['active_services'][service_type][exchange]
    if port is not None:  # restarting a portfolio
        _ = port
        service_dict = params_t['active_services'][service_type][port]

    service = service_dict['service']
    script = service_dict['script']
    last_restart = service_dict['last_restart']
    cool_down = service_dict['cool_down']

    # hasn't been long enough... return the same params_t dict and wait till next iteration
    if last_restart is not None and last_restart + cool_down > time.time():
        cooldown_str = ('---- WATCHDOG: COOLDOWN prevented restart ---- service_type ' + service_type + ' ---- ' + _
                        + ' --- aka script ---- ' + script + ' \n') * 5
        print(cooldown_str)
        return params_t

    else:
        send_email(subject='WATCHDOG UPDATE: ' + service + ' ---- restart',
                   message=('restarting: \n'
                            + '---- service: ' + service
                            + '---- script: ' + script),
                   script=script)
        if mode == 'restart':
            command = 'sudo systemctl restart ' + service + '.service'
            p = os.system('echo %s|sudo -S %s' % (pword, command))
        if mode == 'hard_restart':

            try:
                stop_command = 'sudo systemctl stop ' + service + '.service '
                p = os.system('echo %s|sudo -S %s' % (pword, stop_command))
            except:
                print(3*('watchdog ---- stop errored on service: ' + service), flush=True)

            command = 'sudo chmod u+x ' + script \
                      + '&& sudo systemctl daemon-reload' \
                      + '&& sudo systemctl enable ' + service + '.service' \
                      + '&& sudo systemctl restart ' + service + '.service'
            p = os.system('echo %s|sudo -S %s' % (pword, command))

        # reset last_restart and put the new service_dict back into params_t
        service_dict['last_restart'] = time.time()
        params_t['active_services'][service_type][_] = service_dict

        return params_t


def trade_watchdog():
    """checks if we are getting trades and will hard reset the trade datascrape service
    """

    global params

    print("-=-=-=-=-=-=-=-= ALGOS WATCHDOG: ------------ CHECKING TRADES -=-=-=-=-=-=-=-=\n", flush=True)

    for exchange in params['active_services']['trades'].keys():
        service = params['active_services']['trades'][exchange]['service']
        restart_notification_string = 3 * ('NOT GETTING TRADES - exchange: ' + exchange +
                                           ' - RESTARTING  -  ' + service + '\n')

        try:
            check_ticker = params['active_services']['trades'][exchange]['ticker_to_check']
            no_trade_time = params['active_services']['trades'][exchange]['no_trade_time']
            trades = get_live_trades_data(check_ticker, exchange=exchange)
            time_since_last_btc_trade = time.time() - trades.iloc[-1]['trade_time']

            # restart ---- too long since last trade received
            if time_since_last_btc_trade > no_trade_time:  # restart systemd service
                # restart it
                print(restart_notification_string, flush=True)
                params = restart_service(service_type='trades',
                                         params_t=params,
                                         exchange=exchange,
                                         )

            else:
                params['active_services']['trades'][exchange]['error_count'] = 0
                print("-=-=-=-=-=-=-=-= ALGOS WATCHDOG: trades being received for     " + exchange + "    -=-=-=-=-=\n",
                      flush=True)

        # some exchanges are slow, so we will give 3 checks untill we force a restart
        except (FileNotFoundError, IndexError):
            params['active_services']['trades'][exchange]['error_count'] += 1
            if params['active_services']['trades'][exchange]['error_count'] > 3:
                # restart it
                print('-=-=-=-=-=-=-=-= ALGOS WATCHDOG: max ERROR count for exchange: ' + exchange, flush=True)
                print(restart_notification_string, flush=True)
                # restart_service(service, script)
                params = restart_service(service_type='trades',
                                         params_t=params,
                                         exchange=exchange,
                                         port=None,
                                         )

    return None


def price_crypto_making_watchdog():
    """checks if we are making prices from trades and will hard reset orders.py service
    """

    global params

    print('-=-=-=-=-=-=-=-= ALGOS WATCHDOG: ------------ CHECKING PRICES -=-=-=-=-=-=-=-=\n', flush=True)
    for exchange in params['active_services']['prices'].keys():
        service = params['active_services']['prices'][exchange]['service']
        service_restart_str = ('-=-=-=-=- RESTARTING CRYPTO PRICE MAKER: ' + service + ' -=-=-') * 5

        try:
            check_ticker = params['active_services']['trades'][exchange]['ticker_to_check']
            prices = get_data(data_type='prices', pair=check_ticker, exchange=exchange)

            # get most recent BTC trade (or whatever is the highest frequency)
            most_recent_price_timestamp = pd.to_datetime(prices.index[-1])
            epoch_price_time = (most_recent_price_timestamp - pd.Timestamp("1970-01-01")) // pd.Timedelta('1s')
            seconds_since_last_price = time.time() - epoch_price_time

            if seconds_since_last_price > params['active_services']['prices'][exchange]['no_price_time']:
                # restart it
                print(service_restart_str + ' DUE TO EXCHANGE: ' + exchange + '\n', flush=True)
                params = restart_service(service_type='prices',
                                         params_t=params,
                                         exchange=exchange,
                                         )

            else:
                print('-=-=-=-=-=-=-=-= ALGOS WATCHDOG prices being made for    ' + exchange + '    -=-=-=-=-=-=-=-=\n',
                      flush=True)
                params['active_services']['prices'][exchange]['error_count'] = 0

        except FileNotFoundError:  # sometimes the price may not have been made ... weird stuff happens...
            params['active_services']['prices'][exchange]['error_count'] += 1

            if params['active_services']['prices'][exchange]['error_count'] > 3:
                print('-=-=-=-=-=- ALGOS WATCHDOG: price making RESTART FROM ERRORS  -=-=-=-=-=-' * 10, flush=True)
                print(restart_str, flush=True)
                params = restart_service(service_type='prices',
                                         params_t=params,
                                         exchange=exchange,
                                         )

    return None


def check_if_orders_being_updated():
    """checks the last time orders updated for a port_name (ie. the strategy runnning). If too long it will
    return False, which is used to indicate that the systemd service for that portfolio needs to be restarted
    if True, then orders are being updated then we are good.
    """

    global params
    global word

    print('-=-=-=-=-=-=-=-= ALGOS WATCHDOG: ------------ CHECKING LIVE BOTS -=-=-=-=-=-=-=-= on ---- ' \
          + device_name + '\n', flush=True)

    active_ports = params['active_services']['ports'].keys()

    if len(active_ports) == 0:
        print('-=-=-=-=-=-=-=-= no bots running on ---- ' + device_name, flush=True)
    for port_name in active_ports:
        # try:
        exchange = params['active_services']['ports'][port_name]['exchange']
        service = params['active_services']['ports'][port_name]['service']
        signal_based_order_interval = params['active_services']['ports'][port_name]['signal_based_order_interval']
        restart_str = 3 * ('-=-=-=-=- ALGOS - RESTARTING LIVE BOT: ' + service + ' -=-=-=-=-=-=-\n')

        fp = get_data_file_path(data_type='last_order_check',
                                pair=None,
                                date='live',
                                port=port_name,
                                exchange=exchange)

        try:
            with open(fp, 'r') as f:
                last_update_time = f.readline()

                if last_update_time == '':
                    last_update_time = 0  # this means we haven't checked yet
                last_update_time = float(last_update_time)
                time_since_last_order_update = time.time() - last_update_time
            os.chmod(fp, 0o777)
            new_file = False

        except FileNotFoundError:
            print(10*('   WATCHDOG - new systemd service to start up ---- ' + fp + '\n'))
            new_file = True  # since its not there this is the first time spinning up a portfolio

        # if the service does not exist or the order check file is not found, spin up service
        service_exists = os.path.isfile('/usr/lib/systemd/system/' + service + '.service')
        if new_file or not service_exists:
            print(5 * ('   WATCHDOG - making service for - port_name ---- ' + port_name + '\n'), flush=True)

            # handle script permissions
            os.chmod('/mnt/algos/systemd_bot_spinup.py', 0o777)
            give_bot_spinup_permissions = 'sudo chmod u+x /mnt/algos/systemd_bot_spinup.py'
            _ = os.system('echo %s|sudo -S %s' % (word, give_bot_spinup_permissions))

            os.chdir('/mnt/algos/')
            command = './systemd_bot_spinup.py ' + port_name
            _ = os.system('echo %s|sudo -S %s' % (word, command))

        # too long without order ---- over 3 order cycles without updating the last order check file is too long
        elif time_since_last_order_update > signal_based_order_interval*3:
            # restart itclear
            print(restart_str, flush=True)
            params = restart_service(service_type='ports',
                                     params_t=params,
                                     port=port_name,
                                     )

        else:  # orders being checked / placed for this portfolio
            params['active_services']['ports'][port_name]['error_count'] = 0
            print('-=-=-=-=-=-=-=-= ALGOS WATCHDOG:   port   ' + port_name + '  ---- is active on   ' + exchange
                  + '   -=-=-=-=-=\n',
                  flush=True)

        # except:
        #     params['active_services']['ports'][port_name]['error_count'] += 1
        #
        #     if params['active_services']['ports'][port_name]['error_count'] > 3:
        #         print('---- WACHDOG: restarting port due to ERRORS ----'*5, flush=True)
        #         print(restart_str, flush=True)
        #         params = restart_service(service_type='ports',
        #                                  params_t=params,
        #                                  port=port_name,
        #                                  )


def check_down_ports_not_running():
    down_ports = params['active_services']['down_ports']


    for port_name in down_ports.keys():
        print(5 * ('   WATCHDOG - shutting down service for - port_name ---- ' + port_name + '\n'), flush=True)

        # handle script permissions
        os.chmod('/mnt/algos/systemd_bot_shutdown.py', 0o777)
        command = 'sudo chmod u+x /mnt/algos/systemd_bot_shutdown.py'
        _ = os.system('echo %s|sudo -S %s' % (word, command))


        os.chdir('/mnt/algos/')
        command = './systemd_bot_shutdown.py ' + port_name
        _ = os.system('echo %s|sudo -S %s' % (word, command))

    return None


print('---- WATCHDOG: started ---- \n' * 10, flush=True)

# run this task once at the beginning of each watchdog update (re-run) should be sufficient
check_down_ports_not_running()

# trade reception watchdog
check_trades_interval = params['active_services']['watchdog']['check_trades_interval']
trade_watchdog_task = task.LoopingCall(f=trade_watchdog)
trade_watchdog_task.start(check_trades_interval)

# price making watch dog looping task
check_prices_interval = params['active_services']['watchdog']['check_prices_interval']
price_crypto_watchdog_task = task.LoopingCall(f=price_crypto_making_watchdog)
price_crypto_watchdog_task.start(check_prices_interval)

# portfolio order watchdog
check_order_out_interval = params['active_services']['watchdog']['check_order_out_interval']
livebot_check_task = task.LoopingCall(f=check_if_orders_being_updated)
livebot_check_task.start(check_order_out_interval)

# run it all
reactor.run()
