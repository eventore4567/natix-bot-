#!/usr/bin/env python3
"""Génère les emojis du bot (PNG 128x128 transparents + GIF animés) à partir de glyphes SVG dessinés à la main.
Usage : python3 -I gen_emojis.py <dossier_sortie>
Style : badge rond à dégradé + glyphe blanc à traits arrondis (même grille 24x24 pour tous)."""
import io, math, os, sys
from PIL import Image
from playwright.sync_api import sync_playwright

OUT = sys.argv[1]
os.makedirs(OUT, exist_ok=True)

# clé -> (dégradé haut, dégradé bas, glyphe SVG sur grille 24x24). {c} = couleur du badge (pour les "trous").
S = 'fill="none" stroke="#fff" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"'
F = 'fill="#fff" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"'

def gear():
    teeth = ''.join(f'<rect x="10.3" y="2.6" width="3.4" height="4.6" rx="1" transform="rotate({a} 12 12)"/>' for a in range(0, 360, 45))
    return f'<g fill="#fff">{teeth}<circle cx="12" cy="12" r="6.2"/></g><circle cx="12" cy="12" r="2.6" fill="{{c}}"/>'

GLYPHS = {
 'success':      ('#22c55e', '#15803d', f'<path {S} d="M5.5 12.5l4.3 4.3L18.6 7.8"/>'),
 'error':        ('#ef4444', '#b91c1c', f'<path {S} d="M7 7l10 10M17 7L7 17"/>'),
 'denied':       ('#f43f5e', '#9f1239', f'<circle {S} cx="12" cy="12" r="7.6"/><path {S} d="M6.6 6.6l10.8 10.8"/>'),
 'warning':      ('#f59e0b', '#b45309', f'<path {S} d="M12 6.5v7"/><path {S} d="M12 17.6h.01"/>'),
 'security':     ('#3b82f6', '#1d4ed8', f'<path {S} d="M12 3.8l6.6 2.4v5.3c0 4.2-2.8 7.1-6.6 8.8-3.8-1.7-6.6-4.6-6.6-8.8V6.2z"/><path {S} d="M9 11.8l2.3 2.3 3.9-4.3"/>'),
 'sanction':     ('#dc2626', '#7f1d1d', f'<g transform="rotate(45 12 12)"><rect x="5.2" y="4.2" width="13.6" height="6.2" rx="1.8" {F}/><path {S} d="M12 10.4v9.2"/></g><path {S} d="M5 20.2h7"/>'),
 'lock':         ('#64748b', '#1e293b', f'<rect x="5.8" y="10.8" width="12.4" height="9.2" rx="2.4" {F}/><path {S} d="M8.6 10.8V8.2a3.4 3.4 0 0 1 6.8 0v2.6"/><path fill="none" stroke="{{c}}" stroke-width="2.4" stroke-linecap="round" d="M12 14.4v2.2"/>'),
 'unlock':       ('#14b8a6', '#0f766e', f'<rect x="5.8" y="10.8" width="12.4" height="9.2" rx="2.4" {F}/><path {S} d="M8.6 10.8V8.2a3.4 3.4 0 0 1 6.5-1.4"/><path fill="none" stroke="{{c}}" stroke-width="2.4" stroke-linecap="round" d="M12 14.4v2.2"/>'),
 'info':         ('#0ea5e9', '#0369a1', f'<path {S} d="M12 11v6"/><path {S} d="M12 7.2h.01"/>'),
 'config':       ('#8392aa', '#475569', gear()),
 'ticket':       ('#ec4899', '#9d174d', f'<path {S} d="M4.5 8.2a1 1 0 0 1 1-1h13a1 1 0 0 1 1 1v2a2 2 0 0 0 0 3.6v2.2a1 1 0 0 1-1 1h-13a1 1 0 0 1-1-1v-2.2a2 2 0 0 0 0-3.6z"/><path {S} d="M14.2 8.6v1.2M14.2 11.4v1.2M14.2 14.2v1.2" stroke-width="2"/>'),
 'logs':         ('#6366f1', '#3730a3', f'<rect x="5.8" y="5" width="12.4" height="15" rx="2.4" {S}/><path {S} d="M9.4 11h5.2M9.4 15h5.2"/><path {S} d="M9.6 3.8h4.8" stroke-width="3"/>'),
 'notification': ('#f97316', '#c2410c', f'<path {S} d="M6.4 16.8v-5.2a5.6 5.6 0 0 1 11.2 0v5.2l1.6 1.6H4.8z"/><path {S} d="M10.2 21a2 2 0 0 0 3.6 0"/>'),
 'games':        ('#8b5cf6', '#5b21b6', f'<rect x="3.4" y="7.4" width="17.2" height="10" rx="5" {S}/><path {S} d="M8 10.6v3.6M6.2 12.4h3.6" stroke-width="2"/><circle cx="15.2" cy="11.2" r="1.15" fill="#fff"/><circle cx="17.6" cy="13.6" r="1.15" fill="#fff"/>'),
 'reward':       ('#f59e0b', '#a16207', f'<path {S} d="M8 4.5h8v5.2a4 4 0 0 1-8 0z"/><path {S} d="M8 6.2H5.4v1.4A2.6 2.6 0 0 0 8 10.2M16 6.2h2.6v1.4a2.6 2.6 0 0 1-2.6 2.6"/><path {S} d="M12 13.8v3.4M8.6 19.6h6.8"/>'),
 'kick':         ('#f97316', '#9a3412', f'<path {S} d="M10 5H7a1.6 1.6 0 0 0-1.6 1.6v10.8A1.6 1.6 0 0 0 7 19h3"/><path {S} d="M14.2 8.2l3.8 3.8-3.8 3.8M18 12H9.4"/>'),
 'mute':         ('#eab308', '#854d0e', f'<path d="M4.4 9.8h2.8l3.9-3.4v11.2l-3.9-3.4H4.4z" {F}/><path {S} d="M15.2 9.8l4.4 4.4M19.6 9.8l-4.4 4.4"/>'),
 'unmute':       ('#14b8a6', '#115e59', f'<path d="M4.4 9.8h2.8l3.9-3.4v11.2l-3.9-3.4H4.4z" {F}/><path {S} d="M15.2 9.4a3.6 3.6 0 0 1 0 5.2M17.8 6.8a7.2 7.2 0 0 1 0 10.4"/>'),
 'timer':        ('#a855f7', '#6b21a8', f'<circle {S} cx="12" cy="13.4" r="7"/><path {S} d="M12 13.4V9.8M12 13.4l2.4 1.6M10 3.6h4"/>'),
 'on':           ('#22c55e', '#15803d', f'<path {S} d="M12 4.6v6.6M7.4 7.6a7 7 0 1 0 9.2 0"/>'),
 'off':          ('#94a3b8', '#475569', f'<path {S} d="M12 4.6v6.6M7.4 7.6a7 7 0 1 0 9.2 0"/>'),
 'user':         ('#3b82f6', '#1e40af', f'<circle cx="12" cy="8.4" r="3.6" {F}/><path {S} d="M5.2 19.6a6.8 6.8 0 0 1 13.6 0"/>'),
 'server':       ('#6366f1', '#3730a3', f'<rect x="4.8" y="4.8" width="14.4" height="6" rx="2" {S}/><rect x="4.8" y="13.2" width="14.4" height="6" rx="2" {S}/><path {S} d="M8.2 7.8h.01M8.2 16.2h.01"/>'),
 'delete':       ('#64748b', '#334155', f'<path {S} d="M5 7.2h14M9.6 7.2V5h4.8v2.2M7 7.2l.8 11.6a1 1 0 0 0 1 .9h6.4a1 1 0 0 0 1-.9L17 7.2M10.4 11v5M13.6 11v5"/>'),
 'edit':         ('#0ea5e9', '#075985', f'<path {S} d="M5.2 18.8l.9-3.8L15.8 5.3a2 2 0 0 1 2.9 2.9L9 17.9z"/><path {S} d="M14.2 6.9l2.9 2.9"/>'),
 'join':         ('#22c55e', '#166534', f'<circle cx="10" cy="8.6" r="3.2" {F}/><path {S} d="M4 19a6 6 0 0 1 12 0"/><path {S} d="M18.4 8.4v5M15.9 10.9h5"/>'),
 'leave':        ('#fb7185', '#be123c', f'<circle cx="10" cy="8.6" r="3.2" {F}/><path {S} d="M4 19a6 6 0 0 1 12 0"/><path {S} d="M15.9 10.9h5"/>'),
 'bot':          ('#8b5cf6', '#4c1d95', f'<rect x="5.2" y="8.4" width="13.6" height="10.4" rx="3.2" {S}/><path {S} d="M12 8.4V5.4"/><circle cx="12" cy="4.4" r="1.1" fill="#fff"/><path {S} d="M9.2 13.4h.01M14.8 13.4h.01"/>'),
 'clean':        ('#06b6d4', '#0e7490', f'<path {S} d="M17.6 4.6l-6.2 7"/><path d="M11.2 11.4l2.6 2.2-1.8 6.2H5.2l1-5.4z" {F}/>'),
 'slowmode':     ('#f59e0b', '#9a3412', f'<path {S} d="M7 4.6h10M7 19.4h10M8 4.6c0 3.6 4 5.2 4 7.4s-4 3.8-4 7.4M16 4.6c0 3.6-4 5.2-4 7.4s4 3.8 4 7.4"/>'),
 'help':         ('#0ea5e9', '#0c4a6e', f'<path {S} d="M12 7c-1.5-1.3-3.7-2-6.6-2v12.4c2.9 0 5.1.7 6.6 2 1.5-1.3 3.7-2 6.6-2V5c-2.9 0-5.1.7-6.6 2zM12 7v12.4"/>'),
 'diagnostic':   ('#10b981', '#047857', f'<path {S} d="M3.8 12.4h4l2.1-5.4 3.8 10.4 2.2-5h4.4"/>'),
}

def badge(top, bottom, glyph, rot=None, extra=''):
    c = bottom
    glyph = glyph.replace('{c}', c)
    g = f'<g transform="translate(64 64) scale(3.55) translate(-12 -12)">{glyph}</g>'
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="128" height="128" viewBox="0 0 128 128">
<defs><linearGradient id="g" x1="0.2" y1="0" x2="0.8" y2="1"><stop offset="0" stop-color="{top}"/><stop offset="1" stop-color="{bottom}"/></linearGradient>
<linearGradient id="h" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff" stop-opacity=".13"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></linearGradient></defs>
<circle cx="64" cy="64" r="61" fill="url(#g)"/>
<ellipse cx="64" cy="30" rx="52" ry="34" fill="url(#h)"/>
<circle cx="64" cy="64" r="60.5" fill="none" stroke="#000" stroke-opacity=".14" stroke-width="1"/>
{g}{extra}</svg>'''

def spin_arc(angle):
    return f'<g transform="rotate({angle} 12 12)"><path {S} d="M12 4.2a7.8 7.8 0 1 1-7.8 7.8"/></g>'

def bell_frame(a):
    top, bot, _ = GLYPHS['notification']
    bell = f'<g transform="rotate({a} 12 4)"><path {S} d="M6.4 16.8v-5.2a5.6 5.6 0 0 1 11.2 0v5.2l1.6 1.6H4.8z"/><path {S} d="M12 6V4.2"/></g><path {S} d="M10.2 21a2 2 0 0 0 3.6 0" transform="rotate({a*0.5} 12 12)"/>'
    return badge(top, bot, bell)

def reward_frame(t):
    top, bot, glyph = GLYPHS['reward']
    # étoile qui scintille en haut à droite + petit éclat en bas à gauche
    def star(cx, cy, r, ph):
        k = max(0.0, math.sin(2 * math.pi * (t + ph)))
        r = r * (0.25 + 0.75 * k)
        return f'<path d="M{cx} {cy-r} Q{cx} {cy} {cx+r} {cy} Q{cx} {cy} {cx} {cy+r} Q{cx} {cy} {cx-r} {cy} Q{cx} {cy} {cx} {cy-r}z" fill="#fff"/>'
    extra_glyph = glyph + star(19.6, 4.6, 3.1, 0.0) + star(4.4, 15.4, 2.2, 0.5)
    return badge(top, bot, extra_glyph)

def anim_frames(key):
    if key == 'loading':
        return [badge('#3b82f6', '#1d4ed8', spin_arc(i * 360 / 12)) for i in range(12)], 65
    if key == 'notification':
        seq = [0, 14, -12, 10, -8, 5, -2, 0, 0, 0, 0, 0, 0, 0]
        return [bell_frame(a) for a in seq], 70
    if key == 'reward':
        return [reward_frame(i / 12) for i in range(12)], 90

def to_gif(frames_rgba, ms, path):
    matte = (43, 45, 49)  # gris Discord sombre : réduit le liseré sur les bords (le GIF n'a pas d'alpha progressif)
    pal = []
    for im in frames_rgba:
        a = im.getchannel('A')
        bg = Image.new('RGB', im.size, matte); bg.paste(im.convert('RGB'), mask=a)
        p = bg.quantize(colors=255, method=Image.Quantize.MEDIANCUT)
        mask = a.point(lambda v: 255 if v < 110 else 0)
        p.paste(255, mask=mask)
        pal.append(p)
    pal[0].save(path, save_all=True, append_images=pal[1:], duration=ms, loop=0, transparency=255, disposal=2, optimize=False)

with sync_playwright() as pw:
    br = pw.chromium.launch()
    page = br.new_page(viewport={'width': 128, 'height': 128}, device_scale_factor=1)
    def render(svg):
        page.set_content(f'<html><body style="margin:0;background:transparent">{svg}</body></html>')
        png = page.screenshot(omit_background=True, clip={'x': 0, 'y': 0, 'width': 128, 'height': 128})
        return Image.open(io.BytesIO(png)).convert('RGBA')
    made = []
    for key, (top, bot, glyph) in GLYPHS.items():
        if key in ('loading',):
            continue
        if key in ('notification', 'reward'):
            frames, ms = anim_frames(key)
            to_gif([render(f) for f in frames], ms, os.path.join(OUT, f'{key}.gif'))
            made.append(f'{key}.gif')
            continue
        render(badge(top, bot, glyph)).save(os.path.join(OUT, f'{key}.png'), optimize=True)
        made.append(f'{key}.png')
    frames, ms = anim_frames('loading')
    to_gif([render(f) for f in frames], ms, os.path.join(OUT, 'loading.gif'))
    made.append('loading.gif')
    br.close()
print(len(made), 'fichiers')
for m in sorted(made):
    print(m, os.path.getsize(os.path.join(OUT, m)))
