#!/usr/bin/env python3
"""
VIGIA - Pizarra overlay transparente (Windows, Tkinter+Win32).
Se lanza como subproceso del cliente. Lee comandos JSON de stdin (uno por línea).
Uso: python3 vigia_overlay_win.py <left> <top> <width> <height>

Equivalente exacto de vigia_overlay.py pero para Windows.
Reemplaza: GTK+Cairo → Tkinter+Canvas, XFixes click-through → WS_EX_TRANSPARENT.
"""

import sys
import os
import json
import threading
import ctypes
import ctypes.wintypes

try:
    import tkinter as tk
except ImportError:
    print("[vigia_overlay_win] Tkinter no disponible.", file=sys.stderr)
    sys.exit(1)

# Win32 constants
GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOPMOST = 0x00000008
LWA_COLORKEY = 0x00000001
LWA_ALPHA = 0x00000002
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
HWND_TOPMOST = -1

user32 = ctypes.windll.user32


def _hex_rgb(color):
    c = color.lstrip('#')
    return f'#{c}'  # Tkinter already uses #RRGGBB


def _set_clickthrough(hwnd):
    """Hace la ventana click-through usando WS_EX_TRANSPARENT + WS_EX_LAYERED."""
    try:
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE,
                              style | WS_EX_LAYERED | WS_EX_TRANSPARENT)
        # Poner siempre encima
        user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                            SWP_NOMOVE | SWP_NOSIZE)
        print("[vigia_overlay_win] click-through activado.", file=sys.stderr)
    except Exception as e:
        print(f"[vigia_overlay_win] click-through fallido: {e}", file=sys.stderr)


class PizarraOverlay:
    def __init__(self, root, l, t, w, h):
        self.root = root
        self.l, self.t, self.w, self.h = l, t, w, h

        # Ventana transparente sin decoración
        self.root.overrideredirect(True)
        self.root.geometry(f'{w}x{h}+{l}+{t}')
        self.root.attributes('-topmost', True)

        # Color de transparencia (magenta como color key)
        self._transparent_color = '#ff00ff'
        self.root.configure(bg=self._transparent_color)
        self.root.attributes('-transparentcolor', self._transparent_color)

        # Canvas para dibujar
        self.canvas = tk.Canvas(self.root, width=w, height=h,
                                bg=self._transparent_color,
                                highlightthickness=0, bd=0)
        self.canvas.pack(fill='both', expand=True)

        self._items = []
        self._visible = False

        # Aplicar click-through después de que la ventana se muestre
        self.root.after(100, self._apply_clickthrough)

        print(f"[vigia_overlay_win] Overlay creado en ({l},{t}) {w}x{h}.",
              file=sys.stderr)

    def _apply_clickthrough(self):
        """Obtiene el HWND de la ventana Tkinter y aplica click-through."""
        try:
            hwnd = ctypes.windll.user32.FindWindowW(None, self.root.title())
            if hwnd:
                _set_clickthrough(hwnd)
            else:
                # Método alternativo: usar winfo_id
                hwnd = self.root.winfo_id()
                # winfo_id en Windows devuelve el HWND del widget interno,
                # necesitamos el del toplevel
                parent = user32.GetParent(hwnd)
                if parent:
                    _set_clickthrough(parent)
                else:
                    _set_clickthrough(hwnd)
        except Exception as e:
            print(f"[vigia_overlay_win] Error al aplicar click-through: {e}",
                  file=sys.stderr)

    def show(self):
        self._visible = True
        self.root.deiconify()
        self.root.attributes('-topmost', True)
        self.root.after(50, self._apply_clickthrough)

    def hide(self):
        self._visible = False
        self.root.withdraw()

    def draw(self, x0, y0, x1, y1, color, size):
        self._items.append(('line', x0, y0, x1, y1, color, size))
        self.canvas.create_line(
            float(x0), float(y0), float(x1), float(y1),
            fill=_hex_rgb(color), width=max(1, float(size)),
            capstyle='round', joinstyle='round',
        )

    def text(self, x, y, t, color, size):
        self._items.append(('text', x, y, t, color, size))
        font_size = max(14, int(float(size) * 3))
        self.canvas.create_text(
            float(x), float(y), text=str(t),
            fill=_hex_rgb(color), font=('Arial', font_size, 'bold'),
            anchor='sw',
        )

    def clear(self):
        self._items = []
        self.canvas.delete('all')


_ov = None


def _handle(cmd):
    global _ov
    t = cmd.get('type', '')
    if t == 'overlay_toggle':
        if cmd.get('enabled') and _ov:
            _ov.show()
        elif _ov:
            _ov.hide()
    elif t == 'overlay_draw' and _ov:
        _ov.draw(cmd.get('x0', 0), cmd.get('y0', 0),
                 cmd.get('x1', 0), cmd.get('y1', 0),
                 cmd.get('color', '#ff3b30'), cmd.get('size', 6))
    elif t == 'overlay_text' and _ov:
        _ov.text(cmd.get('x', 0), cmd.get('y', 0),
                 cmd.get('text', ''),
                 cmd.get('color', '#ff3b30'), cmd.get('size', 6))
    elif t == 'overlay_clear' and _ov:
        _ov.clear()


def _read_stdin(root):
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            cmd = json.loads(line)
            root.after(0, _handle, cmd)
        except Exception:
            pass
    root.after(0, root.quit)


if __name__ == '__main__':
    try:
        l = int(sys.argv[1]) if len(sys.argv) > 1 else 0
        t = int(sys.argv[2]) if len(sys.argv) > 2 else 0
        w = int(sys.argv[3]) if len(sys.argv) > 3 else 1920
        h = int(sys.argv[4]) if len(sys.argv) > 4 else 1080
    except Exception:
        l, t, w, h = 0, 0, 1920, 1080

    root = tk.Tk()
    root.title('VIGIA Overlay')
    root.withdraw()  # Oculta inicialmente

    _ov = PizarraOverlay(root, l, t, w, h)
    threading.Thread(target=_read_stdin, args=(root,), daemon=True).start()
    root.mainloop()
