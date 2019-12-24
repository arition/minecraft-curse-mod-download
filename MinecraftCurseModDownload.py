import re
import sys
import os
import yaml
import collections
import logging
import pathlib
import hashlib
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
        self.mods_lock_dict = {"files": {}, "mods": {}}
        self.mods_lock_updated = {}

    # update: if set to True, would update existing mods in Lock file to latest version, otherwise, would always use existing version in Lock file if present

    def download(self, mods_info_file, update=False):
        mods_info_dict = {}
        with open(mods_info_file, 'r', encoding='utf-8') as f:
            mods_info_dict = yaml.load(f, Loader=yaml.FullLoader)

        mods_lock_file = f"{mods_info_file}.lock"
        if os.path.exists(mods_lock_file):
            with open(mods_lock_file, 'r', encoding='utf-8') as f:
                self.mods_lock_dict = yaml.load(f, Loader=yaml.FullLoader)

        mod_urls = set(self.flat_gen(mods_info_dict['Mods']))
        for i, mod_url in enumerate(mod_urls):
            self.logger.info(f'Downloading {mod_url} ({i+1}/{len(mod_urls)})')
            try:
                if not update and mod_url in self.mods_lock_dict['mods']:
                    file_name = self.mods_lock_dict['mods'][mod_url]
                    download_url = self.mods_lock_dict['files'][file_name]['url']
                    self.download_file(mod_url, download_url, file_name)
                else:
                    if re.match(r'https?://www.curseforge.com/minecraft/mc-mods/', mod_url):
                        download_url = self.parse_curse_url(
                            mod_url, mods_info_dict)
                        self.download_file(mod_url, download_url)
                    else:
                        self.download_file(mod_url, mod_url)
            except Exception:
                tb = traceback.format_exc()
                self.logger.error(f'Error downloading {mod_url}')
                self.logger.error(f'{tb}')

        self.mods_lock_dict['mods'] = self.mods_lock_updated
        with open(mods_lock_file, 'w', encoding='utf-8') as f:
            yaml.dump(self.mods_lock_dict, f)

    # Download mods according to Lock file
    # Lock file contains two dicts:
    #    'mods' dict stores mapping from mods (as identified by mod URL) to their locked version file names
    #    'files' dict stores sha256sum of mod versions, indexed by version file names
    def download_locked_version(self, mods_lock_file):
        with open(mods_lock_file, 'r', encoding='utf-8') as f:
            self.mods_lock_dict = yaml.load(f, Loader=yaml.FullLoader)
        total_mods_number = len(self.mods_lock_dict['mods'])
        for i, mod_url in enumerate(self.mods_lock_dict['mods']):
            self.logger.info(
                f'Downloading {mod_url} ({i+1}/{total_mods_number})')
            try:
                file_name = self.mods_lock_dict['mods'][mod_url]
                download_url = self.mods_lock_dict['files'][file_name]['url']
                self.download_file(mod_url, download_url, file_name)
            except Exception:
                tb = traceback.format_exc()
                self.logger.error(f'Error downloading {mod_url}')
                self.logger.error(f'{tb}')

    def get_html(self, url, *args, **kwargs):
        response = self.session.get(url, *args, **kwargs)
        response.raise_for_status()
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

    # mod_url: URL for identifying the mod in modlist.yml
    # download_url: URL for downloading the specific version of the mod
    # file_name: file name for saving the downloaded file
    #
    # This function would perform check on existing files accroding to sha256sums from Lock file
    # If file_name is set to an non-empty string, pre-request check for existing files would be performed, this helps performance
    # This function would update Lock file if it finds that the version downloaded for a mod is changed
    def download_file(self, mod_url, download_url, file_name=""):
        if file_name and self.hash_check(file_name):
            self.logger.info("File exists, skipping")
            return
        pathlib.Path(self.download_folder).mkdir(parents=True, exist_ok=True)
        response = self.session.get(download_url, stream=True)
        response.raise_for_status()
        final_url = response.url
        if not file_name:
            file_name = posixpath.basename(urlsplit(final_url).path)
            if self.hash_check(file_name):
                self.logger.info("File exists, skipping")
                return
        save_path = os.path.join(self.download_folder, file_name)
        total_size = int(response.headers.get('content-length', 0))
        block_size = 1024
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
        if file_name in self.mods_lock_dict['files']:
            if not self.hash_check(file_name):
                os.remove(save_path)
                raise DownloadIncomplete()
        else:
            self.mods_lock_dict['files'][file_name] = {
                "url": download_url,
                "mod_url": mod_url,
                "sha256sum": self.get_sha256_for_file(save_path)
            }
        if file_name != self.mods_lock_dict['mods'].get(mod_url, ''):
            self.logger.info(f'{mod_url}: Locked version updated')
        self.mods_lock_updated[mod_url] = file_name

    # Check if file_name in download folder matches the version recorded in Lock file
    # If file_name is not recorded in Lock file, would return False
    def hash_check(self, file_name):
        save_path = os.path.join(self.download_folder, file_name)
        if os.path.exists(save_path) and file_name in self.mods_lock_dict['files']:
            existing_file_hash = self.get_sha256_for_file(save_path)
            locked_hash = self.mods_lock_dict['files'][file_name].get(
                'sha256sum', '')
            return locked_hash == existing_file_hash
        return False

    def get_sha256_for_file(self, filepath):
        sha256_hash = hashlib.sha256()
        with open(filepath, 'rb') as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
            return sha256_hash.hexdigest()

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
