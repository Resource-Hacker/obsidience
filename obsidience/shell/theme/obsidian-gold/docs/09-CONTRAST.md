# Token contrast review

Computed from sRGB token luminance. This evaluates these color pairs only, not full application accessibility.

| Foreground | Background | Ratio | Target | Result |
|---|---|---:|---:|---|
| `text` | `surface` | 15.65:1 | 4.5:1 | Pass |
| `text_secondary` | `surface` | 8.99:1 | 4.5:1 | Pass |
| `gold` | `surface` | 8.13:1 | 4.5:1 | Pass |
| `gold_bright` | `selection` | 10.24:1 | 4.5:1 | Pass |
| `canvas` | `gold` | 8.36:1 | 4.5:1 | Pass |
| `border_control` | `surface` | 5.23:1 | 3:1 | Pass |
| `focus` | `surface` | 12.65:1 | 3:1 | Pass |
| `success` | `surface` | 8.74:1 | 4.5:1 | Pass |
| `danger` | `surface` | 8.13:1 | 4.5:1 | Pass |
| `information` | `surface` | 8.94:1 | 4.5:1 | Pass |

Decorative separators and disabled controls are not claimed to meet normal text contrast. Meaningful controls use the stronger control-border token. Essential body text does not use low-contrast decorative gold. Native focus, semantics, keyboard navigation and toolkit rendering still require acceptance.
