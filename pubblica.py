#!/usr/bin/env python3
"""Pubblica su Instagram un post preparato da post.py (carosello + didascalia).

Uso (lo lancia il workflow .github/workflows/pubblica.yml):
  python3 pubblica.py <cartella del post>

Usa la "Instagram API with Instagram Login" (graph.instagram.com):
  - token nel segreto IG_TOKEN del repository (mai nel codice);
  - immagini scaricate da Instagram dal ramo "anteprime" di questo
    repository pubblico (raw.githubusercontent.com), dove le mette prepara.yml.
Scrive pubblicato.json nella cartella (id e link del post). Se esiste gia',
non pubblica una seconda volta.

Solo libreria standard.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API = 'https://graph.instagram.com/v23.0'
RAW = 'https://raw.githubusercontent.com/Gidus-Pixel/cardsnap-social/anteprime'


def chiama(metodo: str, path: str, token: str, **params) -> dict:
    params['access_token'] = token
    data = urllib.parse.urlencode(params).encode()
    url = f'{API}/{path}'
    if metodo == 'GET':
        req = urllib.request.Request(f'{url}?{data.decode()}')
    else:
        req = urllib.request.Request(url, data=data, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        corpo = e.read().decode(errors='replace')
        try:
            err = json.loads(corpo).get('error', {})
            msg = f"{err.get('type')} {err.get('code')}: {err.get('message')}"
        except Exception:  # noqa: BLE001
            msg = corpo[:300]
        sys.exit(f'Instagram ha risposto {e.code} su {path}: {msg}')


def aspetta(cid: str, token: str):
    for _ in range(30):
        st = chiama('GET', cid, token, fields='status_code').get('status_code')
        if st == 'FINISHED':
            return
        if st in ('ERROR', 'EXPIRED'):
            sys.exit(f'Contenitore {cid} in stato {st}')
        time.sleep(5)
    sys.exit(f'Contenitore {cid} non pronto dopo 150 secondi')


def main():
    cartella = Path(sys.argv[1]).resolve()
    token = os.environ.get('IG_TOKEN', '').strip()
    if not token:
        sys.exit('Segreto IG_TOKEN mancante: va inserito nelle impostazioni del repository')
    fatto = cartella / 'pubblicato.json'
    if fatto.exists():
        print(f'Gia\' pubblicato: {json.loads(fatto.read_text())["permalink"]}')
        return
    dati = json.loads((cartella / 'dati.json').read_text(encoding='utf-8'))
    if dati.get('prova'):
        sys.exit('Questo e\' un post di prova con prezzi finti: non si pubblica')
    immagini = sorted(cartella.glob('[0-9][0-9].jpg'))
    if not 2 <= len(immagini) <= 20:
        sys.exit(f'{len(immagini)} immagini: un carosello ne vuole da 2 a 20')
    didascalia = (cartella / 'didascalia.txt').read_text(encoding='utf-8').strip()

    io_ = chiama('GET', 'me', token, fields='user_id,username')
    uid = io_.get('user_id') or io_.get('id')
    print(f"Account: @{io_.get('username')}")

    figli = []
    for im in immagini:
        url = f'{RAW}/{urllib.parse.quote(cartella.name)}/{im.name}'
        cid = chiama('POST', f'{uid}/media', token, image_url=url, is_carousel_item='true')['id']
        aspetta(cid, token)
        figli.append(cid)
        print(f'  {im.name} caricata')
    car = chiama('POST', f'{uid}/media', token, media_type='CAROUSEL', children=','.join(figli),
                 caption=didascalia)['id']
    aspetta(car, token)
    mid = chiama('POST', f'{uid}/media_publish', token, creation_id=car)['id']
    link = chiama('GET', mid, token, fields='permalink').get('permalink', '')
    fatto.write_text(json.dumps({'id': mid, 'permalink': link, 'pubblicato': time.strftime('%Y-%m-%dT%H:%M:%SZ',
                                                                                           time.gmtime())},
                                indent=1), encoding='utf-8')
    print(f'Pubblicato: {link}')
    out = os.environ.get('GITHUB_STEP_SUMMARY')
    if out:
        with open(out, 'a', encoding='utf-8') as f:
            f.write(f'Post pubblicato: {link}\n')


if __name__ == '__main__':
    main()
