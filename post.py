#!/usr/bin/env python3
"""Post Instagram di CardSnap: classifiche prezzi delle carte.

Uso (lo lancia il workflow .github/workflows/prepara.yml):
  python3 post.py auto                formato del giorno (ora di Roma)
  python3 post.py top --set 30th      le carte piu' care di un'espansione
  python3 post.py movimenti           5 carte che salgono e 5 che scendono
  python3 post.py illustrazioni       le 10 Illustration Rare piu' care dell'ultimo anno
  python3 post.py bulk                comuni e non comuni sopra 1 euro, confermati da
                                      CardTrader (oggi quasi sempre vuoto: non e' in rotazione)
  opzioni: --n 10 (quante carte), --data 2026-10-27 (finge un altro giorno),
           --mock (prezzi e immagini FINTI, solo per provare la grafica)

Settimana ("auto"):
  lunedi'   top 20 di una delle 4 espansioni piu' recenti (a rotazione)
  martedi'  movimenti della settimana (espansioni degli ultimi 2 anni)
  mercoledi' le 10 Illustration Rare piu' care dell'ultimo anno
  giovedi'  top 10 di un'espansione amata (151, Evoluzioni Prismatiche...)
  venerdi'  top 10 di un'espansione vintage
  sabato e domenica nessun post automatico.

Dati:
  - prezzi: guida prezzi ufficiale di Cardmarket (trend, medie 7 e 30 giorni),
    uguale per tutte le lingue, condizione NM;
  - prezzo in italiano: offerta NM piu' bassa in italiano su CardTrader, dal
    listino del giorno che il workflow CardTrader pubblica in tcg-vault-updates;
  - nomi, numeri e codici Cardmarket: catalogo dell'app CardSnap, pubblicato
    nella release "dati" di tcg-vault-updates.

Uscita: out/<data>-<formato>-<chiave>/ con 01..NN.jpg (1080x1350, JPEG
come vuole Instagram), didascalia.txt, dati.json e controlli.txt (avvisi da
guardare prima di pubblicare).

Solo libreria standard + Pillow.
"""
from __future__ import annotations

import argparse
import gzip
import io
import json
import os
import random
import sys
import time
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = Path(__file__).resolve().parent
OUT = HERE / 'out'
CATALOGO = 'https://github.com/Gidus-Pixel/tcg-vault-updates/releases/download/dati/catalog_it.json.gz'
ROMA = ZoneInfo('Europe/Rome')

CM_GUIDE = 'https://downloads.s3.cardmarket.com/productCatalog/priceGuide/price_guide_6.json'
CT_LISTINO = 'https://github.com/Gidus-Pixel/tcg-vault-updates/releases/download/dati/prezzi.json.gz'
UA = {'User-Agent': 'CardSnap-social/1.0 (+https://cardsnap.it)'}

AMATE = ['sv03.5', 'sv08.5', 'swsh7', 'sv04.5', 'swsh12.5', 'sv10', 'sv06', 'sv07', 'sv08', 'sv09',
         'me01', 'me02', 'me02.5']
VINTAGE = ['base1', 'base2', 'base3', 'base5', 'neo1', 'gym1', 'neo2', 'gym2', 'neo3', 'neo4', 'base4']
SPECIALI = {'cosmos': 'Cosmos', 'pokeball': 'Poké Ball', 'energy': 'Energia', 'masterball': 'Master Ball',
            'rainbow': 'Rainbow', 'gold': 'Gold', 'galaxy': 'Galaxy', 'league': 'Lega Pokémon',
            'cracked-ice': 'Cracked Ice', 'duskball': 'Dusk Ball', 'loveball': 'Love Ball',
            'friendball': 'Friend Ball', 'quickball': 'Quick Ball', 'tinsel': 'Tinsel',
            'team-rocket': 'Team Rocket', 'starlight': 'Starlight'}
SOTTOTIPI = {'shadowless': 'Shadowless', 'unlimited': 'Unlimited'}
RGB = {'R': 'versione rossa', 'G': 'versione verde', 'B': 'versione blu'}

W, H = 1080, 1350
SCURO = (14, 16, 34)
CARTA = (24, 27, 52)
BIANCO = (255, 255, 255)
TENUE = (168, 174, 204)
SU = (74, 222, 128)
GIU = (251, 113, 133)
HOLO = [(124, 196, 255), (169, 155, 255), (242, 138, 200), (255, 179, 138)]


# ---------------------------------------------------------------------------
# Rete e dati
# ---------------------------------------------------------------------------

def scarica(url: str, timeout: int = 60, tries: int = 3) -> bytes:
    err = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            err = e
            time.sleep(2 * (i + 1))
    raise RuntimeError(f'{url}: {err}')


class Dati:
    def __init__(self, mock: bool):
        locale = os.environ.get('CATALOGO_FILE')  # per le prove: catalogo gia' scaricato
        raw = Path(locale).read_bytes() if locale else scarica(CATALOGO, timeout=120)
        self.cat = json.loads(gzip.decompress(raw).decode('utf-8'))
        self.sets = {s['id']: s for s in self.cat['sets']}
        self.mock = mock
        self.escluse: list[str] = []
        if mock:
            rnd = random.Random(7)
            self.guida = {}
            for c in self.cat['cards']:
                for v in c.get('v', []):
                    if v.get('cm') and v['cm'] not in self.guida:
                        t = round(rnd.choice([0.05, 0.2, 0.5, 1, 1.5, 3, 8, 20, 60, 200]) * rnd.uniform(0.6, 1.4), 2)
                        th = round(t * rnd.uniform(1, 4), 2)
                        self.guida[v['cm']] = {'trend': t, 'avg7': t * rnd.uniform(0.7, 1.3), 'avg30': t,
                                               'trend-holo': th, 'avg7-holo': th, 'avg30-holo': th}
            self.ct = {'d': 'finto', 'ct': {str(c['ct']): [None, None, round(rnd.uniform(0.5, 300), 2), None, 3]
                                            for c in self.cat['cards'] if c.get('ct') and rnd.random() < 0.3}}
        else:
            g = json.loads(scarica(CM_GUIDE, timeout=180).decode('utf-8'))
            self.guida = {x['idProduct']: x for x in g.get('priceGuides', []) if 'idProduct' in x}
            try:
                self.ct = json.loads(gzip.decompress(scarica(CT_LISTINO)).decode('utf-8'))
            except Exception as e:  # noqa: BLE001  il post vale anche senza
                print(f'::warning::listino CardTrader non scaricato: {e}')
                self.ct = {}
            # un listino vecchio darebbe prezzi italiani sbagliati: meglio non mostrarli
            d_ct = self.ct.get('d')
            if d_ct and date.fromisoformat(d_ct) < date.today() - timedelta(days=2):
                print(f'::warning::listino CardTrader del {d_ct}: troppo vecchio, niente "IT da"')
                self.ct = {'d': f'{d_ct} (scartato)'}

    def carte(self, set_ids) -> list[dict]:
        ids = set(set_ids)
        return [c for c in self.cat['cards'] if c['s'] in ids]

    def set_principali(self, oggi: date) -> list[dict]:
        """Espansioni principali uscite, dalla piu' recente."""
        out = [s for s in self.cat['sets']
               if s.get('cm') and (s.get('tot') or 0) >= 60 and s.get('rel') and s['rel'] <= oggi.isoformat()
               and not s['id'].endswith('-c') and s.get('serie') not in ('tk',) and 'promo' not in s['en'].lower()]
        return sorted(out, key=lambda s: s['rel'], reverse=True)


def numero(c: dict, s: dict) -> str:
    n = str(c.get('n', ''))
    if n.isdigit() and s.get('off'):
        return f'{n}/{s["off"]}'
    if c.get('r') == 'RGB Rare' and n in RGB:
        return RGB[n]
    return n


def immagini_candidate(c: dict, s: dict) -> list[str]:
    """Prima l'immagine italiana di TCGdex, poi le riserve in inglese."""
    urls = [f'https://assets.tcgdex.net/it/{s["serie"]}/{s["id"]}/{c["n"]}/high.png']
    if s.get('im'):
        urls.append(s['im'].replace('{n}', str(c.get('pn') or c['n'])))
    if c.get('ci'):
        urls.append(c['ci'])
    urls.append(f'https://assets.tcgdex.net/en/{s["serie"]}/{s["id"]}/{c["n"]}/high.png')
    return urls


def voci(d: Dati, carte: list[dict]) -> list[dict]:
    """Una voce per ogni prodotto Cardmarket con prezzo (reverse compresi)."""
    out = []
    for c in carte:
        s = d.sets[c['s']]
        vs = c.get('v', [])
        base_cm = {v.get('cm') for v in vs if v.get('t') != 'reverse' and v.get('cm')}
        piu_prodotti = len(base_cm) > 1
        visti = set()
        for v in vs:
            cm = v.get('cm')
            if not cm:
                continue
            reverse_stesso = v.get('t') == 'reverse' and cm in base_cm
            chiave = (cm, reverse_stesso)
            if chiave in visti:
                continue
            visti.add(chiave)
            g = d.guida.get(cm) or {}
            suf = '-holo' if reverse_stesso else ''
            trend, a7, a30 = g.get('trend' + suf), g.get('avg7' + suf), g.get('avg30' + suf)
            if not trend:
                continue
            f = v.get('f')
            st = v.get('st') or ''
            # timbro solo su questa versione (non su tutta l'espansione): e' un'altra carta
            timbrata = bool(st) and 'first' not in st and any(not w.get('st') for w in vs)
            if timbrata:
                variante = 'Timbrata'
            elif v.get('t') == 'reverse':
                variante = f'Reverse {SPECIALI.get(f, f)}' if f else 'Reverse'
            elif f:
                variante = SPECIALI.get(f, f)
            elif piu_prodotti:
                variante = SOTTOTIPI.get(v.get('s') or '', '') or (
                    '1ª edizione' if 'first' in (v.get('st') or '') else '')
            else:
                variante = ''
            nota = []
            dubbia = False
            it = None
            row = (d.ct.get('ct') or {}).get(str(c.get('ct')))
            # controllo incrociato: se su CardTrader la stessa carta costa molto meno,
            # il codice Cardmarket potrebbe puntare a un'altra carta (timbrata, promo...)
            ct_min = None
            if row and not f and not timbrata:
                ct_min = row[1] if reverse_stesso else row[0]
                if ct_min and trend > 4 * ct_min and trend - ct_min > 2:
                    nota.append(f'trend {trend} ma su CardTrader da {ct_min}: possibile carta sbagliata, esclusa')
                    dubbia = True
            if not v.get('t') == 'reverse' and not f and not timbrata:
                if row and len(row) > 2 and row[2]:
                    it = row[2]
                    # un'offerta fuori mercato confonde: non la mostro
                    if it > 1.5 * trend and it - trend > 1:
                        nota.append(f'offerta IT {it} oltre 1,5 volte il trend ({trend}), nascosta')
                        it = None
            if a30 and trend > 3 * a30:
                nota.append(f'trend {trend} oltre 3 volte la media 30 gg ({a30})')
                picco = True
            elif a7 and trend < a7 / 3:
                nota.append(f'trend {trend} molto sotto la media 7 gg ({a7})')
                picco = True
            else:
                picco = False
            # medie 7 e 30 identiche: poche vendite, la variazione non dice nulla
            stabile = bool(a7 and a30 and abs(a7 - a30) < 0.005)
            coerente = bool(a7 and 0.6 * a7 <= trend <= 1.6 * a7)
            if dubbia:
                d.escluse.append(f'{c["it"]} {numero(c, s)}: ' + '; '.join(nota))
                continue
            out.append({'id': c['id'], 'nome': c['it'], 'numero': numero(c, s), 'variante': variante,
                        'set': s['id'], 'set_it': s['it'], 'set_abbr': s.get('abbr') or '',
                        'rarita': c.get('r'), 'cm': cm, 'trend': trend, 'avg7': a7, 'avg30': a30,
                        'var': round((a7 - a30) / a30 * 100, 1) if a7 and a30 and not stabile else None,
                        'speciale': bool(f) or timbrata, 'picco': picco, 'coerente': coerente,
                        # seconda fonte d'accordo: su CardTrader la carta parte da almeno il 40% del trend
                        'confermata': bool(ct_min and ct_min >= 0.4 * trend),
                        'it_ct': it, 'nota': nota, 'img_urls': immagini_candidate(c, s)})
    return out


def immagine(urls: list[str], mock: bool) -> tuple[Image.Image | None, str]:
    if mock:  # carta d'esempio del sito, solo per vedere l'impaginazione
        es = Image.open(HERE / 'img' / 'carta_esempio.webp').convert('RGBA')
        return es.crop((74, 220, 467, 769)), 'finta'
    for u in urls:
        try:
            im = Image.open(io.BytesIO(scarica(u, timeout=30, tries=2)))
            im.load()
            if im.width >= 200:
                return im.convert('RGBA'), u
        except Exception:  # noqa: BLE001
            continue
    return None, ''


# ---------------------------------------------------------------------------
# Grafica
# ---------------------------------------------------------------------------

def font(nome: str, size: int, peso: int = 700) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(str(HERE / 'fonts' / nome), size, layout_engine=ImageFont.Layout.BASIC)
    axes = []
    for a in f.get_variation_axes():
        n = a['name'].decode() if isinstance(a['name'], bytes) else a['name']
        if n == 'Weight':
            axes.append(max(a['minimum'], min(a['maximum'], peso)))
        elif n == 'Optical size':
            axes.append(max(a['minimum'], min(a['maximum'], size)))
        else:
            axes.append(a['default'])
    f.set_variation_by_axes(axes)
    return f


def TIT(size, peso=800):
    return font('BricolageGrotesque.ttf', size, peso)


def TXT(size, peso=600):
    return font('Figtree.ttf', size, peso)


def euro(x: float) -> str:
    s = f'{x:,.0f}' if x >= 100 else f'{x:,.2f}'
    return s.replace(',', 'X').replace('.', ',').replace('X', '.') + ' €'


def pct(x: float) -> str:
    return ('+' if x > 0 else '') + f'{x:.1f}'.replace('.', ',') + '%'


def gradiente(w: int, h: int, stops=HOLO) -> Image.Image:
    g = Image.new('RGB', (w, 1))
    px = g.load()
    for x in range(w):
        t = x / max(1, w - 1) * (len(stops) - 1)
        i = min(int(t), len(stops) - 2)
        f = t - i
        a, b = stops[i], stops[i + 1]
        px[x, 0] = tuple(int(a[k] + (b[k] - a[k]) * f) for k in range(3))
    return g.resize((w, h))


def testo_holo(img: Image.Image, xy, txt: str, f, anchor='la'):
    m = Image.new('L', img.size, 0)
    ImageDraw.Draw(m).text(xy, txt, font=f, fill=255, anchor=anchor)
    box = m.getbbox()
    if not box:
        return
    g = gradiente(box[2] - box[0], box[3] - box[1])
    img.paste(g, box[:2], m.crop(box))


def sfondo() -> Image.Image:
    img = Image.new('RGB', (W, H), SCURO)
    glow = Image.new('RGB', (W, H), SCURO)
    d = ImageDraw.Draw(glow)
    for (cx, cy, r, col) in [(160, 120, 420, (60, 70, 150)), (980, 1250, 520, (110, 60, 120)),
                             (1000, 200, 300, (40, 90, 130))]:
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=col)
    glow = glow.filter(ImageFilter.GaussianBlur(160))
    return Image.blend(img, glow, 0.55)


def logo(img: Image.Image, pagina: int, pagine: int):
    lg = Image.open(HERE / 'img' / 'logo.png').convert('RGBA')
    lg = lg.resize((int(lg.width * 58 / lg.height), 58), Image.LANCZOS)
    img.paste(lg, (48, 44), lg)
    ImageDraw.Draw(img).text((W - 48, 73), f'{pagina}/{pagine}', font=TXT(30, 700), fill=TENUE, anchor='rm')


def segnaposto(w: int, h: int, testo: str) -> Image.Image:
    im = Image.new('RGBA', (w, h), (52, 58, 96, 255))
    d = ImageDraw.Draw(im)
    d.rectangle((0, 0, w - 1, h - 1), outline=(90, 98, 150), width=3)
    d.multiline_text((w // 2, h // 2), testo, font=TXT(max(14, w // 9), 700), fill=TENUE,
                     anchor='mm', align='center')
    return im


def incolla_carta(img: Image.Image, carta: Image.Image | None, box, etichetta: str, bordo_holo=False):
    x, y, w, h = box
    im = carta.copy() if carta is not None else segnaposto(w, h, etichetta)
    im = im.resize((w, h), Image.LANCZOS)
    r = max(6, w // 22)
    m = Image.new('L', (w, h), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, w - 1, h - 1), r, fill=255)
    ombra = Image.new('RGBA', (w + 60, h + 60), (0, 0, 0, 0))
    ImageDraw.Draw(ombra).rounded_rectangle((30, 38, w + 30, h + 38), r, fill=(0, 0, 0, 150))
    ombra = ombra.filter(ImageFilter.GaussianBlur(14))
    img.paste(ombra, (x - 30, y - 30), ombra)
    if bordo_holo:
        b = 6
        g = gradiente(w + 2 * b, h + 2 * b)
        mb = Image.new('L', (w + 2 * b, h + 2 * b), 0)
        ImageDraw.Draw(mb).rounded_rectangle((0, 0, w + 2 * b - 1, h + 2 * b - 1), r + b, fill=255)
        img.paste(g, (x - b, y - b), mb)
    img.paste(im.convert('RGB'), (x, y), m)


def pillola(d: ImageDraw.ImageDraw, xy, testo: str, col, f, anchor='mm'):
    x, y = xy
    l, t, r_, b = d.textbbox((x, y), testo, font=f, anchor=anchor)
    sfondo_col = tuple(int(c * 0.22 + s * 0.78) for c, s in zip(col, SCURO))
    d.rounded_rectangle((l - 12, t - 6, r_ + 12, b + 6), 999, fill=sfondo_col)
    d.text((x, y), testo, font=f, fill=col, anchor=anchor)


def col_var(v):
    return SU if v > 0 else GIU if v < 0 else TENUE


def accorcia(d, testo: str, f, maxw: int) -> str:
    if d.textlength(testo, font=f) <= maxw:
        return testo
    while testo and d.textlength(testo + '…', font=f) > maxw:
        testo = testo[:-1]
    return testo.rstrip() + '…'


def a_capo(d, testo: str, f, maxw: int) -> list[str]:
    out, cur = [], ''
    for w in testo.split():
        prova = (cur + ' ' + w).strip()
        if d.textlength(prova, font=f) <= maxw:
            cur = prova
        else:
            out.append(cur)
            cur = w
    if cur:
        out.append(cur)
    return out


def sotto(r: dict, multi: bool) -> str:
    """Seconda riga sotto il nome: numero, variante ed espansione."""
    parti = []
    if multi:
        parti.append(r['set_abbr'] or r['set_it'])
    parti.append(r['numero'])
    if r['variante']:
        parti.append(r['variante'])
    return ' · '.join(p for p in parti if p)


def pagina_copertina(p: dict, imgs, data_txt, pagine) -> Image.Image:
    img = sfondo()
    logo(img, 1, pagine)
    d = ImageDraw.Draw(img)
    top = p['voci']
    d.text((48, 168), p['kicker'], font=TXT(28, 800), fill=TENUE)
    d.text((48, 206), p['titolo'], font=TIT(84 if len(p['titolo']) <= 22 else 70), fill=BIANCO)
    testo_holo(img, (48, 304), p['holo'], TIT(84 if len(p['holo']) <= 18 else 64))
    d.text((48, 410), p['info'], font=TXT(30, 500), fill=TENUE)

    pos = [(1, 48, 560, 290), (2, W - 48 - 290, 560, 290), (0, (W - 360) // 2, 500, 360)]
    for i, x, y, w in pos:
        if i >= len(top):
            continue
        r = top[i]
        h = int(w * 1.395)
        incolla_carta(img, imgs[i], (x, y, w, h), f'#{i + 1}\n{r["nome"]}', bordo_holo=(i == 0))
        cx = x + w // 2
        d.text((cx, y + h + 34), euro(r['trend']), font=TIT(52 if i == 0 else 44), fill=BIANCO, anchor='mm')
        d.text((cx, y + h + 78), accorcia(d, r['nome'], TXT(27, 700), w + 30), font=TXT(27, 700),
               fill=BIANCO, anchor='mm')
        d.text((cx, y + h + 112), accorcia(d, sotto(r, p['multi']), TXT(22, 500), w + 30), font=TXT(22, 500),
               fill=TENUE, anchor='mm')
        bx, by = x + 18, y + 18
        d.rounded_rectangle((bx, by, bx + 70, by + 52), 14, fill=SCURO)
        d.text((bx + 35, by + 26), f'#{i + 1}', font=TIT(34), fill=BIANCO, anchor='mm')

    sale = [r for r in top if r['var'] is not None and r['var'] > 0]
    if sale:
        m = max(sale, key=lambda r: r['var'])
        d.rounded_rectangle((48, 1150, W - 48, 1240), 24, fill=CARTA)
        d.text((84, 1195), 'Sale di più in 7 giorni', font=TXT(30, 700), fill=TENUE, anchor='lm')
        f_ = TXT(30, 800)
        lab = pct(m['var'])
        d.text((W - 84, 1195), lab, font=f_, fill=SU, anchor='rm')
        lw = d.textlength(lab, font=f_)
        d.text((W - 84 - lw - 16, 1195), accorcia(d, f'{m["nome"]} {m["numero"]}', f_, 360), font=f_,
               fill=BIANCO, anchor='rm')
    d.text((W // 2, H - 52), f'Prezzi trend Cardmarket al {data_txt} · scorri per la classifica →',
           font=TXT(26, 600), fill=TENUE, anchor='mm')
    return img


def pagina_griglia(p: dict, righe, imgs, start, data_txt, n_pag, pagine) -> Image.Image:
    img = sfondo()
    logo(img, n_pag, pagine)
    d = ImageDraw.Draw(img)
    d.text((48, 150), f'Dalla {start + 1}ª alla {start + len(righe)}ª', font=TIT(56), fill=BIANCO)
    testo_holo(img, (48, 220), p['holo'], TIT(40, 700))
    cols, gap, mx = 5, 18, 48
    cw = (W - 2 * mx - (cols - 1) * gap) // cols
    ch = int(cw * 1.395)
    y0, riga_h = 290, ch + 202
    for k, r in enumerate(righe):
        cx = mx + (k % cols) * (cw + gap)
        cy = y0 + (k // cols) * riga_h
        incolla_carta(img, imgs[k], (cx, cy, cw, ch), f'#{start + k + 1}\n{r["nome"]}')
        d.rounded_rectangle((cx + 8, cy + 8, cx + 66, cy + 46), 10, fill=SCURO)
        d.text((cx + 37, cy + 27), f'#{start + k + 1}', font=TIT(26), fill=BIANCO, anchor='mm')
        mid = cx + cw // 2
        d.text((mid, cy + ch + 30), accorcia(d, r['nome'], TXT(24, 700), cw), font=TXT(24, 700),
               fill=BIANCO, anchor='mm')
        d.text((mid, cy + ch + 58), accorcia(d, sotto(r, p['multi']), TXT(20, 500), cw + 12),
               font=TXT(20, 500), fill=TENUE, anchor='mm')
        d.text((mid, cy + ch + 96), euro(r['trend']), font=TIT(36), fill=BIANCO, anchor='mm')
        if r['var'] is not None:
            pillola(d, (mid, cy + ch + 138), pct(r['var']), col_var(r['var']), TXT(21, 800))
        if r['it_ct']:
            d.text((mid, cy + ch + 170), f'IT da {euro(r["it_ct"])}', font=TXT(19, 600), fill=TENUE,
                   anchor='mm')
    d.text((W // 2, H - 52), f'Trend Cardmarket al {data_txt} · % = media 7 giorni contro 30 giorni',
           font=TXT(24, 600), fill=TENUE, anchor='mm')
    return img


def pagina_lista(titolo: str, holo: str, righe, imgs, data_txt, n_pag, pagine) -> Image.Image:
    """Cinque carte in righe: miniatura, nome, espansione, prezzo e variazione."""
    img = sfondo()
    logo(img, n_pag, pagine)
    d = ImageDraw.Draw(img)
    d.text((48, 150), titolo, font=TIT(60), fill=BIANCO)
    testo_holo(img, (48, 224), holo, TIT(36, 700))
    y = 300
    tw, th = 112, 156
    for k, r in enumerate(righe):
        d.rounded_rectangle((48, y, W - 48, y + th + 2 * 8), 24, fill=CARTA)
        incolla_carta(img, imgs[k], (64, y + 8, tw, th), r['nome'])
        x = 64 + tw + 28
        d.text((x, y + 40), accorcia(d, r['nome'], TXT(36, 800), 470), font=TXT(36, 800), fill=BIANCO, anchor='lm')
        d.text((x, y + 82), accorcia(d, r['set_it'], TXT(26, 600), 470), font=TXT(26, 600), fill=TENUE,
               anchor='lm')
        d.text((x, y + 118), accorcia(d, ' · '.join(p for p in (r['numero'], r['variante']) if p),
                                      TXT(24, 500), 470), font=TXT(24, 500), fill=TENUE, anchor='lm')
        d.text((W - 76, y + 60), euro(r['trend']), font=TIT(46), fill=BIANCO, anchor='rm')
        if r['var'] is not None:
            f_ = TXT(28, 800)
            pillola(d, (W - 76, y + 120), pct(r['var']), col_var(r['var']), f_, anchor='rm')
        y += th + 16 + 14
    d.text((W // 2, H - 52), f'Trend Cardmarket al {data_txt} · % = media 7 giorni contro 30 giorni',
           font=TXT(24, 600), fill=TENUE, anchor='mm')
    return img


def pagina_finale(data_txt, pagine, extra: tuple[str, str] | None = None) -> Image.Image:
    img = sfondo()
    logo(img, pagine, pagine)
    d = ImageDraw.Draw(img)
    d.text((48, 170), 'Come leggere', font=TIT(72), fill=BIANCO)
    testo_holo(img, (48, 254), 'questi prezzi', TIT(72))
    voci_ = [
        ('Prezzo grande', 'Trend di Cardmarket: media delle vendite recenti, '
                          'tutte le lingue insieme, carte Near Mint.'),
        ('Percentuale', 'Media degli ultimi 7 giorni confrontata con quella '
                        'degli ultimi 30. Verde sale, rosso scende.'),
        extra or ('IT da', "Offerta più bassa in italiano, Near Mint, su CardTrader. "
                           "Manca quando nessuno la vende in italiano."),
        ('Data', f'Prezzi al {data_txt}. Cambiano ogni giorno: controlla '
                 'sempre prima di comprare o vendere.'),
    ]
    y = 420
    for tit, desc in voci_:
        d.rounded_rectangle((48, y, W - 48, y + 150), 26, fill=CARTA)
        d.text((84, y + 30), tit, font=TXT(32, 800), fill=BIANCO)
        d.multiline_text((84, y + 74), '\n'.join(a_capo(d, desc, TXT(27, 500), W - 2 * 84)),
                         font=TXT(27, 500), fill=TENUE, spacing=8)
        y += 170
    g = gradiente(W - 96, 150)
    m = Image.new('L', (W - 96, 150), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, W - 97, 149), 30, fill=255)
    img.paste(g, (48, y + 20), m)
    d.text((W // 2, y + 70), 'Quanto vale la tua collezione?', font=TIT(42), fill=SCURO, anchor='mm')
    d.text((W // 2, y + 122), 'Scansionala con CardSnap · link in bio', font=TXT(30, 700), fill=SCURO,
           anchor='mm')
    return img


def timbro_prova(img: Image.Image) -> Image.Image:
    lay = Image.new('RGBA', img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    for y in range(120, H, 360):
        d.text((W // 2, y), 'PROVA · PREZZI FINTI', font=TIT(70), fill=(255, 60, 60, 110), anchor='mm')
    return Image.alpha_composite(img.convert('RGBA'), lay).convert('RGB')


# ---------------------------------------------------------------------------
# Formati
# ---------------------------------------------------------------------------

def hashtag(extra: list[str]) -> str:
    base = ['#carteitaliane', '#cartecollezionabili', '#tcgitalia', '#collezionismo', '#cardmarket']
    tag = [t for t in base + extra + ['#cardsnap'] if t]
    return ' '.join(dict.fromkeys(tag))


def tag_set(s: dict) -> str:
    t = ''.join(ch for ch in s['en'].lower() if ch.isalnum())
    return f'#{t}' if t and not t.isdigit() else ''


def NOTA_PREZZI(data_txt):
    return (f'Prezzi trend Cardmarket al {data_txt}: tutte le lingue insieme, carte Near Mint. '
            'La percentuale confronta la media degli ultimi 7 giorni con quella degli ultimi 30.')


def andamento(top) -> str | None:
    vs = sorted(r['var'] for r in top if r['var'] is not None)
    if not vs:
        return None
    med = vs[len(vs) // 2]
    if med <= -5:
        return (f'📉 Il resto è in calo: per metà di queste carte la media degli ultimi 7 giorni '
                f'è almeno del {abs(med):.0f}% sotto quella del mese')
    if med >= 5:
        return (f'🔥 Momento caldo: per metà di queste carte la media degli ultimi 7 giorni '
                f'è almeno del {med:.0f}% sopra quella del mese')
    return None


def podio_testo(top, multi) -> list[str]:
    med = ['🥇', '🥈', '🥉']
    return [f'{med[i]} {r["nome"]} {sotto(r, multi)} · {euro(r["trend"])}' for i, r in enumerate(top[:3])]


def fmt_top(d: Dati, set_id: str, n: int, oggi: date) -> dict:
    s = d.sets.get(set_id)
    if s is None:
        sys.exit(f'Espansione {set_id} non trovata nel catalogo')
    tutte = sorted(voci(d, d.carte([set_id])), key=lambda r: -r['trend'])
    top = tutte[:n]
    data_txt = oggi.strftime('%d/%m/%Y')
    anno = s['rel'][:4]
    vintage = s['rel'] < '2005'
    info = f'Espansione {s["en"]} · uscita {datetime.fromisoformat(s["rel"]).strftime("%d/%m/%Y")}'
    if any(c.get('noIt') for c in d.carte([set_id])):
        info = f'{s["en"]} ({anno}) · uscita solo in inglese'
    righe = [f'Le {len(top)} carte più care di {s["it"]} su Cardmarket, oggi 💸', '']
    righe += podio_testo(top, False)
    sale = [r for r in top if r['var'] is not None and r['var'] > 0]
    if sale:
        m = max(sale, key=lambda r: r['var'])
        righe += ['', f'📈 Sale di più: {m["nome"]} {sotto(m, False)} ({pct(m["var"])} in 7 giorni)']
    a = andamento(top)
    if a:
        righe.append(a)
    righe += ['', NOTA_PREZZI(data_txt) + (' Per le carte vintage il prezzo mescola le edizioni.' if vintage
                                           else ' "IT da" è l\'offerta più bassa in italiano su CardTrader.'),
              '', 'Quale ti manca? Scrivilo nei commenti 👇', '📲 Scansiona la tua collezione con CardSnap: link in bio',
              '', hashtag([tag_set(s), '#pokemonvintage' if vintage else ''])]
    return {'formato': 'top', 'chiave': set_id, 'voci': top, 'multi': False,
            'kicker': 'CLASSIFICA PREZZI CARDMARKET', 'titolo': f'Le {len(top)} carte più care',
            'holo': s['it'], 'info': info, 'didascalia': '\n'.join(righe),
            'escluse': sum(1 for c in d.carte([set_id]) for v in c.get('v', []) if v.get('cm')) - len(tutte)}


def fmt_movimenti(d: Dati, oggi: date) -> dict:
    sets = [s['id'] for s in d.set_principali(oggi)
            if oggi - timedelta(days=730) <= date.fromisoformat(s['rel']) <= oggi - timedelta(days=21)]
    pool = [r for r in voci(d, d.carte(sets))
            if r['var'] is not None and r['trend'] >= 3 and (r['avg30'] or 0) >= 3 and (r['avg7'] or 0) >= 3
            and not r['picco'] and r['coerente']
            and (r['confermata'] or r['rarita'] not in ('Common', 'Uncommon'))]
    su = sorted([r for r in pool if r['var'] > 0], key=lambda r: -r['var'])[:5]
    giu = sorted([r for r in pool if r['var'] < 0], key=lambda r: r['var'])[:5]
    data_txt = oggi.strftime('%d/%m/%Y')
    righe = ['Le carte che si muovono di più questa settimana su Cardmarket 📊', '', '📈 Salgono:']
    righe += [f'• {r["nome"]} ({r["set_it"]} {r["numero"]}) {pct(r["var"])} · {euro(r["trend"])}' for r in su]
    righe += ['', '📉 Scendono:']
    righe += [f'• {r["nome"]} ({r["set_it"]} {r["numero"]}) {pct(r["var"])} · {euro(r["trend"])}' for r in giu]
    righe += ['', NOTA_PREZZI(data_txt) + ' Solo carte sopra i 3 € delle espansioni uscite negli ultimi 2 anni.',
              '', 'Ne avevi una da parte? Scrivilo nei commenti 👇',
              '📲 Scansiona la tua collezione con CardSnap: link in bio', '', hashtag(['#pokemoncards'])]
    return {'formato': 'movimenti', 'chiave': 'settimana', 'su': su, 'giu': giu, 'voci': su + giu,
            'multi': True, 'didascalia': '\n'.join(righe), 'n_set': len(sets)}


def fmt_bulk(d: Dati, oggi: date) -> dict:
    sets = [s['id'] for s in d.set_principali(oggi)
            if date.fromisoformat(s['rel']) >= oggi - timedelta(days=730)]
    pool = [r for r in voci(d, d.carte(sets))
            if r['rarita'] in ('Common', 'Uncommon') and not r['speciale'] and not r['picco']
            and r['confermata'] and r['trend'] >= 1 and (r['avg30'] or 0) >= 0.8]
    top = sorted(pool, key=lambda r: -r['trend'])[:10]
    data_txt = oggi.strftime('%d/%m/%Y')
    righe = ["Bulk d'oro 💰 Comuni e non comuni che valgono più di 1 € su Cardmarket", '']
    righe += podio_testo(top, True)
    righe += ['', f'Controlla raccoglitori e scatole: in tutto {len(pool)} comuni e non comuni '
                  '(normali o reverse) delle espansioni degli ultimi 2 anni superano 1 €.',
              '', NOTA_PREZZI(data_txt) + ' "Reverse" indica la versione reverse holo.',
              '', 'Ne hai trovata una? Scrivilo nei commenti 👇',
              '📲 Scansiona i tuoi doppioni con CardSnap e scopri quali vendere: link in bio',
              '', hashtag(['#bulk', '#pokemoncards'])]
    return {'formato': 'bulk', 'chiave': 'comuni', 'voci': top, 'multi': True,
            'kicker': "BULK D'ORO · COMUNI E NON COMUNI", 'titolo': 'Valgono più di 1 €',
            'holo': 'Controlla i doppioni', 'info': f'Espansioni degli ultimi 2 anni · {len(pool)} carte sopra 1 €',
            'didascalia': '\n'.join(righe), 'totale': len(pool)}


def fmt_illustrazioni(d: Dati, oggi: date) -> dict:
    sets = [s['id'] for s in d.set_principali(oggi)
            if date.fromisoformat(s['rel']) >= oggi - timedelta(days=365)]
    pool = [r for r in voci(d, d.carte(sets))
            if r['rarita'] == 'Illustration rare' and not r['speciale'] and not r['picco']]
    top = sorted(pool, key=lambda r: -r['trend'])[:10]
    data_txt = oggi.strftime('%d/%m/%Y')
    righe = ["Le 10 Illustration Rare più care dell'ultimo anno su Cardmarket 🎨", '']
    righe += podio_testo(top, True)
    sale = [r for r in top if r['var'] is not None and r['var'] > 0]
    if sale:
        m = max(sale, key=lambda r: r['var'])
        righe += ['', f'📈 Sale di più: {m["nome"]} ({m["set_it"]} {m["numero"]}, {pct(m["var"])} in 7 giorni)']
    righe += ['', NOTA_PREZZI(data_txt) + ' "IT da" è l\'offerta più bassa in italiano su CardTrader.',
              '', 'Qual è la tua preferita? Scrivilo nei commenti 👇',
              '📲 Scansiona la tua collezione con CardSnap: link in bio', '',
              hashtag(['#illustrationrare', '#pokemonart'])]
    return {'formato': 'illustrazioni', 'chiave': 'anno', 'voci': top, 'multi': True,
            'kicker': 'CLASSIFICA PREZZI CARDMARKET', 'titolo': 'Illustration Rare',
            'holo': 'le più care', 'info': f"Espansioni uscite nell'ultimo anno · {len(pool)} carte",
            'didascalia': '\n'.join(righe)}


def scegli(d: Dati, oggi: date) -> dict | None:
    sett = oggi.isocalendar()[1]
    g = oggi.weekday()
    if g == 0:
        recenti = [s['id'] for s in d.set_principali(oggi)][:4]
        return fmt_top(d, recenti[sett % len(recenti)], 20, oggi)
    if g == 1:
        return fmt_movimenti(d, oggi)
    if g == 2:
        return fmt_illustrazioni(d, oggi)
    if g == 3:
        amate = [x for x in AMATE if x in d.sets]
        return fmt_top(d, amate[sett % len(amate)], 10, oggi)
    if g == 4:
        vin = [x for x in VINTAGE if x in d.sets]
        return fmt_top(d, vin[sett % len(vin)], 10, oggi)
    return None


# ---------------------------------------------------------------------------

def genera(p: dict, d: Dati, oggi: date):
    data_txt = oggi.strftime('%d/%m/%Y')
    avvisi = []
    imgs, fonti = [], []
    for r in p['voci']:
        avvisi += [f'{r["nome"]} {r["numero"]}: {n}' for n in r.pop('nota')]
        im, u = immagine(r['img_urls'], d.mock)
        if im is None and not d.mock:
            avvisi.append(f'{r["nome"]} {r["numero"]}: immagine non trovata')
        elif u.startswith('http') and '/it/' not in u:
            avvisi.append(f'{r["nome"]} {r["numero"]}: immagine non italiana ({u.split("/")[2]})')
        imgs.append(im)
        fonti.append(u)
    avvisi += [f'ESCLUSA {x}' for x in d.escluse[:40]]
    if len(p['voci']) < 3:
        sys.exit(f'Solo {len(p["voci"])} carte: post non generato')

    slides = []
    if p['formato'] == 'movimenti':
        n_su, n_giu = len(p['su']), len(p['giu'])
        pagine = 1 + (1 if n_su else 0) + (1 if n_giu else 0)
        k = 1
        if n_su:
            slides.append(pagina_lista('Salgono', 'Media 7 giorni contro 30', p['su'], imgs[:n_su],
                                       data_txt, k, pagine))
            k += 1
        if n_giu:
            slides.append(pagina_lista('Scendono', 'Media 7 giorni contro 30', p['giu'], imgs[n_su:],
                                       data_txt, k, pagine))
            k += 1
        slides.append(pagina_finale(data_txt, pagine, ('Quali carte', 'Solo carte sopra i 3 € delle '
                                                       'espansioni uscite negli ultimi 2 anni.')))
    else:
        top = p['voci']
        pagine = 2 + (len(top) + 9) // 10
        slides.append(pagina_copertina(p, imgs, data_txt, pagine))
        for i, start in enumerate(range(0, len(top), 10)):
            slides.append(pagina_griglia(p, top[start:start + 10], imgs[start:start + 10], start,
                                         data_txt, i + 2, pagine))
        extra = None
        if p['formato'] == 'bulk':
            extra = ('Reverse', 'La versione reverse holo della carta: ha un prezzo diverso da quella '
                                'normale. "IT da" è l\'offerta più bassa in italiano su CardTrader.')
        elif d.sets[p['chiave']]['rel'] < '2005':
            extra = ('Vintage', 'Il trend mescola edizioni e lingue: una 1ª edizione o una carta '
                                'in condizioni perfette vale molto di più.')
        slides.append(pagina_finale(data_txt, pagine, extra))

    nome = f'{oggi:%Y-%m-%d}-{p["formato"]}-{p["chiave"]}{"-PROVA" if d.mock else ""}'
    cartella = OUT / nome
    cartella.mkdir(parents=True, exist_ok=True)
    for i, sl in enumerate(slides, 1):
        if d.mock:
            sl = timbro_prova(sl)
        sl.save(cartella / f'{i:02d}.jpg', 'JPEG', quality=92, optimize=True, progressive=True)
    (cartella / 'didascalia.txt').write_text(p['didascalia'], encoding='utf-8')
    for r, u in zip(p['voci'], fonti):
        r['img'] = u
        r.pop('img_urls', None)
    (cartella / 'dati.json').write_text(json.dumps({
        'data': oggi.isoformat(), 'generato': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'formato': p['formato'], 'chiave': p['chiave'], 'prova': d.mock, 'pagine': len(slides),
        'listino_cardtrader': d.ct.get('d'), 'voci': p['voci']}, ensure_ascii=False, indent=1),
        encoding='utf-8')
    (cartella / 'controlli.txt').write_text('\n'.join(avvisi) or 'Nessun avviso', encoding='utf-8')
    print(f'Post in {cartella} ({len(slides)} pagine)')
    for r in p['voci']:
        print(f"  {sotto(r, True):>28}  {r['nome']:<24} {euro(r['trend']):>12}  "
              f"{pct(r['var']) if r['var'] is not None else '':>8}  IT {r['it_ct'] or '-'}")
    if avvisi:
        print('Controlli:\n  ' + '\n  '.join(avvisi))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('formato', choices=['auto', 'top', 'movimenti', 'illustrazioni', 'bulk'])
    ap.add_argument('--set', default='30th')
    ap.add_argument('--n', type=int, default=20)
    ap.add_argument('--data', help='giorno da usare (AAAA-MM-GG), di default oggi a Roma')
    ap.add_argument('--mock', action='store_true', help='prezzi e immagini finti, solo per la grafica')
    a = ap.parse_args()
    oggi = date.fromisoformat(a.data) if a.data else datetime.now(ROMA).date()
    d = Dati(a.mock)
    if a.formato == 'auto':
        p = scegli(d, oggi)
        if p is None:
            print('Nessun post previsto oggi (sabato o domenica).')
            return
    elif a.formato == 'top':
        p = fmt_top(d, a.set, a.n, oggi)
    elif a.formato == 'movimenti':
        p = fmt_movimenti(d, oggi)
    elif a.formato == 'illustrazioni':
        p = fmt_illustrazioni(d, oggi)
    else:
        p = fmt_bulk(d, oggi)
    genera(p, d, oggi)


if __name__ == '__main__':
    main()
