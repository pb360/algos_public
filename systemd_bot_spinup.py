#!/home/paul/miniconda3/envs/algos/bin/python3 -u

"""this script puts a bot together and launches it.
it should exist on its own as a utility used by the watchdog
DO NOT DELETE AND DO NOT TOUCH UNLESS NECESSARY
"""

import sys
from bot_utils import make_and_start_systemd_bot_service

def make_and_start_systemd_bot_service(port_name, pword=word):
    """this is included in this script for public visibility
    normally this sits in a different location
    """
    
    port_params = params['active_services']['ports'][port_name]

    service = port_params['service']
    script = port_params['script']

    sysd_str = """[Unit]
Description=%s
StartLimitIntervalSec=5
StartLimitBurst=10
Wants=network.target
After=network.target

[Service]
User=paul
ExecStartPre=/bin/sleep 10
ExecStart=%s %s
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target""" % (service,
                                 script,
                                 port_name,
                                 )



    command = 'sudo chmod u+x ' + script \
              + '&& sudo echo "' + sysd_str + '" > /usr/lib/systemd/system/' + service + '.service' \
              + '&& sudo systemctl enable ' + service + '.service' \
              + '&& sudo systemctl start ' + service + '.service'

    _ = os.system('echo %s|sudo -S %s' % (pword, command))

    return None

port_name = sys.argv[1]
make_and_start_systemd_bot_service(port_name)
