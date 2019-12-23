import re
import sys
import os
import yaml
import collections
import logging
import pathlib
import cloudscraper
import posixpath
import traceback
from tqdm import tqdm
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from urllib.parse import urlsplit


class VersionNotFound(Exception):
    def __init__(self, version):
        super().__init__(self, f'Version {version} not found')
        self.version = version


class DownloadIncomplete(Exception):
    def __init__(self):
        super().__init__(self, 'Download Incomplete')


class MinecraftCurseModDownload():
    logger = logging.getLogger(__name__)

    def __init__(self):
        self.logger.addHandler(logging.StreamHandler(sys.stdout))
        self.logger.setLevel(logging.INFO)

        self.env_config = {
            'download-folder': 'mods'
        }
        if os.path.isfile('env_config.yaml'):
            with open('env_config.yaml', 'r', encoding='utf-8') as f:
                self.env_config.update(yaml.load(f, Loader=yaml.FullLoader))

        with open('env_config.yaml', 'w', encoding='utf-8') as f:
            yaml.dump(self.env_config, f)

        self.session = cloudscraper.create_scraper()
        self.download_folder = self.env_config['download-folder']

    def download(self, mods_info_file):
        mods_info_dict = {}
        with open(mods_info_file, 'r', encoding='utf-8') as f:
            mods_info_dict = yaml.load(f, Loader=yaml.FullLoader)

        mod_urls = set(self.flat_gen(mods_info_dict['Mods']))
        for i, mod_url in enumerate(mod_urls):
            self.logger.info(f'Downloading {mod_url} ({i+1}/{len(mod_urls)})')
            try:
                if re.match(r'https?://www.curseforge.com/minecraft/mc-mods/', mod_url):
                    self.download_file(
                        self.parse_curse_url(mod_url, mods_info_dict))
                else:
                    self.download_file(mod_url)
            except Exception:
                tb = traceback.format_exc()
                self.logger.error(f'Error downloading {mod_url}')
                self.logger.error(f'{tb}')

    def get_html(self, url, *args, **kwargs):
        response = self.session.get(url, *args, **kwargs)
        soup = BeautifulSoup(response.text, 'html.parser')
        return soup

    def parse_curse_url(self, mod_url, config):
        if re.search(r'\/files\/\d+', mod_url) is None:
            file_page_url = mod_url + "/files/all"
            file_page_html = self.get_html(file_page_url)
            game_version_options = file_page_html.select(
                "select#filter-game-version > option")
            version_code = None
            for version_option in game_version_options:
                if version_option.text.strip() in config['Version']:
                    version_code = version_option.get("value")
                    break
            if not version_code:
                raise VersionNotFound(config['Version'])
            version_page_html = self.get_html(file_page_url, params={
                "filter-game-version": version_code
            })
            file_table_entries = version_page_html.select("table.listing tr")
            latest_file = file_table_entries[1]
            file_path = latest_file.select("td")[1].select_one("a").get("href")
            mod_url = urljoin(file_page_url, file_path)

        download_url = re.sub(r'\/files\/', '/download/', mod_url)
        return f'{download_url}/file'

    def download_file(self, url):
        pathlib.Path(self.download_folder).mkdir(parents=True, exist_ok=True)
        response = self.session.get(url, stream=True)
        response.raise_for_status()
        final_url = response.url
        file_name = posixpath.basename(urlsplit(final_url).path)
        total_size = int(response.headers.get('content-length', 0))
        block_size = 1024
        save_path = os.path.join(self.download_folder, file_name)
        if os.path.exists(save_path):
            self.logger.info("File exists, skipping")
            return
        progress = tqdm(total=total_size, unit='iB', unit_scale=True)
        with open(save_path, 'wb') as f:
            for data in response.iter_content(block_size):
                progress.update(len(data))
                f.write(data)
        progress.close()
        f.close()
        if total_size != 0 and progress.n != total_size:
            os.remove(save_path)
            raise DownloadIncomplete()

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
