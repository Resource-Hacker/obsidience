#!/usr/bin/env python3
"""Generate color-only optional projections. Does not install or activate them."""
from __future__ import annotations
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parent

def rgb(value: str) -> str:
    return ','.join(str(int(value[i:i+2],16)) for i in (1,3,5))

def main() -> int:
    colors=json.loads((ROOT/'tokens.json').read_text())['color']
    out=ROOT/'exports'
    out.mkdir(exist_ok=True)
    (out/'tokens.css').write_text(':root {\n'+''.join('  --'+k.replace('_','-')+': '+v+';\n' for k,v in colors.items())+'}\n')
    ansi=['#252b2c','#d98883','#91b9a3','#c6a56b','#8fb8cc','#baa6cf','#8ebfc0','#d8d4c9',
          '#747d7a','#efaaa2','#b1d2bd','#efcf91','#b5d0df','#d8c5e7','#b6dadd','#f5efe1']
    terminal={'name':'Obsidian Gold','background':colors['surface'],'foreground':colors['text'],
        'cursor':colors['gold_bright'],'selection_background':colors['selection'],
        'selection_foreground':colors['text'],'ansi':ansi}
    (out/'terminal-ansi.json').write_text(json.dumps(terminal,indent=2)+'\n')
    kitty=['# Color-only export. No executable hooks. Not installed automatically.',
        'background '+colors['surface'],'foreground '+colors['text'],'cursor '+colors['gold_bright'],
        'selection_background '+colors['selection'],'selection_foreground '+colors['text']]
    kitty += [f'color{i} {color}' for i,color in enumerate(ansi)]
    (out/'kitty.conf').write_text('\n'.join(kitty)+'\n')
    konsole=['[General]','Description=Obsidian Gold','Opacity=1','Blur=false','ColorRandomization=false','']
    for name,color in [('Background',colors['surface']),('Foreground',colors['text'])]+[(f'Color{i}',c) for i,c in enumerate(ansi[:8])]+[(f'Color{i}Intense',c) for i,c in enumerate(ansi[8:])]:
        konsole.extend([f'[{name}]','Color='+rgb(color),'Transparent=false',''])
    (out/'ObsidianGold.colorscheme').write_text('\n'.join(konsole))
    kde=['[General]','Name=Obsidian Gold','ColorScheme=ObsidianGold','shadeSortColumn=true','']
    for group in ('Window','View','Button','Selection','Tooltip','Complementary','Header'):
        selected=group=='Selection'
        values={'BackgroundNormal':colors['gold'] if selected else colors['surface'],
            'BackgroundAlternate':colors['selection'] if not selected else colors['gold_bright'],
            'ForegroundNormal':colors['canvas'] if selected else colors['text'],
            'ForegroundInactive':'#30372f' if selected else colors['text_secondary'],
            'ForegroundActive':colors['canvas'] if selected else colors['gold_bright'],
            'ForegroundLink':'#17303c' if selected else colors['information'],
            'ForegroundVisited':'#3c244a' if selected else colors['skill'],
            'ForegroundPositive':'#18382a' if selected else colors['success'],
            'ForegroundNeutral':'#382a09' if selected else colors['warning'],
            'ForegroundNegative':'#481f1b' if selected else colors['danger'],
            'DecorationFocus':colors['gold_bright'],'DecorationHover':colors['gold']}
        kde.append('[Colors:'+group+']')
        kde.extend(k+'='+rgb(v) for k,v in values.items());kde.append('')
    kde.extend(['[WM]','activeBackground='+rgb(colors['surface']),'activeForeground='+rgb(colors['text']),
        'inactiveBackground='+rgb(colors['canvas']),'inactiveForeground='+rgb(colors['text_secondary']),''])
    (out/'ObsidianGold.colors').write_text('\n'.join(kde))
    (out/'README.md').write_text('''# Optional color projections

These generated files are color-only assets. They are not installed, selected or activated by the atlas or exporter.

`tokens.css` supplies the offline atlas. `terminal-ansi.json` is the neutral sixteen-color terminal design. `kitty.conf` contains only Kitty color keys. `ObsidianGold.colorscheme` is a Konsole color-scheme projection. `ObsidianGold.colors` is an original KDE/Qt color-scheme projection using the installed toolkit's schema keys.

Native terminal and application integration must use the existing owners and installed toolkit support. Application-native controls can ignore external colors, especially in custom widgets or libadwaita applications; this is not a guarantee that every GTK/Qt application is themed. Browser policy already has a separate existing Obsidience adapter. Fonts, executable hooks, startup commands and plugins are intentionally absent.

Regenerate from the package's semantic colors with `python3 export_tokens.py`. Review ANSI contrast and syntax semantics in the real terminal before activation. The native compatible `palette.json` remains a separate explicitly reviewed mapping because it has its own exact runtime schema and alpha ordering.
''')
    print('Generated CSS, ANSI, Kitty, Konsole and KDE/Qt color-only projections. Nothing was installed.')
    return 0

if __name__=='__main__':
    raise SystemExit(main())
