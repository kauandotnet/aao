from datetime import datetime as dt
import json
import os
import time

from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC

from .spider import Spider


class SpiderBet365(Spider):
    name = 'bet365'
    base_url = 'https://www.bet365.com/'
    file_path = os.path.dirname(__file__)
    table_path = os.path.join(file_path, 'tables', f'{name}.json')
    with open(table_path) as f:
        table = json.load(f)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.start_session()
        self._soccer = Soccer(self.browser, self.log, self.table)

    def start_session(self):
        self.log.info('starting new session ...')
        self.homepage()
        lang = '//ul[@class="lpnm"]/li/a'
        lang_bt = self.wait.until(EC.element_to_be_clickable((By.XPATH, lang)))
        time.sleep(2)
        lang_bt.click()
        if 'lng' not in self.browser.current_url:
            lang_bt = self.wait.until(EC.element_to_be_clickable((By.XPATH, lang)))
            time.sleep(2)
            lang_bt.click()
        self.log.debug('set english language')
        self.login()
        self.change_odds_format('Decimal')

    def change_odds_format(self, format_):
        # three formats possible: Fractional, Decimal, American
        drop = '//div[@class="hm-OddsDropDownSelections hm-DropDownSelections "]'
        type_ = (f'//div[@class="hm-DropDownSelections_ContainerInner "]'
                 f'/a[text() = "{format_}"]')
        drop_bt = self.wait.until(EC.element_to_be_clickable((By.XPATH, drop)))
        drop_bt.click()
        self.log.debug('set odds format to decimal')
        self.browser.find_element_by_xpath(type_).click()

    def login(self):
        self.log.debug(f'trying to log using {self.username} ...')
        username_box, password_box = self.browser.find_elements_by_xpath(
            '//input[@class="hm-Login_InputField "]')
        password_box_hidden = self.browser.find_element_by_xpath(
            '//input[@class="hm-Login_InputField Hidden "]')
        submit_button = self.browser.find_element_by_class_name(
            'hm-Login_LoginBtn')
        username_box.clear()
        username_box.send_keys(self.username)
        password_box.click()
        password_box_hidden.clear()
        password_box_hidden.send_keys(self.password)
        submit_button.click()
        self.browser.find_element_by_class_name('hm-UserName_UserNameShown')
        # close the pop up that ask to confirm the identity
        self.log.debug('closing the confermation-identity pop up ...')
        time.sleep(2)
        self.browser.get(self.base_url)
        self.log.info(f'logged in with {self.username}')

    @property
    def soccer(self):
        xpath = '//div[@class="wn-Classification "][text()="Soccer"]'
        is_soccer_close = self.browser.find_elements_by_xpath(xpath)
        if is_soccer_close:
            is_soccer_close[0].click()
        self.log.debug('opening soccer page ...')
        return self._soccer


class Soccer(SpiderBet365):

    def __init__(self, browser, log, table):
        self.browser = browser
        self.log = log
        self.log.debug('loading countries table ...')
        self.countries_dict = table['soccer']['countries']
        self.log.debug('loading leagues table ...')
        self.leagues_dict = table['soccer']['leagues']

    def _country(self, country_name):
        try:
            self.country = country_name
            xpath = f'//div[@class="sm-Market "]//div[text()="{country_name}"]'
            country = self.browser.find_element_by_xpath(xpath)
            header = country.find_element_by_xpath('..').get_attribute('class')
            if header == 'sm-Market_HeaderClosed ':
                self.log.debug(f'expanding {country_name} tab ...')
                time.sleep(0.5)  # necessary
                country.click()

        except NoSuchElementException:
            msg = f'{country_name} not found in countries table'
            self.log.warning(msg)
            raise KeyError(f'{msg}. Check the docs for a list of supported countries')

    def _league(self, league_name):
        try:
            xpath = (f'//div[@class="sm-Market "]//div[text()="{self.country}"]'
                     f'/../..//div[text()="{league_name}"]')
            league = self.browser.find_element_by_xpath(xpath)
            league.click()
            self.league = league_name
            self.log.debug(f'opened {league_name} page.')

        except NoSuchElementException:
            msg = f'{league_name} not found in {self.country}'
            self.log.warning(msg)
            raise KeyError(f'{msg}. Check the docs for a list of supported leagues')

    def _matches(self, country, league):
        self._country(country)
        self._league(league)
        self.log.info(f'* start scraping: {country}, {league} *')
        # scrape events
        events = []
        days = ('Sun ', 'Mon ', 'Tue ', 'Wed ', 'Thu ', 'Fri ', 'Sat ')
        rows = self.browser.find_elements_by_xpath(
            '//div[@class="sl-MarketCouponFixtureLabelBase '
            'gl-Market_General gl-Market_HasLabels "]/div')
        for r in rows:
            if r.text.startswith(days):
                date = r.text
                continue
            _time, teams = r.text.split('\n')
            home_team, away_team = teams.split(' v ')
            dt_str = ' '.join([str(dt.now().year), date, _time])
            datetime = dt.strptime(dt_str, '%Y %a %d %b  %H:%M')
            timestamp = int(dt.timestamp(datetime))
            event = {
                'timestamp': timestamp,
                'datetime': datetime,
                'country': country,
                'league': league,
                'home_team': home_team,
                'away_team': away_team,
            }
            events.append(event)
        self.log.debug(' * got events data')

        # scrape odds
        k = len(events)
        odds = [{} for i in range(k)]

        def get_odds(index_):
            self.browser.find_element_by_class_name(
                'cm-CouponMarketGroup_ChangeMarket').click()
            self.browser.find_elements_by_class_name('wl-DropDownItem')[index_].click()
            xpath_odds = '//span[@class="gl-ParticipantOddsOnly_Odds"]'
            o = self.browser.find_elements_by_xpath(xpath_odds)
            return [float(i.text) for i in o]

        # market_1X2
        o = get_odds(0)
        for i, _1, _X, _2 in zip(range(k), o[:], o[k:-k], o[-k:]):
            odds[i]['full_time_result'] = {'1': _1, 'X': _X, '2': _2}
        self.log.debug(' * got 1 x 2 odds')

        # market_double_chance
        o = get_odds(1)
        for i, _1X, _X2, _12 in zip(range(k), o[:], o[k:-k], o[-k:]):
            odds[i]['double_chance'] = {'1X': _1X, 'X2': _X2, '12': _12}
        self.log.debug(' * got double chance odds')

        # market under_over_2.5
        o = get_odds(2)
        for i, over, under in zip(range(k), o[:k], o[k:]):
            odds[i]['under_over_2.5'] = {'under': under, 'over': over}
        self.log.debug(' * got under/over 2.5 odds')

        # market both_teams_to_score
        o = get_odds(3)
        for i, yes, no in zip(range(k), o[:k], o[k:]):
            odds[i]['both_teams_to_score'] = {'yes': yes, 'no': no}
        self.log.debug(' * got both teams to score odds')

        # market draw_no_bet
        o = get_odds(7)
        for i, _1, _2 in zip(range(k), o[:k], o[k:]):
            odds[i]['draw_no_bet'] = {'1': _1, '2': _2}
        self.log.debug(' * got draw no bet odds')

        self.log.info('finished the scrape')
        return events, odds

    def odds(self, country_std, league_std):
        league = self.leagues_dict[country_std][league_std]
        country = self.countries_dict[country_std]
        if league is None:
            raise KeyError(f'{league_std} is not supported in {self.name}')
        return self._matches(country, league)


# TODO add here other sport class
