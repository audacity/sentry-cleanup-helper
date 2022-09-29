import os
from datetime import datetime
from datetime import timedelta
import dateutil.parser
import pytz as pytz
import requests
import re

dsym_endpoint = "https://sentry.audacityteam.org/api/0/projects/sentry/audacity-crash/files/dsyms/"

audacity_files = [
    re.compile(r"Audacity.*"),
    re.compile(r"audacity.*"),
    re.compile(r"lib-.+"),
    re.compile(r"mod-.+"),
    re.compile(r"crashreporter.*"),
    re.compile(r"Wrapper.*"),
]


def format_file_size(size):
    if size < 1024:
        return f'{size} B'
    elif size < 1024 * 1024:
        return f'{size / 1024:.2f} KB'
    elif size < 1024 * 1024 * 1024:
        return f'{size / 1024 / 1024:.2f} MB'
    else:
        return f'{size / 1024 / 1024 / 1024:.2f} GB'


class SentryAuth(requests.auth.AuthBase):
    def __call__(self, r):
        r.headers["Authorization"] = f'Bearer {os.environ["SENTRY_TOKEN"]}'
        return r


class SentryFile:
    def __init__(self, file_json):
        self.id = file_json["id"]
        self.date_created = dateutil.parser.isoparse(file_json['dateCreated'])
        self.size = int(file_json["size"])
        self.name = file_json["objectName"]


class Contex:
    now = datetime.now(tz=pytz.utc)
    releases = []

    deleted_files_count = 0
    deleted_files_size = 0

    skipped_release_files_count = 0
    skipped_release_files_size = 0

    skipped_files_count = 0
    skipped_files_size = 0

    processed_files_count = 0

    non_audacity_libs = set()

    def __init__(self):
        self._get_github_releases()
        self.safe_time = self.now - timedelta(days=7)

        self.session = requests.Session()

    def _get_github_releases(self):
        current_url = "https://api.github.com/repos/audacity/audacity/releases"

        s = requests.Session()

        while None != current_url:
            print(f'Requesting {current_url}...')

            r = s.get(current_url)

            for release_json in r.json():
                self.releases.append(dateutil.parser.isoparse(release_json['published_at']))

            if "next" in r.links:
                current_url = r.links["next"]["url"]
            else:
                current_url = None

    def _is_in_release_timeframe(self, file):
        delta = timedelta(days=1)
        for release in self.releases:
            if release - delta < file.date_created < release:
                return True

        return False

    def _is_audacity_file(self, file):
        for pattern in audacity_files:
            if pattern.match(file.name):
                return True

        return False

    def process_file(self, file):
        self.processed_files_count = self.processed_files_count + 1

        skipped = False
        if self._is_in_release_timeframe(file):
            skipped = True
            self.skipped_release_files_count = self.skipped_release_files_count + 1
            self.skipped_release_files_size = self.skipped_release_files_size + file.size
            print(
                f'({self.processed_files_count}) Skipped file {file.name} ({file.id}, {datetime.isoformat(file.date_created)}): matches release.')
        elif file.date_created > self.safe_time:
            print(
                f'({self.processed_files_count}) Skipped file {file.name} ({file.id}, {datetime.isoformat(file.date_created)}): too new.')
            skipped = True

        is_audacity_file = self._is_audacity_file(file)

        if not skipped and not is_audacity_file:
            if file.name not in self.non_audacity_libs:
                print(f'({self.processed_files_count}) Skipped file {file.name} ({file.id}, {datetime.isoformat(file.date_created)}): first occurrence of the file.')
                skipped = True

        if skipped:
            if not is_audacity_file:
                self.non_audacity_libs.add(file.name)

            self.skipped_files_count = self.skipped_files_count + 1
            self.skipped_files_size = self.skipped_files_size + file.size
            return

        print(
            f'({self.processed_files_count}) Deleting file {file.name} ({file.id}, {datetime.isoformat(file.date_created)}).')
        self.deleted_files_count = self.deleted_files_count + 1
        self.deleted_files_size = self.deleted_files_size + file.size

        url = f'{dsym_endpoint}?id={file.id}'
        r = self.session.delete(url, auth=SentryAuth())
        if r.status_code != 204:
            print(f'Error deleting file {file.name} ({file.id}, {datetime.isoformat(file.date_created)}): {r.status_code} {r.text}')
            raise Exception(f'Error deleting file {file.name} ({file.id}, {datetime.isoformat(file.date_created)}): {r.status_code} {r.text}')

    def print_stats(self):
        print(f'Processed files: {self.processed_files_count}')
        print(f'Deleted files: {self.deleted_files_count}')
        print(f'Deleted files size: {format_file_size(self.deleted_files_size)}')
        print(f'Skipped files: {self.skipped_files_count}')
        print(f'Skipped files size: {format_file_size(self.skipped_files_size)}')
        print(f'Skipped release files: {self.skipped_release_files_count}')
        print(f'Skipped release files size: {format_file_size(self.skipped_release_files_size)}')


def request_dsyms(context):
    has_more = True
    current_url = dsym_endpoint

    s = requests.Session()

    while has_more:
        print(f'Requesting {current_url}...')
        r = s.get(current_url, auth=SentryAuth())

        for file_json in r.json():
            file = SentryFile(file_json)
            context.process_file(file)

        has_more = r.links["next"]["results"] == 'true'
        current_url = r.links["next"]["url"]


# Press the green button in the gutter to run the script.
if __name__ == '__main__':
    context = Contex()
    request_dsyms(context)
    context.print_stats()
