#!/home/paul/miniconda3/envs/algos/bin/python3 -u

"""this script puts a bot together and launches it.
it should exist on its own as a utility used by the watchdog
DO NOT DELETE AND DO NOT TOUCH UNLESS NECESSARY
"""

import sys
from bot_utils import stop_and_remove_systemd_bot_service

def stop_and_remove_systemd_bot_service(port_name, pword=word):
    """this is included in this script for public visibility 
    normally this sits in a different location
    """

    service = params['active_services']['down_ports'][port_name]['service']

    commands = []
    commands.append('sudo systemctl stop ' + service + '.service')
    commands.append('sudo systemctl disable ' + service + '.service')
    commands.append('sudo rm /usr/lib/systemd/system/' + service + '.service')  # remove job's unit file
    commands.append('sudo rm /etc/systemd/system/' + service + '.service')     # remove jobs
    commands.append('sudo systemctl daemon-reload')
    commands.append('sudo systemctl reset-failed')

    for command in commands:
        # try:
        _ = os.system('echo %s|sudo -S %s' % (pword, command))
    # except:
    #     print(5*('STOP AND REMOVE JOB: command failed ---- ' + command + '\n'), flush=True)

    return None

port_name = sys.argv[1]
stop_and_remove_systemd_bot_service(port_name)
