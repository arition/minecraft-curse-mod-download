from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.firefox_binary import FirefoxBinary
from selenium.webdriver.common.desired_capabilities import DesiredCapabilities
from webdriverdownloader import GeckoDriverDownloader
from webdriverdownloader import ChromeDriverDownloader
import re
import sys
import os
import threading
import time
import yaml
import collections
import logging
import json


class MinecraftCurseModDownload():
    logger = logging.getLogger(__name__)

    def __init__(self):
        self.logger.addHandler(logging.StreamHandler(sys.stdout))
        self.logger.setLevel(logging.INFO)

        self.env_config = {
            'driver': 'firefox',
            'firefox-path': '',
            'headless': True,
            'download-folder': 'mods'
        }
        if os.path.isfile('env_config.yaml'):
            with open('env_config.yaml', 'r', encoding='utf-8') as f:
                self.env_config.update(yaml.load(f, Loader=yaml.FullLoader))

        with open('env_config.yaml', 'w', encoding='utf-8') as f:
            yaml.dump(self.env_config, f)

        if 'driver' in self.env_config and self.env_config['driver'] == 'chrome':
            self.driver = self.configure_chrome_driver()
        else:
            self.driver = self.configure_firefox_driver()

    def configure_firefox_driver(self):
        gdd = GeckoDriverDownloader(download_root='webdriver', link_path='.')
        gdd.download_and_install()

        profile = webdriver.FirefoxProfile()
        profile.set_preference('browser.download.folderList', 2)
        profile.set_preference('browser.download.manager.showWhenStarting', False)
        profile.set_preference('browser.download.dir', os.path.abspath(self.env_config['download-folder']))
        profile.set_preference('browser.helperApps.neverAsk.saveToDisk', 'application/java-archive;application/x-java-archive;application/x-jar;application/x-amz-json-1.0;application/octet-stream')
        options = webdriver.FirefoxOptions()
        caps = DesiredCapabilities().FIREFOX
        caps['pageLoadStrategy'] = 'eager'
        options.headless = self.env_config['headless']

        if self.env_config['firefox-path'] != '':
            firefox_dev_binary = FirefoxBinary(self.env_config['firefox-path'])
            return webdriver.Firefox(capabilities=caps, options=options, firefox_binary=firefox_dev_binary, firefox_profile=profile)
        return webdriver.Firefox(capabilities=caps, options=options, firefox_profile=profile)

    def configure_chrome_driver(self):
        cdd = ChromeDriverDownloader(download_root='webdriver', link_path='.')
        cdd.download_and_install()

        options = webdriver.ChromeOptions()
        options.add_argument('user-data-dir=chrome_dir')
        options.add_argument('blink-settings=imagesEnabled=false')
        options.add_argument('safebrowsing-disable-download-protection')
        options.headless = self.env_config['headless']
        options.add_experimental_option('prefs', {
            'download.default_directory': os.path.abspath(self.env_config['download-folder']),
            'download.prompt_for_download': False
        })

        return webdriver.Chrome(options=options)

    def download(self, mods_info_file):
        mods_info_dict = {}
        with open(mods_info_file, 'r', encoding='utf-8') as f:
            mods_info_dict = yaml.load(f, Loader=yaml.FullLoader)

        for mod_url in set(self.flat_gen(mods_info_dict['Mods'])):
            self.logger.info(f'Downloading {mod_url}')
            if re.match(r'https?://www.curseforge.com/minecraft/mc-mods/', mod_url):
                self.download_file(self.parse_curse_url(mod_url, mods_info_dict))
            else:
                self.download_file(mod_url)
        # we never know if downloading has been completed, so just wait for 10 secs
        time.sleep(10)

    def parse_curse_url(self, mod_url, config):
        if re.search(r'\/files\/\d+', mod_url) is None:
            self.driver.get(mod_url)
            version_titles = self.driver.find_elements(By.CSS_SELECTOR, '.e-sidebar-subheader')
            version_urls = self.driver.find_elements(By.CSS_SELECTOR, '.cf-recentfiles')
            for version_title, version_url in zip(version_titles, version_urls):
                version = re.search(r'\d+\.\d+', version_title.text).group(0)
                if version not in config['Version']:
                    continue
                version_url_element = max(version_url.find_elements(By.CSS_SELECTOR, 'li'), key=lambda t: int(t.find_element(By.CSS_SELECTOR, 'abbr').get_attribute('data-epoch')))
                mod_url = version_url_element.find_element(By.CSS_SELECTOR, 'a').get_attribute('href')

        download_url = re.sub(r'\/files\/', '/download/', mod_url)
        return f'{download_url}/file'

    def download_file(self, url):
        self.driver.execute_script(f'window.open("{url}","_blank");')

    def quit(self):
        self.driver.quit()

    # https://stackoverflow.com/questions/16176742/python-3-replacement-for-deprecated-compiler-ast-flatten-function
    def flat_gen(self, x):
        def iselement(e):
            return not(isinstance(e, collections.Iterable) and not isinstance(e, str))
        for el in x:
            if isinstance(el, dict):
                for k in el.keys():
                    yield k
                    yield from self.flat_gen(el[k])
            elif iselement(el):
                yield el
            else:
                yield from self.flat_gen(el)
