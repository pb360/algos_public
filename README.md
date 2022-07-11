# algos (public)
#### this is a select group of scripts from my personal trading platform 

all code presented in this repo is written by myself

this is intended for prospective employers to gauge my programming skills

anyone who stumbles upon this may feel free to use this for their <b> personal </b> trading purposes. Nothing here should be considered open source for <b> corporate use </b>.

Anyone interested in using this code outside of their personal use, please email me at <i> paulboehringer@gmail.com</i>. 

* A description of the code in this repo 

* data_scrape_binance_foreign.py

  * connects to exchanges with a websocket and collects trades, saves trades to filepaths structured
    * daily trades
      * ./data/live/trades_daily/\<exchange\>/\<ticker\>/\<date\>.csv
    * live trades (all trades in the last 10 minutes)
      * ./data/live/trades_live/\<exchange\>/\<ticker\>.csv

* data_pipe_prices_from_trades.py

  * this pipes data from live trade files managed by the exchange data scraping bots 

    * ./data/live/price/\<exchange\>/\<ticker\>/1s/\<date\>.csv

    * ./data/live/price/\<exchange\>/\<ticker\>/60s/\<date\>.csv

* watchdog.py
  * makes sure the above are running
  * will spin up (or shut down) a systemd job for a trading bot with the script
    * bot_v2_general.py
      * this is a systemd bot that can be spunup to run momentum bots 
      * I have a v3 that does more (runs markowitz and ML based signals) however that is not "clean" enough for me to share publicly 
  * systemd_bot_spinup.py
    * create and start a systemd job that uses the above bot script along with signal type and parameters given to it
  * systemd_bot_shutdown.py
    * stop the systemd job for that bot / parameter combo  and delete the unit file 
  * watchdog also watches over the trading bots that it starts to ensure they are running. it will automatically stop and delete them when it notices they have been removed from a config file. 
