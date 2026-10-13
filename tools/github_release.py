"""Publish signed artifacts to Farry; credentials remain in Git's credential manager."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import urllib.error
import urllib.request

REPOSITORY = 'victorccronemberger-blip/Farry'


def request(path, *, method='GET', data=None, content_type='application/json', length=None):
    token = os.environ.get('GITHUB_TOKEN')
    if not token:
        result = subprocess.run(['git', 'credential', 'fill'],
            input='protocol=https\nhost=github.com\n\n', text=True, capture_output=True, check=True)
        token = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line).get('password')
    if not token:
        raise RuntimeError('GitHub authentication unavailable')
    url = path if path.startswith('https://uploads.github.com/') else 'https://api.github.com' + path
    headers = {
        'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github+json',
        'Content-Type': content_type, 'User-Agent': 'Farry-Publisher', 'X-GitHub-Api-Version': '2022-11-28'}
    if length is not None:
        headers['Content-Length'] = str(length)
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=600) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f'GitHub HTTP {exc.code}') from None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--inspect', action='store_true')
    parser.add_argument('--version')
    parser.add_argument('--publish', action='store_true')
    args = parser.parse_args()
    if args.inspect:
        user = request('/user')
        repo = request('/repos/' + REPOSITORY)
        print(json.dumps({'login': user['login'], 'id': user['id'], 'private': repo['private'],
                          'can_push': repo.get('permissions', {}).get('push', False)}))
        return
    if not args.version:
        parser.error('--version required')
    import re
    if not re.fullmatch(r'(0|[1-9]\d{0,5})\.(0|[1-9]\d{0,5})\.(0|[1-9]\d{0,5})', args.version):
        parser.error('invalid version')
    root = Path(__file__).resolve().parent.parent
    paths = [root / 'dist' / name for name in ('Farry-windows-x64.zip', 'FarrySetup.exe', 'release.json', 'release.json.sig')]
    if not all(path.is_file() for path in paths):
        raise RuntimeError('Build and sign all four artifacts before creating a release')
    # A draft stays invisible to clients until all uploads succeed.
    result = request('/repos/' + REPOSITORY + '/releases', method='POST', data=json.dumps({
        'tag_name': 'v' + args.version, 'name': 'QMoney ' + args.version, 'draft': True,
        'body': 'Distribuição Windows pelo launcher Farry. Manifesto assinado e pacote verificado.'}).encode())
    for path in paths:
        with path.open('rb') as source:
            # urllib accepts a readable file and streams it with an explicit length.
            request(result['upload_url'].split('{')[0] + '?name=' + path.name,
                    method='POST', data=source, content_type='application/octet-stream', length=path.stat().st_size)
        print('Uploaded:', path.name)
    if args.publish:
        request('/repos/' + REPOSITORY + '/releases/' + str(result['id']), method='PATCH',
                data=json.dumps({'draft': False}).encode())
    print(result['html_url'])


if __name__ == '__main__':
    main()
